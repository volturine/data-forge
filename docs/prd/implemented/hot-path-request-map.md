# Hot-path profiling record

> **Status (audited 2026-08-09): Implemented — timing, requests, and occupancy attributed.**
> **Portfolio:** [PRD index](../README.md)

_Last audited: 2026-08-09_

The required measurements and remediation are complete. Full commands, raw
summary values, acceptance criteria, and the replacement five-run baseline are
published in the
[Performance Regression Investigation](performance-regression-investigation.md).

## Findings

- Per-file profiling covered `analysis-editor`, `analysis-pipeline`,
  `analysis-output`, `analysis-operations`, `namespace-isolation`, and
  `profile` under both sequential and four-worker load.
- Full-suite tracing recorded 5,204 API requests and 685 completed compute API
  requests used for occupancy analysis.
- Compute was active for 226.5s of a 384.5s browser window, with 1.21 mean and
  8 peak concurrent requests. Only 11.2s occurred above concurrency four, so
  request-worker capacity and build starvation were rejected as owners.
- Preview, schema, and row-count execution are the measured cost owners.
  Request-by-test inspection found no duplicate identical fanout: calls were
  tied to visible mounts, pipeline changes, or explicit actions.
- Namespace/Profile churn retained correctness-sensitive refetches; caching
  them across namespaces would violate the ownership guardrail.
- Command startup/build/cleanup overhead is the difference between the timed
  command and Playwright's critical path. The final command mean was 410.93s;
  the five stable-slot critical-path lower bounds were 362.7–382.2s.

## Delivered tooling

- `PLAYWRIGHT_JSON_REPORT=<path>` emits per-test timing.
- `PLAYWRIGHT_REQUEST_TRACE_DIR=<dir>` emits per-test API JSONL traces.
- `scripts/analyze_e2e_profile.py` reports per-file timing and stable worker-slot load.
- `scripts/analyze_request_trace.py` reports endpoint/test timing and cross-worker occupancy.
- `PLAYWRIGHT_TEST_FILES="..." just test-e2e` profiles canonical subsets.

## Completion checklist

- [x] Per-file timing for all six target files.
- [x] Four-worker compute occupancy.
- [x] Editor, inline-preview, output build/rebuild, and namespace request counts.
- [x] Command envelope separated from browser critical path.
- [x] Ranked bottlenecks mapped to implemented owners.
- [x] Focused remediation and before/after evidence.
- [x] Replacement five-run baseline.
