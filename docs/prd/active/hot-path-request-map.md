# Hot-path request map

> **Status (audited 2026-08-02): Active — ownership mapped; direct request and timing profiles remain open.**
> **Portfolio:** [PRD index](../README.md)

_Last audited: 2026-08-02_

This map ties expensive user-facing flows to the files that own them. The
current five-run baseline establishes a stable 411.98–460.99s envelope, but
does not identify which flow caused the 54.0% increase over the historical
mean.

## Tier 1 hot paths

| User flow | Frontend owner | Backend owner | Runtime / worker owner | Why it matters |
| --- | --- | --- | --- | --- |
| Datasource upload / create | `packages/frontend/src/routes/datasources/new/+page.svelte` | `packages/backend/modules/datasource/routes.py` + `commands.py` | `packages/worker/datasources/execution.py` | User-triggered create is synchronous and must not wait behind background ingest. |
| Datasource preview load | `packages/frontend/src/routes/datasources/+page.svelte` | `packages/backend/modules/compute/routes.py` | `packages/worker/runtime/compute_service.py` | Preview cold start affects Datasources and Monitoring flows. |
| Analysis editor open | `packages/frontend/src/routes/analysis/[id]/+page.svelte` | `packages/backend/modules/compute/routes.py` | `packages/worker/runtime/compute_service.py` | Editor load is shared by many analysis tests. |
| Inline preview | `packages/frontend/src/lib/components/pipeline/InlineDataTable.svelte` | `packages/backend/modules/compute/routes.py` | `packages/worker/runtime/compute_request_runtime.py` | Pipeline and configuration flows repeatedly use this path. |
| Output build / rebuild | `packages/frontend/src/lib/components/pipeline/OutputNode.svelte` | `packages/backend/modules/analysis/routes.py` | `packages/worker/runtime/compute_service.py` + `packages/worker/datasources/execution.py` | Visible build completion is a critical user-facing wait. |
| Monitoring history / detail | `packages/frontend/src/routes/monitoring/+page.svelte` | `packages/backend/modules/engine_runs/routes.py` | `packages/backend/backend_core/engine_runs_service.py` | Monitoring must reflect preview and build semantics quickly and correctly. |
| Namespace / profile remount | `packages/frontend/src/routes/profile/+page.svelte`, `SystemTab.svelte` | datasource and namespace routes | `packages/worker/datasources/datasource_loading.py` | Namespace-sensitive state can introduce stale UI and cold-start costs. |

## Scheduling and prioritization

| Concern | Owner | Required rule |
| --- | --- | --- |
| Compute request ordering | `packages/backend/backend_core/compute_requests_service.py` | Interactive work first, user datasource creation second, background ingest last. |
| Compute request execution | `packages/worker/runtime/compute_request_runtime.py` | Blocking work stays off-loop and bounded. |
| Engine reuse | `packages/worker/runtime/compute_service.py` | Shared preview engines remain warm until cleanup; build triggers retain isolated identities. |
| Mutation safety | `packages/worker/datasources/execution.py` and backend publication commands | Conflicting mutations use durable fenced claims. |

## Current evidence

- Five consecutive `just test-e2e` runs passed 351 tests with zero retries.
- The command-level mean was 445.91s, versus 289.55s historically (+54.0%).
- Test counts identify broad workloads, not isolated duration: editor 49,
  profile 44, datasources 36, monitoring 34, pipeline 28, and operations 28.
- One intentionally drained lost lease occurred per run without stale publication.

No per-file timing, worker-utilization trace, or per-flow request count has yet
been captured. Those measurements remain required before assigning the
regression to a particular owner.

## Required profiling output

- [ ] Per-file timing or tracing for the long analysis and profile suites.
- [ ] Worker occupancy during full four-worker E2E load.
- [ ] Request counts for editor open, inline preview, output build, and rebuild.
- [ ] Request counts for namespace switches on Datasources, Monitoring, and Profile.
- [ ] A finding that attributes the regression to measured product paths.

## Guardrails

- Setup helpers must leave transient pages parked away from heavy routes.
- Namespace-sensitive API reads must not trade correctness for caching speed.
- Preview fanout must not starve visible builds.
- Lost leases must drain without publication.
- Coverage, visible assertions, and zero retries remain non-negotiable.
