from langchain_core.tools import tool

from services import book_context_service, catalog_service
from tools.output import serialize_tool_result


@tool
def get_book_context(book_id: int):
    """Return catalog-only metadata by ID. Prefer load_book_context for natural-language questions because it also includes the local index and reader context."""
    book = catalog_service.get(book_id)
    return serialize_tool_result(book or {"error": "Book not found in the catalog."})


@tool
def load_book_context(query: str):
    """Load one merged context for a book, author, series, or local filename, including indexed files, catalog metadata, reading progress, ratings, favorites, wishlist, preferences, and related books. Pass a concise title, author, series, or filename. This only queries SQLite and never scans the folder."""
    if not query.strip():
        return serialize_tool_result({"error": "Provide a book, author, series, or filename to look up."})
    return serialize_tool_result(book_context_service.load(query))
