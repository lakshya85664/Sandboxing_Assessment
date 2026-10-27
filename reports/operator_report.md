
# Topic 19 — Sandboxing Assessment Operator Report

## 1. Overview

This project implements a restricted transformation tool with an explicit
operation allowlist, validated request contracts, role-based authorization,
worker-process execution, bounded execution time, and output-size checks.

The gateway applies replay protection and per-principal rate limiting.
Structured JSONL traces and in-memory metrics support assessment and
troubleshooting.

## 2. Architecture

Request flow:

1. Receive a tool call and principal context.
2. Resolve the requested tool from the registry.
3. Check the principal role.
4. Validate the request using Pydantic.
5. Verify principal identity and allowed operation.
6. Reject duplicate request IDs.
7. Apply the rate limiter.
8. Invoke the restricted worker process.
9. Validate the worker response and output length.
10. Record outcome metrics and structured trace events.

## 3. Security Controls

- Explicit allowlist of five text transformations.
- Unknown input fields are rejected.
- Input length and transformation limits are validated.
- Role-based access and principal identity checks.
- Worker execution timeout.
- Output-size checks in the worker and gateway.
- Replay protection and per-principal rate limiting.
- Safe public errors for worker failures.
- Trace field allowlist to reduce sensitive-data exposure.

## 4. Assessment Evidence

The evidence generator runs four scenarios:

- Successful transformation.
- Rate-limit enforcement.
- Duplicate-request rejection.
- Worker-timeout handling.

Evidence files:

- `outputs/evidence_summary.json`
- `traces/assessment_trace.jsonl`
- `traces/gateway.jsonl`

Use the generated evidence summary for the actual scenario results and
metrics. Do not report a scenario as passed unless the generator confirms it.

## 5. Verification Commands

Run the complete test suite:

    python -m pytest -q

Generate assessment evidence:

    python outputs/generate_evidence.py

Inspect the evidence summary:

    type outputs\evidence_summary.json

Inspect the assessment trace:

    type traces\assessment_trace.jsonl

## 6. Known Limitations

- Replay protection and rate limiting use in-memory state and reset when
  the process restarts.
- Controls are not shared between independent application processes.
- A subprocess and timeout do not constitute a hardened operating-system
  sandbox.
- The worker avoids arbitrary Python execution and supports only allowlisted
  deterministic transformations.
- Metrics are in-memory counters, not a persistent monitoring service.
- JSONL trace writing is local-file based.

## 7. Operational Recommendation

Keep the transformation allowlist narrow. Before deploying untrusted
code execution, add operating-system-level isolation, restrictive filesystem
and network permissions, resource quotas, and external monitoring. Validate
the deployed configuration independently rather than treating unit tests
as proof of a complete security boundary.
