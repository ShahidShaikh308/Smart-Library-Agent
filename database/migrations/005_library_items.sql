CREATE TABLE library_items (
    id INTEGER PRIMARY KEY,
    library_file_id INTEGER UNIQUE REFERENCES library_files(id) ON DELETE SET NULL,
    catalog_book_id INTEGER REFERENCES catalog_books(id) ON DELETE SET NULL,
    filename TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    extension TEXT NOT NULL DEFAULT '',
    file_size_bytes INTEGER,
    last_modified_at TEXT,
    file_hash TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_library_items_catalog_book ON library_items(catalog_book_id);

INSERT INTO library_items(
    library_file_id,catalog_book_id,filename,path,extension,
    file_size_bytes,last_modified_at,file_hash
)
SELECT id,matched_book_id,filename,path,extension,file_size_bytes,
       last_modified_at,file_hash
FROM library_files;

-- Keep existing catalog-only reader data usable through virtual library items.
INSERT INTO library_items(catalog_book_id,filename,path)
SELECT b.id,b.title,'catalog:' || b.id
FROM catalog_books b
WHERE (
       EXISTS (SELECT 1 FROM reading_records r WHERE r.book_id=b.id)
    OR EXISTS (SELECT 1 FROM favorites f WHERE f.book_id=b.id)
    OR EXISTS (SELECT 1 FROM book_ratings r WHERE r.book_id=b.id)
    OR EXISTS (SELECT 1 FROM wishlist w WHERE w.book_id=b.id)
    OR EXISTS (SELECT 1 FROM reading_journey j WHERE j.book_id=b.id)
)
  AND NOT EXISTS (
      SELECT 1 FROM library_items i WHERE i.catalog_book_id=b.id
  );

CREATE TABLE library_item_state (
    library_item_id INTEGER PRIMARY KEY REFERENCES library_items(id) ON DELETE CASCADE,
    status TEXT CHECK(status IS NULL OR status IN ('want_to_read','reading','read')),
    current_page INTEGER CHECK(current_page IS NULL OR current_page >= 0),
    progress_percent REAL CHECK(progress_percent IS NULL OR (progress_percent >= 0 AND progress_percent <= 100)),
    rating INTEGER CHECK(rating IS NULL OR rating BETWEEN 1 AND 5),
    review TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    is_favorite INTEGER NOT NULL DEFAULT 0 CHECK(is_favorite IN (0,1)),
    is_wishlisted INTEGER NOT NULL DEFAULT 0 CHECK(is_wishlisted IN (0,1)),
    tags TEXT NOT NULL DEFAULT '[]',
    bookmarks TEXT NOT NULL DEFAULT '[]',
    started_at TEXT,
    completed_at TEXT,
    last_opened_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE library_item_journey (
    id INTEGER PRIMARY KEY,
    library_item_id INTEGER NOT NULL REFERENCES library_items(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    progress_value TEXT,
    note TEXT NOT NULL DEFAULT '',
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE reader_collections (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE library_item_collections (
    library_item_id INTEGER NOT NULL REFERENCES library_items(id) ON DELETE CASCADE,
    collection_id INTEGER NOT NULL REFERENCES reader_collections(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(library_item_id,collection_id)
);

-- Migrate each old catalog record to the best local match, or its virtual item.
INSERT INTO library_item_state(
    library_item_id,status,current_page,progress_percent,rating,review,
    is_favorite,is_wishlisted,started_at,completed_at
)
SELECT i.id,r.status,r.current_page,r.progress_percent,ra.rating,
       COALESCE(ra.review,''),
       EXISTS(SELECT 1 FROM favorites f WHERE f.book_id=i.catalog_book_id),
       EXISTS(SELECT 1 FROM wishlist w WHERE w.book_id=i.catalog_book_id),
       r.started_at,r.completed_at
FROM library_items i
LEFT JOIN reading_records r ON r.book_id=i.catalog_book_id
LEFT JOIN book_ratings ra ON ra.book_id=i.catalog_book_id
WHERE i.id=(
    SELECT preferred.id FROM library_items preferred
    WHERE preferred.catalog_book_id=i.catalog_book_id
    ORDER BY preferred.library_file_id IS NULL,preferred.id LIMIT 1
)
AND (r.id IS NOT NULL OR ra.book_id IS NOT NULL
     OR EXISTS(SELECT 1 FROM favorites f WHERE f.book_id=i.catalog_book_id)
     OR EXISTS(SELECT 1 FROM wishlist w WHERE w.book_id=i.catalog_book_id));

INSERT INTO library_item_journey(
    library_item_id,event_type,progress_value,note,occurred_at
)
SELECT i.id,j.event_type,j.progress_value,j.note,j.occurred_at
FROM reading_journey j
JOIN library_items i ON i.id=(
    SELECT preferred.id FROM library_items preferred
    WHERE preferred.catalog_book_id=j.book_id
    ORDER BY preferred.library_file_id IS NULL,preferred.id LIMIT 1
);
