# Performance violation checklist

> **Status (audited 2026-08-02): Active — stable, but 54.0% slower than the historical baseline.**
> **Portfolio:** [PRD index](../README.md)

_Last audited: 2026-08-02_

Use this checklist before claiming that e2e runtime or stability work is done.

## Current verified gates

- [x] `just verify` passes.
- [x] `just test` passes.
- [x] `packages/frontend/playwright.config.ts` keeps `retries: 0`.
- [x] Five consecutive canonical `just test-e2e` runs passed all 351 tests.
- [x] All five runs used zero retries.
- [x] A dated wall-clock measurement is published in the [E2E Runtime Baseline](../implemented/e2e-runtime-baseline.md).
- [ ] Explain or reverse the increase from the May mean of 289.55s to the current measured mean of 445.91s (+54.0%).

The five-run gate proves current stability. It does not substitute for direct
profiling, worker-occupancy evidence, or request counts.

## Product-level regressions that must stay fixed

- [x] Hidden setup pages do not eagerly burn editor prewarm budget.
- [x] Compute requests no longer block the asyncio loop.
- [x] Compute request fanout is bounded so builds are not starved.
- [x] Interactive work is prioritized above background ingest.
- [x] User-triggered datasource create is prioritized above background ingest.
- [x] Same-datasource ingest writes are serialized.
- [x] Concurrent Iceberg namespace bootstrap is treated idempotently.
- [x] Namespace-sensitive GETs default to `cache: 'no-store'`.
- [x] Datasource creation uses browser-visible ids from UI flow.
- [x] Engine shutdown uses the real UI.

## Open profiling work

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

- [ ] Measure per-file timing or traces for `analysis-editor`, `analysis-pipeline`, `analysis-output`, `analysis-operations`, `namespace-isolation`, and `profile`.
- [ ] Attribute the regression only after direct evidence identifies an owner.

## Anti-patterns

Do not use these to get the number down:

- Increasing Playwright retries.
- Deleting meaningful e2e coverage.
- Replacing visible UI assertions with backend assertions.
- Hiding latency with longer waits instead of fixing the product path.
- Reintroducing backend-only engine shutdown where the UI already supports it.
- Reintroducing network-response coupling when the browser already exposes the needed id or state.
