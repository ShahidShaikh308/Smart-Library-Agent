"""Streamlit conversational UI; all application access goes through the agent facade."""

import logging
import tkinter as tk
from tkinter import filedialog

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage

from agent.agent import (
    create_agent,
    get_library_folder,
    get_reader_snapshot,
    handle_message,
    initialize,
    set_library_folder,
)
from agent.orchestrator_errors import AgentExecutionError, ProviderRequestError
from utils.logging_config import configure_logging

st.set_page_config(
    page_title="Smart Library | Reading Companion", page_icon="📚", layout="wide"
)
configure_logging()
logger = logging.getLogger(__name__)


@st.cache_resource
def boot():
    initialize()
    return create_agent()


def choose_folder():
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    selected = filedialog.askdirectory(title="Choose your book library folder")
    root.destroy()
    return selected


try:
    agent = boot()
except (AgentExecutionError, ProviderRequestError, ValueError) as exc:
    st.error(f"Could not start Smart Library: {exc}")
    st.info(
        "Check the configured LLM provider and make sure the catalog CSV is available."
    )
    st.stop()
except Exception:
    logger.exception("Smart Library startup failed")
    st.error("Could not start Smart Library because an internal startup step failed.")
    st.info("Check the application logs, provider settings, database, and catalog CSV.")
    st.stop()

if "messages" not in st.session_state:
    st.session_state.messages = []
if "active_book" not in st.session_state:
    st.session_state.active_book = None
if "turn_events" not in st.session_state:
    st.session_state.turn_events = {}

st.sidebar.title("📚 Your reading space")
folder = get_library_folder()
if folder:
    st.sidebar.caption("Personal library folder")
    st.sidebar.code(folder, language=None)
else:
    st.sidebar.info("Choose your book folder to enable local-library scans.")
if st.sidebar.button("Choose / change folder", use_container_width=True):
    selected = choose_folder()
    if selected:
        try:
            set_library_folder(selected)
            st.sidebar.success("Library folder saved.")
            st.rerun()
        except ValueError as exc:
            st.sidebar.error(str(exc))

snapshot = get_reader_snapshot()
profile = snapshot["profile"]
dashboard = snapshot["dashboard"]
with st.sidebar.expander("Reading dashboard", expanded=True):
    counts = dashboard["counts"]
    st.metric("Books completed", counts["read"])
    st.caption(f"Reading {counts['reading']} · Want to read {counts['want_to_read']}")
    if dashboard["average_rating"]:
        st.caption(f"Average rating: {dashboard['average_rating']} / 5")
    if profile.get("favorite_genres"):
        st.caption(f"Favorite genres: {profile['favorite_genres']}")
    if profile.get("reading_goals"):
        st.caption(f"Goal: {profile['reading_goals']}")
if snapshot["wishlist"]:
    with st.sidebar.expander(f"Wishlist ({len(snapshot['wishlist'])})"):
        for book in snapshot["wishlist"]:
            st.write(f"{book['title']} — {book['author']}")
if st.sidebar.button("Clear conversation"):
    st.session_state.messages = []
    st.session_state.active_book = None
    st.session_state.turn_events = {}
    st.rerun()

st.title("Smart Library")
st.caption("Your Personal AI Reading Companion")
st.markdown(
    "Discover your next book, keep your reading journey, and ask about books in a natural conversation."
)


def display_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            if isinstance(block, dict) and block.get("type") == "text"
            else ""
            for block in content
        )
    return str(content)


for index, message in enumerate(st.session_state.messages):
    if isinstance(message, HumanMessage):
        with st.chat_message("user"):
            st.markdown(str(message.content))
    elif (
        isinstance(message, AIMessage)
        and message.content
        and not message.tool_calls
        and not message.invalid_tool_calls
    ):
        with st.chat_message("assistant"):
            allowed_events = {
                "🧠 Understanding request...",
                "🤖 Consulting the reading assistant...",
                "📚 Searching book catalog...",
                "🔎 Loading book and personal context...",
                "⭐ Preparing recommendation...",
                "📂 Checking personal library...",
                "📖 Loading reader profile...",
                "💾 Updating memory...",
                "💾 Updating reading progress...",
                "💾 Updating reading journey...",
                "🔎 Retrieving book information...",
                "✅ Tool step complete.",
                "✅ Response ready.",
            }
            events = [
                event
                for event in st.session_state.turn_events.get(str(index), [])
                if event in allowed_events
            ]
            if events:
                with st.status("Agent activity", expanded=False):
                    for event in events:
                        st.write(event)
            st.markdown(display_content(message.content))

prompt = st.chat_input("Ask about books or your reading...")
if prompt:
    new_messages = st.session_state.messages + [HumanMessage(content=prompt)]
    with st.status("Smart Library is working...", expanded=True) as activity:

        def show_event(event):
            activity.write(event)

        try:
            result = handle_message(
                agent, new_messages, 1, st.session_state.active_book, show_event
            )
            st.session_state.messages = result["messages"]
            st.session_state.active_book = result["active_book"]
        except (AgentExecutionError, ProviderRequestError, ValueError) as exc:
            st.error(f"The agent could not complete that request: {exc}")
        except Exception:
            logger.exception("Unhandled chat request error")
            st.error(
                "The agent could not complete that request because of an internal error. Please try again."
            )
        else:
            st.session_state.turn_events[str(len(st.session_state.messages) - 1)] = (
                result["events"]
            )
            activity.update(label="Response ready", state="complete", expanded=False)
            st.rerun()
