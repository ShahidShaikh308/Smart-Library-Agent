from dataclasses import dataclass


@dataclass
class Book:
    id: int
    title: str
    author: str
    genre: str
    description: str
    series: str | None = None
    series_number: str | None = None
    publication_year: int | None = None
    isbn: str | None = None
    publisher: str | None = None
    language: str | None = None
    average_rating: float | None = None
    page_count: int | None = None
    popularity: int | None = None
