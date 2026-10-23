from langchain_core.tools import tool

from services import catalog_service, recommendation_service
from tools.output import serialize_tool_result


@tool
def search_catalog(query: str, genre: str = "", series: str = ""):
    """Search catalog titles, authors, genres, descriptions, or series. Use for book discovery and resolving a book title before recording it."""
    rows = catalog_service.search(query, genre or None, 15, series or None)
    return serialize_tool_result(rows)


@tool
def recommend_books():
    """Return deterministic personalized recommendations using profile, reading history, series, ratings, popularity, and owned books."""
    return serialize_tool_result(recommendation_service.recommend())


@tool
def find_similar_books(book_id: int):
    """Find catalog books in the same genre as a known book."""
    return serialize_tool_result(recommendation_service.similar(book_id))


@tool
def find_next_in_series(book_id: int):
    """Find the next catalog entry in the same series when series ordering is available."""
    return serialize_tool_result(recommendation_service.next_in_series(book_id))
