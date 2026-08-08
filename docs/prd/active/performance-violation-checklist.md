# Performance regression investigation

> **Status (audited 2026-08-07): Active — first per-file timing evidence recorded.**
> **Portfolio:** [PRD index](../README.md)

_Last audited: 2026-08-07_

The current suite is stable, but the five-run mean is 445.91s: 156.36s and
54.0% slower than the historical 289.55s mean. This PRD contains the work that
remains to attribute and remove the regression.

Completed stability evidence and permanent guardrails are archived in the
[Performance Stability Gate](../implemented/performance-stability-gate.md).
The exact measurements are in the
[E2E Runtime Baseline](../implemented/e2e-runtime-baseline.md).

## Measured per-file timing (2026-08-07)

Single clean run of the six target files, `PW_E2E_WORKERS=1` (sequential, so
per-test durations are directly attributable; no worker contention). 170/170
passed in 7.1m; sum of test durations 407.7s. Environment: same M4 worktree,
postgres:18 + rustfs via the canonical harness.

| File | Tests | Total | Mean | Median | p90 | Slowest |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `analysis-operations` | 28 | 99.9s | 3.6s | 3.2s | 4.4s | 7.9s |
| `analysis-pipeline` | 28 | 99.5s | 3.6s | 3.5s | 3.8s | 4.6s |
| `analysis-editor` | 49 | 79.3s | 1.6s | 0.6s | 3.5s | 4.0s |
| `analysis-output` | 17 | 68.0s | 4.0s | 3.7s | 5.3s | 8.4s |
| `profile` | 43 | 31.3s | 0.7s | 0.5s | 1.2s | 2.9s |
| `namespace-isolation` | 5 | 29.8s | 6.0s | 7.7s | 8.5s | 8.8s |

Reading:
- The cost is concentrated in **step-Apply / build round trips**, not UI-only
  work. `analysis-editor` (49 tests, 0.6s median) is mostly UI interaction and
  cheap; `analysis-operations`/`analysis-pipeline`/`analysis-output` each settle
  in ~3.6–4.0s per Apply-style test, and `namespace-isolation` is the most
  expensive per test (6.0s mean) because each case switches namespace and waits
  for a build.
- This directly supports the "snappier app = faster tests" hypothesis: cutting
  build/apply latency and preview fanout removes the dominant per-test cost.
  The next step is request-count and build-timing traces to say *where* the
  3–4s per Apply goes (backend build vs. UI settle vs. test polling).

## Local e2e instability (measurement caveat)

Local full-suite runs on this worktree were intermittently disrupted by
OOM-kills of the backend under memory pressure caused by concurrent workloads
on the same machine (not the app). Affected runs surface as
`ClaimBuildJob` → `UNAVAILABLE: Connection refused` once the restarted backend
loses its internal-gRPC server. Single-file/single-worker runs recover on retry
and produced the clean measurement above. This is an environment/load
observation, not the 54.0% regression and not a product bug; the baseline
stability gate was verified on the recording environment. Full four-worker
runs should be re-measured where the 5-clean baseline was established, on an
otherwise idle machine.

## Objective

- [ ] Attribute the 54.0% regression to measured product paths.
- [ ] Remove or redesign the verified bottlenecks without weakening coverage.
- [ ] Publish a replacement five-run baseline on the optimized revision.
- [ ] Decide and document an explicit performance acceptance threshold.

## Required investigation

### Residual editor-open work

- [ ] Profile analysis-route mount work after the page becomes visible and stable.
- [ ] Confirm helper-created hidden pages remain parked away from heavy routes.

### Build-worker occupancy

- [ ] Capture build-worker utilization while all four Playwright workers are active.
- [ ] Confirm preview and helper traffic are not stealing capacity from visible builds.

### Preview/build request fanout

- [ ] Count warmup, load, preview, and build requests in analysis output and inline-preview flows.
- [ ] Remove overlapping requests that do not change visible state.

### Namespace-switch request churn

- [ ] Count requests during namespace switches on Datasources, Monitoring, and Profile.
- [ ] Remove duplicate remount or fetch work that does not change visible state.

### Long-suite profiling

- [x] Measure per-file timing or traces for `analysis-editor`, `analysis-pipeline`, `analysis-output`, `analysis-operations`, `namespace-isolation`, and `profile`. See [Measured per-file timing](#measured-per-file-timing-2026-08-07).
- [ ] Trace request counts and build timing for the Apply/output flows that dominate the per-test cost.
- [ ] Attribute the regression only after direct evidence identifies an owner.

## Measurement tooling added

- `packages/frontend/playwright.config.ts`: `PLAYWRIGHT_JSON_REPORT=<path>`
  enables the Playwright JSON reporter for per-test durations.
- `scripts/analyze_e2e_profile.py`: aggregates a JSON report into per-file
  totals/percentiles and worker load.
- `scripts/test_e2e.sh`: `PLAYWRIGHT_TEST_FILES="tests/a.test.ts ..."` runs a
  Playwright subset through the canonical harness.

## Anti-patterns

Do not use these to get the number down:

- Increasing Playwright retries.
- Deleting meaningful e2e coverage.
- Replacing visible UI assertions with backend assertions.
- Hiding latency with longer waits instead of fixing the product path.
- Reintroducing backend-only engine shutdown where the UI already supports it.
- Reintroducing network-response coupling when the browser already exposes the needed id or state.

## Exit criteria

- [ ] Direct timing, occupancy, and request-count evidence is checked in.
- [ ] Each implemented optimization has focused regression coverage.
- [ ] `just verify` and `just test` pass on the final revision.
- [ ] Five consecutive `just test-e2e` runs pass with zero retries.
- [ ] The new baseline and comparison are published.
- [ ] The result meets the documented threshold, or the remaining gap is
  explicitly accepted as a product decision.
