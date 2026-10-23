CREATE TABLE IF NOT EXISTS favorites (
    book_id INTEGER PRIMARY KEY REFERENCES catalog_books(id),
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS book_ratings (
    book_id INTEGER PRIMARY KEY REFERENCES catalog_books(id),
    rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
    review TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT OR IGNORE INTO favorites(book_id)
SELECT book_id FROM reading_records WHERE is_favorite=1;
INSERT OR IGNORE INTO book_ratings(book_id,rating,review)
SELECT book_id,rating,review FROM reading_records WHERE rating IS NOT NULL;
