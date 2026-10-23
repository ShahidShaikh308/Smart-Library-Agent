"""SQLite data access. No service, tool, or UI contains SQL."""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .catalog_loader import load_catalog
from .migrations.migrate import migrate

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("LIBRARY_DB_PATH", ROOT / "database" / "smart_library.db"))
SCHEMA_PATH = Path(__file__).with_name("schema.sql")
CATALOG_PATH = Path(os.getenv("BOOK_CATALOG_PATH", ROOT / "books.csv"))


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize() -> None:
    with connection() as conn:
        migrate(conn, SCHEMA_PATH)
        conn.execute("INSERT OR IGNORE INTO reader_profile(id,name) VALUES(1,'Reader')")
        if (
            CATALOG_PATH.exists()
            and conn.execute("SELECT COUNT(*) FROM catalog_books").fetchone()[0] == 0
        ):
            load_catalog(conn, CATALOG_PATH)


def query_all(sql: str, params: tuple = ()) -> list[dict]:
    with connection() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def query_one(sql: str, params: tuple = ()) -> dict | None:
    with connection() as conn:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None


def execute(sql: str, params: tuple = ()) -> int:
    with connection() as conn:
        cursor = conn.execute(sql, params)
        return cursor.lastrowid if cursor.lastrowid is not None else 0


# Application queries live here so services never depend on SQLite details.
def search_catalog(
    query: str = "",
    genre: str | None = None,
    limit: int = 12,
    series: str | None = None,
) -> list[dict]:
    sql = "SELECT * FROM catalog_books WHERE 1=1"
    params: list = []
    for word in query.split():
        like = f"%{word}%"
        sql += " AND (title LIKE ? OR author LIKE ? OR genre LIKE ? OR description LIKE ? OR COALESCE(series,'') LIKE ?)"
        params.extend([like] * 5)
    if genre:
        sql += " AND LOWER(genre)=LOWER(?)"
        params.append(genre)
    if series:
        sql += " AND LOWER(COALESCE(series,'')) LIKE LOWER(?)"
        params.append(f"%{series}%")
    sql += " ORDER BY COALESCE(average_rating,0) DESC,title LIMIT ?"
    params.append(limit)
    return query_all(sql, tuple(params))


def get_book(book_id: int) -> dict | None:
    return query_one("SELECT * FROM catalog_books WHERE id=?", (book_id,))


def catalog_genres() -> list[str]:
    return [
        r["genre"]
        for r in query_all("SELECT DISTINCT genre FROM catalog_books ORDER BY genre")
    ]


def get_reader_profile() -> dict | None:
    return query_one("SELECT * FROM reader_profile WHERE id=1")


def update_reader_profile(values: tuple[str, str, str, str]) -> None:
    execute(
        "UPDATE reader_profile SET favorite_genres=?,favorite_authors=?,favorite_books=?,reading_goals=? WHERE id=1",
        values,
    )


def get_reading_record(book_id: int) -> dict | None:
    return query_one("SELECT * FROM reading_records WHERE book_id=?", (book_id,))


def library_item(item_id: int) -> dict | None:
    return query_one(
        """SELECT i.*,i.id AS library_item_id,b.title AS catalog_title,b.author AS catalog_author,
           b.genre AS catalog_genre,b.description AS catalog_description,
           b.series,b.series_number,b.publication_year,b.isbn,b.publisher,
           b.language,b.average_rating,b.page_count,
           COALESCE(f.matched_confidence,0) AS matched_confidence,
           i.catalog_book_id AS matched_book_id
           FROM library_items i LEFT JOIN library_files f ON f.id=i.library_file_id
           LEFT JOIN catalog_books b ON b.id=i.catalog_book_id
           WHERE i.id=?""",
        (item_id,),
    )


def find_library_items(query: str) -> list[dict]:
    """Resolve a natural-language title or filename against indexed items."""
    words = query.split()
    conditions = []
    params: list[str] = []
    for word in words:
        like = f"%{word}%"
        conditions.append(
            "(i.filename LIKE ? OR i.path LIKE ? OR COALESCE(b.title,'') LIKE ? "
            "OR COALESCE(b.author,'') LIKE ?)"
        )
        params.extend([like] * 4)
    where = " AND ".join(conditions) if conditions else "1=0"
    return query_all(
        f"""SELECT i.*,i.id AS library_item_id,b.title AS catalog_title,b.author AS catalog_author,
            b.genre AS catalog_genre,b.description AS catalog_description,
            b.series,b.series_number,b.publication_year,b.isbn,b.publisher,
            b.language,b.average_rating,b.page_count,
            COALESCE(f.matched_confidence,0) AS matched_confidence,
            i.catalog_book_id AS matched_book_id
            FROM library_items i LEFT JOIN library_files f ON f.id=i.library_file_id
            LEFT JOIN catalog_books b ON b.id=i.catalog_book_id
            WHERE {where}
            ORDER BY CASE WHEN LOWER(i.filename)=LOWER(?) OR LOWER(COALESCE(b.title,''))=LOWER(?) THEN 0 ELSE 1 END,
                     i.library_file_id IS NULL,i.filename,i.path""",
        (*params, query, query),
    )


def ensure_catalog_library_item(book_id: int) -> dict | None:
    """Resolve to a local item or create a virtual item for catalog-only books."""
    with connection() as conn:
        row = conn.execute(
            """SELECT id FROM library_items WHERE catalog_book_id=?
               ORDER BY library_file_id IS NULL,id LIMIT 1""",
            (book_id,),
        ).fetchone()
        if row is None:
            book = conn.execute(
                "SELECT id,title FROM catalog_books WHERE id=?", (book_id,)
            ).fetchone()
            if book is None:
                return None
            conn.execute(
                "INSERT OR IGNORE INTO library_items(catalog_book_id,filename,path) VALUES(?,?,?)",
                (book["id"], book["title"], f"catalog:{book['id']}"),
            )
            row = conn.execute(
                "SELECT id FROM library_items WHERE path=?", (f"catalog:{book_id}",)
            ).fetchone()
        item_id = int(row["id"])
    return library_item(item_id)


def library_item_state(item_id: int) -> dict:
    return query_one(
        "SELECT * FROM library_item_state WHERE library_item_id=?", (item_id,)
    ) or {
        "library_item_id": item_id,
        "status": None,
        "current_page": None,
        "progress_percent": None,
        "rating": None,
        "review": "",
        "notes": "",
        "is_favorite": 0,
        "is_wishlisted": 0,
        "tags": "[]",
        "bookmarks": "[]",
        "started_at": None,
        "completed_at": None,
        "last_opened_at": None,
    }


def save_library_item_state(state: dict, event: tuple[str, str | None, str] | None = None) -> dict:
    """Persist reader state and its optional journey event atomically."""
    with connection() as conn:
        conn.execute(
            """INSERT INTO library_item_state(
                library_item_id,status,current_page,progress_percent,rating,review,
                notes,is_favorite,is_wishlisted,tags,bookmarks,started_at,
                completed_at,last_opened_at
            ) VALUES(
                :library_item_id,:status,:current_page,:progress_percent,:rating,
                :review,:notes,:is_favorite,:is_wishlisted,:tags,:bookmarks,
                :started_at,:completed_at,:last_opened_at
            ) ON CONFLICT(library_item_id) DO UPDATE SET
                status=excluded.status,current_page=excluded.current_page,
                progress_percent=excluded.progress_percent,rating=excluded.rating,
                review=excluded.review,notes=excluded.notes,
                is_favorite=excluded.is_favorite,is_wishlisted=excluded.is_wishlisted,
                tags=excluded.tags,bookmarks=excluded.bookmarks,
                started_at=excluded.started_at,completed_at=excluded.completed_at,
                last_opened_at=excluded.last_opened_at,updated_at=CURRENT_TIMESTAMP""",
            state,
        )
        if event:
            conn.execute(
                "INSERT INTO library_item_journey(library_item_id,event_type,progress_value,note) VALUES(?,?,?,?)",
                (state["library_item_id"], event[0], event[1], event[2]),
            )
        row = conn.execute(
            "SELECT * FROM library_item_state WHERE library_item_id=?",
            (state["library_item_id"],),
        ).fetchone()
        return dict(row)


def reading_history() -> list[dict]:
    return query_all(
        """SELECT i.id AS library_item_id,i.filename,i.path,b.id AS book_id,
            COALESCE(b.title,i.filename) AS title,COALESCE(b.author,'Unknown author') AS author,
            COALESCE(b.genre,'') AS genre,s.status,s.current_page,s.progress_percent,
            s.started_at,s.completed_at,s.updated_at,s.rating,s.review,s.is_favorite,
            s.notes,s.is_wishlisted,s.last_opened_at
            FROM library_item_state s JOIN library_items i ON i.id=s.library_item_id
            LEFT JOIN catalog_books b ON b.id=i.catalog_book_id
            WHERE s.status IS NOT NULL ORDER BY s.updated_at DESC"""
    )


def library_item_journey() -> list[dict]:
    return query_all(
        """SELECT j.*,i.filename,i.path,COALESCE(b.title,i.filename) AS title
            FROM library_item_journey j JOIN library_items i ON i.id=j.library_item_id
            LEFT JOIN catalog_books b ON b.id=i.catalog_book_id
            ORDER BY j.occurred_at DESC,j.id DESC LIMIT 100"""
    )


def change_collection(item_id: int, name: str, add: bool = True) -> dict:
    clean_name = " ".join(name.split())
    if not clean_name:
        raise ValueError("Provide a collection name.")
    with connection() as conn:
        if add:
            conn.execute(
                "INSERT OR IGNORE INTO reader_collections(name) VALUES(?)",
                (clean_name,),
            )
            collection_id = conn.execute(
                "SELECT id FROM reader_collections WHERE name=? COLLATE NOCASE",
                (clean_name,),
            ).fetchone()[0]
            conn.execute(
                "INSERT OR IGNORE INTO library_item_collections(library_item_id,collection_id) VALUES(?,?)",
                (item_id, collection_id),
            )
            conn.execute(
                """INSERT INTO library_item_state(library_item_id,last_opened_at)
                   VALUES(?,CURRENT_TIMESTAMP) ON CONFLICT(library_item_id)
                   DO UPDATE SET last_opened_at=CURRENT_TIMESTAMP""",
                (item_id,),
            )
        else:
            conn.execute(
                "DELETE FROM library_item_collections WHERE library_item_id=? AND collection_id IN (SELECT id FROM reader_collections WHERE name=? COLLATE NOCASE)",
                (item_id, clean_name),
            )
        return {
            "library_item_id": item_id,
            "collection": clean_name,
            "included": add,
        }


def save_book_note(item_id: int, note: str) -> dict:
    with connection() as conn:
        conn.execute(
            """INSERT INTO library_item_state(library_item_id,notes,last_opened_at)
               VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(library_item_id) DO UPDATE SET
               notes=CASE WHEN excluded.notes='' THEN library_item_state.notes
                          WHEN library_item_state.notes='' THEN excluded.notes
                          ELSE library_item_state.notes || char(10) || excluded.notes END,
               last_opened_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP""",
            (item_id, note.strip()),
        )
        if note.strip():
            conn.execute(
                "INSERT INTO library_item_journey(library_item_id,event_type,note) VALUES(?,'note_added',?)",
                (item_id, note.strip()),
            )
        return dict(
            conn.execute(
                "SELECT * FROM library_item_state WHERE library_item_id=?",
                (item_id,),
            ).fetchone()
        )


def collections(item_id: int | None = None) -> list[dict]:
    if item_id is None:
        return query_all("SELECT id,name,created_at FROM reader_collections ORDER BY name")
    return query_all(
        """SELECT c.id,c.name,ic.added_at FROM library_item_collections ic
            JOIN reader_collections c ON c.id=ic.collection_id
            WHERE ic.library_item_id=? ORDER BY c.name""",
        (item_id,),
    )


def average_book_rating() -> float | None:
    """Return the mean of ratings held by reader library items."""
    row = query_one("SELECT AVG(rating) AS average_rating FROM library_item_state")
    return float(row["average_rating"]) if row and row["average_rating"] is not None else None


def reading_journey() -> list[dict]:
    return library_item_journey()[:30]


def wishlist_books() -> list[dict]:
    return query_all(
        """SELECT COALESCE(b.id,0) AS id,i.id AS library_item_id,
            COALESCE(b.title,i.filename) AS title,COALESCE(b.author,'Unknown author') AS author,
            COALESCE(b.genre,'') AS genre,COALESCE(b.description,'') AS description
            FROM library_item_state s JOIN library_items i ON i.id=s.library_item_id
            LEFT JOIN catalog_books b ON b.id=i.catalog_book_id
            WHERE s.is_wishlisted=1 ORDER BY s.updated_at DESC"""
    )


def recommendation_data() -> dict:
    return {
        "history": query_all(
            """SELECT i.catalog_book_id AS book_id,s.status,b.genre,b.author,b.series
               FROM library_item_state s JOIN library_items i ON i.id=s.library_item_id
               JOIN catalog_books b ON b.id=i.catalog_book_id WHERE s.status IS NOT NULL"""
        ),
        "wishlist": query_all(
            "SELECT DISTINCT i.catalog_book_id AS book_id FROM library_item_state s JOIN library_items i ON i.id=s.library_item_id WHERE s.is_wishlisted=1 AND i.catalog_book_id IS NOT NULL"
        ),
        "favorites": query_all(
            "SELECT DISTINCT i.catalog_book_id AS book_id FROM library_item_state s JOIN library_items i ON i.id=s.library_item_id WHERE s.is_favorite=1 AND i.catalog_book_id IS NOT NULL"
        ),
        "owned": query_all(
            "SELECT matched_book_id FROM library_files WHERE matched_book_id IS NOT NULL"
        ),
        "books": query_all("SELECT * FROM catalog_books"),
    }


def series_books(series: str) -> list[dict]:
    return query_all("SELECT * FROM catalog_books WHERE series=?", (series,))


def library_folder() -> str | None:
    row = query_one("SELECT folder_path FROM library_settings WHERE id=1")
    return row["folder_path"] if row else None


def library_scan_status() -> dict:
    """Return the configured library path and persisted index freshness metadata."""
    return query_one(
        "SELECT s.folder_path,s.last_scanned_at,(SELECT COUNT(*) FROM library_files) AS indexed_file_count FROM library_settings s WHERE s.id=1"
    ) or {"folder_path": None, "last_scanned_at": None, "indexed_file_count": 0}


def save_library_folder(path: str, clear_index: bool) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO library_settings(id,folder_path) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET folder_path=excluded.folder_path,updated_at=CURRENT_TIMESTAMP,last_scanned_at=CASE WHEN ? THEN NULL ELSE library_settings.last_scanned_at END",
            (path, int(clear_index)),
        )
        if clear_index:
            conn.execute("DELETE FROM library_files")


def catalog_match_candidates() -> list[dict]:
    return query_all("SELECT id,title,author FROM catalog_books")


def sync_library_files(
    changed_files: list[dict], observed_paths: set[str]
) -> dict[str, int]:
    """Apply an incremental scan atomically and record its completion time."""
    with connection() as conn:
        existing_paths = {
            row[0] for row in conn.execute("SELECT path FROM library_files").fetchall()
        }
        removed_paths = existing_paths - observed_paths
        conn.executemany(
            "DELETE FROM library_files WHERE path=?",
            ((path,) for path in removed_paths),
        )
        conn.executemany(
            """INSERT INTO library_files(
                filename,path,extension,file_size_bytes,last_modified_at,
                matched_book_id,matched_confidence,file_hash
            ) VALUES(
                :filename,:path,:extension,:file_size_bytes,:last_modified_at,
                :matched_book_id,:matched_confidence,:file_hash
            ) ON CONFLICT(path) DO UPDATE SET
                filename=excluded.filename,
                extension=excluded.extension,
                file_size_bytes=excluded.file_size_bytes,
                last_modified_at=excluded.last_modified_at,
                matched_book_id=excluded.matched_book_id,
                matched_confidence=excluded.matched_confidence,
                file_hash=excluded.file_hash,
                scanned_at=CURRENT_TIMESTAMP""",
            changed_files,
        )
        conn.execute(
            """INSERT INTO library_items(
                library_file_id,catalog_book_id,filename,path,extension,
                file_size_bytes,last_modified_at,file_hash
            ) SELECT id,matched_book_id,filename,path,extension,file_size_bytes,
                     last_modified_at,file_hash FROM library_files WHERE 1=1
              ON CONFLICT(path) DO UPDATE SET
                library_file_id=excluded.library_file_id,
                catalog_book_id=excluded.catalog_book_id,
                filename=excluded.filename,extension=excluded.extension,
                file_size_bytes=excluded.file_size_bytes,
                last_modified_at=excluded.last_modified_at,
                file_hash=excluded.file_hash"""
        )
        conn.execute(
            "UPDATE library_settings SET last_scanned_at=CURRENT_TIMESTAMP WHERE id=1"
        )
    return {"removed_count": len(removed_paths)}


def library_files() -> list[dict]:
    return query_all(
        "SELECT f.*,i.id AS library_item_id,b.title AS matched_title,b.author AS matched_author FROM library_files f JOIN library_items i ON i.library_file_id=f.id LEFT JOIN catalog_books b ON b.id=f.matched_book_id"
    )


def search_library_files(query: str = "") -> list[dict]:
    """Search indexed file metadata directly in SQLite."""
    sql = "SELECT f.id,f.filename,f.path,f.extension,f.file_size_bytes,f.last_modified_at,f.matched_book_id,f.matched_confidence,f.scanned_at,i.id AS library_item_id,b.title AS matched_title,b.author AS matched_author FROM library_files f JOIN library_items i ON i.library_file_id=f.id LEFT JOIN catalog_books b ON b.id=f.matched_book_id WHERE 1=1"
    params: list[str] = []
    for word in query.split():
        like = f"%{word}%"
        sql += " AND (f.filename LIKE ? OR f.path LIKE ? OR COALESCE(b.title,'') LIKE ? OR COALESCE(b.author,'') LIKE ?)"
        params.extend([like] * 4)
    sql += " ORDER BY COALESCE(b.title,f.filename),f.path"
    return query_all(sql, tuple(params))


def book_context_data(query: str, limit: int = 5) -> dict:
    """Read catalog, indexed-file, and personal context in one database session."""
    words = query.split()
    book_conditions = []
    book_params: list[str] = []
    for word in words:
        like = f"%{word}%"
        book_conditions.append(
            "(b.title LIKE ? OR b.author LIKE ? OR b.genre LIKE ? "
            "OR b.description LIKE ? OR COALESCE(b.series,'') LIKE ? "
                "OR EXISTS(SELECT 1 FROM library_files fx WHERE "
                "fx.matched_book_id=b.id "
            "AND (fx.filename LIKE ? OR fx.path LIKE ?)))"
        )
        book_params.extend([like] * 7)

    with connection() as conn:
        book_sql = """SELECT b.*,
            (SELECT i.id FROM library_items i WHERE i.catalog_book_id=b.id ORDER BY i.library_file_id IS NULL,i.id LIMIT 1) AS reading_library_item_id,
            COALESCE((SELECT s.status FROM library_item_state s JOIN library_items i ON i.id=s.library_item_id WHERE i.catalog_book_id=b.id ORDER BY i.library_file_id IS NULL,i.id LIMIT 1),r.status) AS reading_status,
            COALESCE((SELECT s.current_page FROM library_item_state s JOIN library_items i ON i.id=s.library_item_id WHERE i.catalog_book_id=b.id ORDER BY i.library_file_id IS NULL,i.id LIMIT 1),r.current_page) AS current_page,
            COALESCE((SELECT s.progress_percent FROM library_item_state s JOIN library_items i ON i.id=s.library_item_id WHERE i.catalog_book_id=b.id ORDER BY i.library_file_id IS NULL,i.id LIMIT 1),r.progress_percent) AS progress_percent,
            COALESCE((SELECT s.started_at FROM library_item_state s JOIN library_items i ON i.id=s.library_item_id WHERE i.catalog_book_id=b.id ORDER BY i.library_file_id IS NULL,i.id LIMIT 1),r.started_at) AS started_at,
            COALESCE((SELECT s.completed_at FROM library_item_state s JOIN library_items i ON i.id=s.library_item_id WHERE i.catalog_book_id=b.id ORDER BY i.library_file_id IS NULL,i.id LIMIT 1),r.completed_at) AS completed_at,
            COALESCE((SELECT s.rating FROM library_item_state s JOIN library_items i ON i.id=s.library_item_id WHERE i.catalog_book_id=b.id ORDER BY i.library_file_id IS NULL,i.id LIMIT 1),ra.rating) AS rating,
            COALESCE((SELECT s.review FROM library_item_state s JOIN library_items i ON i.id=s.library_item_id WHERE i.catalog_book_id=b.id ORDER BY i.library_file_id IS NULL,i.id LIMIT 1),ra.review,'') AS review,
            COALESCE((SELECT s.is_favorite FROM library_item_state s JOIN library_items i ON i.id=s.library_item_id WHERE i.catalog_book_id=b.id ORDER BY i.library_file_id IS NULL,i.id LIMIT 1),EXISTS(SELECT 1 FROM favorites f WHERE f.book_id=b.id)) AS is_favorite,
            COALESCE((SELECT s.is_wishlisted FROM library_item_state s JOIN library_items i ON i.id=s.library_item_id WHERE i.catalog_book_id=b.id ORDER BY i.library_file_id IS NULL,i.id LIMIT 1),EXISTS(SELECT 1 FROM wishlist w WHERE w.book_id=b.id)) AS is_wishlisted
            FROM catalog_books b
            LEFT JOIN reading_records r ON r.book_id=b.id
            LEFT JOIN book_ratings ra ON ra.book_id=b.id
            WHERE """ + " AND ".join(book_conditions or ["0"])
        book_sql += " ORDER BY CASE WHEN LOWER(b.title)=LOWER(?) THEN 0 ELSE 1 END, COALESCE(b.average_rating,0) DESC,b.title LIMIT ?"
        book_rows = [
            dict(row)
            for row in conn.execute(book_sql, (*book_params, query, limit)).fetchall()
        ]
        book_ids = [row["id"] for row in book_rows]

        file_conditions = []
        file_params: list[str | int] = []
        if book_ids:
            marks = ",".join("?" for _ in book_ids)
            file_conditions.append(f"f.matched_book_id IN ({marks})")
            file_params.extend(book_ids)
        filename_conditions = []
        filename_params: list[str] = []
        for word in words:
            like = f"%{word}%"
            filename_conditions.append(
                "(f.filename LIKE ? OR f.path LIKE ? OR COALESCE(b.title,'') LIKE ?)"
            )
            filename_params.extend([like] * 3)
        if filename_conditions:
            file_conditions.append("(" + " AND ".join(filename_conditions) + ")")
            file_params.extend(filename_params)
        file_rows = []
        if file_conditions:
            file_sql = """SELECT i.id,i.id AS library_item_id,i.library_file_id,i.catalog_book_id,
                i.catalog_book_id AS matched_book_id,i.filename,i.path,i.extension,
                i.file_size_bytes,i.last_modified_at,i.file_hash,
                f.matched_confidence,f.scanned_at,b.title AS matched_title,
                b.author AS matched_author,b.title AS catalog_title,
                b.author AS catalog_author,b.genre AS catalog_genre,
                b.description AS catalog_description,s.status,s.current_page,
                s.progress_percent,s.rating,s.review,s.notes,
                COALESCE(s.is_favorite,0) AS is_favorite,
                COALESCE(s.is_wishlisted,0) AS is_wishlisted,
                s.started_at,s.completed_at,s.last_opened_at,s.tags,s.bookmarks,
                COALESCE((SELECT GROUP_CONCAT(c.name,' | ')
                    FROM library_item_collections ic
                    JOIN reader_collections c ON c.id=ic.collection_id
                    WHERE ic.library_item_id=i.id),'') AS collections
                FROM library_items i
                LEFT JOIN library_files f ON f.id=i.library_file_id
                LEFT JOIN catalog_books b ON b.id=i.catalog_book_id
                LEFT JOIN library_item_state s ON s.library_item_id=i.id
                WHERE i.library_file_id IS NOT NULL AND """
            file_conditions = [condition.replace("f.filename", "i.filename").replace("f.path", "i.path").replace("b.title", "COALESCE(b.title,'')") for condition in file_conditions]
            file_sql += "(" + " OR ".join(file_conditions) + ")"
            file_sql += " ORDER BY COALESCE(b.title,i.filename),i.path"
            file_rows = [
                dict(row)
                for row in conn.execute(file_sql, tuple(file_params)).fetchall()
            ]

        journey_rows = []
        related_rows = []
        item_ids = [row["id"] for row in file_rows]
        if book_ids or item_ids:
            journey_conditions = []
            journey_params: list[int] = []
            if book_ids:
                marks = ",".join("?" for _ in book_ids)
                journey_conditions.append(f"i.catalog_book_id IN ({marks})")
                journey_params.extend(book_ids)
            if item_ids:
                marks = ",".join("?" for _ in item_ids)
                journey_conditions.append(f"i.id IN ({marks})")
                journey_params.extend(item_ids)
            journey_rows = [dict(row) for row in conn.execute(
                """SELECT j.*,i.catalog_book_id AS book_id,i.id AS library_item_id,
                   COALESCE(b.title,i.filename) AS title
                   FROM library_item_journey j JOIN library_items i ON i.id=j.library_item_id
                   LEFT JOIN catalog_books b ON b.id=i.catalog_book_id WHERE """
                + " OR ".join(journey_conditions)
                + " ORDER BY j.occurred_at DESC,j.id DESC LIMIT 100",
                tuple(journey_params),
            ).fetchall()]
        if book_ids:
            marks = ",".join("?" for _ in book_ids)
            related_rows = [
                dict(row)
                for row in conn.execute(
                    f"""WITH ranked_related AS (
                      SELECT source.id AS source_book_id,related.*,
                        ROW_NUMBER() OVER(PARTITION BY source.id
                          ORDER BY COALESCE(related.average_rating,0) DESC,related.title) AS rank_in_group
                      FROM catalog_books source JOIN catalog_books related
                        ON related.id<>source.id AND (
                          (source.series IS NOT NULL AND source.series<>'' AND related.series=source.series)
                          OR LOWER(related.genre)=LOWER(source.genre))
                    WHERE source.id IN ({marks})
                    ) SELECT * FROM ranked_related WHERE rank_in_group<=5
                    ORDER BY source_book_id,rank_in_group""",
                    tuple(book_ids),
                ).fetchall()
            ]

        profile_row = conn.execute("SELECT * FROM reader_profile WHERE id=1").fetchone()
        status_row = conn.execute(
            "SELECT s.folder_path,s.last_scanned_at,(SELECT COUNT(*) FROM library_files) AS indexed_file_count FROM library_settings s WHERE s.id=1"
        ).fetchone()

    return {
        "books": book_rows,
        "local_files": file_rows,
        "journey": journey_rows,
        "related_books": related_rows,
        "reader_profile": dict(profile_row) if profile_row else None,
        "library_index": dict(status_row) if status_row else None,
    }


def library_duplicates() -> list[dict]:
    return query_all(
        "SELECT b.title,b.author,COUNT(*) AS file_count,GROUP_CONCAT(f.filename,' | ') AS filenames FROM library_files f JOIN catalog_books b ON b.id=f.matched_book_id GROUP BY f.matched_book_id HAVING COUNT(*)>1"
    )
