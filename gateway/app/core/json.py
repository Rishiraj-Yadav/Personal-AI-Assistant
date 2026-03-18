"""
JSON utilities for the Gateway
"""
from __future__ import annotations
import json
from typing import Any


def dumps(obj: Any) -> str:
    """Serialize object to JSON string, handling non-serializable types."""
    return json.dumps(obj, default=str, ensure_ascii=False)


def loads(s: str) -> Any:
    """Deserialize JSON string to object."""
    return json.loads(s)


def safe_jsonable(obj: Any) -> Any:
    """Convert an object to a JSON-serializable form."""
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)
