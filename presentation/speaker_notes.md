# Smart Library Agent — Speaker Notes

**Target duration:** 7–10 minutes (about one minute per slide)

## Title

Good morning. Our project is Smart Library Agent, a personal reading companion built for the Agentic AI and LLM subject. The idea is to let a reader speak naturally about their collection and reading habits, then have one AI agent decide which deterministic tools to use. The project combines a CSV book catalog, a local file index, and SQLite memory for reading state. It is deliberately smaller than a library management system: the focus is the agent workflow, tool calling, and useful personalization. Replace the editable identity fields on this slide with your name, department, college, and guide before presenting.

---

## The reading problem

Readers can own a large digital collection while still having trouble finding a particular book or choosing what to read next. A public-facing assistant can discuss well-known titles, but it usually does not know which files are in a person’s own folder or what they have already finished. Progress, ratings, and notes can also end up scattered across separate apps or memory. Our project addresses this by connecting the reader’s local file index with catalog metadata and a small persistent reading profile. The goal is not to replace every reading app. It is to make book discovery and personal reading context available through one natural-language interface.

---

## Proposed solution

Smart Library presents the user with a chat interface. The agent receives the conversation and current book context, then the orchestrator sends the request to the configured language model with the registered tool definitions. When a tool is selected, the tool calls a service; the service reads or updates the catalog, SQLite, or the local file index. The results return to the model so it can produce a conversational answer. A request can involve more than one sequential tool call, but this remains one agent. The tools themselves are deterministic and do not call the language model. The interface shows safe execution events, not internal reasoning.

---

## System architecture

The UI calls the Smart Library Agent facade, not the database or services directly. The facade hands the conversation to the request orchestrator, which is implemented as a LangGraph StateGraph. The orchestrator invokes a provider router; OpenRouter is the default route, using LangChain’s OpenAI-compatible integration. Tool definitions are registered centrally and run through deterministic tools. Those tools call services, and the services use the SQLite data-access layer, CSV catalog loader, or filesystem scanner. This is one agent with an internal workflow graph. It is not a multi-agent design. The separation is useful both for reliability and for explaining which component owns each responsibility.

---

## Key features

Version 1 includes catalog search, deterministic recommendations, similar-book suggestions, and series continuation when the catalog has the required metadata. The local scanner indexes PDF, EPUB, and MOBI file metadata. It hashes new or changed files and matches filenames to catalog entries where possible, but it does not extract text. Reading progress is manual: the user reports a page or percentage, or says they finished a book. The agent can also maintain favorites, ratings and reviews, notes, wishlist entries, tags, collections, bookmarks, and a reading journey. An important design choice is that an unmatched local file is still a personal library item and can still receive reader state.

---

## Technology stack

The interface is built with Streamlit and the application is written in Python. LangChain provides tool and message abstractions, while LangGraph provides the StateGraph orchestration workflow. The configured default language model provider is OpenRouter, accessed using the ChatOpenAI-compatible integration. Provider configuration is read from the environment file, so model credentials are not embedded in the application code. SQLite stores the reader profile, reading state, collections, and file index. The catalog starts from CSV and supports optional metadata columns. The project has automated tests with Pytest and uses Ruff and Pyright tooling for code quality checks. The scanner remains metadata-only.

---

## Demo workflow

For the live demonstration, start by choosing one local folder from the sidebar. Ask the agent to scan the library. The scanner walks the folder for supported PDF, EPUB, and MOBI files, stores their metadata, and attempts deterministic catalog matching. The user can then ask a natural-language question about a title. The agent loads the existing index first and uses catalog metadata to enrich a local match. Finally, ask it to save a manual progress update or mark the title as a favorite. These actions are tied to the library item and persisted in SQLite. The repository does not include application screenshots, so this slide uses an editable flow diagram instead.

---

## Conclusion and future work

Smart Library demonstrates a complete agentic workflow within a focused Version 1 scope. A reader can speak naturally, the single agent can choose from deterministic tools, and those tools can act on catalog data, a local file index, and persistent reader state. The local library is the source of truth for ownership and reader actions; catalog matching enriches an item but is optional. Future versions could explore OCR, semantic search, retrieval over book contents, multi-user accounts, cloud synchronization, or a mobile application. None of those are part of the current build. We kept them outside Version 1 so the core agent, tool calls, and clear data boundaries remain straightforward to demonstrate. Thank you; I’m happy to take questions.
