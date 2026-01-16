# Task: Full DAG execution + recompute downstream only

## Goal
Support full DAG execution (no merges) with topological ordering and cycle detection. Recompute only downstream nodes after changes instead of the entire pipeline.

## Scope
Frontend + Backend.

## Affected files
Frontend:
- `frontend/src/lib/utils/pipeline-calculator.ts`
- `frontend/src/lib/utils/pipeline-rules.ts`
- `frontend/src/lib/stores/pipeline.svelte.ts`

Backend:
- `backend/modules/compute/engine.py`
- `backend/modules/compute/service.py`
- `backend/modules/compute/step_converter.py`

## Requirements
- Enforce DAG (no merges), detect cycles, and provide clear errors.
- Compute order must be topological and dependency-aware.
- Frontend schema recomputation must only update downstream nodes.
- Backend execution must respect dependencies rather than list order.

## Acceptance criteria
- Cycle detection prevents invalid graphs.
- Editing a node recomputes only its downstream dependents.
- Results are consistent between frontend schema preview and backend compute.

## Implementation outline
1. Implement DAG validation and topological sort.
2. Update frontend pipeline calculator to use dependency graph.
3. Update backend engine to execute based on topo order.
4. Add tests for cycle detection and downstream-only recompute.
