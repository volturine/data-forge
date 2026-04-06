# AGENTS.md

**Mandatory for all AI assistants.** Read fully before any work in this repository.

## Commands

```bash
just verify          # REQUIRED before declaring any task done (format + check)
just format          # ruff format + prettier
just test            # backend pytest
just check           # ruff + mypy + svelte-check + eslint
just dev             # start both servers
```

## Package Managers

- **Frontend**: `bun` — use `bun add` to install packages, never edit `package.json` directly
- **Backend**: `uv` — use `uv add` to install packages, never edit `pyproject.toml` directly

## Definition of Done

- Run `just verify` before declaring any task done or asking for review
- If `just verify` fails, fix the underlying issues immediately
- Do not ignore or suppress warnings, even if they seem unrelated
- Write backend Python tests for new/changed functionality
- Pre-existing warnings are tech debt — fix them, do not ignore them
- If a warning cannot be fixed (third-party stubs), suppress with an inline comment explaining why

## Workflow

1. **Explore** — Read relevant files, understand context
2. **Plan** — Produce a structured plan before coding
3. **Code** — Implement. Use parallel agents when possible
4. **Verify** — Run `just verify` mandatorily before declaring any task done
5. **Reviewer** — Ask for review and address feedback
6. **Finish** — Clean up, ensure tests pass
7. **Reflect** — Update `AGENTS.md` if you did anything wrong on first pass either prompted by user feedback or your own reflection

**Do not ask for confirmation on implementation details.** Make decisions, implement, verify. Stop and ask only on genuine ambiguity about requirements or conflicts with these rules.

**Reflect on your work.** After completing a task, review the process and outcome. If you made any mistakes or could have done something better, update this document to prevent future issues.

## Non-Negotiables

- **No workarounds.** Fix root causes or stop and ask
- **No hidden compromises.** State conflicts and propose alternatives
- **No silent behavior changes.** All changes explicit and intentional
- **Redesign over hotfix.** If existing code is wrong, redesign properly
- **Fix warnings, not just errors.** Treat warnings as bugs
- **Autonomous completion.** Continue until every requirement is implemented, tested, and verified
- **No legacy support.** New features/redesigns must not preserve legacy paths or backward compatibility

## Frontend Development

### Svelte / SvelteKit

- All Svelte components must have `lang="ts"` on the `<script>` tag
- Use Svelte 5 runes throughout — runes mode is enforced compiler-wide
- Prefer `$derived` over `$effect` for computed state
- `$effect` is only for side effects (DOM access, subscriptions, timers, network) — not for deriving state
- If `$effect` is used, include a one-line comment explaining why `$derived` is insufficient

### TypeScript

- Avoid `as any` — infer types from function signatures instead
- Avoid `as SomeType` casts unless absolutely necessary; prefer type guards
- Use `satisfies` for object literals that should conform to a type
- Prioritize type inference — let TypeScript figure it out from context

### Styling

- **Panda CSS** for all styling — custom inline styles only when Panda cannot express it
- Never use `transition-all` — use specific properties (see Transitions below)
- Use semantic color tokens from the design system, never raw hex/rgb values

### Transitions

**Never use `transition-all`.** Always use specific properties:

- `transition-colors` for hover effects
- `transition-opacity` for fades
- `transition-[color,background-color,border-color,opacity]` for combined
- Add `transform` to the list only when transform changes

## Backend Development

- FastAPI async patterns throughout — no blocking calls in route handlers
- Pydantic V2 models for all request/response schemas
- SQLAlchemy 2.0 async sessions — no sync DB calls
- Polars for all data computation — avoid pandas

## Code Style

See [`STYLE_GUIDE.md`](STYLE_GUIDE.md)

## Git

- NEVER push to remote unless explicitly asked
- Local commits only
- Create PRs for sharing changes

## Learnings

- When adding API endpoints that mirror existing compute behavior, inspect the raw engine payload shape end-to-end before mapping it into API schemas. The engine returns `schema` + `data`; backend adapters must translate that shape explicitly instead of assuming preview-style fields already exist.
- MCP tool contracts should reject unknown top-level args (`additionalProperties: false`) and expose path/query/payload placement metadata so AI prompts can describe exact input placement without drift.
- Path-template failures in MCP execution should return structured `validation_error` responses, not indirect 404/422s, so AI agents can repair missing parameters.
- MCP tool onboarding is `MCPRouter`-only: tool-exposed API modules must use `MCPRouter`, and routes are onboarded only with explicit `mcp=True` on the router decorator; plain `APIRouter` routes must not be onboarded.
- MCP registry discovery should start from MCP-attached `APIRoute` metadata and use OpenAPI only to enrich input/output schemas and details; raw endpoint scanning and fallback onboarding paths are forbidden.
- FastAPI `include_router()` can re-create route objects; for MCP metadata to survive nesting, `MCPRouter` must enforce an MCP-aware `route_class` that re-attaches metadata during route construction, not only in `add_api_route()`.
- Chart/plot preview responses expose visualization columns like `x`/`y`; frontend schema propagation must treat chart steps as schema-transparent and never cache chart preview schemas as downstream pipeline schema.
- SvelteKit client-side `goto()` transitions can leave Playwright `waitForURL()` hanging; for in-app navigation tests prefer `expect(page).toHaveURL()` after the click, and wait for hydration (`networkidle`) before clicking JS-bound controls.
- Monitoring and modal e2e flows are much more reliable when tests target accessible semantics (`role="tab"`, `role="dialog"`, `aria-label`) instead of DOM order, hover-only buttons, or global `.first()` selectors.
- Datasource list/read endpoints must stay side-effect free: schema extraction and `schema_cache` backfill belong on write/create paths, not inside `list_datasources()`, or concurrent e2e traffic can trigger transient upload/delete races.
- Before replying that a PR follow-up is ready, confirm the branch log/diff includes the intended code changes; review notes without a corresponding commit are not enough.
- When tightening TypeScript config shapes across shared components, keep callback signatures compatible with component contracts (`Record<string, unknown>`) and normalize into stricter typed objects inside handlers.
- When normalizing config objects, avoid duplicate-key object literals (for example `{ branch, ...normalized }`) because they hide overwrite order; build a single explicit normalized object first.
- After broad enum/dataclass refactors, rerun focused schema-contract tests immediately; JSON schema often moves enum values under `$defs`/`$ref`, so tests that assert inline enums should resolve refs explicitly instead of assuming inlined `enum`.
- In Svelte store modules, avoid native mutable collections like `Map`/`Set` in reactive code paths; prefer `SvelteMap`/`SvelteSet` (or plain objects/arrays) to satisfy `svelte/prefer-svelte-reactivity` and keep lint clean.
