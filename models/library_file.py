from dataclasses import dataclass


@dataclass
class LibraryFile:
    filename: str
    path: str
    extension: str
    file_size_bytes: int
    last_modified_at: str
    matched_book_id: int | None = None
    matched_confidence: float | None = None
    file_hash: str | None = None
