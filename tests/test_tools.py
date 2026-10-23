"""Focused tests for Version 1 Smart Library tools and services."""

import csv
import json
import math
import sqlite3
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent import orchestrator, providers, tool_registry
from agent.providers import ModelRoute, ModelRouter
from database import database
from database.migrations.migrate import migrate
from services import (
    book_context_service,
    catalog_service,
    local_library_service,
    reading_service,
    recommendation_service,
)
from tools.output import serialize_tool_result
from utils.book_matcher import match_filename


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "smart_library.db")
    catalog_path = tmp_path / "books.csv"
    rows = [
        {
            "title": "Dune",
            "author": "Frank Herbert",
            "genre": "Science Fiction",
            "description": "Desert planet",
            "series": "Dune",
            "series_number": "1",
            "average_rating": "4.5",
        },
        {
            "title": "Dune Messiah",
            "author": "Frank Herbert",
            "genre": "Science Fiction",
            "description": "The sequel",
            "series": "Dune",
            "series_number": "2",
            "average_rating": "4.0",
        },
        {
            "title": "Foundation",
            "author": "Isaac Asimov",
            "genre": "Science Fiction",
            "description": "Galactic future",
            "average_rating": "4.2",
        },
        {
            "title": "Pride and Prejudice",
            "author": "Jane Austen",
            "genre": "Classic",
            "description": "A romance",
        },
    ]
    with catalog_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setattr(database, "CATALOG_PATH", catalog_path)
    database.initialize()
    return {book["title"]: book for book in catalog_service.search("", limit=20)}


def test_schema_flexible_catalog_and_search(catalog):
    assert catalog["Pride and Prejudice"]["page_count"] is None
    assert catalog_service.search("Herbert", limit=10)[0]["title"] == "Dune"


def test_every_registered_tool_is_callable_and_returns_json(catalog, tmp_path):
    folder = tmp_path / "books"
    folder.mkdir()
    (folder / "Dune - Frank Herbert.pdf").write_bytes(b"indexed metadata only")
    local_library_service.set_folder(str(folder))
    dune_id = catalog["Dune"]["id"]
    calls = {
        "search_catalog": {"query": "Dune"},
        "recommend_books": {},
        "find_similar_books": {"book_id": dune_id},
        "find_next_in_series": {"book_id": dune_id},
        "update_reading_progress": {"title": "Dune", "current_page": 12},
        "mark_book_completed": {"title": "Dune"},
        "start_reading": {"title": "Dune"},
        "get_reading_history": {},
        "get_reading_dashboard": {},
        "scan_library": {},
        "list_owned_books": {},
        "find_missing_books": {"query": "Dune"},
        "find_library_duplicates": {},
        "get_book_context": {"book_id": dune_id},
        "load_book_context": {"query": "Dune"},
        "get_reader_profile": {},
        "update_reader_preferences": {"favorite_genres": "Science Fiction"},
        "save_book_rating": {"book_id": dune_id, "rating": 5},
        "set_book_favorite": {"book_id": dune_id, "is_favorite": True},
        "add_to_wishlist": {"book_id": dune_id},
        "remove_from_wishlist": {"book_id": dune_id},
        "get_wishlist": {},
        "save_book_note": {"note": "Great worldbuilding", "title": "Dune"},
        "add_to_collection": {"collection_name": "Favorites", "title": "Dune"},
        "get_book_collections": {"title": "Dune"},
        "update_book_tags": {"tags": ["favorite", "fantasy"], "title": "Dune"},
        "add_bookmark": {"page": 12, "title": "Dune", "note": "A clue"},
    }
    registered = tool_registry.get_tool_map()

    assert set(calls) == set(registered)
    for name, arguments in calls.items():
        result = registered[name].invoke(arguments)
        assert isinstance(result, str) and result.strip(), name
        json.loads(result)


def test_tool_results_are_always_nonempty_json_strings():
    assert serialize_tool_result(None) == "null"
    assert serialize_tool_result([]) == "[]"
    assert serialize_tool_result({"book": "Dune"}) == '{"book": "Dune"}'


def test_tool_serializer_produces_valid_json_for_non_finite_and_untyped_values():
    encoded = serialize_tool_result(
        {"rating": math.nan, "values": {3, 1}, "path": Path("books.csv")}
    )
    decoded = json.loads(encoded)
    assert decoded["rating"] is None
    assert decoded["values"] == [1, 3]
    assert decoded["path"].endswith("books.csv")


def test_empty_legacy_tool_messages_are_repaired_for_api_history():
    history = [ToolMessage(content="", tool_call_id="legacy-call")]
    normalized = orchestrator._normalize_tool_messages(history)
    assert normalized[0].content == "null"


@pytest.mark.parametrize(
    "provider,model,key_name",
    [
        ("openrouter", "cohere/north-mini-code:free", "OPENROUTER_API_KEY"),
        ("openai", "gpt-4o-mini", "OPENAI_API_KEY"),
        ("gemini", "gemini-3.8-flash", "GOOGLE_API_KEY"),
        ("groq", "openai/gpt-oss-120b", "GROQ_API_KEY"),
        ("ollama", "llama3.1:8b", None),
    ],
)
def test_provider_factory_switches_from_configuration(
    monkeypatch, provider, model, key_name
):
    monkeypatch.setattr(providers, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        providers, "_provider_model", lambda selected, name: (selected, name)
    )
    monkeypatch.setenv("LLM_PROVIDER", provider)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    if key_name:
        monkeypatch.setenv(key_name, "test-key")
    router = providers.create_model_router([])
    assert [(route.provider, route.model_name) for route in router.routes] == [
        (provider, model)
    ]


def test_provider_factory_rejects_unknown_provider_cleanly(monkeypatch):
    monkeypatch.setattr(providers, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("LLM_PROVIDER", "unknown-provider")

    with pytest.raises(providers.ProviderRequestError, match="Unsupported LLM_PROVIDER"):
        providers.create_model_router([])


def test_openrouter_default_constructs_openai_compatible_chat_model(monkeypatch):
    from langchain_openai import ChatOpenAI

    monkeypatch.setattr(providers, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    route = providers.create_model_router([]).routes[0]

    assert route.model_name == "cohere/north-mini-code:free"
    assert isinstance(route.model, ChatOpenAI)
    assert str(route.model.root_client.base_url).rstrip("/") == "https://openrouter.ai/api/v1"


def test_openrouter_fallback_models_are_configured_in_order(monkeypatch):
    monkeypatch.setattr(providers, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(providers, "_provider_model", lambda selected, name: name)
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "primary/model")
    monkeypatch.setenv(
        "OPENROUTER_FALLBACK_MODELS", "backup/one,backup/two,primary/model"
    )
    router = providers.create_model_router([])
    assert [route.model_name for route in router.routes] == [
        "primary/model",
        "backup/one",
        "backup/two",
    ]


def test_invalid_provider_numeric_settings_fall_back_safely(monkeypatch, caplog):
    monkeypatch.setattr(providers, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(providers, "_provider_model", lambda selected, name: name)
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("LLM_RETRIES", "not-a-number")
    monkeypatch.setenv("LLM_RETRY_BASE_SECONDS", "NaN")
    monkeypatch.setenv("LLM_RETRY_MAX_SECONDS", "-10")

    router = providers.create_model_router([])

    assert router.retries == 2
    assert router.backoff_seconds == 1.0
    assert router.max_backoff_seconds == 0.0
    assert "Invalid LLM_RETRIES" in caplog.text
    assert "Invalid LLM_RETRY_BASE_SECONDS" in caplog.text


def test_rating_and_favorite_do_not_create_reading_records(catalog):
    dune_id = catalog["Dune"]["id"]
    reading_service.save_rating(dune_id, 5, "Loved it")
    reading_service.set_favorite(dune_id, True)
    assert database.get_reading_record(dune_id) is None
    assert database.recommendation_data()["favorites"] == [{"book_id": dune_id}]
    assert reading_service.dashboard()["average_rating"] == 5.0


def test_recommendation_favorite_is_not_excluded_and_gets_reason(catalog):
    dune_id = catalog["Dune"]["id"]
    reading_service.set_favorite(dune_id, True)
    result = recommendation_service.recommend()
    dune = next(book for book in result["recommendations"] if book["id"] == dune_id)
    assert "saved favorite" in dune["match_reasons"]


def test_progress_and_journey_are_recorded(catalog):
    result = reading_service.update_progress(title="Dune", current_page=135)
    assert result["current_page"] == 135
    assert database.reading_journey()[0]["event_type"] == "progress_updated"


def test_unmatched_local_item_supports_favorite_rating_progress_notes_and_collection(
    catalog, tmp_path
):
    folder = tmp_path / "books"
    folder.mkdir()
    (folder / "Lord_of_Mysteries.pdf").write_bytes(b"metadata only")
    local_library_service.set_folder(str(folder))
    local_library_service.scan()
    item = database.search_library_files("Lord of Mysteries")[0]
    item_id = item["library_item_id"]

    reading_service.set_favorite(None, True, title="Lord of Mysteries")
    reading_service.save_rating(None, 5, "Intriguing story", title="Lord of Mysteries")
    progress = reading_service.update_progress(
        title="Lord of Mysteries", current_page=135
    )
    reading_service.add_note("Discuss the mystery system", title="Lord of Mysteries")
    reading_service.add_to_collection("Fantasy", title="Lord of Mysteries")
    reading_service.update_tags(
        ["mystery", "fantasy"], title="Lord of Mysteries"
    )
    reading_service.add_bookmark(135, "Reveal", title="Lord of Mysteries")

    state = database.library_item_state(item_id)
    assert state["is_favorite"] == 1
    assert state["rating"] == 5
    assert state["current_page"] == 135
    assert state["status"] == "reading"
    assert "mystery system" in state["notes"]
    assert database.collections(item_id)[0]["name"] == "Fantasy"
    assert progress["library_item_id"] == item_id
    context = book_context_service.load("Lord of Mysteries")
    assert context["local_files"][0]["is_favorite"] is True
    assert context["local_files"][0]["rating"] == 5
    assert context["local_files"][0]["notes"] == "Discuss the mystery system"
    assert context["local_files"][0]["collections"] == "Fantasy"
    assert context["local_files"][0]["tags"] == '["mystery", "fantasy"]'
    assert context["local_files"][0]["bookmarks"] == '[{"page": 135, "note": "Reveal"}]'
    assert database.query_one("SELECT COUNT(*) AS count FROM reading_records")["count"] == 0
    assert database.query_one("SELECT COUNT(*) AS count FROM favorites")["count"] == 0
    assert database.query_one("SELECT COUNT(*) AS count FROM book_ratings")["count"] == 0


def test_catalog_book_reader_actions_use_virtual_library_item(catalog):
    dune_id = catalog["Dune"]["id"]

    reading_service.set_favorite(dune_id, True)
    reading_service.save_rating(dune_id, 4, "A classic")
    record = reading_service.update_progress(title="Dune", progress_percent=40)

    assert record["status"] == "reading"
    assert record["library_item_id"]
    assert record["book"]["id"] == dune_id
    assert database.get_reading_record(dune_id) is None
    rec_data = database.recommendation_data()
    assert {item["book_id"] for item in rec_data["favorites"]} == {dune_id}


def test_author_information_improves_match_confidence():
    books = [{"id": 1, "title": "Dune", "author": "Frank Herbert"}]
    title_only = match_filename("Dune.pdf", books)[1]
    title_and_author = match_filename("Dune - Frank Herbert.epub", books)[1]
    assert title_only is not None and title_and_author is not None
    assert title_and_author > title_only


def test_library_scan_replaces_index_transactionally(catalog, tmp_path):
    folder = tmp_path / "books"
    folder.mkdir()
    (folder / "Dune - Frank Herbert.epub").write_bytes(b"metadata only")
    local_library_service.set_folder(str(folder))
    scan = local_library_service.scan()
    assert scan["indexed_count"] == 1
    assert scan["matched_count"] == 1
    assert local_library_service.files()[0]["matched_title"] == "Dune"


def test_empty_library_scan_succeeds_and_missing_folder_preserves_index(
    catalog, tmp_path
):
    folder = tmp_path / "books"
    folder.mkdir()
    local_library_service.set_folder(str(folder))

    empty_result = local_library_service.scan()
    assert empty_result["indexed_count"] == 0

    book_file = folder / "Dune.pdf"
    book_file.write_bytes(b"indexed")
    local_library_service.scan()
    indexed_before = database.library_files()
    book_file.unlink()
    folder.rmdir()

    with pytest.raises(ValueError, match="unavailable"):
        local_library_service.scan()
    assert database.library_files() == indexed_before


def test_book_context_merges_local_catalog_and_reader_data(catalog, tmp_path):
    folder = tmp_path / "books"
    folder.mkdir()
    (folder / "Dune - Frank Herbert.epub").write_bytes(b"ebook metadata source")
    local_library_service.set_folder(str(folder))
    local_library_service.scan()

    dune_id = catalog["Dune"]["id"]
    reading_service.update_progress(title="Dune", current_page=135)
    reading_service.save_rating(dune_id, 5, "Loved the worldbuilding")
    reading_service.set_favorite(dune_id, True)
    reading_service.wishlist(True, catalog["Foundation"]["id"])
    from services import reader_service

    reader_service.update_preferences(favorite_genres="Science Fiction")

    result = book_context_service.load("Dune")
    match = result["matches"][0]
    assert match["book"]["title"] == "Dune"
    assert match["local_files"][0]["filename"] == "Dune - Frank Herbert.epub"
    assert result["local_files"][0]["file_hash"]
    assert result["local_files"][0]["filename"] == "Dune - Frank Herbert.epub"
    assert match["reading_record"]["current_page"] == 135
    assert match["rating"] == 5
    assert match["review"] == "Loved the worldbuilding"
    assert match["is_favorite"] is True
    assert result["reader_profile"]["favorite_genres"] == "Science Fiction"
    assert result["library_index"]["initialized"] is True
    assert any(book["title"] == "Dune Messiah" for book in match["related_books"])


def test_book_context_prefers_partial_local_filename_over_catalog(catalog, tmp_path):
    folder = tmp_path / "books"
    folder.mkdir()
    (folder / "Lord_of_Mysteries.pdf").write_bytes(b"metadata only")
    local_library_service.set_folder(str(folder))
    local_library_service.scan()

    result = book_context_service.load("Lord of Mysteries")

    assert result["local_files"][0]["filename"] == "Lord_of_Mysteries.pdf"
    assert result["local_files"][0]["catalog_book_id"] is None
    assert result["matches"] == []


def test_book_context_uses_catalog_when_no_local_file_matches(catalog, tmp_path):
    folder = tmp_path / "books"
    folder.mkdir()
    (folder / "Foundation.pdf").write_bytes(b"metadata only")
    local_library_service.set_folder(str(folder))
    local_library_service.scan()

    result = book_context_service.load("Dune")

    assert result["local_files"] == []
    assert result["matches"][0]["book"]["title"] == "Dune"


def test_book_lookup_prompt_requires_local_context_before_catalog_search():
    from agent.prompts import build_system_prompt

    prompt = build_system_prompt()

    assert "first call load_book_context" in prompt
    assert "If local files are found, lead with the user's copy/copies" in prompt
    assert "If no local file matches, use catalog matches as fallback" in prompt


def test_incremental_scan_skips_unchanged_files_and_updates_changes(
    catalog, tmp_path, monkeypatch
):
    folder = tmp_path / "books"
    folder.mkdir()
    dune = folder / "Dune - Frank Herbert.epub"
    dune.write_bytes(b"first version")
    local_library_service.set_folder(str(folder))

    hash_calls = []
    original_hash = local_library_service.hash_file

    def record_hash(path):
        hash_calls.append(path)
        return original_hash(path)

    monkeypatch.setattr(local_library_service, "hash_file", record_hash)
    first = local_library_service.scan()
    assert first["new_count"] == 1
    assert first["changes_detected"] is True
    assert len(hash_calls) == 1
    first_hash = database.library_files()[0]["file_hash"]

    second = local_library_service.scan()
    assert second["unchanged_count"] == 1
    assert second["changes_detected"] is False
    assert len(hash_calls) == 1

    dune.write_bytes(b"changed Dune edition")
    foundation = folder / "Foundation - Isaac Asimov.pdf"
    foundation.write_bytes(b"new book")
    updated = local_library_service.scan()
    assert updated["updated_count"] == 1
    assert updated["new_count"] == 1
    assert updated["changes_detected"] is True
    assert updated["indexed_count"] == 2
    assert len(hash_calls) == 3
    changed_dune_hash = next(
        row["file_hash"]
        for row in database.library_files()
        if row["filename"] == dune.name
    )
    assert changed_dune_hash != first_hash

    dune.unlink()
    removed = local_library_service.scan()
    assert removed["removed_count"] == 1
    assert [row["filename"] for row in local_library_service.files()] == [
        foundation.name
    ]


def test_incomplete_library_walk_does_not_delete_existing_index(
    catalog, tmp_path, monkeypatch
):
    from utils import file_scanner

    folder = tmp_path / "books"
    folder.mkdir()
    (folder / "Dune - Frank Herbert.epub").write_bytes(b"indexed")
    local_library_service.set_folder(str(folder))
    local_library_service.scan()
    indexed_before = database.library_files()
    scan_time_before = database.library_scan_status()["last_scanned_at"]

    def failed_walk(_root, onerror):
        onerror(PermissionError("inaccessible subdirectory"))
        yield  # pragma: no cover - the callback must abort before yielding

    monkeypatch.setattr(file_scanner.os, "walk", failed_walk)
    with pytest.raises(PermissionError):
        local_library_service.scan()

    assert database.library_files() == indexed_before
    assert database.library_scan_status()["last_scanned_at"] == scan_time_before


def test_unreadable_new_file_is_not_counted_as_indexed(catalog, tmp_path, monkeypatch):
    folder = tmp_path / "books"
    folder.mkdir()
    (folder / "Dune - Frank Herbert.epub").write_bytes(b"new file")
    local_library_service.set_folder(str(folder))

    def unreadable_hash(_path):
        raise OSError("unreadable")

    monkeypatch.setattr(local_library_service, "hash_file", unreadable_hash)

    result = local_library_service.scan()

    assert result["failed_count"] == 1
    assert result["indexed_count"] == 0
    assert database.library_files() == []


def test_book_context_lookup_does_not_scan_the_folder(catalog, tmp_path, monkeypatch):
    folder = tmp_path / "books"
    folder.mkdir()
    (folder / "Dune.pdf").write_bytes(b"metadata only")
    local_library_service.set_folder(str(folder))
    local_library_service.scan()

    def unexpected_scan():
        raise AssertionError("A context lookup must not scan the filesystem")

    monkeypatch.setattr(local_library_service, "scan", unexpected_scan)
    result = book_context_service.load("Dune")
    assert result["matches"][0]["book"]["title"] == "Dune"


def test_agent_answer_receives_indexed_local_metadata(catalog, tmp_path, monkeypatch):
    folder = tmp_path / "books"
    folder.mkdir()
    (folder / "Dune - Frank Herbert.epub").write_bytes(b"indexed file")
    local_library_service.set_folder(str(folder))
    local_library_service.scan()

    class ContextAnswerModel:
        calls = 0

        def bind_tools(self, _tools):
            return self

        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "load_book_context",
                            "args": {"query": "Dune"},
                            "id": "context-call",
                            "type": "tool_call",
                        }
                    ],
                )
            context_message = next(
                message
                for message in reversed(messages)
                if isinstance(message, ToolMessage)
            )
            assert "Dune - Frank Herbert.epub" in context_message.content
            assert "Frank Herbert" in context_message.content
            return AIMessage(content="Dune is indexed in your local library.")

    model = ContextAnswerModel()
    router = ModelRouter([ModelRoute("fake", "fake", model)], [], retries=0)
    monkeypatch.setattr(orchestrator, "create_model_router", lambda _tools: router)

    result = orchestrator.execute(
        orchestrator.build_orchestrator(),
        [HumanMessage(content="Tell me about Dune")],
    )

    assert result["messages"][-1].content == "Dune is indexed in your local library."
    assert result["active_book"] == "Dune"


def test_library_index_migration_adds_hash_and_last_scan_columns(tmp_path):
    conn = sqlite3.connect(tmp_path / "library.db")
    migrate(conn, database.SCHEMA_PATH)
    file_columns = {row[1] for row in conn.execute("PRAGMA table_info(library_files)")}
    settings_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(library_settings)")
    }
    assert "file_hash" in file_columns
    assert "last_scanned_at" in settings_columns
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
    conn.close()


def test_failed_migration_rolls_back_partial_schema_changes(tmp_path):
    schema_path = tmp_path / "schema.sql"
    schema_path.write_text(
        "CREATE TABLE base(id INTEGER PRIMARY KEY); PRAGMA user_version=1;",
        encoding="utf-8",
    )
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "002_partial.sql").write_text(
        "CREATE TABLE partial(id INTEGER PRIMARY KEY); INVALID SQL;",
        encoding="utf-8",
    )
    conn = sqlite3.connect(tmp_path / "migration.db")

    with pytest.raises(sqlite3.Error):
        migrate(conn, schema_path)

    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "base" in tables
    assert "partial" not in tables
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    conn.close()


def test_migrations_separate_preferences_and_preserve_legacy_values(tmp_path):
    conn = sqlite3.connect(tmp_path / "legacy.db")
    conn.executescript(database.SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute(
        "INSERT INTO catalog_books(title,author,genre,description) VALUES('Dune','Frank Herbert','SF','Desert planet')"
    )
    conn.execute(
        "INSERT INTO reading_records(book_id,status,rating,review,is_favorite) VALUES(1,'read',4,'Legacy review',1)"
    )
    migrate(conn, database.SCHEMA_PATH)
    assert conn.execute(
        "SELECT rating,review FROM book_ratings WHERE book_id=1"
    ).fetchone() == (4, "Legacy review")
    assert conn.execute("SELECT book_id FROM favorites WHERE book_id=1").fetchone() == (
        1,
    )
    item_state = conn.execute(
        "SELECT status,rating,review,is_favorite FROM library_item_state"
    ).fetchone()
    assert item_state == ("read", 4, "Legacy review", 1)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(reading_records)")}
    assert not {"rating", "review", "is_favorite"} & columns
    conn.close()
