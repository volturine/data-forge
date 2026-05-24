# Engine Lifecycle Alignment

Status: complete except Docker-native engine swap
Owner: AI implementation pass on 2026-05-23
Scope: align engine lifecycle semantics for datasource preview, analysis interaction, and builds before the later Docker-native engine swap.

## Goal

Make the runtime follow one clear lifecycle contract:

1. **Datasource preview** uses one shared engine per datasource.
2. **Analysis interaction** uses one shared engine per analysis.
3. **Builds** use one fresh engine per build trigger.
4. **Client navigation** is not allowed to tear down shared analysis engines.
5. **Server-side lifecycle** owns idle cleanup.
6. **Engine identity** is explicit enough to survive the later move from local subprocesses to Docker containers.

## Out of Scope

- Docker/container orchestration itself
- Container resource scheduling
- Container lease/placement logic
- Cross-host engine orchestration

Those belong to the later Docker-native runtime swap.

## Lifecycle Contract

### Datasource preview

- Engine key: `__preview__{datasource_id}`
- Reuse policy: `shared`
- Maximum live preview engines: one per datasource key per namespace
- Time travel, branch changes, and preview revisits reuse the same engine key
- Engine stops on datasource delete or server-side idle cleanup

### Analysis interaction

- Engine key: `{analysis_id}`
- Reuse policy: `shared`
- Shared by analysis preview, schema, row-count, and download flows
- Shared across simultaneous viewers of the same analysis
- Client route teardown must not shut it down
- Engine stops on analysis delete or server-side idle cleanup

### Build execution

- Engine key: `build:{build_id}`
- Reuse policy: `exclusive`
- One engine per build trigger
- Reused within a single build across that build's tabs/steps only
- Must be shut down when the build reaches a terminal state

## Implementation Checklist

### Phase 1 — freeze the contract in docs and helpers

- [x] Add a dedicated lifecycle tracking doc
- [x] Add central engine identity helpers for preview / analysis / build keys
- [x] Parse engine scope and reuse policy from engine keys

### Phase 2 — align runtime lifecycle behavior

- [x] Route interactive compute operations through one shared engine acquisition path
- [x] Remove the temporary export-engine fallback path
- [x] Change build engines from per-analysis reuse to per-build exclusivity
- [x] Shut down build engines after completed builds
- [x] Add server-side idle cleanup for shared engines
- [x] Preserve engine metadata needed for the later Docker swap (`scope`, `reuse_policy`, `datasource_id`, `build_id`, `current_build_id`, `current_engine_run_id`)

### Phase 3 — align frontend behavior

- [x] Stop shutting down shared analysis engines on route unmount
- [x] Keep datasource preview warmup on the datasource page
- [x] Keep existing engine monitoring compatible with the richer engine status payload

### Phase 4 — verification

- [x] Add engine identity tests
- [x] Add runtime tests for build engine uniqueness / shutdown
- [x] Add runtime tests for idle shared-engine cleanup
- [x] Add runtime overview coverage for explicit engine scope metadata
- [x] Run `just verify`
- [x] Run `just test`
- [x] Run `just test-e2e`

## Code Map

Primary implementation files:

- `packages/shared/core/engine_identity.py`
- `packages/worker-manager/runtime/compute_manager.py`
- `packages/worker-manager/runtime/compute_service.py`
- `packages/frontend/src/routes/analysis/[id]/+page.svelte`
- `packages/shared/core/engine_instances_service.py`

Primary verification files:

- `packages/shared/tests/test_engine_identity.py`
- `packages/worker-manager/tests/test_engine_lifecycle.py`
- `packages/worker-manager/tests/test_fixes.py`
- `packages/backend/tests/test_runtime_overview.py`
- `packages/backend/tests/test_compute_routes.py`

## Progress Notes

### 2026-05-23

Implemented in this pass:

- repository verification passed: `just verify`, `just test`, `just test-e2e`


- central engine identity helper module
- shared/exclusive lifecycle metadata on engine status payloads
- shared interactive engine retention after leaving analysis pages
- unique build-engine keys per build trigger
- build engine shutdown after normal build completion path
- idle shared-engine reaper in `ProcessManager`
- removal of temporary export-engine fallback
- updated tests for the new lifecycle contract

Remaining in this pass:

- later Docker-native engine execution swap only

## Follow-up: Docker-native engine swap

This document intentionally stops before container orchestration. The later Docker-native pass should reuse the lifecycle contract above and replace only the engine execution backend:

- subprocess engine -> container engine
- in-memory spawn/shutdown -> container create/stop
- process resource config -> container resource config
- process lifecycle -> container lifecycle

The identity and reuse semantics implemented here are the compatibility layer for that swap.
