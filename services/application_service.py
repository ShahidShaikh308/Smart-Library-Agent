"""Application bootstrap and UI operations behind the service layer."""

from database import database
from services import local_library_service, reader_service, reading_service


def initialize() -> None:
    database.initialize()


def library_folder() -> str | None:
    return local_library_service.get_folder()


def save_library_folder(path: str) -> str:
    return local_library_service.set_folder(path)


def reader_snapshot() -> dict:
    return {
        "profile": reader_service.get_profile(),
        "dashboard": reading_service.dashboard(),
        "wishlist": reading_service.wishlist_items(),
    }
