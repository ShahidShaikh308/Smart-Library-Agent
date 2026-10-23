PRAGMA foreign_keys = ON;
PRAGMA user_version = 1;
CREATE TABLE IF NOT EXISTS catalog_books (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, author TEXT NOT NULL, genre TEXT NOT NULL, description TEXT NOT NULL,
 series TEXT, series_number TEXT, publication_year INTEGER, isbn TEXT, publisher TEXT, language TEXT,
 average_rating REAL, page_count INTEGER, popularity INTEGER, UNIQUE(title, author)
);
CREATE TABLE IF NOT EXISTS reader_profile (
 id INTEGER PRIMARY KEY CHECK(id = 1), name TEXT NOT NULL DEFAULT 'Reader', favorite_genres TEXT NOT NULL DEFAULT '',
 favorite_authors TEXT NOT NULL DEFAULT '', favorite_books TEXT NOT NULL DEFAULT '', reading_goals TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS reading_records (
 id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL UNIQUE REFERENCES catalog_books(id),
 status TEXT NOT NULL CHECK(status IN ('want_to_read','reading','read')),
 current_page INTEGER CHECK(current_page IS NULL OR current_page >= 0),
 progress_percent REAL CHECK(progress_percent IS NULL OR (progress_percent >= 0 AND progress_percent <= 100)),
 rating INTEGER CHECK(rating IS NULL OR (rating BETWEEN 1 AND 5)), review TEXT NOT NULL DEFAULT '',
 is_favorite INTEGER NOT NULL DEFAULT 0 CHECK(is_favorite IN (0,1)), started_at TEXT, completed_at TEXT,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS reading_journey (
 id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL REFERENCES catalog_books(id), event_type TEXT NOT NULL,
 progress_value TEXT, note TEXT NOT NULL DEFAULT '', occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS wishlist (
 id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL UNIQUE REFERENCES catalog_books(id),
 added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS library_settings (
 id INTEGER PRIMARY KEY CHECK(id = 1), folder_path TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS library_files (
 id INTEGER PRIMARY KEY, filename TEXT NOT NULL, path TEXT NOT NULL UNIQUE, extension TEXT NOT NULL,
 file_size_bytes INTEGER NOT NULL, last_modified_at TEXT NOT NULL,
 matched_book_id INTEGER REFERENCES catalog_books(id), matched_confidence REAL,
 scanned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_catalog_genre ON catalog_books(genre);
CREATE UNIQUE INDEX IF NOT EXISTS idx_catalog_isbn ON catalog_books(isbn) WHERE isbn IS NOT NULL AND isbn <> '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_catalog_title_author_normalized ON catalog_books(LOWER(title),LOWER(author));
CREATE INDEX IF NOT EXISTS idx_reading_status ON reading_records(status);
