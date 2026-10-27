
import json

import pytest

from authorization.gateway import dispatch
from reliability.controls import (
    JsonlTraceWriter,
    ReliabilityMetrics,
    ReplayGuard,
    SlidingWindowRateLimiter,
)


def make_call(request_id: str = "req-001") -> dict:
    return {
        "tool": "sandbox_transform",
        "arguments": {
            "request_id": request_id,
            "principal_id": "user-001",
            "operation": "uppercase",
            "text": "hello",
            "limit": 100,
        },
    }


def principal() -> dict:
    return {"principal_id": "user-001", "role": "support_writer"}


def fake_success(request, **kwargs):
    return {
        "status": "ok",
        "data": {"result": request["text"].upper()},
        "elapsed_seconds": 0.001,
    }


def test_replay_guard_rejects_duplicate_request():
    guard = ReplayGuard()

    assert guard.claim("user-001", "req-1") is True
    assert guard.claim("user-001", "req-1") is False


def test_replay_guard_scopes_ids_to_principal():
    guard = ReplayGuard()

    assert guard.claim("user-001", "req-1") is True
    assert guard.claim("user-002", "req-1") is True


def test_replay_guard_requires_positive_capacity():
    with pytest.raises(ValueError):
        ReplayGuard(max_entries=0)


def test_rate_limiter_allows_requests_under_limit():
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)

    assert limiter.check("user-001")[0] is True
    assert limiter.check("user-001")[0] is True


def test_rate_limiter_rejects_requests_over_limit():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)

    assert limiter.check("user-001")[0] is True
    allowed, retry_after = limiter.check("user-001")

    assert allowed is False
    assert retry_after > 0


def test_rate_limiter_is_per_principal():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)

    assert limiter.check("user-001")[0] is True
    assert limiter.check("user-002")[0] is True


def test_rate_limiter_validates_configuration():
    with pytest.raises(ValueError):
        SlidingWindowRateLimiter(max_requests=0)

    with pytest.raises(ValueError):
        SlidingWindowRateLimiter(window_seconds=0)


def test_metrics_increment_and_snapshot():
    metrics = ReliabilityMetrics()
    metrics.increment("status.ok")
    metrics.increment("status.ok")
    metrics.increment("status.denied")

    assert metrics.snapshot() == {
        "status.denied": 1,
        "status.ok": 2,
    }


def test_metrics_reject_non_positive_increment():
    with pytest.raises(ValueError):
        ReliabilityMetrics().increment("status.ok", 0)


def test_trace_writer_redacts_unapproved_fields(tmp_path):
    path = tmp_path / "trace.jsonl"
    writer = JsonlTraceWriter(str(path))

    writer.write(
        {
            "event": "worker_completed",
            "request_id": "req-1",
            "principal_id": "user-1",
            "text": "private text",
            "api_key": "secret",
        }
    )

    event = json.loads(path.read_text(encoding="utf-8"))

    assert event["event"] == "worker_completed"
    assert event["request_id"] == "req-1"
    assert "text" not in event
    assert "api_key" not in event


def test_gateway_rejects_replayed_request(tmp_path):
    guard = ReplayGuard()
    limiter = SlidingWindowRateLimiter()
    metrics = ReliabilityMetrics()
    writer = JsonlTraceWriter(str(tmp_path / "trace.jsonl"))

    first = dispatch(
        make_call("same-id"),
        principal(),
        worker=fake_success,
        replay_guard=guard,
        rate_limiter=limiter,
        metrics=metrics,
        trace_writer=writer,
    )
    second = dispatch(
        make_call("same-id"),
        principal(),
        worker=fake_success,
        replay_guard=guard,
        rate_limiter=limiter,
        metrics=metrics,
        trace_writer=writer,
    )

    assert first.status == "ok"
    assert second.status == "denied"
    assert second.error == "Duplicate request ID"


def test_gateway_enforces_rate_limit(tmp_path):
    guard = ReplayGuard()
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    metrics = ReliabilityMetrics()
    writer = JsonlTraceWriter(str(tmp_path / "trace.jsonl"))

    first = dispatch(
        make_call("first"),
        principal(),
        worker=fake_success,
        replay_guard=guard,
        rate_limiter=limiter,
        metrics=metrics,
        trace_writer=writer,
    )
    second = dispatch(
        make_call("second"),
        principal(),
        worker=fake_success,
        replay_guard=guard,
        rate_limiter=limiter,
        metrics=metrics,
        trace_writer=writer,
    )

    assert first.status == "ok"
    assert second.status == "rate_limited"
    assert second.error == "Request rate limit exceeded"


def test_gateway_records_metrics_and_traces(tmp_path):
    metrics = ReliabilityMetrics()
    trace_path = tmp_path / "trace.jsonl"
    writer = JsonlTraceWriter(str(trace_path))

    result = dispatch(
        make_call("metric-test"),
        principal(),
        worker=fake_success,
        replay_guard=ReplayGuard(),
        rate_limiter=SlidingWindowRateLimiter(),
        metrics=metrics,
        trace_writer=writer,
    )

    assert result.status == "ok"
    assert metrics.snapshot()["status.ok"] == 1
    assert metrics.snapshot()["provider.attempts"] == 1

    records = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(item["event"] == "worker_completed" for item in records)
    assert any(item["event"] == "request_completed" for item in records)
