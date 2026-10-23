"""Smart Library Agent application interface; UI calls this module only."""

from agent import orchestrator


def initialize():
    return orchestrator.initialize_application()


def get_library_folder():
    return orchestrator.get_library_folder()


def set_library_folder(path: str):
    return orchestrator.set_library_folder(path)


def get_reader_snapshot():
    return orchestrator.get_reader_snapshot()


def create_agent():
    return orchestrator.build_orchestrator()


def handle_message(agent, messages, reader_id=1, active_book=None, on_event=None):
    return orchestrator.execute(agent, messages, reader_id, active_book, on_event)
