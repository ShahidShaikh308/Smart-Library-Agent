"""Encode deterministic tool results as non-empty JSON message content."""
import json
import math
from collections.abc import Mapping


def _json_safe(value: object) -> object:
    """Convert tool data into JSON-safe primitives, including non-finite numbers."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_json_safe(item) for item in value]
        return sorted(items, key=repr) if isinstance(value, (set, frozenset)) else items
    return str(value)


def serialize_tool_result(value: object) -> str:
    """Return a JSON string suitable for LLM tool-result messages."""
    return json.dumps(_json_safe(value), ensure_ascii=False, allow_nan=False)
