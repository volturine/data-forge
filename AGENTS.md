# AGENTS.md

**MANDATORY READ FOR AI ASSISTANTS** — all assistants must follow this guidance in this repository.

This document defines strict, non-negotiable rules for assisting in this codebase.

**Stack (context):** SvelteKit 2 + FastAPI + SQLite

## Definition of Done

Nothing is complete until ALL of these pass with **zero errors AND zero warnings**:

```bash
just verify
```

This runs backend tests, ruff format, ruff check, mypy, svelte-check, prettier, eslint. **Pre-existing warnings are tech debt — fix them, do not ignore them.** If a warning cannot be fixed (e.g., third-party type stubs), suppress it with an inline comment explaining why.

- Always run `just verify` before declaring any task done
- Always keep `docs/taskfile.md` updated as work progresses
- Always write backend Python tests for new/changed functionality
- Frontend API calls must match backend schema types exactly

## Workflow

1. **Explore** → Read relevant files, understand context
2. **Plan** → Create plan with `/plan` prompt in subagent. Update `docs/taskfile.md`.
3. **Code** → Implement solution. Use parallel agents when possible.
4. **Verify** → Run `just verify`. Fix everything. No exceptions.
5. **Review** → Use Second Opinion agent before completing
6. **Commit** → Create well-formed commit. Update `docs/taskfile.md`.

Use `vibe_check` after planning. Use `vibe_learn` to record discoveries.

**Do not ask for confirmation on implementation details.** Make decisions, implement, verify. Stop and ask only when there is genuine ambiguity about requirements or when a change conflicts with these rules.

## Non-Negotiables (Strict Enforcement)

- **No workaround solutions.** Do not ship hacks, temporary fixes, or "good enough" patches. Fix root causes or stop and ask for direction.
- **No hidden compromises.** If a requested change conflicts with rules or quality, state it and propose an acceptable alternative.
- **No silent behavior changes.** All behavior changes must be explicit, intentional, and documented in the response.
- **Redesign over hotfix.** If the existing code is wrong, redesign it properly. Do not patch around broken architecture.
- **Fix warnings, not just errors.** Treat warnings as bugs. If you touch a file with pre-existing warnings, fix them.

## Backend (Python/FastAPI)

- Use async/await for all DB operations
- Follow RORO: Pydantic in, Pydantic out
- Type hints everywhere
- Pydantic V2 with `model_config = ConfigDict(from_attributes=True)`
- SQLAlchemy `Mapped` types for models
- Keep routes thin — logic in services
- File naming: `snake_case.py`
- **SQLite datetime handling:** Always store naive UTC. Use `datetime.now(UTC).replace(tzinfo=None)`. SQLite silently strips timezone info — comparing aware and naive datetimes causes `TypeError`.
- **Subprocess-safe patterns:** Handlers run in engine subprocesses. Sync HTTP calls (e.g., `httpx`) are fine — they don't block FastAPI's event loop.

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

### Svelte Autofixer

**Always run `svelte-autofixer` before writing any `.svelte` file.** It catches:
- Missing `{#each}` keys
- Using `Map` instead of `SvelteMap`
- Deprecated patterns

### TanStack Svelte Query (Strict Patterns)

```typescript
// Queries — arrow function wrapper, access directly (NO $store syntax)
const query = createQuery(() => ({
  queryKey: ['items'],
  queryFn: fetchItems
}));
// Access: query.data, query.isFetching, query.error (NOT $query.data)

// Mutations
const mutation = createMutation(() => ({
  mutationFn: (data: CreateItem) => createItem(data),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['items'] })
}));
```

### API Client

```typescript
// apiRequest<T>() returns ResultAsync<T, ApiError> from neverthrow
import { apiRequest } from '$lib/api/client';

// Usage in query functions:
async function fetchItems(): Promise<Item[]> {
  const result = await apiRequest<Item[]>('/items');
  return result.match(
    (data) => data,
    (error) => { throw error; }
  );
}
```

### Data Fetching

```typescript
import { createQuery } from "@tanstack/svelte-query";
const query = createQuery(() => ({ queryKey: ["items"], queryFn: fetchItems }));
```

### Styling

- No inline styles (except dynamic positioning)
- No CSS vars in markup — use `app.css`
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

**Icons:** Use Lucide. Store as component references, type as `typeof Filter` not `Component<IconProps>`. Render as `<Icon />`.

**Dynamic Styles:** Use Svelte actions (e.g., `use:setWidth`) not inline styles.

**Modal Pattern:**
- `$bindable()` open prop
- Backdrop click handler
- Escape key listener
- Body scroll lock via `$effect` (DOM mutation — `$derived` insufficient)

**$effect Rules (Strict):**

- **Allowed only for side effects** that cannot be expressed via `$derived` or pure functions.
- **Allowed examples:** DOM access, event listeners, subscriptions, timers, network calls, localStorage/sessionStorage.
- **Explicitly forbidden:** data initialization, validation, derived state, mapping, filtering, sorting, or transforming props/state.
- **Requirement:** if `$effect` is used, include a one-line comment explaining why `$derived` is not sufficient.

## Code Style

From `STYLE_GUIDE.md`:

- **No temporary workarounds. Ever.** If a real fix is not possible, stop and request guidance.
- Prefer `const` over `let`
- Avoid `else` — use early returns
- Single word names where possible
- Keep functions unified unless composable
- Avoid unnecessary destructuring
- Avoid `try/catch` where possible
- No `any` type

## Testing

- Write backend tests for every new feature and bug fix
- Create new analysis per test session
- Report results in table format
- Never ignore timeouts — investigate immediately
- Check DevTools + `npm run check` if UI unresponsive

## Git

- NEVER push to remote
- Local commits only
- Create PRs for sharing changes

## Architecture

### Pipeline Execution Flow

```
HTTP request → routes.py → service.py → engine subprocess (via queue)
→ engine.py::_build_pipeline() → step_converter.convert_config_to_params()
→ handler.__call__() → Params.model_validate(params)
```

### Data Model

- **Tabs** live inside `Analysis.pipeline_definition` as a JSON array — NOT a separate DB table
- **Datasources** are immutable. Schema and location cannot change after creation. Refresh re-extracts schema.
- **Settings** (SMTP/Telegram/AI) are env-var-based via pydantic-settings, not runtime-editable
- **DataTable** is a pure presentation component — no `datasource_id` prop. Receives `columns`, `data`, `columnTypes` already resolved.
- **Analysis-source tabs** defer datasource creation to save. Backend `update_analysis` auto-creates analysis datasources when `datasource_id` is null.

### Cross-Tab Dependencies

When tab A is used as input for tab B (same analysis), changes to tab A's pipeline must invalidate tab B's preview cache. The `updateStepConfig` method in the analysis store handles this by marking dependent tabs' view steps for re-run.

### Preview Caching

- Preview cache key: `analysisId:datasourceId:snapshotKey:rowLimit:stepId`
- `buildAnalysisPipelinePayload` includes ALL tabs with their steps — changes to any tab's steps change the payload hash
- Export config fields (like `output`) are excluded from `datasourceKey` to prevent unnecessary preview refreshes
- Tab switches do NOT trigger preview refreshes

## Runed Utilities

```typescript
import {
  PersistedState,
  Debounced,
  FiniteStateMachine,
  onClickOutside,
} from "runed";
```

## Key Learnings

- **Border consistency:** Use `border-tertiary` everywhere in tables
- **Nested buttons:** Replace tab containers with `<div>` + separate buttons
- **Width attributes:** Use Svelte actions, not attributes (causes check errors)
- **Config defaults:** Centralize defaults at creation, not in components
- **Column Dropdown Width:** Set `.column-menu` to `min-width: 100%; width: 100%; max-width: 100%;` to match trigger field width
- **Number Input Cursor:** Use `oninput` without immediate coercion, coerce to number on `onblur` to prevent cursor jumping
- **Iceberg Export:** Use `table.overwrite(df)` for existing tables to replace data in a single snapshot
- **Svelte Action-Based Positioning:** Use Svelte actions to set CSS variables on portal elements for dynamic positioning
- **Inline Style Exception:** Keep inline `style=` for drag previews that require runtime mouse-following
- **CSS Paint Isolation:** `contain: content` on embedded scroll containers + `content-visibility: auto` on repeated items
- **transition-all Bloat:** Narrow to specific properties — `transition-all` forces tracking every CSS property across 1000+ elements
- **SQLite Naive Datetimes:** Always normalize to naive UTC before comparison. `datetime.now(UTC).replace(tzinfo=None)` for storage.
- **Pydantic Field Validators:** Use `field_validator` for type coercion (e.g., JSON string → dict) instead of fixing every caller
- **Cross-Tab Invalidation:** When modifying steps in tab A, also mark view steps in dependent tabs for re-run

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

- `/plan` — Create implementation plan
- `/review` — Code review
- `/clarify` — Ask clarifying questions
- `/rmslop` — Clean up AI slop
