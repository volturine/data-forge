# Performance stability gate

> **Status (audited 2026-08-02): Implemented — current stability contract verified.**
> **Portfolio:** [PRD index](../README.md)

_Last audited: 2026-08-02_

This completion record captures the original performance safeguards and
repeatability gate. The later optimization and accepted replacement baseline
are published in the implemented
[Performance Regression Investigation](performance-regression-investigation.md).

## Verified gate

- [x] `just verify` passed.
- [x] `just test` passed.
- [x] `packages/frontend/playwright.config.ts` uses `retries: 0`.
- [x] Five consecutive canonical `just test-e2e` runs passed all 351 tests.
- [x] All five runs completed with zero retries.
- [x] The dated measurements and environment are recorded in the
  [E2E Runtime Baseline](e2e-runtime-baseline.md).

The final command-level measurements were 411.98s, 452.59s, 460.99s, 450.03s,
and 453.94s. Their mean is 445.91s. This proves repeatability and coverage, not
performance acceptance: the mean is 54.0% slower than the historical 289.55s
baseline.

## Delivered runtime safeguards

- [x] Hidden setup pages do not leave eager editor prewarm work behind.
- [x] Blocking compute requests run off the asyncio event loop.
- [x] Compute-request execution is bounded so interactive fanout cannot consume
  unlimited worker capacity.
- [x] Interactive work is prioritized above user-triggered datasource creation,
  which is prioritized above background ingest.
- [x] Conflicting datasource mutations use durable fenced claims.
- [x] Concurrent Iceberg namespace bootstrap is idempotent.
- [x] Namespace-sensitive GETs retain explicit cache correctness.
- [x] Datasource creation and engine shutdown remain browser-visible flows.
- [x] Lost compute-request leases drain without stale publication.

## Permanent test policy

- Do not increase Playwright retries to hide instability.
- Do not delete meaningful browser coverage to reduce wall-clock time.
- Do not replace visible UI assertions with backend-only assertions where the UI
  exposes the behavior.
- Do not hide latency with longer waits instead of fixing the product path.
- Do not reintroduce backend-only engine shutdown or network-response coupling.

## Completion boundary

This record is complete because the safeguards and repeated stability gate are
implemented and verified. The following are deliberately not claimed here:

- the cause of the current 54.0% regression;
- per-suite or per-flow timing attribution;
- worker-occupancy measurements;
- request-count measurements; or
- an optimized replacement baseline.

Those deliverables are complete in the implemented investigation record.
