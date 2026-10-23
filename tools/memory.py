from langchain_core.tools import tool

from services import reader_service, reading_service
from tools.output import serialize_tool_result


@tool
def get_reader_profile():
    """Return saved reading preferences for the local reader."""
    return serialize_tool_result(reader_service.get_profile())


@tool
def update_reader_preferences(
    favorite_genres: str = "",
    favorite_authors: str = "",
    favorite_books: str = "",
    reading_goals: str = "",
):
    """Save any reader preferences or goals explicitly provided by the user; leave unrelated fields blank to preserve them."""
    return serialize_tool_result(
        reader_service.update_preferences(
            favorite_genres, favorite_authors, favorite_books, reading_goals
        )
    )


@tool
def save_book_rating(
    rating: int,
    book_id: int = 0,
    review: str = "",
    title: str = "",
    library_item_id: int = 0,
):
    """Store a 1-to-5 rating/review by library item, title, or catalog ID."""
    try:
        return serialize_tool_result(
            reading_service.save_rating(
                book_id or None, rating, review, title or None, library_item_id or None
            )
        )
    except ValueError as exc:
        return serialize_tool_result({"error": str(exc)})


@tool
def set_book_favorite(
    book_id: int = 0,
    is_favorite: bool = True,
    title: str = "",
    library_item_id: int = 0,
):
    """Set or clear a reader-owned local item or catalog-backed favorite."""
    try:
        return serialize_tool_result(
            reading_service.set_favorite(
                book_id or None,
                is_favorite,
                title or None,
                library_item_id or None,
            )
        )
    except ValueError as exc:
        return serialize_tool_result({"error": str(exc)})


@tool
def add_to_wishlist(
    book_id: int = 0, title: str = "", library_item_id: int = 0
):
    """Add a local item or catalog-backed book to the wishlist."""
    try:
        return serialize_tool_result(
            reading_service.wishlist(
                True, book_id or None, title or None, library_item_id or None
            )
        )
    except ValueError as exc:
        return serialize_tool_result({"error": str(exc)})


@tool
def remove_from_wishlist(
    book_id: int = 0, title: str = "", library_item_id: int = 0
):
    """Remove a local item or catalog-backed book from the wishlist."""
    try:
        return serialize_tool_result(
            reading_service.wishlist(
                False, book_id or None, title or None, library_item_id or None
            )
        )
    except ValueError as exc:
        return serialize_tool_result({"error": str(exc)})


@tool
def get_wishlist():
    """List the reader's wishlist."""
    return serialize_tool_result(reading_service.wishlist_items())


@tool
def save_book_note(note: str, title: str = "", book_id: int = 0, library_item_id: int = 0):
    """Save a reader note to a local or catalog-backed library item."""
    try:
        return serialize_tool_result(
            reading_service.add_note(
                note, title or None, book_id or None, library_item_id or None
            )
        )
    except ValueError as exc:
        return serialize_tool_result({"error": str(exc)})


@tool
def add_to_collection(
    collection_name: str,
    title: str = "",
    book_id: int = 0,
    library_item_id: int = 0,
):
    """Add a local or catalog-backed book to a named personal collection."""
    try:
        return serialize_tool_result(
            reading_service.add_to_collection(
                collection_name, title or None, book_id or None, library_item_id or None
            )
        )
    except ValueError as exc:
        return serialize_tool_result({"error": str(exc)})


@tool
def get_book_collections(title: str = "", book_id: int = 0, library_item_id: int = 0):
    """List collections containing a local item or catalog-backed book."""
    try:
        return serialize_tool_result(
            reading_service.collections_for(
                title or None, book_id or None, library_item_id or None
            )
        )
    except ValueError as exc:
        return serialize_tool_result({"error": str(exc)})


@tool
def update_book_tags(
    tags: list[str], title: str = "", book_id: int = 0, library_item_id: int = 0
):
    """Replace personal tags on a library item or catalog-backed book."""
    try:
        return serialize_tool_result(
            reading_service.update_tags(
                tags, title or None, book_id or None, library_item_id or None
            )
        )
    except ValueError as exc:
        return serialize_tool_result({"error": str(exc)})


@tool
def add_bookmark(
    page: int,
    title: str = "",
    note: str = "",
    book_id: int = 0,
    library_item_id: int = 0,
):
    """Save a reader bookmark at a manually supplied page."""
    try:
        return serialize_tool_result(
            reading_service.add_bookmark(
                page, note, title or None, book_id or None, library_item_id or None
            )
        )
    except ValueError as exc:
        return serialize_tool_result({"error": str(exc)})
