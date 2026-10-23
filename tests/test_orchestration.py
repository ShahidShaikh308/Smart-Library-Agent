"""Regression tests for bounded tool execution and provider retry behavior."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent import orchestrator, providers
from agent.orchestrator_errors import ProviderRequestError
from agent.providers import ModelRoute, ModelRouter


class FakeTool:
    name = "fake_tool"

    def __init__(self):
        self.calls = []

    def invoke(self, args) -> Any:
        self.calls.append(args)
        return {"value": args.get("value")}


class FakeModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.bound_tools = None
        self.seen_messages = []

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    def invoke(self, messages):
        self.seen_messages.append(messages)
        return next(self.responses)


def _tool_call(value, call_id="call-1", name="fake_tool"):
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": {"value": value}, "id": call_id, "type": "tool_call"}
        ],
    )


def test_duplicate_tool_calls_execute_once_then_force_final(monkeypatch):
    tool = FakeTool()
    model = FakeModel(
        [
            _tool_call("same"),
            _tool_call("same", call_id="call-2"),
            AIMessage(content="Done."),
        ]
    )
    router = ModelRouter([ModelRoute("fake", "fake", model)], [tool], retries=0)
    monkeypatch.setattr(
        orchestrator.tool_registry, "get_tool_map", lambda: {tool.name: tool}
    )
    monkeypatch.setattr(orchestrator, "create_model_router", lambda _tools: router)

    graph = orchestrator.build_orchestrator()
    result = orchestrator.execute(graph, [HumanMessage(content="Find this")])

    assert len(tool.calls) == 1
    assert result["messages"][-1].content == "Done."
    assert result["stop_reason"] == "repeated_tool_chain"
    tool_messages = [
        message for message in result["messages"] if isinstance(message, ToolMessage)
    ]
    assert len(tool_messages) == 2
    assert all(message.content == '{"value": "same"}' for message in tool_messages)


def test_unknown_tool_is_reported_as_json_and_does_not_loop(monkeypatch):
    model = FakeModel(
        [
            _tool_call("x", name="hallucinated"),
            AIMessage(content="I couldn't safely do that."),
        ]
    )
    router = ModelRouter([ModelRoute("fake", "fake", model)], [], retries=0)
    monkeypatch.setattr(orchestrator.tool_registry, "get_tool_map", dict)
    monkeypatch.setattr(orchestrator, "create_model_router", lambda _tools: router)

    result = orchestrator.execute(
        orchestrator.build_orchestrator(), [HumanMessage(content="Do it")]
    )
    assert result["stop_reason"] == "repeated_or_failed_tool_call"
    assert any(
        isinstance(message, ToolMessage) and '"error"' in message.content
        for message in result["messages"]
    )


def test_model_can_plan_sequential_context_and_recommendation_tools(monkeypatch):
    context = FakeTool()
    context.name = "load_book_context"
    recommendation = FakeTool()
    recommendation.name = "recommend_books"
    tool_calls = [
        {
            "name": "load_book_context",
            "args": {"query": "Dune"},
            "id": "context-1",
            "type": "tool_call",
        },
        {
            "name": "recommend_books",
            "args": {},
            "id": "recommend-1",
            "type": "tool_call",
        },
    ]
    model = FakeModel(
        [
            AIMessage(content="", tool_calls=tool_calls),
            AIMessage(content="Here are related books."),
        ]
    )
    router = ModelRouter(
        [ModelRoute("fake", "fake", model)], [context, recommendation], retries=0
    )
    monkeypatch.setattr(
        orchestrator.tool_registry,
        "get_tool_map",
        lambda: {context.name: context, recommendation.name: recommendation},
    )
    monkeypatch.setattr(orchestrator, "create_model_router", lambda _tools: router)

    result = orchestrator.execute(
        orchestrator.build_orchestrator(),
        [HumanMessage(content="More books like Dune")],
    )

    assert len(context.calls) == 1
    assert len(recommendation.calls) == 1
    tool_results = [
        message for message in result["messages"] if isinstance(message, ToolMessage)
    ]
    assert [message.name for message in tool_results] == [
        "load_book_context",
        "recommend_books",
    ]
    second_request = model.seen_messages[1]
    assistant_call = next(
        message
        for message in second_request
        if isinstance(message, AIMessage) and message.tool_calls
    )
    for call in assistant_call.tool_calls:
        matching = [
            message
            for message in second_request
            if isinstance(message, ToolMessage)
            and message.tool_call_id == call["id"]
        ]
        assert len(matching) == 1
        assert isinstance(matching[0].content, str)
        assert matching[0].content
    assert [type(message) for message in second_request[-3:]] == [
        AIMessage,
        ToolMessage,
        ToolMessage,
    ]
    system_prompt = next(
        message.content
        for message in model.seen_messages[0]
        if isinstance(message, SystemMessage)
    )
    assert "first call load_book_context" in system_prompt


def test_similar_books_tool_does_not_replace_active_title_with_numeric_id(monkeypatch):
    class SimilarBooksTool(FakeTool):
        def invoke(self, args):
            self.calls.append(args)
            return [{"title": "Foundation", "author": "Isaac Asimov"}]

    tool = SimilarBooksTool()
    tool.name = "find_similar_books"
    model = FakeModel(
        [_tool_call(7, name=tool.name), AIMessage(content="Try Foundation.")]
    )
    router = ModelRouter([ModelRoute("fake", "fake", model)], [tool], retries=0)
    monkeypatch.setattr(
        orchestrator.tool_registry, "get_tool_map", lambda: {tool.name: tool}
    )
    monkeypatch.setattr(orchestrator, "create_model_router", lambda _tools: router)

    result = orchestrator.execute(
        orchestrator.build_orchestrator(),
        [HumanMessage(content="Find books like Dune")],
        active_book="Dune",
    )

    assert result["active_book"] == "Dune"


def test_tool_round_limit_forces_final_response(monkeypatch):
    tool = FakeTool()
    model = FakeModel(
        [_tool_call("first"), AIMessage(content="Finished with the available result.")]
    )
    router = ModelRouter([ModelRoute("fake", "fake", model)], [tool], retries=0)
    monkeypatch.setenv("AGENT_MAX_TOOL_ROUNDS", "1")
    monkeypatch.setattr(
        orchestrator.tool_registry, "get_tool_map", lambda: {tool.name: tool}
    )
    monkeypatch.setattr(orchestrator, "create_model_router", lambda _tools: router)

    result = orchestrator.execute(
        orchestrator.build_orchestrator(), [HumanMessage(content="Find this")]
    )
    assert len(tool.calls) == 1
    assert result["messages"][-1].content == "Finished with the available result."
    assert result["stop_reason"] == "max_tool_rounds"


def test_tool_activity_streams_to_callback_on_calling_thread(monkeypatch):
    callback_received = threading.Event()

    class WaitingTool(FakeTool):
        callback_was_live = False

        def invoke(self, args):
            self.callback_was_live = callback_received.wait(timeout=2)
            return super().invoke(args)

    tool = WaitingTool()
    tool.name = "search_catalog"
    model = FakeModel(
        [
            _tool_call("Dune", name="search_catalog"),
            AIMessage(content="Here is the result."),
        ]
    )
    router = ModelRouter([ModelRoute("fake", "fake", model)], [tool], retries=0)
    monkeypatch.setattr(
        orchestrator.tool_registry, "get_tool_map", lambda: {tool.name: tool}
    )
    monkeypatch.setattr(orchestrator, "create_model_router", lambda _tools: router)
    caller_thread = threading.get_ident()
    callbacks = []

    def receive_event(event):
        callbacks.append((event, threading.get_ident()))
        if event == "📚 Searching book catalog...":
            callback_received.set()

    result = orchestrator.execute(
        orchestrator.build_orchestrator(),
        [HumanMessage(content="Search for Dune")],
        on_event=receive_event,
    )

    event_names = [event for event, _thread_id in callbacks]
    assert event_names == result["events"]
    assert event_names == [
        "🧠 Understanding request...",
        "🤖 Consulting the reading assistant...",
        "📚 Searching book catalog...",
        "✅ Tool step complete.",
        "🤖 Consulting the reading assistant...",
        "✅ Response ready.",
    ]
    assert all(thread_id == caller_thread for _event, thread_id in callbacks)
    assert tool.callback_was_live


def test_router_retries_transient_status_then_succeeds(monkeypatch):
    class RateLimited(Exception):
        status_code = 429

    class IntermittentModel(FakeModel):
        def invoke(self, messages):
            self.attempts += 1
            if self.attempts == 1:
                raise RateLimited()
            return AIMessage(content="ok")

    model = IntermittentModel([])
    model.attempts = 0
    monkeypatch.setattr(providers.time, "sleep", lambda _seconds: None)
    router = ModelRouter([ModelRoute("openrouter", "test-model", model)], [], retries=1)
    assert (
        router.invoke([HumanMessage(content="hi")], allow_tools=False).content == "ok"
    )
    assert model.attempts == 2


def test_router_fails_over_after_retry_budget(monkeypatch):
    class Unavailable(Exception):
        status_code = 503

    class AlwaysUnavailable(FakeModel):
        def invoke(self, messages):
            raise Unavailable()

    primary = AlwaysUnavailable([])
    fallback = FakeModel([AIMessage(content="fallback")])
    monkeypatch.setattr(providers.time, "sleep", lambda _seconds: None)
    router = ModelRouter(
        [
            ModelRoute("openrouter", "primary", primary),
            ModelRoute("openrouter", "fallback", fallback),
        ],
        [],
        retries=1,
    )
    assert (
        router.invoke([HumanMessage(content="hi")], allow_tools=False).content
        == "fallback"
    )


def test_router_does_not_retry_invalid_model_configuration():
    class MissingModel(Exception):
        status_code = 404

    class InvalidModel(FakeModel):
        attempts = 0

        def invoke(self, messages):
            self.attempts += 1
            raise MissingModel()

    model = InvalidModel([])
    router = ModelRouter([ModelRoute("openrouter", "missing", model)], [], retries=3)

    with pytest.raises(ProviderRequestError, match="model was not found"):
        router.invoke([HumanMessage(content="hello")], allow_tools=False)

    assert model.attempts == 1


def test_openrouter_debug_logs_serialized_messages_and_full_error_body(caplog):
    from types import SimpleNamespace

    class BadRequest(Exception):
        status_code = 400

        def __init__(self):
            super().__init__("Bad request")
            self.response = SimpleNamespace(
                text='{"error":{"message":"messages[2].content is invalid"}}'
            )

    class FailingModel(FakeModel):
        def invoke(self, messages):
            raise BadRequest()

    messages = [HumanMessage(content="Look up Dune")]
    router = ModelRouter(
        [ModelRoute("openrouter", "cohere/north-mini-code:free", FailingModel([]))],
        [],
        retries=0,
    )
    caplog.set_level("DEBUG", logger="agent.providers")

    with pytest.raises(ProviderRequestError):
        router.invoke(messages, allow_tools=False)

    assert '"role": "user"' in caplog.text
    assert 'messages[2].content is invalid' in caplog.text


def test_history_trim_starts_at_complete_user_turn():
    history = [HumanMessage(content=str(index)) for index in range(10)]
    trimmed = orchestrator._trim(history, limit=4)
    assert [message.content for message in trimmed] == ["6", "7", "8", "9"]


def test_agent_debug_enables_root_logger(monkeypatch):
    import logging

    from utils.logging_config import configure_logging

    root_logger = logging.getLogger()
    previous_level = root_logger.level
    try:
        monkeypatch.setenv("AGENT_DEBUG", "true")
        configure_logging()
        assert root_logger.level == logging.DEBUG
    finally:
        root_logger.setLevel(previous_level)
