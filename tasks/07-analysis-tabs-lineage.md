# Task: Per-analysis tabs with lineage

## Goal
Add multi-tab support to each analysis, where tabs can be sourced from datasources or derived from any tab within the same analysis. Show inline lineage using tab names with arrows.

## Scope
Frontend + Backend.

## Affected files
Frontend:
- `frontend/src/routes/analysis/[id]/+page.svelte`
- `frontend/src/lib/api/analysis.ts`
- `frontend/src/lib/stores/analysis.svelte.ts` (or new tab store)

Backend:
- `backend/modules/analysis/routes.py`
- `backend/modules/analysis/service.py`
- `backend/modules/analysis/schemas.py`
- `backend/modules/analysis/models.py`

## Requirements
- Each analysis must have at least one datasource tab.
- Derived tabs can be created from any tab within the same analysis.
- Editing any upstream tab should update derived tabs.
- Inline lineage in tab headers, e.g., `Source → Derived` (using tab names).

## Acceptance criteria
- Tabs persist for an analysis and load on page open.
- Derived tabs reflect updates from their source tab.
- Inline lineage appears in tab headers.

## Implementation outline
1. Define tab model (id, name, type, parent_id, datasource_id).
2. Add API endpoints to create/update/delete tabs.
3. Add UI for tab list, creation, and selection.
4. Wire lineage display and recompute on upstream changes.
