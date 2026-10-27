
from __future__ import annotations

import json
import sys
from typing import Any


ALLOWED_OPERATIONS = {
    "uppercase",
    "lowercase",
    "reverse",
    "word_count",
    "truncate",
}

MAX_INPUT_CHARS = 10_000
MAX_OUTPUT_CHARS = 1_000


def transform(operation: str, text: str, limit: int = 100) -> dict[str, Any]:
    """Run one explicitly allowlisted, deterministic transformation."""
    if operation not in ALLOWED_OPERATIONS:
        raise ValueError("Operation is not allowlisted")

    if not isinstance(text, str):
        raise ValueError("Text must be a string")

    if len(text) > MAX_INPUT_CHARS:
        raise ValueError("Input exceeds the permitted size")

    if "\x00" in text:
        raise ValueError("Null bytes are not allowed")

    if type(limit) is not int or not 1 <= limit <= 1_000:
        raise ValueError("Limit is outside the permitted range")

    if operation == "uppercase":
        result: str | int = text.upper()
    elif operation == "lowercase":
        result = text.lower()
    elif operation == "reverse":
        result = text[::-1]
    elif operation == "word_count":
        result = len(text.split())
    else:  # truncate
        result = text[:limit]

    if isinstance(result, str) and len(result) > MAX_OUTPUT_CHARS:
        result = result[:MAX_OUTPUT_CHARS]

    return {"result": result}


def main() -> int:
    """Read one JSON request and emit one JSON response."""
    try:
        raw = sys.stdin.read(MAX_INPUT_CHARS + 2)

        if len(raw) > MAX_INPUT_CHARS + 1:
            raise ValueError("Request exceeds the permitted size")

        request = json.loads(raw)

        if not isinstance(request, dict):
            raise ValueError("Request must be a JSON object")

        operation = request.get("operation")
        text = request.get("text")
        limit = request.get("limit", 100)

        if not isinstance(operation, str):
            raise ValueError("Operation must be a string")

        if not isinstance(text, str):
            raise ValueError("Text must be a string")

        result = transform(operation, text, limit)
        response = {"status": "ok", "data": result}

    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        response = {
            "status": "invalid",
            "error": str(exc)[:200],
        }
    except Exception:
        response = {
            "status": "failed",
            "error": "Worker failed safely",
        }

    print(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
