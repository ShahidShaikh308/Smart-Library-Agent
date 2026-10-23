"""Apply the base schema and any later numbered SQL migrations."""

import re
import sqlite3
from pathlib import Path


def _run_script_atomically(connection: sqlite3.Connection, script: str) -> None:
    """Apply a SQL script as one transaction, rolling back partial migrations."""
    try:
        connection.executescript(f"BEGIN IMMEDIATE;\n{script}\nCOMMIT;")
    except sqlite3.Error:
        if connection.in_transaction:
            connection.rollback()
        raise


def migrate(connection: sqlite3.Connection, schema_path: Path) -> int:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version == 0:
        _run_script_atomically(connection, schema_path.read_text(encoding="utf-8"))
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    migration_dir = schema_path.parent / "migrations"
    for path in sorted(migration_dir.glob("*.sql")):
        match = re.match(r"(\d+)_", path.name)
        if not match:
            continue
        target = int(match.group(1))
        if target > version:
            script = path.read_text(encoding="utf-8")
            _run_script_atomically(connection, f"{script}\nPRAGMA user_version = {target};")
            version = target
    return version
