
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from reliability.controls import (
    JsonlTraceWriter,
    ReliabilityMetrics,
    ReplayGuard,
    SlidingWindowRateLimiter,
)
from sandbox.runner import (
    SandboxTimeoutError,
    SandboxWorkerError,
    run_sandbox,
)
from schemas.registry import TOOL_REGISTRY
from schemas.tool_contract import SandboxInput, SandboxOutput


Worker = Callable[..., dict[str, Any]]

_DEFAULT_REPLAY_GUARD = ReplayGuard()
_DEFAULT_RATE_LIMITER = SlidingWindowRateLimiter()
_DEFAULT_METRICS = ReliabilityMetrics()
_DEFAULT_TRACE = JsonlTraceWriter(
    str(Path(__file__).resolve().parents[1] / "traces" / "gateway.jsonl")
)


def dispatch(
    call: dict[str, Any],
    principal: dict[str, Any],
    registry: dict[str, Any] | None = None,
    worker: Worker = run_sandbox,
    replay_guard: ReplayGuard | None = None,
    rate_limiter: SlidingWindowRateLimiter | None = None,
    metrics: ReliabilityMetrics | None = None,
    trace_writer: JsonlTraceWriter | None = None,
) -> SandboxOutput:
    """Validate, authorize, protect, and dispatch a sandbox transformation."""
    tools = TOOL_REGISTRY if registry is None else registry
    replay = replay_guard or _DEFAULT_REPLAY_GUARD
    limiter = rate_limiter or _DEFAULT_RATE_LIMITER
    counters = metrics or _DEFAULT_METRICS
    tracer = trace_writer or _DEFAULT_TRACE

    events: list[dict[str, str | int | float | bool | None]] = []
    started_at: float | None = None
    request_id: str | None = None
    principal_id: str | None = None
    tool_name: str | None = None

    def record(event: str, **fields: Any) -> None:
        safe_event: dict[str, Any] = {"event": event}
        safe_event.update(fields)
        events.append(safe_event)
        try:
            tracer.write(safe_event)
        except OSError:
            # Observability failure must not expose internal details.
            counters.increment("trace.write_error")

    def result(
        status: str,
        *,
        error: str | None = None,
        next_action: str | None = None,
        data: dict[str, str | int] | None = None,
    ) -> SandboxOutput:
        counters.increment(f"status.{status}")
        fields: dict[str, Any] = {
            "status": status,
        }
        if request_id:
            fields["request_id"] = request_id
        if principal_id:
            fields["principal_id"] = principal_id
        if tool_name:
            fields["tool"] = tool_name
        record("request_completed", **fields)

        return SandboxOutput(
            status=status,
            request_id=request_id,
            data=data or {},
            error=error,
            next_action=next_action,
            events=events.copy(),
        )

    if not isinstance(call, dict):
        record("validation_rejected")
        return result(
            "invalid",
            error="Request must be an object",
            next_action="correct_request",
        )

    tool_name = call.get("tool")
    if not isinstance(tool_name, str) or tool_name not in tools:
        record("tool_rejected")
        return result(
            "denied",
            error="Tool is not registered",
            next_action="choose_registered_tool",
        )

    spec = tools[tool_name]
    record("tool_selected", tool=tool_name)

    if not isinstance(principal, dict):
        record("authorization_denied", tool=tool_name)
        return result(
            "denied",
            error="Principal is not authorized",
            next_action="request_authorization",
        )

    role = principal.get("role")
    principal_id = principal.get("principal_id")

    if not isinstance(role, str) or role not in spec.allowed_roles:
        record("authorization_denied", tool=tool_name)
        return result(
            "denied",
            error="Principal is not authorized",
            next_action="request_authorization",
        )

    arguments = call.get("arguments")
    if not isinstance(arguments, dict):
        record("validation_rejected", tool=tool_name)
        return result(
            "invalid",
            error="Arguments must be an object",
            next_action="correct_arguments",
        )

    try:
        request = SandboxInput.model_validate(arguments)
    except ValidationError:
        record("validation_rejected", tool=tool_name)
        return result(
            "invalid",
            error="Arguments failed validation",
            next_action="correct_arguments",
        )

    request_id = request.request_id

    if request.principal_id != principal_id:
        record("authorization_denied", tool=tool_name)
        return result(
            "denied",
            error="Principal identity mismatch",
            next_action="verify_identity",
        )

    if request.operation not in spec.allowed_operations:
        record("operation_rejected", tool=tool_name)
        return result(
            "denied",
            error="Operation is not permitted",
            next_action="choose_allowed_operation",
        )

    if not replay.claim(request.principal_id, request.request_id):
        record("replay_rejected", tool=tool_name)
        return result(
            "denied",
            error="Duplicate request ID",
            next_action="use_new_request_id",
        )

    allowed, retry_after = limiter.check(request.principal_id)
    if not allowed:
        record(
            "rate_limit_rejected",
            tool=tool_name,
            retry_after_seconds=retry_after,
        )
        return result(
            "rate_limited",
            error="Request rate limit exceeded",
            next_action="retry_after_window",
        )

    record("validation_passed", tool=tool_name)
    record("authorization_passed", tool=tool_name)
    record("worker_started", tool=tool_name)

    import time
    started_at = time.monotonic()

    try:
        response = worker(
            {
                "operation": request.operation,
                "text": request.text,
                "limit": request.limit,
            },
            timeout_seconds=spec.timeout_seconds,
            max_output_chars=spec.max_output_chars,
        )
    except SandboxTimeoutError:
        record("worker_timeout", tool=tool_name)
        counters.increment("provider.attempts")
        return result(
            "timeout",
            error="Sandbox execution timed out",
            next_action="review_or_retry",
        )
    except (SandboxWorkerError, OSError):
        record("worker_failed", tool=tool_name)
        counters.increment("provider.attempts")
        return result(
            "failed",
            error="Sandbox worker failed",
            next_action="review_worker",
        )
    except Exception:
        record("worker_failed", tool=tool_name)
        counters.increment("provider.attempts")
        return result(
            "failed",
            error="Sandbox execution failed",
            next_action="review_worker",
        )

    elapsed = time.monotonic() - started_at
    counters.increment("provider.attempts")
    counters.increment("worker.elapsed_ms", max(1, int(elapsed * 1000)))

    if not isinstance(response, dict):
        record("worker_response_invalid", tool=tool_name)
        return result(
            "failed",
            error="Sandbox returned an invalid response",
            next_action="review_worker",
        )

    status = response.get("status")

    if status == "invalid":
        record("worker_rejected", tool=tool_name)
        return result(
            "invalid",
            error="Worker rejected the request",
            next_action="correct_arguments",
        )

    if status != "ok":
        record("worker_failed", tool=tool_name)
        return result(
            "failed",
            error="Sandbox returned an unsuccessful result",
            next_action="review_worker",
        )

    worker_data = response.get("data")
    if not isinstance(worker_data, dict):
        record("worker_response_invalid", tool=tool_name)
        return result(
            "failed",
            error="Sandbox returned an invalid response",
            next_action="review_worker",
        )

    transformed = worker_data.get("result")
    if type(transformed) not in (str, int):
        record("worker_response_invalid", tool=tool_name)
        return result(
            "failed",
            error="Sandbox returned an invalid result type",
            next_action="review_worker",
        )

    if isinstance(transformed, str) and len(transformed) > spec.max_output_chars:
        record("output_limit_rejected", tool=tool_name)
        return result(
            "failed",
            error="Sandbox output exceeded the permitted size",
            next_action="reduce_output",
        )

    record(
        "worker_completed",
        tool=tool_name,
        elapsed_seconds=round(elapsed, 6),
    )
    return result("ok", data={"result": transformed})
