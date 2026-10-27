
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from authorization.gateway import dispatch
from reliability.controls import (
    JsonlTraceWriter,
    ReliabilityMetrics,
    ReplayGuard,
    SlidingWindowRateLimiter,
)
from sandbox.runner import SandboxTimeoutError


OUTPUT_DIR = ROOT / "outputs"
TRACE_DIR = ROOT / "traces"
SUMMARY_PATH = OUTPUT_DIR / "evidence_summary.json"
TRACE_PATH = TRACE_DIR / "assessment_trace.jsonl"


def make_call(request_id: str, operation: str = "uppercase") -> dict:
    return {
        "tool": "sandbox_transform",
        "arguments": {
            "request_id": request_id,
            "principal_id": "evidence-user",
            "operation": operation,
            "text": "sandbox evidence",
            "limit": 100,
        },
    }


def make_principal() -> dict:
    return {
        "principal_id": "evidence-user",
        "role": "support_writer",
    }


def run_evidence() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TRACE_DIR.mkdir(parents=True, exist_ok=True)

    # Rebuild only this dedicated assessment trace on each run.
    TRACE_PATH.write_text("", encoding="utf-8")

    metrics = ReliabilityMetrics()
    tracer = JsonlTraceWriter(str(TRACE_PATH))
    scenarios: list[dict[str, Any]] = []

    def record(name: str, result, expected: str) -> None:
        passed = result.status == expected
        scenarios.append(
            {
                "scenario": name,
                "status": result.status,
                "expected_status": expected,
                "passed": passed,
                "error": result.error,
                "events": result.events,
            }
        )

    # Scenario 1: successful transformation.
    success = dispatch(
        make_call("evidence-success"),
        make_principal(),
        worker=None or __import__(
            "sandbox.runner", fromlist=["run_sandbox"]
        ).run_sandbox,
        replay_guard=ReplayGuard(),
        rate_limiter=SlidingWindowRateLimiter(),
        metrics=metrics,
        trace_writer=tracer,
    )
    record("successful_transformation", success, "ok")

    # Scenario 2: rate limit blocks the second request.
    rate_guard = ReplayGuard()
    rate_limiter = SlidingWindowRateLimiter(
        max_requests=1,
        window_seconds=60,
    )
    first_rate_call = dispatch(
        make_call("evidence-rate-1"),
        make_principal(),
        replay_guard=rate_guard,
        rate_limiter=rate_limiter,
        metrics=metrics,
        trace_writer=tracer,
    )
    limited = dispatch(
        make_call("evidence-rate-2"),
        make_principal(),
        replay_guard=rate_guard,
        rate_limiter=rate_limiter,
        metrics=metrics,
        trace_writer=tracer,
    )
    record("rate_limit_enforced", limited, "rate_limited")
    scenarios[-1]["setup_request_status"] = first_rate_call.status

    # Scenario 3: duplicate request IDs are rejected.
    replay_guard = ReplayGuard()
    replay_limiter = SlidingWindowRateLimiter()
    dispatch(
        make_call("evidence-replay"),
        make_principal(),
        replay_guard=replay_guard,
        rate_limiter=replay_limiter,
        metrics=metrics,
        trace_writer=tracer,
    )
    duplicate = dispatch(
        make_call("evidence-replay"),
        make_principal(),
        replay_guard=replay_guard,
        rate_limiter=replay_limiter,
        metrics=metrics,
        trace_writer=tracer,
    )
    record("duplicate_request_rejected", duplicate, "denied")

    # Scenario 4: timeout is reported safely.
    def timeout_worker(request, **kwargs):
        raise SandboxTimeoutError("private worker detail")

    timed_out = dispatch(
        make_call("evidence-timeout"),
        make_principal(),
        worker=timeout_worker,
        replay_guard=ReplayGuard(),
        rate_limiter=SlidingWindowRateLimiter(),
        metrics=metrics,
        trace_writer=tracer,
    )
    record("worker_timeout_handled", timed_out, "timeout")

    summary = {
        "topic": 19,
        "assessment": "Implement Sandboxing in Code",
        "scenario_count": len(scenarios),
        "passed_scenarios": sum(item["passed"] for item in scenarios),
        "all_scenarios_passed": all(item["passed"] for item in scenarios),
        "metrics": metrics.snapshot(),
        "scenarios": scenarios,
        "trace_file": "traces/assessment_trace.jsonl",
    }

    SUMMARY_PATH.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print("Topic 19 — Evidence Generation")
    print("=" * 38)
    print(f"Scenarios passed: {summary['passed_scenarios']}/{summary['scenario_count']}")
    print(f"Trace file: {TRACE_PATH}")
    print(f"Summary file: {SUMMARY_PATH}")
    print(f"All scenarios passed: {summary['all_scenarios_passed']}")

    return summary


if __name__ == "__main__":
    run_evidence()
