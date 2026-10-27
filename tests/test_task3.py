
import tempfile
from pathlib import Path

import pytest

from authorization.gateway import dispatch
from reliability.controls import (
    JsonlTraceWriter,
    ReliabilityMetrics,
    ReplayGuard,
    SlidingWindowRateLimiter,
)
from sandbox.runner import SandboxTimeoutError, SandboxWorkerError


def valid_call() -> dict:
    return {
        "tool": "sandbox_transform",
        "arguments": {
            "request_id": "req-task3-001",
            "principal_id": "user-001",
            "operation": "uppercase",
            "text": "hello",
            "limit": 100,
        },
    }


def valid_principal() -> dict:
    return {
        "principal_id": "user-001",
        "role": "support_writer",
    }


def fake_success(request, **kwargs):
    return {
        "status": "ok",
        "data": {"result": request["text"].upper()},
        "elapsed_seconds": 0.001,
    }


def dispatch_isolated(call, principal, worker):
    """Dispatch using fresh controls so tests do not share state."""
    trace_dir = Path(tempfile.mkdtemp(prefix="sandbox-task3-"))

    return dispatch(
        call,
        principal,
        worker=worker,
        replay_guard=ReplayGuard(),
        rate_limiter=SlidingWindowRateLimiter(),
        metrics=ReliabilityMetrics(),
        trace_writer=JsonlTraceWriter(str(trace_dir / "trace.jsonl")),
    )


def test_gateway_success():
    result = dispatch_isolated(
        valid_call(), valid_principal(), fake_success
    )

    assert result.status == "ok"
    assert result.data["result"] == "HELLO"
    assert any(
        event["event"] == "authorization_passed"
        for event in result.events
    )


def test_unknown_tool_is_denied():
    call = valid_call()
    call["tool"] = "unknown_tool"

    result = dispatch_isolated(call, valid_principal(), fake_success)

    assert result.status == "denied"


def test_unauthorized_role_is_denied():
    principal = {
        "principal_id": "user-001",
        "role": "guest",
    }

    result = dispatch_isolated(
        valid_call(), principal, fake_success
    )

    assert result.status == "denied"


def test_principal_identity_mismatch_is_denied():
    principal = {
        "principal_id": "different-user",
        "role": "support_writer",
    }

    result = dispatch_isolated(
        valid_call(), principal, fake_success
    )

    assert result.status == "denied"
    assert result.error == "Principal identity mismatch"


def test_denied_call_does_not_start_worker():
    calls = []

    def spy_worker(request, **kwargs):
        calls.append(request)
        return fake_success(request, **kwargs)

    result = dispatch_isolated(
        valid_call(),
        {"principal_id": "user-001", "role": "guest"},
        spy_worker,
    )

    assert result.status == "denied"
    assert calls == []


def test_invalid_arguments_do_not_start_worker():
    calls = []
    call = valid_call()
    call["arguments"]["operation"] = "execute_python"

    def spy_worker(request, **kwargs):
        calls.append(request)
        return fake_success(request, **kwargs)

    result = dispatch_isolated(
        call, valid_principal(), spy_worker
    )

    assert result.status == "invalid"
    assert calls == []


def test_non_object_request_is_rejected():
    result = dispatch_isolated(
        None, valid_principal(), fake_success
    )

    assert result.status == "invalid"


def test_malformed_arguments_are_rejected():
    call = valid_call()
    call["arguments"] = "not-an-object"

    result = dispatch_isolated(
        call, valid_principal(), fake_success
    )

    assert result.status == "invalid"


def test_worker_timeout_is_handled_safely():
    def timeout_worker(request, **kwargs):
        raise SandboxTimeoutError("internal details")

    result = dispatch_isolated(
        valid_call(), valid_principal(), timeout_worker
    )

    assert result.status == "timeout"
    assert result.error == "Sandbox execution timed out"
    assert "internal details" not in (result.error or "")


def test_worker_failure_is_handled_safely():
    def failed_worker(request, **kwargs):
        raise SandboxWorkerError("private implementation details")

    result = dispatch_isolated(
        valid_call(), valid_principal(), failed_worker
    )

    assert result.status == "failed"
    assert result.error == "Sandbox worker failed"
    assert "private implementation details" not in (result.error or "")


def test_unexpected_worker_exception_is_redacted():
    def broken_worker(request, **kwargs):
        raise RuntimeError("secret internal message")

    result = dispatch_isolated(
        valid_call(), valid_principal(), broken_worker
    )

    assert result.status == "failed"
    assert "secret internal message" not in (result.error or "")


def test_worker_response_with_invalid_result_type_is_rejected():
    def invalid_worker(request, **kwargs):
        return {
            "status": "ok",
            "data": {"result": ["unsafe"]},
        }

    result = dispatch_isolated(
        valid_call(), valid_principal(), invalid_worker
    )

    assert result.status == "failed"


def test_worker_output_limit_is_checked():
    def oversized_worker(request, **kwargs):
        return {
            "status": "ok",
            "data": {"result": "X" * 1_001},
        }

    result = dispatch_isolated(
        valid_call(), valid_principal(), oversized_worker
    )

    assert result.status == "failed"
    assert result.error == (
        "Sandbox output exceeded the permitted size"
    )


def test_worker_invalid_status_is_handled():
    def invalid_worker(request, **kwargs):
        return {
            "status": "invalid",
            "error": "unsafe internal detail",
        }

    result = dispatch_isolated(
        valid_call(), valid_principal(), invalid_worker
    )

    assert result.status == "invalid"
    assert result.error == "Worker rejected the request"
