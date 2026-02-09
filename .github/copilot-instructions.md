# Copilot Instructions

Follow `AGENTS.md` and `STYLE_GUIDE.md` at all times.

## Workflow

- Explore first: read relevant files for context.
- Plan before coding: use `/plan` and wait for approval.
- After planning, use `vibe_check` mcp.
- Use the Second Opinion agent before completing tasks.
- Use `vibe_learn` mcp to record discoveries.
- Create local commits only; never push to remote.

## Stack

- Frontend: SvelteKit 2, Svelte 5 runes, TypeScript, TanStack Query.
- Backend: FastAPI, async/await, SQLAlchemy, SQLite.

## Backend Rules

- Use async/await for DB operations.
- Follow RORO: Pydantic in, Pydantic out.
- Type hints everywhere.
- Pydantic v2 with `model_config = ConfigDict(from_attributes=True)`.
- SQLAlchemy `Mapped` types for models.
- Keep routes thin; logic in services.
- File naming: `snake_case.py`.

## Frontend Rules

- Runes only (`$state`, `$derived`, `$props`, `$effect`, `$bindable`).
- Never use legacy syntax (`export let`, `$:`, `onMount`).
- Data fetching via `@tanstack/svelte-query`.
- No inline styles except dynamic positioning.
- No CSS vars in markup; use `app.css` utilities.
- Avoid `@apply` and component `<style>` blocks.
- Use `border-tertiary` for table/view borders.
- Use theme accents: `bg-accent-bg`, `text-accent-primary`, `border-info`.
- Dynamic styles via Svelte actions (e.g., `use:setWidth`).
- Use `$lib` alias imports.

## Patterns

- Config defaults belong in `step-config-defaults.ts`.
- Lucide icons are stored as component references and rendered as `<Icon />`.
- Datasources are immutable after creation; schema/location never change.

## Code Style

- Prefer `const` over `let`.
- Avoid `else`; use early returns.
- Single word names where possible.
- Keep functions unified unless composable.
- Avoid unnecessary destructuring.
- Avoid `try/catch` when possible.
- No `any` types.

## Testing & Reporting

- Report test results in table format.
- Never ignore timeouts; investigate immediately.
