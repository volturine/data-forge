# AGENTS.md

**MANDATORY READ FOR AI ASSISTANTS** — all assistants must follow this guidance in this repository.

This document defines strict, non-negotiable rules for assisting in this codebase.

**Stack (context):** SvelteKit 2 + FastAPI + SQLite

## Workflow

1. **Explore** → Read relevant files, understand context
2. **Plan** → Create plan with `/plan`, get approval before coding
3. **Code** → Implement solution
4. **Review** → Use Second Opinion agent before completing
5. **Commit** → Create well-formed commit

Use `vibe_check` after planning. Use `vibe_learn` to record discoveries.

## Non-Negotiables (Strict Enforcement)

- **No workaround solutions.** Do not ship hacks, temporary fixes, or “good enough” patches. Fix root causes or stop and ask for direction.
- **No hidden compromises.** If a requested change conflicts with rules or quality, state it and propose an acceptable alternative.
- **No silent behavior changes.** All behavior changes must be explicit, intentional, and documented in the response.

## Backend (Python/FastAPI)

- Use async/await for all DB operations
- Follow RORO: Pydantic in, Pydantic out
- Type hints everywhere
- Pydantic V2 with `model_config = ConfigDict(from_attributes=True)`
- SQLAlchemy `Mapped` types for models
- Keep routes thin - logic in services
- File naming: `snake_case.py`

## Frontend (Svelte 5 + TypeScript)

### Runes Only

```svelte
<script lang="ts">
  let count = $state(0);
  let doubled = $derived(count * 2);
  let { name }: Props = $props();
  let value = $bindable(0);

  $effect(() => { /* side effects only */ });
</script>
```

**Never use:** `let x = 0` (use `$state`), `$: x = ...`, `export let`, `onMount`

### Data Fetching

```typescript
import { createQuery } from "@tanstack/svelte-query";
const query = createQuery({ queryKey: ["items"], queryFn: fetchItems });
```

### Styling

- No inline styles (except dynamic positioning)
- No CSS vars in markup - use `app.css`
- Prefer utility classes from `app.css`
- Avoid `@apply` in CSS
- Avoid component `<style>` blocks
- Use `border-tertiary` for table/view borders (matches header)
- Use theme accents: `bg-accent-bg`, `text-accent-primary`, `border-info`

### Transitions (Strict)

- **Never use `transition-all`** — it forces the browser to track every CSS property during style recalc. With hundreds of elements this causes scroll jank and paint storms.
- **Always use specific transition properties:**
  - `transition-colors` for hover effects that change color/background/border
  - `transition-opacity` for fade effects
  - `transition-[color,background-color,border-color,opacity]` when both color and opacity change
  - `transition-[color,background-color,border-color,opacity,transform]` when transform also changes (e.g., drag targets)
- The global `button` base style in `app.css` uses specific properties — do not revert to `transition: all`.

### CSS Containment (Strict)

- **Embedded scrollable components** (e.g., DataTable inside StepNode inside PipelineCanvas) must use `contain: content` on their wrapper to isolate paint/layout from parent compositing layers. Without this, scrolling triggers repaints across the entire parent tree.
- **Repeated list items** inside scroll containers (e.g., `.step-node` inside PipelineCanvas) should use `content-visibility: auto` with `contain-intrinsic-size` to skip rendering off-screen items.
- When adding a new scrollable component embedded inside a complex DOM tree, always check if it needs paint isolation.

### File Naming

- Components: `PascalCase.svelte`
- Utilities: `kebab-case.ts`
- Stores: `*.svelte.ts`

### Imports

```typescript
// Use $lib alias
import { apiRequest } from "$lib/api/client";
import { authStore } from "$lib/stores/auth.svelte";
```

### Patterns

**Config Defaults:** Centralize in `step-config-defaults.ts`

```typescript
export function getDefaultConfig(stepType: string) {
  const defaults = { select: { columns: [] }, filter: { conditions: [] } };
  return JSON.parse(JSON.stringify(defaults[stepType] ?? {}));
}
```

**Icons:** Use Lucide. Store as component references, render as `<Icon />`.

**Dynamic Styles:** Use Svelte actions (e.g., `use:setWidth`) not inline styles.

**$effect Rules (Strict):**

- **Allowed only for side effects** that cannot be expressed via `$derived` or pure functions.
- **Allowed examples:** DOM access, event listeners, subscriptions, timers, network calls, localStorage/sessionStorage.
- **Explicitly forbidden:** data initialization, validation, derived state, mapping, filtering, sorting, or transforming props/state.
- **Requirement:** if `$effect` is used, include a one-line comment explaining why `$derived` is not sufficient.

## Code Style

From `STYLE_GUIDE.md`:

- **No temporary workarounds. Ever.** If a real fix is not possible, stop and request guidance.
- Prefer `const` over `let`
- Avoid `else` - use early returns
- Single word names where possible
- Keep functions unified unless composable
- Avoid unnecessary destructuring
- Avoid `try/catch` where possible
- No `any` type

## Commands

```bash
# Backend
cd backend && uv sync --extra dev && uv run main.py
uv run pytest && uv run ruff format . && uv run ruff check --fix . && uv run mypy .

# Frontend
cd frontend && npm install && npm run dev
npm run check && npm run lint && npm run format
```

## Testing

- Create new analysis per test session
- Report results in table format
- Never ignore timeouts - investigate immediately
- Check DevTools + `npm run check` if UI unresponsive

## Git

- NEVER push to remote
- Local commits only
- Create PRs for sharing changes

## Key Learnings

- **Border consistency:** Use `border-tertiary` everywhere in tables
- **Nested buttons:** Replace tab containers with `<div>` + separate buttons
- **Width attributes:** Use Svelte actions, not attributes (causes check errors)
- **Step icons:** Store Lucide components, render as `<stepType.icon />`
- **Config defaults:** Centralize defaults at creation, not in components
- **Border Color Consistency:** Use `border-tertiary` (same color as `--bg-tertiary`) for all borders in data tables and views to create a cleaner, more cohesive appearance that matches the table header background.
- **Svelte Component Typing:** When using dynamic Lucide icons in Svelte components, type as `typeof Filter` instead of `Component<IconProps>` to avoid TypeScript narrowing issues. Use helper functions if needed to maintain type safety when accessing from `Record<string, T>`.
- **Column Dropdown Width Matching:** When implementing column dropdown menus, set `.column-menu` to `min-width: 100%; width: 100%; max-width: 100%;` to ensure the popup width exactly matches the trigger field, preventing awkward width mismatches in filter UIs.
- **Number Input Cursor Stability:** For numeric inputs in filter configurations, use `oninput` without immediate coercion and only coerce to number on `onblur` to prevent cursor jumping during typing. This allows smooth editing while maintaining data integrity.
- **Iceberg Table Export Snapshots:** When exporting data to Iceberg tables, use `table.overwrite(df)` for existing tables to replace data in a single snapshot, avoiding the empty intermediate snapshots that occur with append operations or manual file management.
- **Preview Trigger Exclusion:** To prevent unnecessary preview refreshes, exclude export configuration fields (like `output`) from the `datasourceKey` derivation in data table components, ensuring edits to export settings don't trigger preview runs.
- **Filter Layout Responsiveness:** In complex filter UIs, use `min-w-55` and `min-w-37.5` custom utilities with flexible layouts to accommodate varying column name lengths without cramping the interface.
- **Svelte Action-Based Positioning for Popovers:** Use Svelte actions to set CSS variables on portal elements for dynamic positioning, then consume them in dedicated CSS classes instead of inline `style=`.
- **Inline Style Exceptions in Svelte:** Keep inline `style=` for drag previews that require runtime mouse-following, as CSS-only positioning doesn't suffice for dynamic pointer tracking.
- **Analysis-Wide Save Status:** Save status is tracked at the analysis level instead of per-tab, ensuring consistent feedback across all tabs and requiring centralized state management in stores.
- **Preview Caching Key:** Preview caching uses a composite key of datasource + snapshot + pipeline to avoid redundant API calls, improving performance when switching between similar configurations.
- **Preview Persistence Across Navigation:** Previews persist across route changes by storing the preview state in a reactive store that survives navigation, maintaining user context.
- **Tab Change Preview Exclusion:** Tab changes no longer trigger preview refreshes, preventing unnecessary API calls and improving UI responsiveness during navigation.
- **Auto-Refresh Previews on Apply Changes:** Previews automatically refresh when "Apply Changes" is triggered, ensuring the data view stays synchronized with configuration updates.
- **Lucide Icon Consistency:** Use Lucide icons throughout the frontend for UI elements to maintain visual consistency and leverage their component-based rendering.
- **Svelte A11y Compliance:** Remove inline styles and use semantic roles (e.g., role="button") to fix accessibility warnings in Svelte components.
- **CSS Paint Isolation for Embedded Scroll:** InlineDataTable scroll was janky because its DataTable scroll container had no paint isolation from PipelineCanvas. Fix: `contain: content` on `.inline-preview-table` + `content-visibility: auto` on `.step-node`. The root cause was NOT reactive re-renders — no `$state`/`$derived` changes during scroll. It was pure CSS compositing: the browser repainted the entire PipelineCanvas layer on every scroll frame.
- **transition-all Causes Style Recalc Bloat:** The global `button { transition: all }` base style combined with `transition-all` on pipeline elements forced the browser to check every CSS property for transitions during style recalc — across 1000+ buttons in DataTable cells. Fix: narrow to specific properties (`color`, `background-color`, `border-color`, `opacity`, `transform` only where needed).

## Datasource Architecture

Datasources are immutable. Schema and location cannot change after creation. Refresh button re-extracts schema from source. Frontend shows read-only schema inputs.

## Runed Utilities

```typescript
import {
  PersistedState,
  Debounced,
  FiniteStateMachine,
  onClickOutside,
} from "runed";
```

## Agents

| Agent              | When to Use                          |
| ------------------ | ------------------------------------ |
| **Second Opinion** | Before completing ANY task           |
| **E2E Testing**    | Automated UI testing                 |
| **Docks**          | Writing documentation                |
| **Learn**          | After sessions to record discoveries |

## MCP Servers

| Server                  | Purpose                     |
| ----------------------- | --------------------------- |
| **Svelte**              | Documentation and autofixer |
| **Perplexity**          | Research                    |
| **Playwright**          | Browser automation          |
| **Vibe Check**          | Prevent tunnel vision       |
| **Sequential Thinking** | Complex problem solving     |

## Slash Commands

- `/plan` - Create implementation plan
- `/review` - Code review
- `/clarify` - Ask clarifying questions
- `/rmslop` - Clean up AI slop
