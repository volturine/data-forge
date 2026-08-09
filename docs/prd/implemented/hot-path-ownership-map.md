# Hot-path ownership map

> **Status (audited 2026-08-02): Implemented — current product-path ownership documented.**
> **Portfolio:** [PRD index](../README.md)

_Last audited: 2026-08-02_

This record maps the user-facing flows that can dominate E2E runtime to their
current frontend, backend, and runtime owners. It is an ownership contract, not
a timing attribution. Direct profiling is published in the implemented
[Hot-Path Profiling Record](hot-path-request-map.md).

## Tier 1 product paths

| User flow | Frontend owner | Backend owner | Runtime / worker owner | Required behavior |
| --- | --- | --- | --- | --- |
| Datasource upload / create | `packages/frontend/src/routes/datasources/new/+page.svelte` | `packages/backend/modules/datasource/routes.py` and `commands.py` | `packages/worker/datasources/execution.py` | User-triggered creation must not wait behind background ingest. |
| Datasource preview load | `packages/frontend/src/routes/datasources/+page.svelte` | `packages/backend/modules/compute/routes.py` | `packages/worker/runtime/compute_service.py` | Preview cold start must preserve visible responsiveness. |
| Analysis editor open | `packages/frontend/src/routes/analysis/[id]/+page.svelte` | `packages/backend/modules/compute/routes.py` | `packages/worker/runtime/compute_service.py` | Transient setup pages must not consume editor prewarm capacity. |
| Inline preview | `packages/frontend/src/lib/components/pipeline/InlineDataTable.svelte` | `packages/backend/modules/compute/routes.py` | `packages/worker/runtime/compute_request_runtime.py` | Preview requests must remain bounded and lifecycle-fenced. |
| Output build / rebuild | `packages/frontend/src/lib/components/pipeline/OutputNode.svelte` | `packages/backend/modules/analysis/routes.py` | `packages/worker/runtime/compute_service.py` and `packages/worker/datasources/execution.py` | Visible builds must not be starved by preview or helper traffic. |
| Monitoring history / detail | `packages/frontend/src/routes/monitoring/+page.svelte` | `packages/backend/modules/engine_runs/routes.py` | `packages/backend/backend_core/engine_runs_service.py` | Preview and build semantics must remain distinct and current. |
| Namespace / profile remount | `packages/frontend/src/routes/profile/+page.svelte` and `SystemTab.svelte` | datasource and namespace routes | `packages/worker/datasources/datasource_loading.py` | Namespace-sensitive state must not leak or trade correctness for caching speed. |

## Scheduling ownership

| Concern | Owner | Implemented rule |
| --- | --- | --- |
| Compute request ordering | `packages/backend/backend_core/compute_requests_service.py` | Interactive work first, user datasource creation second, background ingest last. |
| Compute request execution | `packages/worker/runtime/compute_request_runtime.py` | Blocking work stays off-loop in a bounded executor. |
| Engine reuse | `packages/worker/runtime/compute_service.py` | Shared preview engines remain warm until cleanup; builds retain isolated identities. |
| Mutation safety | `packages/worker/datasources/execution.py` and backend publication commands | Conflicting mutations use durable fenced claims. |

## Current observed state

- Five consecutive `just test-e2e` runs passed 351 tests with zero retries.
- Command-level wall-clock was 411.98–460.99s with a 445.91s mean.
- The current mean is 54.0% slower than the historical 289.55s mean.
- One intentionally drained lost lease occurred per run without stale
  publication.
- Test populations identify breadth, not duration: editor 49, profile 44,
  datasources 36, monitoring 34, pipeline 28, and operations 28.

## Completion boundary

Ownership and required behavior are documented and therefore implemented. No
per-file timing, worker-utilization trace, or per-flow request count was captured
by this map. Those measurements are now complete in the implemented profiling
record.
