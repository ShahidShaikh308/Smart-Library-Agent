"""Deterministic matching of local filenames to catalog titles."""

import re
from difflib import SequenceMatcher


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def match_filename(filename: str, books: list[dict]) -> tuple[int | None, float | None]:
    stem = normalize(filename.rsplit(".", 1)[0])
    if not stem:
        return None, None
    best_id, best_score = None, 0.0
    for book in books:
        title = normalize(book["title"])
        title_score = (
            1.0 if stem == title else SequenceMatcher(None, stem, title).ratio()
        )
        if title and title in stem:
            title_score = max(title_score, min(0.99, len(title) / max(len(stem), 1)))
        author = normalize(book.get("author", ""))
        author_tokens = [token for token in author.split() if len(token) > 1]
        author_match = bool(author_tokens) and all(
            token in stem for token in author_tokens
        )
        if author_match and title in stem:
            title_score = max(title_score, 0.85)
        # A filename that includes the author earns a confidence boost; otherwise
        # title-only matching remains available for common ebook filenames.
        score = min(
            1.0,
            title_score * (1.0 if not author_tokens else 0.82)
            + (0.18 if author_match else 0.0),
        )
        if score > best_score:
            best_id, best_score = book["id"], score
    return (best_id, round(best_score, 3)) if best_score >= 0.72 else (None, None)
