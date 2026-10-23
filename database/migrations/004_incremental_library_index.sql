ALTER TABLE library_settings ADD COLUMN last_scanned_at TEXT;
ALTER TABLE library_files ADD COLUMN file_hash TEXT;
