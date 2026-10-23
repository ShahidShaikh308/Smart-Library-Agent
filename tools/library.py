from langchain_core.tools import tool

from services import local_library_service
from tools.output import serialize_tool_result


@tool
def scan_library():
    """Explicitly scan or refresh the one configured PDF, EPUB, and MOBI library incrementally; hash only new or changed files, never extract text."""
    try:
        return serialize_tool_result(local_library_service.scan())
    except (ValueError, OSError) as exc:
        return serialize_tool_result({"error": str(exc)})


@tool
def list_owned_books(query: str = ""):
    """List indexed local files and their matched catalog books."""
    return serialize_tool_result(local_library_service.files(query))


@tool
def find_missing_books(query: str = ""):
    """Find catalog books matching query that are not matched to an indexed local file."""
    return serialize_tool_result(local_library_service.missing(query))


@tool
def find_library_duplicates():
    """Find multiple indexed files matched to the same catalog book."""
    return serialize_tool_result(local_library_service.duplicates())
