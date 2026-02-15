# AGENTS.md

> **Mandatory for all AI assistants.** Read fully before any work in this repository.

**Stack:** SvelteKit 2 + Svelte 5 (runes) + TypeScript + TanStack Query | FastAPI + Python 3.13 + Polars + SQLAlchemy 2.0 (async) + SQLite + Pydantic V2

## Commands

```bash
just verify          # REQUIRED before declaring any task done (format + test + check)
just format          # ruff format + prettier
just test            # backend pytest
just check           # ruff + mypy + svelte-check + eslint
just dev             # start both servers
```

## Definition of Done

Nothing is complete until `just verify` passes with **zero errors and zero warnings**.

- Run `just verify` before declaring any task done
- Write backend Python tests for new/changed functionality
- Frontend API calls must match backend schema types exactly
- Keep `docs/taskfile.md` updated as work progresses
- Pre-existing warnings are tech debt — fix them, do not ignore them
- If a warning cannot be fixed (third-party stubs), suppress with an inline comment explaining why

## Workflow

1. **Explore** — Read relevant files, understand context
2. **Plan** — Use `/plan`. Update `docs/taskfile.md`
3. **Code** — Implement. Use parallel agents when possible
4. **Verify** — Run `just verify`. Fix everything. No exceptions
5. **Review** — Use Second Opinion agent before completing
6. **Commit** — Well-formed commit. Update `docs/taskfile.md`

**Do not ask for confirmation on implementation details.** Make decisions, implement, verify. Stop and ask only on genuine ambiguity about requirements or conflicts with these rules.

**Re-read `docs/bugs.md` before declaring any bug/task done** — the user may have updated it while you work.

**Propositions:** If you think of improvements while working, add them to `docs/propositions.md`. The user vets and promotes approved ones to `docs/bugs.md`.

## Non-Negotiables

- **No workarounds.** Fix root causes or stop and ask
- **No hidden compromises.** State conflicts and propose alternatives
- **No silent behavior changes.** All changes explicit and intentional
- **Redesign over hotfix.** If existing code is wrong, redesign properly
- **Fix warnings, not just errors.** Treat warnings as bugs
- **Autonomous completion.** Continue until every requirement in `docs/bugs.md` is implemented, tested, and verified

## Backend (Python / FastAPI)

- Async/await for all DB operations
- RORO pattern: Pydantic in, Pydantic out
- Type hints everywhere — no `Any`
- Pydantic V2 with `model_config = ConfigDict(from_attributes=True)`
- SQLAlchemy `Mapped` types for models
- Routes thin — logic in services
- File naming: `snake_case.py`
- Store naive UTC datetimes: `datetime.now(UTC).replace(tzinfo=None)`
- Handlers run in engine subprocesses — sync HTTP calls (e.g., `httpx`) are fine

## Frontend (Svelte 5 + TypeScript)

### Reactivity — Runes Only

```svelte
<script lang="ts">
  let count = $state(0);
  let doubled = $derived(count * 2);
  let { name }: Props = $props();
  let value = $bindable(0);
  $effect(() => { /* side effects only — comment why $derived won't work */ });
</script>
```

**Banned:** `let x = 0` (use `$state`), `$: x = ...`, `export let`, `onMount`

**$effect rules:** Allowed only for DOM access, event listeners, subscriptions, timers, network calls, localStorage. Forbidden for data init, validation, derived state, mapping, filtering, sorting. Always comment why `$derived` is insufficient.

### TanStack Query

```typescript
// Arrow function wrapper — access directly (NO $store syntax)
const query = createQuery(() => ({
  queryKey: ['items'],
  queryFn: fetchItems
}));
// query.data, query.isFetching (NOT $query.data)
```

### API Client

```typescript
// apiRequest<T>() returns ResultAsync<T, ApiError> from neverthrow
import { apiRequest } from '$lib/api/client';

async function fetchItems(): Promise<Item[]> {
  const result = await apiRequest<Item[]>('/items');
  return result.match(
    (data) => data,
    (error) => { throw error; }
  );
}
```

### Styling

- No inline styles (except dynamic positioning / drag previews)
- No CSS vars in markup — use `app.css`
- Prefer utility classes from `app.css`. Avoid `@apply` and `<style>` blocks
- Use `border-tertiary` for tables, `bg-accent-bg` / `text-accent-primary` / `border-info` for theme accents

### Transitions

**Never use `transition-all`.** Always use specific properties:
- `transition-colors` for hover effects
- `transition-opacity` for fades
- `transition-[color,background-color,border-color,opacity]` for combined
- Add `transform` to the list only when transform changes

### CSS Containment

- Embedded scrollable components must use `contain: content` on their wrapper
- Repeated list items in scroll containers: `content-visibility: auto` + `contain-intrinsic-size`

### File Naming

- Components: `PascalCase.svelte`
- Utilities: `kebab-case.ts`
- Stores: `*.svelte.ts`
- Imports: always use `$lib/` alias

### Patterns

- **Config defaults:** centralize in `step-config-defaults.ts`, not in components
- **Icons:** Lucide. Type as `typeof Filter`, render as `<Icon />`
- **Dynamic styles:** Svelte actions (`use:setWidth`), not inline styles
- **Modals:** `$bindable()` open prop, backdrop click, escape key, body scroll lock via `$effect`
- **Svelte autofixer:** run before writing any `.svelte` file

## Code Style

See [`STYLE_GUIDE.md`](STYLE_GUIDE.md) for full reference. Key rules:

- Prefer `const` over `let`. Avoid `else` — use early returns
- No `any` type. Avoid `try/catch` where possible
- No unnecessary destructuring. Keep functions unified unless composable

## Architecture

### Pipeline Execution

```
HTTP request → routes.py → service.py → engine subprocess (via queue)
→ engine.py::_build_pipeline() → step_converter.convert_config_to_params()
→ handler.__call__() → Params.model_validate(params)
```

### Data Model

- **Tabs** live inside `Analysis.pipeline_definition` as JSON — not a separate DB table
- **Datasources** are immutable after creation. Refresh re-extracts schema
- **DataTable** is a pure presentation component — receives `columns`, `data`, `columnTypes` already resolved
- **`datasource_id`** = tab input. **`output_datasource_id`** = tab export target (auto-created on save)

### Cross-Tab Dependencies

Changes to tab A's pipeline invalidate tab B's preview cache. `updateStepConfig` in the analysis store marks dependent tabs' view steps for re-run.

### Preview Caching

- Cache key: `analysisId:datasourceId:snapshotKey:rowLimit:stepId`
- Export config fields excluded from `datasourceKey` to prevent unnecessary refreshes
- Tab switches do NOT trigger preview refreshes

## Testing

- Write backend tests for every new feature and bug fix
- Create new analysis per test session
- Never ignore timeouts — investigate immediately

## Git

- NEVER push to remote unless explicitly asked
- Local commits only
- Create PRs for sharing changes

## Self-Evolving Rules

When you fix something you got wrong on first implementation, add the lesson to [`docs/key-learnings.md`](docs/key-learnings.md). The goal is to implement correctly from the start. **Read `docs/key-learnings.md` before working on unfamiliar areas.**

## Extended Documentation

Read these before working on related areas:

| Document | Purpose |
|----------|---------|
| [`docs/key-learnings.md`](docs/key-learnings.md) | Project-specific gotchas and lessons |
| [`docs/PRD.md`](docs/PRD.md) | Product requirements and data contracts |
| [`docs/ENV_VARIABLES.md`](docs/ENV_VARIABLES.md) | Environment variable reference |
| [`docs/bugs.md`](docs/bugs.md) | Current bugs and feature requests |
| [`docs/taskfile.md`](docs/taskfile.md) | Task tracking |
| [`STYLE_GUIDE.md`](STYLE_GUIDE.md) | Code style standards |

## Runed Utilities

```typescript
import { PersistedState, Debounced, FiniteStateMachine, onClickOutside } from "runed";
```

## Agents

| Agent | When to Use |
|-------|-------------|
| **Second Opinion** | Before completing ANY task |
| **E2E Testing** | Automated UI testing |
| **Docks** | Writing documentation |
| **Learn** | After sessions to record discoveries |

## MCP Servers

| Server | Purpose |
|--------|---------|
| **Svelte** | Documentation and autofixer |
| **Perplexity** | Research |
| **Playwright** | Browser automation |
| **Vibe Check** | Prevent tunnel vision |
| **Sequential Thinking** | Complex problem solving |

## Slash Commands

- `/plan` — Create implementation plan
- `/review` — Code review
- `/clarify` — Ask clarifying questions
- `/rmslop` — Clean up AI slop
