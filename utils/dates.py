from datetime import date


def today_iso() -> str:
    return date.today().isoformat()
