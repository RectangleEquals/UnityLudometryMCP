"""Strict JSON for the wire: the same rules as the C# package.

Rejects invalid UTF-8, duplicate property names, NaN/Infinity, excessive nesting and oversized input. Writes compact
UTF-8 JSON (unpaired surrogates as escapes, never NaN).
"""

from __future__ import annotations

import codecs
import json
from typing import Any

from .errors import INVALID_FRAME, ProtocolException

DEFAULT_MAX_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_DEPTH = 128


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolException(INVALID_FRAME, f"Invalid JSON: duplicate property name '{key}'.")
        result[key] = value
    return result


def _no_constant(name: str) -> Any:
    raise ProtocolException(INVALID_FRAME, f"Invalid JSON: {name} is not valid JSON.")


def _depth(value: Any, limit: int) -> None:
    stack = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if isinstance(current, (dict, list)):
            if depth > limit:
                raise ProtocolException(INVALID_FRAME, f"Invalid JSON: nesting deeper than {limit} levels.")
            children = current.values() if isinstance(current, dict) else current
            stack.extend((child, depth + 1) for child in children)


def _escape_surrogates(error: UnicodeError) -> tuple[str, int]:
    """Encoding error handler: writes unpaired surrogates as JSON escapes (they can only occur inside JSON strings)."""
    if not isinstance(error, UnicodeEncodeError):
        raise error
    chunk = error.object[error.start:error.end]
    return "".join(f"\\u{ord(c):04x}" for c in chunk), error.end


codecs.register_error("ulm-json-surrogates", _escape_surrogates)


def loads(data: bytes | str, *, max_bytes: int = DEFAULT_MAX_BYTES, max_depth: int = DEFAULT_MAX_DEPTH) -> Any:
    """Parses one JSON document. Raises ProtocolException(INVALID_FRAME)."""
    if isinstance(data, str):
        data = data.encode("utf-8", "ulm-json-surrogates")
    if len(data) > max_bytes:
        raise ProtocolException(INVALID_FRAME, f"Invalid JSON: {len(data)} bytes exceed the limit of {max_bytes} bytes.")
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        text = data.decode("utf-8", "strict")
    except UnicodeDecodeError as e:
        raise ProtocolException(INVALID_FRAME, "Invalid JSON: invalid UTF-8.") from e
    try:
        value = json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except ProtocolException:
        raise
    except RecursionError as e:
        raise ProtocolException(INVALID_FRAME, "Invalid JSON: nesting too deep.") from e
    except ValueError as e:
        raise ProtocolException(INVALID_FRAME, f"Invalid JSON: {e}") from e
    _depth(value, max_depth)
    return value


def dumps(value: Any) -> bytes:
    """Serializes to compact UTF-8 JSON. Raises ValueError for NaN/Infinity."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8", "ulm-json-surrogates")
