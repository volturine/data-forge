# Task: Fix rename pane blocking UI / edit pane visibility

## Goal
Prevent the Rename config UI from blocking other parts of the editor and ensure the edit pane always displays correctly.

## Scope
Frontend only.

## Affected files
- `frontend/src/lib/components/pipeline/operations/RenameConfig.svelte`
- `frontend/src/lib/components/pipeline/StepEditPane.svelte`

## Requirements
- Rename config should not overlay or block the main editor.
- Edit pane should remain visible and accessible at all times.
- Z-index and layout should follow global pane conventions.

## Acceptance criteria
- Rename pane does not block the UI.
- Edit pane appears reliably when a node is selected.

## Implementation outline
1. Inspect layout and container styles in StepEditPane.
2. Fix any absolute positioning or z-index issues in RenameConfig.
3. Align with common config pane styling.
