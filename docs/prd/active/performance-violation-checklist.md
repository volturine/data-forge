# Performance regression investigation

> **Status (audited 2026-08-02): Active — attribution and optimization deferred.**
> **Portfolio:** [PRD index](../README.md)

_Last audited: 2026-08-02_

The current suite is stable, but the five-run mean is 445.91s: 156.36s and
54.0% slower than the historical 289.55s mean. This PRD contains only the work
that remains for a later performance cycle.

Completed stability evidence and permanent guardrails are archived in the
[Performance Stability Gate](../implemented/performance-stability-gate.md).
The exact measurements are in the
[E2E Runtime Baseline](../implemented/e2e-runtime-baseline.md).

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

## Exit criteria

- [ ] Direct timing, occupancy, and request-count evidence is checked in.
- [ ] Each implemented optimization has focused regression coverage.
- [ ] `just verify` and `just test` pass on the final revision.
- [ ] Five consecutive `just test-e2e` runs pass with zero retries.
- [ ] The new baseline and comparison are published.
- [ ] The result meets the documented threshold, or the remaining gap is
  explicitly accepted as a product decision.
