# AGENTS.md

**Mandatory for all AI assistants.** Read fully before any work in this repository.

## Commands

```bash
just verify          # REQUIRED before declaring any task done (format + check)
just format          # ruff format + prettier
just test            # backend pytest
just test-e2e        # e2e tests with Playwright
just check           # ruff + mypy + svelte-check + eslint
just dev             # start both servers
```

- E2E must be run only via `just test-e2e`. Do not run Playwright e2e commands directly.

## Package Managers

- **Frontend**: `bun` — use `bun add` to install packages, never edit `package.json` directly
- **Backend**: `uv` — use `uv add` to install packages, never edit `pyproject.toml` directly

## Definition of Done

- Run `just verify` before declaring any task done or asking for review
- If `just verify` fails, fix the underlying issues immediately
- After `just verify` passes, run tests (`just test` and/or `just test-e2e`) to confirm functionality
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
- **No polling.** Do not add polling/interval refresh logic.
- **No fallback logic.** Do not add permissive fallback/defaulting behavior unless the user explicitly asks for it.
- **Build start is HTTP-only.** Never redesign build start around websockets.
- **Monitoring history is explicit.** Monitoring engine-run rows are history data and should only gain new rows on explicit refresh.
- **Live build websockets are scoped.** Websocket use for builds is limited to engine status in the left panel and live build preview/detail views, including the expanded Monitoring row for a running build.

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
- In Svelte files, do not hide styling behind helpers or intermediate style constants. Avoid `const foo = css(...)`, `const fooStyle = { ... }`, `css(fooStyle, ...)`, or wrapper functions that return `css(...)`; prefer direct `class={css({...})}` at the use site.

### Transitions

**Never use `transition-all`.** Always use specific properties:

- `transition-colors` for hover effects
- `transition-opacity` for fades
- `transition-[color,background-color,border-color,opacity]` for combined
- Add `transform` to the list only when transform changes


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
- Playwright `page.routeWebSocket()` must be registered BEFORE `page.goto()` to reliably intercept WebSocket connections opened later by user actions (e.g., button clicks). Registering after navigation silently fails to intercept through Vite's dev proxy. This applies even when the WS isn't opened until well after page load.
- When using `getByText()` in Playwright tests, beware that test resource names (datasource/analysis names) can contain the status words being asserted (e.g., "Complete", "Failed"). Scope assertions to a parent container (`preview.getByText(...)`) or use `{ exact: true }` to avoid strict mode violations.
- Before claiming Playwright e2e coverage matches real user behavior, audit the suite for `tests/utils/api.ts` setup helpers; API seeding is not user-driven interaction and must be called out or redesigned explicitly.
- Monitoring e2e assertions must track the current Builds UI: live build details are exposed through expandable history rows and `BuildPreview` tabs (`Steps`, `Logs`, `Payload`), not a separate `Active Builds` panel.
- Engine-run websocket handlers should treat close-race `RuntimeError`s like `Cannot call "receive" once a disconnect message has been received` and `Cannot call "send" once a close message has been sent` as normal disconnects to avoid false backend error logs during Playwright teardown.
- From the repo root, backend tool entrypoints should be run via `just` or from `backend/`; direct root-level `uv run pytest` / `uv run ruff` invocations can miss the backend environment and fail to resolve installed commands.
- When tightening frontend request/store typings, replace placeholder test payloads with a shared minimal valid fixture right away; Vitest mocks can hide bad `{}` inputs that `svelte-check` will still reject.
- Svelte 5 `$effect` blocks run in declaration order. When a "reset" effect (e.g., datasource switch) calls `.reset()` / `.close()` on a store, and a "start" effect calls `.start()` on that same store, the reset effect MUST be declared before the start effect. Otherwise the start effect fires first, begins an async fetch, and the reset effect fires second and aborts the in-flight request — leaving the store permanently empty.
- When using pinned icon libraries (for example `lucide-svelte`), verify the icon export exists in the installed version before wiring it into status/cancel UI; missing exports can crash Svelte render paths in e2e flows.
- Build cancellation must be terminal-state authoritative: before writing success state, re-check persisted run status and preserve `cancelled` if another request set it mid-flight, otherwise cancellation can be overwritten by late success finalization.
- Do not run frontend e2e specs directly with Playwright/Bun commands; use `just test-e2e` only so the intended environment and orchestration stay consistent.
- Monitoring builds architecture is strict: no polling, no separate live-preview row, no build-list websocket auto-refresh for history rows. Start builds via HTTP, show new history rows only after explicit refresh, and use websocket only for live preview/detail on the running build itself.
- Do not run `just verify` and `just test-e2e` in parallel. `just verify` rewrites/generated frontend artifacts and can trigger Vite reloads during Playwright, causing false `net::ERR_ABORTED`, missing shell/navigation elements, and flaky option/list assertions. Run them sequentially.
