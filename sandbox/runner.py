
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = PROJECT_ROOT / "sandbox" / "worker.py"

MAX_REQUEST_BYTES = 20_000
MAX_RESPONSE_BYTES = 4_096


class SandboxTimeoutError(Exception):
    """Raised when the worker exceeds its execution deadline."""


class SandboxWorkerError(Exception):
    """Raised when the worker fails or returns an invalid response."""


def run_sandbox(
    request: dict[str, Any],
    timeout_seconds: float = 2.0,
    max_output_chars: int = 1_000,
) -> dict[str, Any]:
    """Run the restricted worker and validate its response envelope."""
    if not 0 < timeout_seconds <= 10:
        raise ValueError("Timeout must be greater than 0 and at most 10 seconds")

    if not 1 <= max_output_chars <= 10_000:
        raise ValueError("Output limit is outside the permitted range")

    payload = json.dumps(request, ensure_ascii=False).encode("utf-8")

    if len(payload) > MAX_REQUEST_BYTES:
        raise ValueError("Serialized request exceeds the permitted size")

    start = time.monotonic()

    try:
        completed = subprocess.run(
            [sys.executable, "-I", str(WORKER_PATH)],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
            cwd=str(PROJECT_ROOT),
            env={
                "PATH": str(Path(sys.executable).parent),
                "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
                "WINDIR": __import__("os").environ.get("WINDIR", ""),
            },
        )
    except subprocess.TimeoutExpired as exc:
        raise SandboxTimeoutError("Sandbox execution timed out") from exc
    except OSError as exc:
        raise SandboxWorkerError("Unable to start sandbox worker") from exc

    elapsed = time.monotonic() - start

    if len(completed.stdout) > MAX_RESPONSE_BYTES:
        raise SandboxWorkerError("Worker response exceeded the permitted size")

    if completed.returncode != 0:
        raise SandboxWorkerError("Worker exited with a non-zero status")

    try:
        response = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SandboxWorkerError("Worker returned an invalid response") from exc

    if not isinstance(response, dict):
        raise SandboxWorkerError("Worker response must be a JSON object")

    status = response.get("status")
    if status not in {"ok", "invalid", "failed"}:
        raise SandboxWorkerError("Worker returned an unknown status")

    data = response.get("data")
    if status == "ok":
        if not isinstance(data, dict) or "result" not in data:
            raise SandboxWorkerError("Worker response is missing result data")

        result = data["result"]
        if isinstance(result, str) and len(result) > max_output_chars:
            raise SandboxWorkerError("Output exceeded the configured character limit")

    response["elapsed_seconds"] = round(elapsed, 6)
    return response
