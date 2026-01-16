# Task: DAG UX with drop targets + drag-and-drop

## Goal
Enable flexible insertion and linking of transformation nodes anywhere in the DAG using drag-and-drop with visible drop targets.

## Scope
Frontend only.

## Affected files
- `frontend/src/lib/components/pipeline/PipelineEditor.svelte`
- `frontend/src/lib/components/pipeline/PipelineCanvas.svelte`
- `frontend/src/lib/components/pipeline/StepLibrary.svelte`
- `frontend/src/lib/components/pipeline/StepNode.svelte`

## Requirements
- Drag nodes from library into any position in the DAG.
- Drop targets should show valid insertion points.
- Enforce no-merge rule while allowing branching.
- Keyboard / click fallback for non-DnD insertion.

## Acceptance criteria
- Users can insert nodes at any location with drop targets.
- DnD works reliably and updates DAG correctly.
- UI indicates invalid drop targets.

## Implementation outline
1. Add DnD handlers and drag metadata in StepLibrary.
2. Render drop targets in PipelineCanvas / StepNode.
3. Update pipeline store to insert nodes with dependencies.
4. Validate and prevent invalid merges.
