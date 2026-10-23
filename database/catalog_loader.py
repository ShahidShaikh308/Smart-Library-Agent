"""Schema-flexible CSV import for the primary book catalog."""

import csv
import re
import sqlite3
from pathlib import Path

REQUIRED = {"title", "author", "genre", "description"}


def _optional(values: dict[str, str], name: str) -> str | None:
    """Return a non-empty optional catalog value, otherwise None."""
    return values.get(name) or None


def _number(
    values: dict[str, str], name: str, cast: type[int] | type[float]
) -> int | float | None:
    """Parse an optional numeric value while tolerating malformed CSV cells."""
    try:
        return cast(values[name]) if values.get(name) else None
    except (ValueError, TypeError):
        return None


def load_catalog(connection: sqlite3.Connection, path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = {h.strip().lower(): h for h in (reader.fieldnames or [])}
        aliases = {
            "average_rating": "rating",
            "page_count": "pages",
            "popularity": "num_ratings",
        }
        missing = REQUIRED - headers.keys()
        if missing:
            raise ValueError(
                f"Catalog is missing required columns: {', '.join(sorted(missing))}"
            )
        records = []
        seen = set()
        for row in reader:
            values = {
                key: (row.get(source) or "").strip() for key, source in headers.items()
            }
            for target, source in aliases.items():
                if target not in values and source in values:
                    values[target] = values[source]
            if not all(values.get(k) for k in REQUIRED):
                continue

            isbn = _optional(values, "isbn")
            norm = lambda text: re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()
            key = (
                ("isbn", isbn.casefold())
                if isbn
                else ("title_author", norm(values["title"]), norm(values["author"]))
            )
            if key in seen:
                continue
            seen.add(key)
            records.append(
                (
                    values["title"],
                    values["author"],
                    values["genre"],
                    values["description"],
                    _optional(values, "series"),
                    _optional(values, "series_number"),
                    _number(values, "publication_year", int),
                    isbn,
                    _optional(values, "publisher"),
                    _optional(values, "language"),
                    _number(values, "average_rating", float),
                    _number(values, "page_count", int),
                    _number(values, "popularity", int),
                )
            )
    connection.executemany(
        """INSERT INTO catalog_books(title,author,genre,description,series,series_number,
        publication_year,isbn,publisher,language,average_rating,page_count,popularity) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT DO UPDATE SET title=excluded.title,author=excluded.author,genre=excluded.genre,description=excluded.description,
        series=excluded.series,series_number=excluded.series_number,publication_year=excluded.publication_year,
        isbn=excluded.isbn,publisher=excluded.publisher,language=excluded.language,
        average_rating=excluded.average_rating,page_count=excluded.page_count,popularity=excluded.popularity""",
        records,
    )
    return len(records)
