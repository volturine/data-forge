# E2E runtime baseline

> **Status (audited 2026-08-02): Implemented — current five-run baseline published.**
> **Portfolio:** [PRD index](../README.md)

_Last audited: 2026-08-02_

This document records the current five-run e2e baseline and retains the historical May measurement for comparison.
It is intentionally strict:

- `packages/frontend/playwright.config.ts` uses **`retries: 0`**
- assertions remain **UI-visible and user-like**
- engine shutdown uses the real UI
- datasource creation uses the real UI
- stability claims require repeated clean `just test-e2e` runs

Related documents:
- [Hot-path request map](../active/hot-path-request-map.md)
- [Performance violation checklist](../active/performance-violation-checklist.md)

## Current baseline — 2026-08-02

Five consecutive clean `just test-e2e` runs on a worktree based on commit
`053c8f945c7876b520500e9aa9b8e6395896f862`, including the documentation and
analysis-creation changes recorded by this PRD batch. The base commit is
recorded for provenance; it is not presented as the final artifact commit.

| Run | Playwright result | Total command wall-clock |
| --- | ---: | ---: |
| 1 | 351 passed in 6.3m | 411.98s |
| 2 | 351 passed in 7.0m | 452.59s |
| 3 | 351 passed in 7.2m | 460.99s |
| 4 | 351 passed in 7.0m | 450.03s |
| 5 | 351 passed in 7.0m | 453.94s |

### Current summary

- Mean: **445.91s**
- Median: **452.59s**
- Best: **411.98s**
- Worst: **460.99s**
- Range: **49.01s**
- Tests per run: **351**
- Retries: **0**
- Consecutive clean runs: **5**
- Compared with the May mean of 289.55s: **+156.36s / +54.0%**

The command-level measurement includes protocol generation, service and
infrastructure startup, browser execution, and cleanup. The Playwright-only
reported envelope was 6.3–7.2 minutes.

### Measurement environment

- Apple M4, 10 logical CPUs, 24 GiB RAM
- macOS/Darwin arm64 25.5.0
- Docker 29.5.2
- Bun 1.3.11
- uv 0.10.4
- Python runtime under the canonical harness: 3.14.2
- Playwright: 4 workers, `fullyParallel: false`, `retries: 0`

### Current interpretation

The suite is stable but materially slower than the historical baseline. The
largest test-file populations remain `analysis-editor` (49), `profile` (44),
`datasources` (36), `monitoring` (34), `analysis-pipeline` (28), and
`analysis-operations` (28). Those flows remain the first profiling targets;
this baseline does not convert their test counts into per-file timing claims.

Each run emitted one drained compute-request lease warning during intentional
route/namespace lifecycle churn. No publication occurred after the lost lease,
all visible behavior passed, and no build starvation or retry was observed.

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

## Superseded single-run audit — 2026-08-02

An earlier single 350-test pass motivated the five-run measurement above. It is
retained only as audit context and is superseded by the current baseline.

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
