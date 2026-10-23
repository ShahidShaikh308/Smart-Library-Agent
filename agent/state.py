"""Temporary conversation context passed through the orchestrator."""

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    reader_id: int
    active_book: str | int | None
    tool_rounds: int
    tool_cache: dict[str, str]
    seen_tool_chains: list[str]
    force_final: bool
    stop_reason: str | None
