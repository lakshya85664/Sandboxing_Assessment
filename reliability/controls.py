
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class ReplayGuard:
    """Thread-safe, in-memory protection against repeated request IDs."""

    def __init__(self, max_entries: int = 10_000) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self.max_entries = max_entries
        self._seen: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def claim(self, principal_id: str, request_id: str) -> bool:
        """Return False if the principal has already used this request ID."""
        key = (principal_id, request_id)
        with self._lock:
            if key in self._seen:
                return False

            if len(self._seen) >= self.max_entries:
                oldest_key = min(self._seen, key=self._seen.get)
                del self._seen[oldest_key]

            self._seen[key] = time.monotonic()
            return True


class SlidingWindowRateLimiter:
    """Limit each principal to a bounded number of calls per time window."""

    def __init__(
        self,
        max_requests: int = 10,
        window_seconds: float = 60.0,
    ) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")

        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, principal_id: str) -> tuple[bool, float]:
        """Return (allowed, retry_after_seconds)."""
        now = time.monotonic()

        with self._lock:
            timestamps = self._requests[principal_id]

            while timestamps and now - timestamps[0] >= self.window_seconds:
                timestamps.popleft()

            if len(timestamps) >= self.max_requests:
                retry_after = self.window_seconds - (now - timestamps[0])
                return False, max(0.0, round(retry_after, 3))

            timestamps.append(now)
            return True, 0.0


class ReliabilityMetrics:
    """Thread-safe counter collection for gateway outcomes."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def increment(self, name: str, amount: int = 1) -> None:
        if amount < 1:
            raise ValueError("amount must be positive")
        with self._lock:
            self._counts[name] += amount

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(sorted(self._counts.items()))


class JsonlTraceWriter:
    """Append compact JSON Lines events while excluding sensitive payloads."""

    ALLOWED_FIELDS = {
        "event",
        "request_id",
        "principal_id",
        "tool",
        "status",
        "elapsed_seconds",
        "retry_after_seconds",
    }

    def __init__(self, path: str) -> None:
        from pathlib import Path

        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, event: dict) -> None:
        import json

        safe_event = {
            key: value
            for key, value in event.items()
            if key in self.ALLOWED_FIELDS
            and isinstance(value, (str, int, float, bool, type(None)))
        }

        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(safe_event, sort_keys=True) + "\n")
