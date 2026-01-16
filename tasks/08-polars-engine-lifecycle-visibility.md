# Task: Per-analysis Polars engine lifecycle + visibility

## Goal
Spawn a dedicated Polars engine per analysis when opened; keep it alive with a 1-minute keepalive and terminate after 1 minute of inactivity or missed keepalive. Expose PID and status in the UI.

## Scope
Frontend + Backend.

## Affected files
Frontend:
- `frontend/src/lib/api/compute.ts`
- `frontend/src/lib/stores/compute.svelte.ts`
- `frontend/src/routes/analysis/[id]/+page.svelte`

Backend:
- `backend/modules/compute/manager.py`
- `backend/modules/compute/service.py`
- `backend/modules/compute/routes.py`
- `backend/modules/compute/schemas.py`

## Requirements
- Spawn engine on analysis open.
- Keepalive every 1 minute; idle timeout is also 1 minute.
- If keepalive stops, engine self-terminates.
- Support multiple concurrent analyses with distinct engines.
- UI shows PID and status (idle, running, error, terminated).

## Acceptance criteria
- Opening analysis creates engine and reports PID.
- Closing tab (no keepalive) stops engine within 1 minute.
- Multiple analyses can run in parallel with distinct engines.
- UI reflects status changes.

## Implementation outline
1. Add engine registry with last-seen timestamps per analysis.
2. Add keepalive endpoint and periodic cleanup.
3. Return status/PID to frontend and render in analysis UI.
4. Implement client keepalive loop tied to analysis page lifecycle.
