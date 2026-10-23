"""Reader-owned library items, manual progress, memory, and collections."""

import json
from datetime import datetime, timezone

from database import database as dal
from utils.dates import today_iso


def resolve_one(
    title: str | None = None,
    book_id: int | None = None,
    library_item_id: int | None = None,
) -> dict:
    """Resolve explicit item, local title/filename, then catalog fallback."""
    if library_item_id is not None:
        item = dal.library_item(library_item_id)
        if item:
            return item
        raise ValueError("That library item could not be found.")
    if book_id is not None:
        item = dal.ensure_catalog_library_item(book_id)
        if item:
            return item
        raise ValueError("Book not found in the catalog or personal library.")
    if title:
        local_matches = dal.find_library_items(" ".join(title.split()))
        local_matches = [item for item in local_matches if item.get("library_file_id")]
        if local_matches:
            reference = title.strip().casefold().replace("_", " ")
            exact_matches = [
                item
                for item in local_matches
                if item["filename"].rsplit(".", 1)[0].casefold().replace("_", " ")
                == reference
                or (item.get("catalog_title") or "").casefold() == reference
            ]
            if len(exact_matches) == 1:
                return exact_matches[0]
            if len(exact_matches) > 1 or len(local_matches) > 1:
                raise ValueError(
                    "That reference matches multiple local copies. Specify a filename or library item ID."
                )
            return local_matches[0]
        catalog_matches = dal.search_catalog(title, limit=20)
        exact_matches = [
            book for book in catalog_matches if book["title"].casefold() == title.casefold()
        ]
        candidates = exact_matches or catalog_matches
        if len(candidates) == 1:
            item = dal.ensure_catalog_library_item(candidates[0]["id"])
            if item:
                return item
        if len(candidates) > 1:
            raise ValueError(
                "That title matches multiple books. Specify the title or filename more precisely."
            )
    raise ValueError("I couldn't find that book in your library or the catalog.")


def _book_details(item: dict) -> dict:
    """Provide a consistent display shape for local and catalog-backed items."""
    return {
        "id": item.get("catalog_book_id"),
        "library_item_id": item["id"],
        "title": item.get("catalog_title") or item["filename"],
        "author": item.get("catalog_author") or "Unknown author",
        "genre": item.get("catalog_genre") or "",
        "description": item.get("catalog_description") or "",
        "filename": item["filename"],
        "path": item["path"],
        "matched_catalog_book_id": item.get("catalog_book_id"),
    }


def _current_state(item: dict) -> dict:
    state = dal.library_item_state(item["id"])
    state["last_opened_at"] = datetime.now(timezone.utc).isoformat()  # noqa: UP017
    return state


def update_progress(
    title: str | None = None,
    book_id: int | None = None,
    current_page: int | None = None,
    progress_percent: float | None = None,
    completed_at: str | None = None,
    library_item_id: int | None = None,
    start: bool = False,
) -> dict:
    if current_page is None and progress_percent is None and completed_at is None and not start:
        raise ValueError("Provide a page, percentage, completion date, or start request.")
    if current_page is not None and current_page < 0:
        raise ValueError("Page cannot be negative.")
    if progress_percent is not None and not 0 <= progress_percent <= 100:
        raise ValueError("Progress must be from 0 to 100%.")
    item = resolve_one(title, book_id, library_item_id)
    existing = _current_state(item)
    done = completed_at is not None or progress_percent == 100
    status = "read" if done else "reading"
    started = existing.get("started_at") or today_iso()
    completed = completed_at or (today_iso() if done else existing.get("completed_at"))
    page = current_page if current_page is not None else existing.get("current_page")
    percent = (
        progress_percent
        if progress_percent is not None
        else existing.get("progress_percent")
    )
    event_value = (
        f"page {current_page}"
        if current_page is not None
        else f"{progress_percent}%"
        if progress_percent is not None
        else "completed"
        if done
        else "started"
    )
    existing.update(
        status=status,
        current_page=page,
        progress_percent=percent,
        started_at=started,
        completed_at=completed,
    )
    saved = dal.save_library_item_state(
        existing,
        ("completed" if done else "progress_updated" if not start else "started", event_value, ""),
    )
    return {"book": _book_details(item), **saved}


def start_reading(
    title: str | None = None,
    book_id: int | None = None,
    library_item_id: int | None = None,
) -> dict:
    return update_progress(title, book_id, library_item_id=library_item_id, start=True)


def mark_completed(
    title: str | None = None,
    book_id: int | None = None,
    completed_at: str | None = None,
    library_item_id: int | None = None,
) -> dict:
    return update_progress(
        title,
        book_id,
        progress_percent=100,
        completed_at=completed_at or today_iso(),
        library_item_id=library_item_id,
    )


def history() -> list[dict]:
    return dal.reading_history()


def dashboard() -> dict:
    rows = history()
    average_rating = dal.average_book_rating()
    return {
        "counts": {
            status: sum(r["status"] == status for r in rows)
            for status in ("read", "reading", "want_to_read")
        },
        "average_rating": round(average_rating, 2) if average_rating is not None else None,
        "records": rows,
        "journey": dal.reading_journey(),
    }


def save_rating(
    book_id: int | None,
    rating: int,
    review: str = "",
    title: str | None = None,
    library_item_id: int | None = None,
) -> dict:
    if not 1 <= rating <= 5:
        raise ValueError("Rating must be from 1 to 5.")
    item = resolve_one(title, book_id, library_item_id)
    state = _current_state(item)
    state["rating"] = rating
    if review:
        state["review"] = review
    saved = dal.save_library_item_state(state, ("rated", None, review))
    return {"book": _book_details(item), **saved}


def set_favorite(
    book_id: int | None,
    favorite: bool,
    title: str | None = None,
    library_item_id: int | None = None,
) -> dict:
    item = resolve_one(title, book_id, library_item_id)
    state = _current_state(item)
    state["is_favorite"] = int(favorite)
    saved = dal.save_library_item_state(
        state, ("favorite_added" if favorite else "favorite_removed", None, "")
    )
    return {
        "library_item_id": item["id"],
        "book_id": item.get("catalog_book_id"),
        "is_favorite": bool(saved["is_favorite"]),
        "filename": item["filename"],
    }


def wishlist(
    add: bool,
    book_id: int | None,
    title: str | None = None,
    library_item_id: int | None = None,
) -> dict:
    item = resolve_one(title, book_id, library_item_id)
    state = _current_state(item)
    state["is_wishlisted"] = int(add)
    saved = dal.save_library_item_state(
        state, ("wishlisted" if add else "removed_from_wishlist", None, "")
    )
    return {
        "library_item_id": item["id"],
        "book_id": item.get("catalog_book_id"),
        "wishlisted": bool(saved["is_wishlisted"]),
        "filename": item["filename"],
    }


def add_note(
    note: str,
    title: str | None = None,
    book_id: int | None = None,
    library_item_id: int | None = None,
) -> dict:
    if not note.strip():
        raise ValueError("Provide a note to save.")
    item = resolve_one(title, book_id, library_item_id)
    state = dal.save_book_note(item["id"], note)
    return {"book": _book_details(item), **state}


def add_to_collection(
    collection_name: str,
    title: str | None = None,
    book_id: int | None = None,
    library_item_id: int | None = None,
) -> dict:
    item = resolve_one(title, book_id, library_item_id)
    result = dal.change_collection(item["id"], collection_name)
    return {"book": _book_details(item), **result}


def collections_for(
    title: str | None = None,
    book_id: int | None = None,
    library_item_id: int | None = None,
) -> list[dict]:
    item = resolve_one(title, book_id, library_item_id)
    return dal.collections(item["id"])


def update_tags(
    tags: list[str],
    title: str | None = None,
    book_id: int | None = None,
    library_item_id: int | None = None,
) -> dict:
    item = resolve_one(title, book_id, library_item_id)
    cleaned = list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))
    state = _current_state(item)
    state["tags"] = json.dumps(cleaned, ensure_ascii=False)
    saved = dal.save_library_item_state(state, ("tags_updated", None, ""))
    return {"library_item_id": item["id"], "tags": json.loads(saved["tags"])}


def add_bookmark(
    page: int,
    note: str = "",
    title: str | None = None,
    book_id: int | None = None,
    library_item_id: int | None = None,
) -> dict:
    if page < 0:
        raise ValueError("Bookmark page cannot be negative.")
    item = resolve_one(title, book_id, library_item_id)
    state = _current_state(item)
    bookmarks = json.loads(state.get("bookmarks") or "[]")
    bookmarks.append({"page": page, "note": note.strip()})
    state["bookmarks"] = json.dumps(bookmarks, ensure_ascii=False)
    saved = dal.save_library_item_state(
        state, ("bookmark_added", f"page {page}", note.strip())
    )
    return {"library_item_id": item["id"], "bookmarks": json.loads(saved["bookmarks"])}


def wishlist_items() -> list[dict]:
    return dal.wishlist_books()
