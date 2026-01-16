# Task: Global CSS cleanup with theme tokens

## Goal
Create a consistent, token-based styling system that supports intuitive dark/light mode switching and is easy to maintain. Replace hard-coded colors across UI with semantic CSS variables.

## Scope
Frontend only.

## Affected files
- `frontend/src/app.css` (add/normalize CSS variables and component tokens)
- Operation config panes (replace hard-coded colors with tokens)
- Pipeline UI components (ensure tokens are used consistently)

## Requirements
- Centralize color, spacing, radius, shadow, and typography in CSS variables.
- Define component-level tokens for panels, forms, tables, and dialogs.
- Ensure dark/light modes switch cleanly using `data-theme`.
- Remove hard-coded hex colors from operation config panes.
- Preserve existing layout and spacing semantics where possible.

## Acceptance criteria
- All config panes and pipeline components use CSS variables for colors.
- Dark and light mode both readable and visually consistent.
- No regressions in layout; only styling changes.

## Implementation outline
1. Audit `app.css` tokens and add missing semantic variables (panel, input, table, dialog, badge).
2. Replace hard-coded colors in operation config panes with tokens.
3. Align pipeline UI components to tokens.
4. Verify dark/light theme legibility.
