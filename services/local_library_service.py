"""Single-folder owned-book index; changed files are hashed, never extracted."""

from dataclasses import asdict
from pathlib import Path

from database import database as dal
from models.library_file import LibraryFile
from services import catalog_service
from utils.book_matcher import match_filename
from utils.file_scanner import hash_file, scan_folder


def set_folder(folder: str) -> str:
    path = Path(folder).expanduser().resolve()
    if not path.is_dir():
        raise ValueError("Choose an existing folder.")
    old = get_folder()
    dal.save_library_folder(str(path), old != str(path))
    return str(path)


def get_folder() -> str | None:
    return dal.library_folder()


def scan() -> dict:
    folder = get_folder()
    if not folder:
        raise ValueError(
            "No library folder is configured. Choose one with the folder picker in the sidebar."
        )
    observed_files = scan_folder(folder)
    existing_files = {item["path"]: item for item in dal.library_files()}
    catalog_books: list[dict] | None = None
    changed_files = []
    observed_paths = set()
    new_count = 0
    updated_count = 0
    unchanged_count = 0
    failed_count = 0

    for item in observed_files:
        path = item["path"]
        observed_paths.add(path)
        previous = existing_files.get(path)
        unchanged = (
            previous is not None
            and previous["file_size_bytes"] == item["file_size_bytes"]
            and previous["last_modified_at"] == item["last_modified_at"]
        )
        if unchanged and previous is not None and previous.get("file_hash"):
            unchanged_count += 1
            continue

        try:
            item["file_hash"] = hash_file(path)
        except OSError:
            failed_count += 1
            # Preserve any existing record; a transient read failure should not
            # be treated as a file deletion or silently remove an indexed book.
            continue

        if unchanged and previous is not None:
            item["matched_book_id"] = previous["matched_book_id"]
            item["matched_confidence"] = previous["matched_confidence"]
            updated_count += 1  # backfill hashes for indexes created before v4
        else:
            if catalog_books is None:
                catalog_books = dal.catalog_match_candidates()
            assert catalog_books is not None
            item["matched_book_id"], item["matched_confidence"] = match_filename(
                item["filename"], catalog_books
            )
            if previous is not None:
                updated_count += 1
            else:
                new_count += 1
        record = asdict(LibraryFile(**{key: value for key, value in item.items() if key != "file_hash"}))
        record["file_hash"] = item["file_hash"]
        changed_files.append(record)

    sync_counts = dal.sync_library_files(changed_files, observed_paths)
    resulting_index = {
        path: item for path, item in existing_files.items() if path in observed_paths
    }
    resulting_index.update({item["path"]: item for item in changed_files})
    matched_count = sum(bool(item.get("matched_book_id")) for item in resulting_index.values())
    return {
        "folder": folder,
        "indexed_count": len(resulting_index),
        "matched_count": matched_count,
        "new_count": new_count,
        "updated_count": updated_count,
        "unchanged_count": unchanged_count,
        "removed_count": sync_counts["removed_count"],
        "changes_detected": bool(new_count or updated_count or sync_counts["removed_count"]),
        "failed_count": failed_count,
        "last_scanned_at": dal.library_scan_status()["last_scanned_at"],
        "files": dal.search_library_files(),
    }


def files(query: str = "") -> list[dict]:
    return dal.search_library_files(query)


def missing(query: str = "") -> list[dict]:
    owned = {f["matched_book_id"] for f in files() if f["matched_book_id"]}
    candidates = catalog_service.search(query, limit=100)
    return [b for b in candidates if b["id"] not in owned]


def duplicates() -> list[dict]:
    return dal.library_duplicates()
