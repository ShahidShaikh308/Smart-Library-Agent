Schema upgrades are applied through versioned SQL migrations. Version 1 creates the initial schema in `schema.sql`.

Version 4 adds `library_files.file_hash` and `library_settings.last_scanned_at` for incremental local-library index refreshes. These columns are additive; existing indexed rows remain available and their hashes are backfilled on the next explicit scan.

Version 5 introduces reader-owned `library_items` and per-item state, journey,
and collection tables. Existing indexed files become library items. Catalog-only
reader records migrate to a virtual item, while records for matched catalog books
prefer an indexed local item. Legacy catalog tables remain in place so migration
does not discard the original data.
