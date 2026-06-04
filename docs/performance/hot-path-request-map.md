# Hot-path request map

_Last updated: 2026-05-21_

This map ties the expensive user-facing flows to the files that own them.
The goal is to keep optimization work attached to the real product path, not to test-only workarounds.

## Tier 1 hot paths

These flows most directly affect e2e wall-clock and stability.

| User flow | Frontend owner | Backend owner | Runtime / worker owner | Why it matters |
| --- | --- | --- | --- | --- |
| Datasource upload / create | `packages/frontend/src/routes/datasources/new/+page.svelte` | `packages/backend/modules/datasource/routes.py` | `packages/worker/datasources/datasource_service.py` | User-triggered create is synchronous and must not wait behind background ingest. |
| Datasource preview load | `packages/frontend/src/routes/datasources/+page.svelte` | `packages/backend/modules/compute/routes.py` | `packages/worker/runtime/compute_service.py` | Preview cold start shows up immediately in Datasources and Monitoring tests. |
| Analysis editor open | `packages/frontend/src/routes/analysis/[id]/+page.svelte` | `packages/backend/modules/compute/routes.py` | `packages/worker/runtime/compute_service.py` | Editor load is a common dependency for many analysis tests. |
| Inline preview on analysis nodes | `packages/frontend/src/lib/components/pipeline/InlineDataTable.svelte` | `packages/backend/modules/compute/routes.py` | `packages/worker/runtime/compute_request_runtime.py` | Pipeline/config tests repeatedly hit this path. |
| Output build / rebuild | `packages/frontend/src/lib/components/pipeline/OutputNode.svelte` | `packages/backend/modules/analysis/routes.py` | `packages/worker/runtime/compute_service.py` + `packages/worker/datasources/datasource_service.py` | Output build completion latency was a major source of failures. |
| Monitoring build history / preview rows | `packages/frontend/src/routes/monitoring/+page.svelte` | `packages/backend/modules/engine_runs/routes.py` | `packages/shared/core/engine_runs_service.py` | Monitoring must reflect preview vs build semantics correctly and quickly. |
| Namespace switch / profile system state | `packages/frontend/src/routes/profile/+page.svelte`, `packages/frontend/src/routes/profile/SystemTab.svelte` | `packages/backend/modules/datasource/routes.py`, `packages/backend/modules/namespaces/routes.py` | `packages/worker/datasources/datasource_service.py` | Namespace-sensitive state used to leak stale UI and cold-start costs. |

## Scheduling and prioritization map

These owners control who gets CPU time first.

| Concern | Owner | Current rule |
| --- | --- | --- |
| Compute request ordering | `packages/shared/core/compute_requests_service.py` | interactive preview/editor/runtime work first, user-triggered datasource creation second, background ingest last |
| Compute request execution model | `packages/worker/runtime/compute_request_runtime.py` | blocking work runs off the event loop in a bounded executor |
| Engine warmup / build reuse | `packages/worker/runtime/compute_service.py` | shared datasource/analysis engines stay warm until idle cleanup; each build trigger gets its own build engine key |
| Same-datasource write safety | `packages/worker/datasources/datasource_service.py` | same datasource ingests are serialized |

## Known cross-cutting latency amplifiers

### Hidden setup pages

Files:
- `packages/frontend/tests/utils/api.ts`
- `packages/frontend/tests/utils/user-flows.ts`
- `packages/frontend/src/routes/analysis/[id]/+page.svelte`

Risk:
- setup helpers briefly touching heavy routes can consume real compute budget before the visible test page arrives.

Guardrail:
- helper pages must not leave active editor/engine work behind.

### Namespace-sensitive cache correctness

Files:
- `packages/frontend/src/lib/api/client.ts`
- `packages/frontend/src/lib/stores/namespace.svelte.ts`

Risk:
- cached GETs can make the app look fast while returning stale namespace-scoped state.

Guardrail:
- namespace-sensitive API requests default to `cache: 'no-store'` unless an explicit override is intentional.

### Build worker starvation

Files:
- `packages/worker/runtime/compute_request_runtime.py`
- `packages/worker/runtime/compute_service.py`
- `config/env/e2e.env`

Risk:
- unbounded helper or preview fanout can steal capacity from the workers that actually need to complete visible builds.

Guardrail:
- off-loop execution stays bounded; interactive latency wins are not allowed to turn into build starvation.

## Current hottest suites by observed wall-clock pressure

Based on recent clean repro runs and earlier profiling, the main runtime pressure is concentrated in these areas:

- `packages/frontend/tests/analysis-editor.test.ts`
- `packages/frontend/tests/analysis-pipeline.test.ts`
- `packages/frontend/tests/analysis-output.test.ts`
- `packages/frontend/tests/analysis-operations.test.ts`
- `packages/frontend/tests/namespace-isolation.test.ts`
- `packages/frontend/tests/profile.test.ts`

Interpretation:
- the biggest remaining costs are **editor startup**, **preview/build completion**, **namespace-sensitive remount/state refresh**, and **repeated interactive step configuration flows**.
- that is a product/runtime signal, not a reason to weaken the tests.
