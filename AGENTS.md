# AGENTS.md

**MANDATORY READ FOR AI ASSISTANTS** - OpenCode, Copilot, Claude Code must follow this guidance when working on this repository.

Guidance for AI coding assistants working on this repository.

**Stack:** SvelteKit 2 + FastAPI + SQLite

## Workflow

1. **Explore** → Read relevant files, understand context
2. **Plan** → Create plan with `/plan`, get approval before coding
3. **Code** → Implement solution
4. **Review** → Use Second Opinion agent before completing
5. **Commit** → Create well-formed commit

Use `vibe_check` after planning. Use `vibe_learn` to record discoveries.

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

**Never use:** `let x = 0`, `$: x = ...`, `export let`, `onMount`

### Data Fetching

```typescript
import { createQuery } from '@tanstack/svelte-query';
const query = createQuery({ queryKey: ['items'], queryFn: fetchItems });
```

### Styling

- No inline styles (except dynamic positioning)
- No CSS vars in markup - use `app.css`
- Prefer utility classes from `app.css`
- Avoid `@apply` in CSS
- Avoid component `<style>` blocks
- Use `border-tertiary` for table/view borders (matches header)
- Use theme accents: `bg-accent-bg`, `text-accent-primary`, `border-info`

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

**$effect Rules:**
- ✗ Never for data validation/initialization
- ✓ DOM manipulation, API calls, localStorage, event listeners
- Prefer `$derived` for computed values

## Code Style

From `STYLE_GUIDE.md`:

- No temporary workarounds allowed
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

## Datasource Architecture

Datasources are immutable. Schema and location cannot change after creation. Refresh button re-extracts schema from source. Frontend shows read-only schema inputs.

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

- `/plan` - Create implementation plan
- `/review` - Code review
- `/clarify` - Ask clarifying questions
- `/rmslop` - Clean up AI slop
