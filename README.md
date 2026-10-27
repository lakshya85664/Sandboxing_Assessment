# Topic 19 — Implement Sandboxing in Code

## Project Overview

This assessment implements a restricted text-transformation tool with validated contracts, a tool registry, role-based authorization, a separate worker process, bounded execution time, output-size checks, replay protection, rate limiting, metrics, and structured JSONL traces.

The worker does not execute arbitrary Python code. It supports only five allowlisted transformations: `uppercase`, `lowercase`, `reverse`, `word_count`, and `truncate`.

## Objectives

- Define strict Pydantic request, response, and tool metadata models.
- Register the sandbox tool with permitted roles, operations, and resource limits.
- Validate requests and authorize principals before worker execution.
- Execute transformations in a separate Python process with a timeout.
- Reject duplicate request IDs and enforce per-principal request limits.
- Return safe public errors and validate worker responses.
- Generate trace and evidence files for four assessment scenarios.

## Architecture

1. The gateway receives a tool name, arguments, and principal context.
2. The registry resolves the tool and its access policy.
3. Pydantic validates the request contract.
4. The gateway checks the role, principal identity, and allowed operation.
5. Replay protection and rate limiting are applied.
6. The runner launches the restricted worker process with a timeout.
7. The gateway validates the worker result and output size.
8. Metrics and JSONL trace events record the outcome.

## Supported Transformations

| Operation | Behavior |
|---|---|
| `uppercase` | Converts text to uppercase |
| `lowercase` | Converts text to lowercase |
| `reverse` | Reverses the text |
| `word_count` | Counts whitespace-separated words |
| `truncate` | Returns up to the requested number of characters |

## Project Structure

```text
Sandboxing_Assessment/
├── authorization/gateway.py
├── schemas/registry.py
├── schemas/tool_contract.py
├── sandbox/runner.py
├── sandbox/worker.py
├── reliability/controls.py
├── tests/test_task1.py
├── tests/test_task2.py
├── tests/test_task3.py
├── tests/test_task4.py
├── outputs/generate_evidence.py
├── outputs/evidence_summary.json
├── traces/assessment_trace.jsonl
├── traces/gateway.jsonl
├── reports/operator_report.md
├── requirements.txt
├── .gitignore
└── README.md
```

## Setup

Use Python 3.13 or a compatible Python 3 version. Activate the project virtual environment, then install dependencies in a fresh environment:

```bat
python -m pip install -r requirements.txt
```

## Verification

Run all tests:

```bat
python -m pytest -q
```

Verified assessment result: **49 tests passed**.

Generate evidence:

```bat
python outputs\generate_evidence.py
```

Verified evidence result: **4 of 4 scenarios passed**.

Inspect evidence:

```bat
type outputs\evidence_summary.json
type traces\assessment_trace.jsonl
```

## Evidence Scenarios

1. Successful transformation — expected status `ok`.
2. Rate-limit enforcement — expected status `rate_limited`.
3. Duplicate-request rejection — expected status `denied`.
4. Worker timeout handling — expected status `timeout`.

The generated summary is the source of truth for the recorded scenario outcomes and counters.

## Security Controls

- Explicit allowlist; no arbitrary `eval()` or `exec()` execution.
- Strict input schema and unknown-field rejection.
- Role-based access and principal identity checks.
- Request and output-size limits.
- Worker timeout and response validation.
- In-memory replay protection and per-principal rate limiting.
- Safe error messages for worker failures.
- Trace writer field allowlist to avoid recording transformation text or arbitrary secret fields.

## Known Limitations

- Replay and rate-limit state is in memory and resets when the process restarts.
- State is not shared across independent application processes.
- A subprocess and timeout alone are not a hardened operating-system sandbox.
- The worker is restricted to deterministic allowlisted transformations and does not run user-supplied Python.
- Metrics are in-memory counters, and trace files are local JSONL files.
- Unit tests demonstrate implemented behavior; they do not prove a complete security boundary.

## Reflection

Working on this assessment helped me connect tool contracts, authorization, process boundaries, and reliability controls into one workflow. I learned that validating a request is only one part of protecting a tool: the gateway must also confirm who is making the request, what operation is permitted, and whether the request has already been processed. Separating the worker from the gateway made the execution path easier to reason about and gave the runner a place to enforce a timeout and check the worker's response.

The test-driven workflow was especially useful. The tests covered valid transformations as well as invalid operations, unauthorized roles, identity mismatches, worker exceptions, duplicate requests, rate limits, and timeouts. A shared replay guard initially caused tests to interfere with one another; using fresh control instances in the tests made the test behavior deterministic without removing the gateway's default controls. The metrics tests also exposed the need to handle very short elapsed-time measurements consistently.

The evidence generator provides repeatable demonstrations of four important outcomes and writes a summary and JSONL trace that can be inspected after a run. This makes the implementation easier to review than relying only on console output.

The most important limitation is that a separate process is not automatically a secure operating-system sandbox. The current design avoids arbitrary code execution by allowing only five predefined text transformations, but a production system that executes untrusted code would need stronger OS-level isolation, filesystem and network restrictions, resource quotas, and externally managed monitoring. Overall, this assessment strengthened my understanding of defense in depth, controlled tool execution, test isolation, and evidence-based verification.
