"""A reader-owned book entry, optionally backed by an indexed local file."""

from dataclasses import dataclass
from typing import Any


@dataclass
class LibraryItem:
    id: int
    filename: str
    path: str
    extension: str = ""
    library_item_id: int | None = None
    library_file_id: int | None = None
    catalog_book_id: int | None = None
    file_size_bytes: int | None = None
    last_modified_at: str | None = None
    file_hash: str | None = None
    matched_confidence: float | None = None
    status: str | None = None
    current_page: int | None = None
    progress_percent: float | None = None
    rating: int | None = None
    review: str = ""
    notes: str = ""
    tags: str = "[]"
    bookmarks: str = "[]"
    collections: str = ""
    journey: list[dict[str, Any]] | None = None
    is_favorite: bool = False
    is_wishlisted: bool = False
    started_at: str | None = None
    completed_at: str | None = None
    last_opened_at: str | None = None
    catalog_title: str | None = None
    catalog_author: str | None = None
    catalog_genre: str | None = None
    catalog_description: str | None = None
