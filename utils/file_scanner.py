"""Index supported document metadata without extracting document contents."""
import hashlib
import os
import stat
from datetime import datetime
from pathlib import Path

SUPPORTED_EXTENSIONS = {".pdf", ".epub", ".mobi"}

def scan_folder(folder: str) -> list[dict]:
    """Collect supported file metadata, failing rather than returning a partial index."""
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("The configured library folder is unavailable.")

    def raise_walk_error(error: OSError) -> None:
        raise error

    files = []
    for directory, _subdirectories, filenames in os.walk(root, onerror=raise_walk_error):
        for filename in filenames:
            path = Path(directory) / filename
            extension = path.suffix.lower()
            if extension not in SUPPORTED_EXTENSIONS:
                continue
            # An incomplete scan must not be synchronized: doing so could treat
            # an inaccessible or concurrently removed file as a real deletion.
            file_stat = path.stat()
            if not stat.S_ISREG(file_stat.st_mode):
                continue
            files.append(
                {
                    "filename": path.name,
                    "path": str(path.resolve()),
                    "extension": extension,
                    "file_size_bytes": file_stat.st_size,
                    "last_modified_at": datetime.fromtimestamp(
                        file_stat.st_mtime
                    ).astimezone().isoformat(),
                }
            )
    return files


def hash_file(path: str, chunk_size: int = 1024 * 1024) -> str:
    """Hash a changed file in chunks without extracting or retaining its contents."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()
