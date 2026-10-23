# Smart Library Agent

**Your Personal AI Reading Companion** · College project for Agentic AI and LLM

Smart Library demonstrates a single LLM agent that understands natural-language reading requests, selects and runs tools, updates a reader's local memory, and produces a natural response. It is intentionally not a Library Management System.

## Version 1

- Discover and search books in the flexible-schema `books.csv` catalog.
- Get deterministic recommendations from saved preferences, reading history, series, catalog ratings/popularity, and indexed owned books.
- Track progress manually by page or percentage; store completion, ratings, reviews, favorites, notes, wishlist, and collections on reader-owned library items, including indexed files without catalog matches.
- Index one local folder for PDF, EPUB, and MOBI files. Explicit scans incrementally add/update changed files and remove deleted paths; unchanged file contents are not rehashed. The scanner stores metadata, a hash for new/changed files, and optional catalog match/confidence. It does not extract text, use OCR, or build RAG.
- Load merged book context from reader-owned library items first, with optional catalog enrichment for matched titles. Book questions never trigger a filesystem scan.
- Ask book questions using catalog metadata and the LLM's existing knowledge.
- See sanitized execution events in the chat UI. Chain-of-thought is never displayed.

See [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) for architecture, data model, module responsibilities, and the recommendation pipeline.

## Architecture

```text
Streamlit → Smart Library Agent → Request Orchestrator → Tool Registry
          → Tools → Services → Database / CSV / Local Files
```

There is one reader profile and one configured library folder. The UI accesses application data only through the agent facade. Tools do not call the LLM; services do not depend on Streamlit or the LLM; SQL stays in `database/`.

## Setup

```powershell
py -3.10 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
streamlit run app.py
```

Configure `LLM_PROVIDER` and `LLM_MODEL` in `.env`; provider-specific credentials are also read from that file. Supported providers are OpenRouter (default), OpenAI, Gemini, Groq, and Ollama. For OpenRouter, set `OPENROUTER_API_KEY`. Optional comma-separated fallback model names can be configured with `OPENROUTER_FALLBACK_MODELS`; other providers use `LLM_FALLBACK_MODELS`. Transient rate-limit and availability failures use bounded retries and then move to the next configured model. See `.env.example` for settings. The initial catalog import happens automatically.

At first launch, choose your personal library folder in the sidebar. Later, ask “Scan my library”, “Scan again”, or “Refresh my library”; the saved folder is reused. The sidebar picker can change the single configured folder.

## Demo prompts

- “Find a highly rated fantasy book about a school of magic.”
- “I'm 60% finished with Dune.”
- “I finished The Hobbit yesterday and loved it.”
- “I usually enjoy mystery and historical fiction. Remember that.”
- “Recommend a book based on my reading history.”
- “Scan my library and tell me which books you matched.”
- “Who wrote it?” after discussing a book, to demonstrate conversation context.

## Project structure

```text
app.py                 Streamlit UI
agent/                 Agent facade, orchestrator, tool registry, state, prompts
tools/                 Discovery, reading, library, knowledge, and memory tools
services/              Catalog, reader, reading, recommendation, and library services
database/              SQLite data access, schema, migrations, CSV loader
models/                Shared typed data models
utils/                 Scanner, matcher, date, config, and logging helpers
docs/                  Project overview for the college report
books.csv              Primary catalog
tests/                 Automated checks
```

## Limitations

- One local reader, no login or authentication.
- One library folder; no cloud sync.
- Local documents are indexed by metadata only. The agent cannot answer from their full text.
- Optional CSV columns are used when present and ignored when absent.
- No scraping, Goodreads integration, OCR, voice, background workers, plugins, event bus, or multi-agent system.

### Author: Shahid Arif Shaikh
### Project: Smart Library Agent
### License: MIT