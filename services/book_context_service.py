"""Build one database-backed view of a book and the reader's related data."""

from dataclasses import asdict, fields

from database import database as dal
from models.book import Book
from models.book_context import BookContext, BookContextEntry, LibraryIndexStatus
from models.library_item import LibraryItem
from models.reader_profile import ReaderProfile
from models.reading_record import ReadingRecord


def _model_values(model_type, values: dict) -> dict:
    """Keep joined query aliases out of shared dataclass constructors."""
    accepted = {item.name for item in fields(model_type)}
    return {key: value for key, value in values.items() if key in accepted}


def load(query: str, limit: int = 5) -> dict:
    """Return catalog, local-file, progress, preference, and related-book context."""
    clean_query = " ".join(query.split())
    data = dal.book_context_data(clean_query, min(max(limit, 1), 10))
    profile = ReaderProfile(**_model_values(ReaderProfile, data.get("reader_profile") or {}))
    index_values = data.get("library_index") or {}
    index = LibraryIndexStatus(
        **_model_values(LibraryIndexStatus, index_values),
        initialized=bool(index_values.get("last_scanned_at")),
    )
    journey_by_item: dict[int, list[dict]] = {}
    journey_by_book: dict[int, list[dict]] = {}
    for event in data.get("journey", []):
        item_id = event.get("library_item_id")
        book_id = event.get("book_id")
        if item_id is not None:
            journey_by_item.setdefault(item_id, []).append(event)
        if book_id is not None:
            journey_by_book.setdefault(book_id, []).append(event)
    local_files = []
    for row in data.get("local_files", []):
        values = _model_values(LibraryItem, row)
        values["is_favorite"] = bool(values.get("is_favorite"))
        values["is_wishlisted"] = bool(values.get("is_wishlisted"))
        local_files.append(LibraryItem(**values))
    for item in local_files:
        item.journey = journey_by_item.get(item.id, [])

    files_by_book: dict[int, list[LibraryItem]] = {}
    for file in local_files:
        if file.catalog_book_id is not None:
            files_by_book.setdefault(file.catalog_book_id, []).append(file)

    related_by_book: dict[int, list[Book]] = {}
    for row in data.get("related_books", []):
        source_id = row.pop("source_book_id")
        related_by_book.setdefault(source_id, []).append(
            Book(**_model_values(Book, row))
        )

    matches = []
    for row in data.get("books", []):
        book = Book(**_model_values(Book, row))
        reading = None
        item_ids = files_by_book.get(book.id, [])
        reading_item_id = row.get("reading_library_item_id") or (
            item_ids[0].id if item_ids else None
        )
        if row.get("reading_status") and reading_item_id is not None:
            reading = ReadingRecord(
                library_item_id=reading_item_id,
                catalog_book_id=book.id,
                status=row["reading_status"],
                current_page=row.get("current_page"),
                progress_percent=row.get("progress_percent"),
                started_at=row.get("started_at"),
                completed_at=row.get("completed_at"),
            )
        matches.append(
            BookContextEntry(
                book=book,
                local_files=files_by_book.get(book.id, []),
                reading_record=reading,
                rating=row.get("rating"),
                review=row.get("review") or "",
                is_favorite=bool(row.get("is_favorite")),
                is_wishlisted=bool(row.get("is_wishlisted")),
                journey=journey_by_book.get(book.id, []),
                related_books=related_by_book.get(book.id, [])[:5],
            )
        )

    return asdict(
        BookContext(
            query=clean_query,
            matches=matches,
            # Return every local hit first (including files matched to catalog
            # books); the merged catalog/personal records below enrich those hits.
            local_files=local_files,
            reader_profile=profile,
            library_index=index,
        )
    )
