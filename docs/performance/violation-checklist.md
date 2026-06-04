# Performance violation checklist

_Last updated: 2026-05-21_

Use this checklist before claiming that e2e runtime or stability work is done.

## Proven-good baseline to protect

- [x] `just verify` passes
- [x] `just test` passes
- [x] `packages/frontend/playwright.config.ts` keeps `retries: 0`
- [x] 5 consecutive clean `just test-e2e` runs exist for the current state
- [x] Current measured e2e wall-clock is back near the historical target (~284s–294s across repro runs)

## Product-level regressions that must stay fixed

- [x] Hidden setup pages do not eagerly burn editor prewarm budget
- [x] Compute requests no longer block the asyncio loop
- [x] Compute request fanout is bounded so builds are not starved
- [x] Interactive work is prioritized above background ingest
- [x] User-triggered datasource create is prioritized above background ingest
- [x] Same-datasource ingest writes are serialized
- [x] Concurrent Iceberg namespace bootstrap is treated idempotently
- [x] Namespace-sensitive GETs default to `cache: 'no-store'`
- [x] Datasource creation uses browser-visible ids from UI flow
- [x] Engine shutdown uses the real UI

## Current watchlist

These areas are currently stable, but they remain the first places to inspect if wall-clock drifts upward again.

### Editor / preview hot center

- [ ] `packages/frontend/src/routes/analysis/[id]/+page.svelte`
- [ ] `packages/frontend/src/lib/components/pipeline/InlineDataTable.svelte`
- [ ] `packages/frontend/src/lib/stores/analysis.svelte.ts`
- [ ] `packages/backend/modules/compute/routes.py`
- [ ] `packages/worker/runtime/compute_service.py`

Failure smell:
- analysis shell readiness or preview readiness starts missing the 5s budget again

### Output build hot center

- [ ] `packages/frontend/src/lib/components/pipeline/OutputNode.svelte`
- [ ] `packages/backend/modules/analysis/routes.py`
- [ ] `packages/worker/runtime/compute_service.py`
- [ ] `packages/worker/datasources/datasource_service.py`

Failure smell:
- output rebuilds linger in visible `Active Build` state instead of reaching `Completed`

### Namespace / remount hot center

- [ ] `packages/frontend/src/routes/profile/+page.svelte`
- [ ] `packages/frontend/src/routes/profile/SystemTab.svelte`
- [ ] `packages/frontend/src/lib/stores/namespace.svelte.ts`
- [ ] `packages/frontend/src/lib/api/client.ts`

Failure smell:
- stale selection, stale onboard state, or route remount drift after namespace changes

### Datasource create / preview hot center

- [ ] `packages/frontend/src/routes/datasources/new/+page.svelte`
- [ ] `packages/frontend/src/routes/datasources/+page.svelte`
- [ ] `packages/frontend/tests/utils/user-flows.ts`
- [ ] `packages/worker/datasources/datasource_service.py`

Failure smell:
- datasource upload feels synchronous but behaves like background work again

## Remaining sub-280 opportunities

These are the next optimizations worth pursuing without weakening coverage.

### 1. Reduce residual editor-open work

- [ ] Audit whether the analysis route still does any mount-time work that can wait until the page is confirmed visible and stable.
- [ ] Keep helper-created hidden pages parked away from heavy routes immediately after setup.

### 2. Measure build-worker occupancy under full shard load

- [ ] Capture build-worker utilization while all 4 Playwright shards are active.
- [ ] Confirm preview and helper traffic are not stealing capacity from small visible builds.

### 3. Trim redundant preview/build request fanout

- [ ] Review analysis output and inline preview flows for duplicate warmup/load requests.
- [ ] Prefer one explicit readiness path over multiple overlapping fetches.

### 4. Trim namespace-switch request churn

- [ ] Count requests fired during namespace switch on Datasources, Monitoring, and Profile.
- [ ] Remove any duplicate remount/fetch work that does not change visible state.

### 5. Re-profile the long suites instead of guessing

- [ ] Re-measure the slowest spec files directly when runtime drifts.
- [ ] Treat `analysis-editor`, `analysis-pipeline`, `analysis-output`, `analysis-operations`, `namespace-isolation`, and `profile` as first suspects.

## Anti-patterns

Do not use these to get the number down:

- [ ] Increasing Playwright retries
- [ ] Deleting meaningful e2e coverage
- [ ] Replacing visible UI assertions with backend assertions
- [ ] Hiding latency with longer waits instead of fixing the product path
- [ ] Reintroducing backend-only engine shutdown where the UI already supports it
- [ ] Reintroducing network-response coupling when the browser already exposes the needed id/state
