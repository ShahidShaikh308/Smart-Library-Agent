"""Singleton reader profile and preference operations."""

from dataclasses import asdict

from database import database as dal
from models.reader_profile import ReaderProfile


def get_profile() -> dict:
    row = dal.get_reader_profile() or asdict(ReaderProfile())
    return asdict(ReaderProfile(**row))


def update_preferences(
    favorite_genres: str = "",
    favorite_authors: str = "",
    favorite_books: str = "",
    reading_goals: str = "",
) -> dict:
    current = get_profile()
    values: tuple[str, str, str, str] = (
        favorite_genres or str(current.get("favorite_genres", "")),
        favorite_authors or str(current.get("favorite_authors", "")),
        favorite_books or str(current.get("favorite_books", "")),
        reading_goals or str(current.get("reading_goals", "")),
    )
    dal.update_reader_profile(values)
    return get_profile()
