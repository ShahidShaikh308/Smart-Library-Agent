"""Catalog queries and schema-flexible metadata access."""

from dataclasses import asdict

from database import database as dal
from models.book import Book


def _book(row: dict | None) -> dict | None:
    return asdict(Book(**row)) if row else None


def search(
    query: str = "",
    genre: str | None = None,
    limit: int = 12,
    series: str | None = None,
) -> list[dict]:
    return [
        asdict(Book(**row)) for row in dal.search_catalog(query, genre, limit, series)
    ]


def get(book_id: int) -> dict | None:
    return _book(dal.get_book(book_id))


def resolve_title(title: str) -> list[dict]:
    return search(title, limit=10)


def genres() -> list[str]:
    return dal.catalog_genres()
