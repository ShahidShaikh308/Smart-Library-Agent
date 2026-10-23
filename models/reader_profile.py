from dataclasses import dataclass


@dataclass
class ReaderProfile:
    id: int = 1
    name: str = "Reader"
    favorite_genres: str = ""
    favorite_authors: str = ""
    favorite_books: str = ""
    reading_goals: str = ""
