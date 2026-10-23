from dataclasses import dataclass


@dataclass
class ReadingRecord:
    library_item_id: int
    catalog_book_id: int | None
    status: str
    current_page: int | None = None
    progress_percent: float | None = None
    started_at: str | None = None
    completed_at: str | None = None
