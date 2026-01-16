# Task: Improve table node visualization and width

## Goal
Make the table node look better and use ~75% of the available width for clearer data previews.

## Scope
Frontend only.

## Affected files
- `frontend/src/lib/components/pipeline/TableNode.svelte`
- `frontend/src/lib/components/pipeline/InlineDataTable.svelte`

## Requirements
- Table node should occupy ~3/4 of available width responsively.
- Better visual styling for table header, row stripes, and borders.
- Ensure readability in dark and light themes.

## Acceptance criteria
- Table node displays wider and cleaner.
- Visual hierarchy and spacing are improved.
- No overflow or clipping.

## Implementation outline
1. Update container width rules and responsive behavior.
2. Improve table styling with tokens (header, rows, hover states).
3. Validate with dark/light themes.
