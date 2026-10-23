from langchain_core.tools import tool

from services import reading_service
from tools.output import serialize_tool_result


@tool
def update_reading_progress(
    title: str = "",
    book_id: int = 0,
    current_page: int = -1,
    progress_percent: float = -1,
    library_item_id: int = 0,
):
    """Save manually reported progress by local item, title/filename, or catalog ID."""
    try:
        return serialize_tool_result(
            reading_service.update_progress(
                title or None,
                book_id or None,
                current_page if current_page >= 0 else None,
                progress_percent if progress_percent >= 0 else None,
                library_item_id=library_item_id or None,
            )
        )
    except ValueError as exc:
        return serialize_tool_result({"error": str(exc)})


@tool
def mark_book_completed(
    title: str = "",
    book_id: int = 0,
    completed_at: str = "",
    library_item_id: int = 0,
):
    """Mark a local item or catalog-backed book completed."""
    try:
        return serialize_tool_result(
            reading_service.mark_completed(
                title or None,
                book_id or None,
                completed_at or None,
                library_item_id=library_item_id or None,
            )
        )
    except ValueError as exc:
        return serialize_tool_result({"error": str(exc)})


@tool
def start_reading(title: str = "", book_id: int = 0, library_item_id: int = 0):
    """Start tracking a book in the reader's personal library."""
    try:
        return serialize_tool_result(
            reading_service.start_reading(
                title or None, book_id or None, library_item_id or None
            )
        )
    except ValueError as exc:
        return serialize_tool_result({"error": str(exc)})


@tool
def get_reading_history():
    """Return the reader's saved reading history and current progress."""
    return serialize_tool_result(reading_service.history())


@tool
def get_reading_dashboard():
    """Return reading counts, ratings, and recent journey events."""
    return serialize_tool_result(reading_service.dashboard())
