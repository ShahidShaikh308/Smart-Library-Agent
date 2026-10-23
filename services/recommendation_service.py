"""Deterministic, explainable recommendation ranking for Version 1."""

from database import database as dal
from services import catalog_service, reader_service


def recommend(limit: int = 5) -> dict:
    profile = reader_service.get_profile()
    data = dal.recommendation_data()
    history = data["history"]
    wishlist = {r["book_id"] for r in data["wishlist"]}
    owned = {r["matched_book_id"] for r in data["owned"]}
    favorite_ids = {r["book_id"] for r in data["favorites"]}
    excluded = {r["book_id"] for r in history} | wishlist
    favorite_genres = {
        x.strip().casefold() for x in profile["favorite_genres"].split(",") if x.strip()
    }
    favorite_authors = {
        x.strip().casefold()
        for x in profile["favorite_authors"].split(",")
        if x.strip()
    }
    completed = [r for r in history if r["status"] == "read"]
    current_series = {
        r["series"] for r in history if r["status"] == "reading" and r["series"]
    }
    favorite_titles = {
        x.strip().casefold()
        for x in profile.get("favorite_books", "").split(",")
        if x.strip()
    }
    candidates = data["books"]
    ranked = []
    for book in candidates:
        if book["id"] in excluded and book["id"] not in favorite_ids:
            continue
        score, reasons = 0.0, []
        if book["genre"].casefold() in favorite_genres:
            score += 5
            reasons.append("favorite genre")
        if book["author"].casefold() in favorite_authors:
            score += 5
            reasons.append("favorite author")
        if book["id"] in favorite_ids or book["title"].casefold() in favorite_titles:
            score += 5
            reasons.append("saved favorite")
        if any(r["genre"] == book["genre"] for r in completed):
            score += 3
            reasons.append("similar to completed reads")
        if book["series"] and book["series"] in current_series:
            score += 6
            reasons.append("continues a series you are reading")
        score += min(float(book.get("average_rating") or 0), 5) * 0.2
        score += min((book.get("popularity") or 0) / 1_000_000, 1) * 0.1
        if book["id"] in owned:
            score += 0.05
            reasons.append("available in your library")
        if score:
            ranked.append((score, book, reasons))
    ranked.sort(
        key=lambda item: (
            -item[0],
            -(item[1].get("average_rating") or 0),
            item[1]["title"].casefold(),
        )
    )
    return {
        "reader_profile": profile,
        "recommendations": [
            {**b, "match_reasons": reasons} for _, b, reasons in ranked[:limit]
        ],
    }


def similar(book_id: int, limit: int = 5) -> list[dict]:
    source = catalog_service.get(book_id)
    if not source:
        return []
    rows = catalog_service.search("", genre=source["genre"], limit=limit + 1)
    return [b for b in rows if b["id"] != book_id][:limit]


def next_in_series(book_id: int) -> dict | None:
    book = catalog_service.get(book_id)
    if not book or not book.get("series"):
        return None
    rows = dal.series_books(book["series"])
    rows.sort(
        key=lambda b: (
            float(b["series_number"])
            if str(b.get("series_number") or "").replace(".", "", 1).isdigit()
            else 10**9,
            b["title"].casefold(),
        )
    )
    for item in rows:
        try:
            if float(item["series_number"]) > float(book.get("series_number") or 0):
                return item
        except (ValueError, TypeError):
            continue
    return None
