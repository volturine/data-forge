# Task: Fix config pane CSS issues (fill null, string transforms, sort, etc.)

## Goal
Normalize layout and styling across operation config panes and fix visible CSS regressions (e.g., wrong colors, poor contrast, inconsistent spacing).

## Scope
Frontend only.

## Affected files
- `frontend/src/lib/components/pipeline/operations/FillNullConfig.svelte`
- `frontend/src/lib/components/pipeline/operations/StringTransformConfig.svelte`
- `frontend/src/lib/components/pipeline/operations/SortConfig.svelte`
- `frontend/src/lib/components/pipeline/operations/RenameConfig.svelte`
- `frontend/src/lib/components/pipeline/operations/ExpressionConfig.svelte`
- `frontend/src/lib/components/pipeline/operations/PivotConfig.svelte`
- `frontend/src/lib/components/pipeline/operations/DeduplicateConfig.svelte`
- `frontend/src/lib/components/pipeline/operations/ExplodeConfig.svelte`
- `frontend/src/lib/components/pipeline/operations/TimeSeriesConfig.svelte`
- `frontend/src/lib/components/pipeline/StepEditPane.svelte`

## Requirements
- Use global CSS tokens from `app.css`.
- Improve spacing and alignment for labels, inputs, lists, and actions.
- Ensure config panes are scrollable without clipping.
- Keep styles consistent across operations.

## Acceptance criteria
- Each config pane has consistent typography, spacing, and input styling.
- Contrast issues are resolved in dark mode.
- No pane blocks the editor or renders outside boundaries.

## Implementation outline
1. Extract common pane styling tokens and apply.
2. Normalize input/list styling (checkboxes, selects, buttons).
3. Fix any overflow/scroll regions.
4. Validate with dark and light themes.
