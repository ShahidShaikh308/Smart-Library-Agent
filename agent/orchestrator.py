"""Bounded single-agent orchestration with sequential, guarded tool execution."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import PurePath
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from agent import tool_registry
from agent.orchestrator_errors import AgentExecutionError, ProviderRequestError
from agent.prompts import build_system_prompt
from agent.providers import create_model_router
from agent.state import AgentState
from tools.output import serialize_tool_result

logger = logging.getLogger(__name__)
TOOL_LABELS = {
    "search_catalog": "📚 Searching book catalog...",
    "load_book_context": "🔎 Loading book and personal context...",
    "recommend_books": "⭐ Preparing recommendation...",
    "scan_library": "📂 Checking personal library...",
    "list_owned_books": "📂 Checking personal library...",
    "find_missing_books": "📂 Checking personal library...",
    "find_library_duplicates": "📂 Checking personal library...",
    "get_reader_profile": "📖 Loading reader profile...",
    "update_reader_preferences": "💾 Updating memory...",
    "save_book_rating": "💾 Updating memory...",
    "set_book_favorite": "💾 Updating memory...",
    "save_book_note": "💾 Updating memory...",
    "add_to_collection": "💾 Updating memory...",
    "update_book_tags": "💾 Updating memory...",
    "add_bookmark": "💾 Updating reading journey...",
    "add_to_wishlist": "💾 Updating memory...",
    "remove_from_wishlist": "💾 Updating memory...",
    "update_reading_progress": "💾 Updating reading progress...",
    "start_reading": "💾 Updating reading progress...",
    "mark_book_completed": "💾 Updating reading journey...",
}
MAX_TOOL_ROUNDS_DEFAULT = 4
MAX_TOOL_ROUNDS_CEILING = 8
DEFAULT_HISTORY_MESSAGES = 16


def _max_tool_rounds() -> int:
    """Read and bound the number of tool cycles for one user request."""
    try:
        requested = int(
            os.getenv("AGENT_MAX_TOOL_ROUNDS", str(MAX_TOOL_ROUNDS_DEFAULT))
        )
    except ValueError:
        logger.warning(
            "Invalid AGENT_MAX_TOOL_ROUNDS; using default=%d", MAX_TOOL_ROUNDS_DEFAULT
        )
        requested = MAX_TOOL_ROUNDS_DEFAULT
    return min(max(requested, 1), MAX_TOOL_ROUNDS_CEILING)


def _trim(
    messages: Sequence[BaseMessage], limit: int = DEFAULT_HISTORY_MESSAGES
) -> list[BaseMessage]:
    """Trim only at a user-turn boundary so tool-call/result pairs stay together."""
    if len(messages) <= limit:
        return list(messages)
    start = max(0, len(messages) - limit)
    while start < len(messages) and not isinstance(messages[start], HumanMessage):
        start += 1
    if start >= len(messages):
        last_user = next(
            (
                index
                for index in range(len(messages) - 1, -1, -1)
                if isinstance(messages[index], HumanMessage)
            ),
            0,
        )
        start = last_user
    return list(messages[start:])


def _normalize_tool_messages(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """Repair empty tool outputs retained by older in-session history."""
    normalized = []
    for message in messages:
        if isinstance(message, ToolMessage) and not message.content:
            message = message.model_copy(update={"content": "null"})
        normalized.append(message)
    return normalized


def _tool_signature(name: str, args: Any) -> str:
    """Canonical signature for tool-call de-duplication and result caching."""
    return json.dumps(
        [name, args],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _tool_json(value: Any) -> str:
    """Guarantee valid, non-empty JSON content for every ToolMessage."""
    if value is None:
        return "null"
    if isinstance(value, str):
        try:
            json.loads(value)
            return value if value else '""'
        except json.JSONDecodeError:
            return serialize_tool_result(value)
    return serialize_tool_result(value)


def _active_book_after_tool(
    name: str, args: dict, output: str, current: str | int | None
):
    """Update book context only after a successful tool result identifies a book."""
    try:
        data = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        return current
    if name == "search_catalog":
        return (
            data[0].get("title") if isinstance(data, list) and len(data) == 1 else None
        )
    if name == "load_book_context" and isinstance(data, dict):
        local_files = data.get("local_files", [])
        if local_files and isinstance(local_files[0], dict):
            local = local_files[0]
            title = local.get("catalog_title") or PurePath(
                local.get("filename", "")
            ).stem.replace("_", " ").strip()
            if title:
                return title
        matches = data.get("matches", [])
        if matches and isinstance(matches[0], dict):
            book = matches[0].get("book") or {}
            title = book.get("title")
            if title and title.casefold() == str(data.get("query", "")).casefold():
                return title
            if len(matches) == 1:
                return title or current
        return current
    if name in {"get_book_context", "find_next_in_series"} and isinstance(data, dict):
        return data.get("title") or (None if data.get("error") else current)
    if (
        name == "find_similar_books"
        and isinstance(data, list)
        and not any("error" in row for row in data if isinstance(row, dict))
    ):
        # The argument is a catalog ID, not a conversational title. Preserve a
        # known title instead of replacing it with an ID that follow-ups cannot use.
        return current
    return current


def _ensure_call_ids(message: AIMessage) -> AIMessage:
    """Give provider-emitted calls stable IDs so every tool result can pair up."""
    if not message.tool_calls:
        return message
    calls = []
    for index, call in enumerate(message.tool_calls):
        normalized = dict(call)
        normalized["id"] = (
            normalized.get("id") or f"agent-call-{uuid.uuid4().hex}-{index}"
        )
        normalized["args"] = (
            normalized.get("args") if isinstance(normalized.get("args"), dict) else {}
        )
        normalized["name"] = str(normalized.get("name") or "")
        calls.append(normalized)
    return message.model_copy(update={"tool_calls": calls})


def build_orchestrator():
    """Build a graph with a hard tool-cycle bound and a sequential tool node."""
    logger.setLevel(
        logging.DEBUG
        if os.getenv("AGENT_DEBUG", "").strip().casefold() in {"1", "true", "yes", "on"}
        else logging.INFO
    )
    tools = tool_registry.get_tool_map()
    router = create_model_router(list(tools.values()))
    max_tool_rounds = _max_tool_rounds()

    def respond(state: AgentState):
        force_final = (
            state.get("force_final", False)
            or state.get("tool_rounds", 0) >= max_tool_rounds
        )
        messages = _normalize_tool_messages(_trim(state.get("messages", [])))
        prompt = SystemMessage(content=build_system_prompt(state.get("active_book")))
        if force_final:
            prompt.content += "\nTool use is disabled for this response. Summarize available results and finish now."
        try:
            get_stream_writer()({"event": "🤖 Consulting the reading assistant..."})
            answer = router.invoke([prompt] + messages, allow_tools=not force_final)
        except ProviderRequestError:
            raise
        except Exception as error:
            logger.exception("Unexpected model orchestration failure")
            raise AgentExecutionError(
                "I hit a temporary issue while preparing your response. Please try again."
            ) from error
        if not isinstance(answer, AIMessage):
            raise AgentExecutionError(
                "The AI provider returned an unexpected response. Please try again."
            )
        if answer.invalid_tool_calls:
            logger.warning(
                "Provider returned malformed or hallucinated tool calls; tool execution stopped"
            )
            answer = answer.model_copy(
                update={
                    "content": answer.content
                    or "I couldn't safely interpret the requested action. Please rephrase it.",
                    "tool_calls": [],
                    "invalid_tool_calls": [],
                }
            )
        answer = _ensure_call_ids(answer)
        if force_final and answer.tool_calls:
            logger.warning(
                "Model returned tool calls with tools disabled; forcing a user-facing final message"
            )
            answer = answer.model_copy(
                update={
                    "content": answer.content
                    or "I have reached the safe tool-use limit for this request. Please try a more specific follow-up.",
                    "tool_calls": [],
                    "invalid_tool_calls": [],
                }
            )
        return {"messages": [answer]}

    def execute_tools(state: AgentState):
        messages = state.get("messages", [])
        assistant_message = next(
            (
                message
                for message in reversed(messages)
                if isinstance(message, AIMessage)
            ),
            None,
        )
        calls = assistant_message.tool_calls if assistant_message else []
        if not calls:
            return {"stop_reason": "no_tool_calls"}

        cache = dict(state.get("tool_cache", {}))
        seen_chains = list(state.get("seen_tool_chains", []))
        rounds = state.get("tool_rounds", 0) + 1
        signatures = [
            _tool_signature(call.get("name", ""), call.get("args", {}))
            for call in calls
        ]
        chain_signature = json.dumps(signatures, separators=(",", ":"))
        repeated_chain = chain_signature in seen_chains
        seen_chains.append(chain_signature)
        results = []
        repeated_call = repeated_chain
        active_book = state.get("active_book")

        for index, (call, signature) in enumerate(zip(calls, signatures)):
            name = call.get("name", "")
            args = call.get("args", {})
            call_id = call.get("id") or f"missing-call-id-{rounds}-{index}"
            started = time.perf_counter()
            logger.debug("Tool selected name=%s args=%r round=%d", name, args, rounds)
            if name not in tools:
                output = serialize_tool_result(
                    {"error": f"Unknown tool '{name}'. Use only registered tools."}
                )
                repeated_call = True
                reason = "hallucinated_tool"
                logger.warning("Stopping unrecognized tool request name=%s", name)
            elif signature in cache:
                output = cache[signature]
                repeated_call = True
                reason = "cached_duplicate"
                logger.warning(
                    "Reusing previous result for repeated tool signature=%s", signature
                )
            elif not isinstance(args, dict):
                output = serialize_tool_result(
                    {"error": "Tool arguments must be a JSON object."}
                )
                cache[signature] = output
                reason = "invalid_arguments"
            else:
                writer: Callable[[Any], None] | None = None
                try:
                    writer = get_stream_writer()
                    if name == "recommend_books":
                        writer({"event": "📖 Loading reader profile..."})
                    writer(
                        {
                            "event": TOOL_LABELS.get(
                                name, "🔎 Retrieving book information..."
                            )
                        }
                    )
                    raw_result = tools[name].invoke(args)
                    output = _tool_json(raw_result)
                    # Parse before caching; malformed outputs are converted to a valid JSON string above.
                    json.loads(output)
                    cache[signature] = output
                    active_book = _active_book_after_tool(
                        name, args, output, active_book
                    )
                    reason = "completed"
                except Exception:
                    logger.exception(
                        "Tool execution failed name=%s args=%r", name, args
                    )
                    output = serialize_tool_result(
                        {
                            "error": f"{name} could not complete this request. Check the book details and try again."
                        }
                    )
                    cache[signature] = output
                    repeated_call = True
                    reason = "tool_error"
                finally:
                    if writer is not None:
                        writer({"event": "✅ Tool step complete."})
            elapsed = time.perf_counter() - started
            logger.debug(
                "Tool finished name=%s duration_seconds=%.3f reason=%s output=%s",
                name,
                elapsed,
                reason,
                output,
            )
            results.append(
                ToolMessage(
                    content=output or "null",
                    tool_call_id=call_id,
                    name=name or "unknown_tool",
                )
            )
        stop = repeated_call or rounds >= max_tool_rounds
        stop_reason = (
            "repeated_tool_chain"
            if repeated_chain
            else "repeated_or_failed_tool_call"
            if repeated_call
            else "max_tool_rounds"
            if rounds >= max_tool_rounds
            else None
        )
        if stop:
            logger.warning(
                "Tool workflow will force a final response reason=%s rounds=%d",
                stop_reason,
                rounds,
            )
        return {
            "messages": results,
            "active_book": active_book,
            "tool_rounds": rounds,
            "tool_cache": cache,
            "seen_tool_chains": seen_chains,
            "force_final": stop,
            "stop_reason": stop_reason,
        }

    def after_agent(state: AgentState):
        last = next(
            (
                message
                for message in reversed(state.get("messages", []))
                if isinstance(message, AIMessage)
            ),
            None,
        )
        if not last or not last.tool_calls:
            return END
        return "tools"

    graph = StateGraph(AgentState)
    graph.add_node("agent", respond)
    graph.add_node("tools", execute_tools)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", after_agent, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


def initialize_application():
    return tool_registry.initialize_application()


def get_library_folder():
    return tool_registry.get_library_folder()


def set_library_folder(path: str):
    return tool_registry.set_library_folder(path)


def get_reader_snapshot():
    return tool_registry.get_reader_snapshot()


def execute(
    orchestrator,
    messages: list[BaseMessage],
    reader_id: int = 1,
    active_book=None,
    on_event=None,
) -> dict:
    events = []

    def emit(event: str) -> None:
        """Forward execution events on the calling UI thread in observed order."""
        events.append(event)
        if on_event:
            try:
                on_event(event)
            except Exception:
                logger.warning("Activity event callback failed", exc_info=True)

    emit("🧠 Understanding request...")
    try:
        graph = orchestrator
        max_tool_rounds = _max_tool_rounds()
        # State is request-local; never pass mutable caches between Streamlit turns.
        initial_state = {
            "messages": list(messages),
            "reader_id": reader_id,
            "active_book": active_book,
            "tool_rounds": 0,
            "tool_cache": {},
            "seen_tool_chains": [],
            "force_final": False,
        }
        result = None
        # Graph nodes may run in executor threads. LangGraph's custom stream
        # relays node events here so UI callbacks run on the calling thread.
        for mode, chunk in graph.stream(
            initial_state,
            config={"recursion_limit": 2 * max_tool_rounds + 3},
            stream_mode=["values", "custom"],
        ):
            if mode == "custom" and isinstance(chunk, dict):
                event = chunk.get("event")
                if isinstance(event, str):
                    emit(event)
            elif mode == "values":
                result = chunk
        if result is None:
            raise AgentExecutionError("The agent finished without a response state.")
    except (ProviderRequestError, AgentExecutionError):
        raise
    except Exception as error:
        logger.exception("Agent graph failed")
        raise AgentExecutionError(
            "I couldn't complete that request safely. Please try again with a more specific request."
        ) from error

    emit("✅ Response ready.")
    logger.info(
        "Agent request stopped reason=%s tool_rounds=%s",
        result.get("stop_reason", "completed"),
        result.get("tool_rounds", 0),
    )
    return {
        "messages": result["messages"],
        "active_book": result.get("active_book"),
        "events": events,
        "stop_reason": result.get("stop_reason", "completed"),
    }
