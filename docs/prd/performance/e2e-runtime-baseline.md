# E2E runtime baseline

> **Status (audited 2026-08-02): Active — re-baselining required.**
> **Portfolio:** [PRD index](../README.md)

_Last audited: 2026-08-02_

This document records historical e2e measurements and the requirements for a new proven baseline. It must not be read as the current performance claim until the re-baselining checklist is completed.
It is intentionally strict:

- `packages/frontend/playwright.config.ts` uses **`retries: 0`**
- assertions remain **UI-visible and user-like**
- engine shutdown uses the real UI
- datasource creation uses the real UI
- stability claims require repeated clean `just test-e2e` runs

Related documents:
- [`./hot-path-request-map.md`](./hot-path-request-map.md)
- [`./violation-checklist.md`](./violation-checklist.md)

## Historical baseline — 2026-05-21

Five consecutive clean `just test-e2e` runs on the then-current state:

| Run | Wall-clock |
| --- | ---: |
| 1 | 284.26s |
| 2 | 285.82s |
| 3 | 293.66s |
| 4 | 290.26s |
| 5 | 293.76s |

### Summary

- Average: **289.55s**
- Best run: **284.26s**
- Worst run: **293.76s**
- Historical target: **~280s**
- Current gap to 280s target: **~4s to ~14s**, depending on run
- Flaky retries: **0**
- Clean runs in a row: **5**

### Historical shard envelope

Across the repro runs, the shard finishes were consistently in this range:

| Shard size | Typical duration |
| --- | ---: |
| 90 tests | 3.8m–4.0m |
| 50 tests | 4.0m–4.1m |
| 62 tests | 4.5m–4.7m |
| 84 tests | 4.5m–4.6m |

Practical takeaway:
- The suite is no longer dominated by catastrophic stalls.
- The slowest wall-clock is now set mostly by the **62-test** and **84-test** shards.
- Additional gains should come from reducing the cost of a few hot user flows, not from weakening coverage.

## Current audit — 2026-08-02

- The latest canonical `just test-e2e` run passed all **350** tests with zero retries in approximately **6.6 minutes**.
- That is one valid measurement, not a replacement baseline.
- The May 2026 284–294 second figures are therefore historical only; the current suite needs five consecutive clean runs before a new target or regression claim is made.

## What got us back here

The runtime recovery came from removing real bottlenecks, not from relaxing tests.

### 1. Hidden setup pages stopped doing real editor work

Problem:
- hidden setup/import helpers could briefly mount `/analysis/{id}`
- that route eagerly prewarmed compute state
- transient helper pages consumed engines and compute budget before the real test page loaded

Fix:
- delay and cancel prewarm on transient mounts

Owner:
- `packages/frontend/src/routes/analysis/[id]/+page.svelte`

### 2. Compute-request concurrency became real instead of fake

Problem:
- blocking request handlers were running inside the asyncio event loop
- uploads, previews, and editor work could block each other even with nominal concurrency configured

Fix:
- move heavy request execution off-loop
- then cap the executor so compute requests do not starve build workers

Owner:
- `packages/worker/runtime/compute_request_runtime.py`

### 3. Interactive work no longer waits behind background ingest

Problem:
- FIFO request claiming let user-facing work sit behind background datasource activity

Fix:
- explicit priority tiers for:
  - interactive preview/editor/runtime work
  - user-triggered datasource creation
  - background ingest

Owner:
- `packages/backend/backend_core/compute_requests_service.py`

### 4. Same-datasource ingest stopped racing itself

Problem:
- true parallelism exposed concurrent Iceberg commits to the same datasource branch
- failures surfaced as `branch main has changed`

Fix:
- serialize same-datasource ingest writes with a process-local mutex

Owner:
- `packages/worker/runtime/compute_service.py`

### 5. Concurrent namespace bootstrap became idempotent

Problem:
- multiple workers creating the same Iceberg namespace could collide during bootstrap

Fix:
- treat concurrent namespace creation as harmless/idempotent

Owners:
- `packages/worker/runtime/compute_service.py`
- `packages/worker/runtime/compute_service.py`

### 6. Datasource creation stayed UI-first without adding helper drag

Problem:
- legacy helper behavior leaned on backend/network coupling
- moving to the real browser flow initially regressed runtime

Fix:
- use browser-visible redirect state (`/datasources?created_id=...`)
- reuse authenticated hidden browser contexts, but not a shared hidden page

Owners:
- `packages/frontend/tests/utils/user-flows.ts`
- `packages/frontend/tests/utils/api.ts`
- `packages/frontend/src/routes/datasources/new/+page.svelte`

## Hard performance rules

These are the current enforcement rules for this area.

### Product rules

- Interactive preview/editor/create flows should normally settle within the existing **5s** assertion budget.
- Small test-fixture builds should reach visible completion state without requiring longer waits.
- Hidden/helper pages must not leave behind long-lived editor or engine work.
- Background ingest must not outrank interactive UI work.
- Browser cache must not be relied on for namespace-scoped correctness.

### Test-policy rules

- No Playwright retries.
- No deleting meaningful coverage to make the suite pass.
- Use backend automation only where the UI does not expose a practical path.
- Prefer browser-visible ids and UI state over backend/network-coupled helper logic.

## How to re-measure

Use the normal command only:

```bash
just test-e2e
```

For a stability claim, require:
- `just verify` clean
- `just test` clean
- **5 consecutive clean `just test-e2e` runs**
- **0 retries**

Do not mix regular test time into the e2e wall-clock claim.
