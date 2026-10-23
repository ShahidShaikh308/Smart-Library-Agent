"""Central registry of available tools; the orchestrator dispatches through it."""

from services import application_service
from tools.discovery import (
    find_next_in_series,
    find_similar_books,
    recommend_books,
    search_catalog,
)
from tools.knowledge import get_book_context, load_book_context
from tools.library import (
    find_library_duplicates,
    find_missing_books,
    list_owned_books,
    scan_library,
)
from tools.memory import (
    add_bookmark,
    add_to_collection,
    add_to_wishlist,
    get_book_collections,
    get_reader_profile,
    get_wishlist,
    remove_from_wishlist,
    save_book_note,
    save_book_rating,
    set_book_favorite,
    update_book_tags,
    update_reader_preferences,
)
from tools.reading import (
    get_reading_dashboard,
    get_reading_history,
    mark_book_completed,
    start_reading,
    update_reading_progress,
)

TOOLS = [
    search_catalog,
    recommend_books,
    find_similar_books,
    find_next_in_series,
    update_reading_progress,
    mark_book_completed,
    start_reading,
    get_reading_history,
    get_reading_dashboard,
    scan_library,
    list_owned_books,
    find_missing_books,
    find_library_duplicates,
    get_book_context,
    load_book_context,
    get_reader_profile,
    update_reader_preferences,
    save_book_rating,
    set_book_favorite,
    add_to_wishlist,
    remove_from_wishlist,
    get_wishlist,
    save_book_note,
    add_to_collection,
    get_book_collections,
    update_book_tags,
    add_bookmark,
]
def get_tools():
    return list(TOOLS)


def get_tool_map():
    """Return a fresh name-to-tool mapping for deterministic dispatch."""
    return {tool.name: tool for tool in TOOLS}


def initialize_application():
    return application_service.initialize()


def get_library_folder():
    return application_service.library_folder()


def set_library_folder(path: str):
    return application_service.save_library_folder(path)


def get_reader_snapshot():
    return application_service.reader_snapshot()
