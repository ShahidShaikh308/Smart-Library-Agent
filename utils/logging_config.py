import logging
import os


def configure_logging() -> None:
    debug_enabled = os.getenv("AGENT_DEBUG", "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    level = logging.DEBUG if debug_enabled else logging.INFO
    logging.basicConfig(
        level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # basicConfig leaves existing Streamlit handlers untouched, so also set the
    # root level to make AGENT_DEBUG effective after Streamlit initializes logs.
    logging.getLogger().setLevel(level)
