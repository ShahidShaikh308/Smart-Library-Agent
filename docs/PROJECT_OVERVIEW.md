# Smart Library Agent — Project Overview

**Tagline:** Your Personal AI Reading Companion  
**Course:** Agentic AI and LLM  
**Version:** 1

## Project vision

Smart Library is a single-agent reading companion that helps one local reader discover books, maintain a manual reading journey, remember preferences, and index their personal collection. The project demonstrates natural-language intent handling, LLM-selected tool use, deterministic service execution, persistent memory, and grounded natural-language responses. It is not a library circulation management system.

## Design principles

- **One agent:** Request coordination is software orchestration, not a second agent.
- **Layered dependencies:** UI → Agent → Request Orchestrator → Tool Registry → Tools → Services → Data sources.
- **Tools stay deterministic:** Tools do one job, return structured results, and never call the LLM.
- **Services stay model-independent:** Business and data operations do not depend on Streamlit or an LLM.
- **Data access is contained:** SQLite statements live in `database/`; the UI never accesses the database directly.
- **Catalog flexibility:** Required CSV columns are title, author, genre, and description. Optional columns may be absent.
- **Manual reading updates:** Progress changes only from what the reader tells the agent.
- **Local library means file index:** Explicitly scan PDF, EPUB, and MOBI metadata incrementally; hash only new or changed files and never extract text, OCR, or build RAG.
- **Private reasoning stays private:** The UI shows execution events, never chain-of-thought or an explicit reasoning plan.
- **Keep Version 1 focused:** One reader and one local folder; no accounts, cloud sync, scraping, voice, workers, plugins, or extra agents.

## Architecture

```text
Streamlit UI
    ↓
Smart Library Agent
    ↓
Request Orchestrator
    ↓
Tool Registry
    ↓
Tools
    ↓
Services
    ↓
Database / CSV / Local Files
```

The Request Orchestrator uses a provider factory configured from `.env`. Supported providers are OpenRouter, OpenAI, Gemini, Groq, and Ollama. OpenRouter and OpenAI use LangChain's OpenAI-compatible chat integration; Gemini, Groq, and Ollama use their corresponding LangChain integrations. The orchestrator executes tools sequentially, validates and serializes each tool result as non-empty JSON, caches identical calls within the request, and forces a final answer after repeated calls or a bounded number of tool rounds. OpenRouter can retry transient 429/503/504 failures and optionally move through configured fallback models. Set `LLM_PROVIDER`, `LLM_MODEL`, and the provider-specific API key in `.env`; see `.env.example` for the full configuration.

## Request flow

1. The reader enters a natural-language request in Streamlit.
2. Streamlit sends the message and temporary conversation state to `agent/agent.py`.
3. The Request Orchestrator supplies conversation context, system instructions, and registered tools to the LLM.
4. The LLM selects zero or more tools. Sequential calls are supported through a bounded orchestration loop.
5. The Tool Registry provides the callable tool to the sequential execution layer. Duplicate calls are served from the request-local result cache; repeated or failed calls trigger a final response.
6. The tool invokes a service; the service reads or writes SQLite, reads the CSV catalog, or scans filesystem metadata.
7. Structured results return to the LLM, which generates the user-facing response.
8. The agent returns the response and execution events to the UI.

## Deterministic recommendation pipeline

Recommendations use a transparent score; there are no embeddings, vector database, semantic search, collaborative filtering, or learned ranking model.

1. Load saved favorite genres/authors and reader state attached to library items.
2. Exclude catalog books represented by a reading item or wishlist item.
3. Score each remaining catalog book: +5 for a favorite genre, +5 for a favorite author, +3 for sharing a genre with a completed book, and +6 for continuing a series currently being read.
4. Add small bounded tie-break contributions from catalog average rating and popularity when those fields exist. Add a small bonus when a file in the personal library matches the book.
5. Sort by score, then rating, then title; return the top five with match reasons.

All inputs come from SQLite/catalog metadata and the filesystem index. Missing optional fields contribute no score.

## Folder structure

```text
app.py                         Streamlit chat, single folder picker, activity panel
agent/agent.py                 Application-facing Smart Library Agent
agent/orchestrator.py          LLM and sequential tool workflow
agent/tool_registry.py         Central callable-tool registry
agent/state.py                 Temporary conversation context
agent/prompts.py               Grounding, tool use, and response instructions
tools/                         LLM-callable deterministic interfaces
services/                      Catalog, reader, reading, recommendation, library logic
database/database.py           SQLite connection and data-access functions
database/schema.sql            Version 1 schema
database/catalog_loader.py     Flexible CSV import
database/migrations/           Versioned SQLite schema changes
models/                         Shared typed data structures
utils/                          File scan/matching, dates, configuration, logging
books.csv                       Primary book catalog
docs/PROJECT_OVERVIEW.md        College-report project overview
tests/                          Automated checks
```

## Module responsibilities

- **Streamlit UI:** Chat interface, initial/change folder picker, dashboard, and tool execution activity. It calls the Agent facade only.
- **Smart Library Agent:** App interface and transfer of conversation state/results.
- **Request Orchestrator:** Coordinates LLM calls, tool calls, sequential execution, merged book-context retrieval, and final response generation.
- **Tool Registry:** Registers and exposes the supported tools to the agent.
- **Tools:** Validate arguments and call services; return structured data only.
- **Services:** Implement catalog queries, merged book context, progress/memory updates, deterministic recommendations, and incremental local-file indexing.
- **Database:** Own SQLite schema, migrations, catalog import, targeted context queries, incremental index synchronization, and parameterized SQL operations.
- **Models:** Typed shared shapes for catalog books, reader-owned library items, merged context, profile, and reading records.
- **Utilities:** Deterministic filesystem scanning and matching, date helpers, configuration, and logging.

## Database design

- `catalog_books`: Global CSV-derived catalog. Requires title, author, genre, description. Optional series, series number, publication year, ISBN, publisher, language, average rating, page count, and popularity.
- `reader_profile`: Singleton local reader preferences and goals.
- `library_items`: Reader-owned primary records for indexed local files, with optional catalog enrichment. Catalog-only records are represented by virtual items.
- `library_item_state`: Favorite, rating/review, notes, reading status/progress, wishlist, tags, bookmarks, and last-opened state keyed by library item.
- `library_item_journey`: Timestamped progress, completion, rating, note, and preference events keyed by library item.
- `reader_collections` and `library_item_collections`: User-defined collections and their library-item membership.
- `reading_records`, `reading_journey`, `favorites`, `book_ratings`, and `wishlist`: Retained as legacy tables for non-destructive upgrade and migration provenance; new reader actions write to library-item tables.
- `library_settings`: One selected folder path and last successful scan time.
- `library_files`: Indexed filename/path/extension/size/modified time, SHA-256 for new/changed files, optional catalog match/confidence, and per-file scan time.

Library items may reference a catalog book but remain usable without one. No reader accounts or profile switching are present.

## Tool layer

- **Discovery:** Search, deterministic recommendation, similar books, next in series.
- **Reading:** Manual start/progress/completion, item history, dashboard.
- **Library:** Scan, list owned files, find missing books, and identify duplicate matches.
- **Knowledge:** `load_book_context` returns indexed reader-owned library items first, including file metadata, matched catalog entry, reading status/progress, rating/review, favorite/wishlist state, notes, and collections. Catalog metadata enriches a local item when matched; an unmatched file remains fully manageable. Catalog-only records use a virtual library item for backward compatibility. Broad discovery still uses catalog search/recommendations.
- **Memory:** Read/update profile, rating/review, favorite, wishlist, notes, and collection membership for library items.

The local scanner recognizes `.pdf`, `.epub`, and `.mobi`. An explicit scan enumerates supported file metadata, hashes and rematches only new or changed files, upserts those rows, and removes paths that no longer exist. Unchanged rows are retained; file size, modified time, SHA-256, and scan time support incremental synchronization. Ordinary context lookups query SQLite and never touch the folder. File contents are not extracted. Without a background watcher, filesystem changes are noticed on an explicit scan/refresh rather than on each book question.

## Execution events

The activity panel displays fixed events such as “Understanding request,” “Searching book catalog,” “Checking personal library,” “Preparing recommendation,” “Updating memory,” and “Response ready.” These are execution labels, not the model's plan or reasoning.

## Future scope

Potential later work includes document retrieval/RAG, additional catalog sources, more advanced matching, and multi-user/cloud features. These are explicitly outside Version 1.
