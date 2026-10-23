"""Typed merged context for a catalog book and the reader's local library."""

from dataclasses import dataclass, field

from models.book import Book
from models.library_item import LibraryItem
from models.reader_profile import ReaderProfile
from models.reading_record import ReadingRecord


@dataclass
class BookContextEntry:
    book: Book
    local_files: list[LibraryItem] = field(default_factory=list)
    reading_record: ReadingRecord | None = None
    rating: int | None = None
    review: str = ""
    is_favorite: bool = False
    is_wishlisted: bool = False
    journey: list[dict] = field(default_factory=list)
    related_books: list[Book] = field(default_factory=list)


@dataclass
class LibraryIndexStatus:
    folder_path: str | None = None
    last_scanned_at: str | None = None
    indexed_file_count: int = 0
    initialized: bool = False


@dataclass
class BookContext:
    query: str
    # Local index hits are deliberately serialized before catalog matches so
    # the agent treats the reader's own collection as the primary source.
    local_files: list[LibraryItem] = field(default_factory=list)
    matches: list[BookContextEntry] = field(default_factory=list)
    reader_profile: ReaderProfile = field(default_factory=ReaderProfile)
    library_index: LibraryIndexStatus = field(default_factory=LibraryIndexStatus)
