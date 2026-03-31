# Production Audit Report

**Date:** 2026-03-31
**Status:** `just verify` passes | 1,023 backend tests | 954 frontend tests | 256/256 e2e tests pass

---

## Summary

| Severity | Backend Security | Frontend Security | Backend Quality | Frontend Quality | Deps & Config | Total |
|----------|:---:|:---:|:---:|:---:|:---:|:---:|
| **CRITICAL** | 3 | 0 | 3 | 4 | 0 | **10** |
| **HIGH** | 6 | 4 | 15 | 16 | 3 | **44** |
| **MEDIUM** | 6 | 6 | 22 | 30 | 11 | **75** |
| **LOW** | 2 | 4 | 9 | 23 | 11 | **49** |

---

## Fixed (33 changes)

### Backend Security Hardening

1. **Security headers middleware** — Added `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, and `Strict-Transport-Security` (in non-debug mode)
2. **`auth_required` default → `True`** — No longer possible to accidentally deploy without auth
3. **`SETTINGS_ENCRYPTION_KEY` validation** — Startup warning when encryption key is empty with auth enabled
4. **WebSocket error sanitization** — Generic error messages to clients, full stack traces logged server-side
5. **`PROD_MODE_ENABLED` → Settings class** — No more scattered `os.getenv()` calls
6. **Uvicorn `reload` gated on `debug`** — No longer auto-reloading in production
7. **Return type annotations** on all `main.py` endpoints
8. **SMTP timeout** — Added missing `timeout=10` to notification service SMTP connection

### Backend Dependency Hygiene

9. **Moved test/dev deps** — `pytest`, `pytest-asyncio`, `pytest-timeout`, `ruff`, `mypy`, `types-openpyxl` moved from runtime to `[dependency-groups] dev`
10. **Cleaned up `[project.optional-dependencies]`** — Removed duplicate dev section

### Frontend Type Safety & Memory Leaks

11. **`err()` → `errAsync()`** — Fixed type mismatch in `analysis.svelte.ts` (removed unsafe `as unknown as ResultAsync` casts)
12. **`ChatStore.destroy()`** — Added proper cleanup for `beforeunload` listener + `EventSource`
13. **Draft timer `$effect` cleanup** — Returns cleanup function to clear timeout on unmount
14. **ChatPanel code copy `$effect` cleanup** — Tracks created buttons and removes them on cleanup

### Docker

15. **`npm ci` → `bun install --frozen-lockfile`** — Docker now uses the correct package manager matching development

### Configuration

16. **`.env.example` updated** — Documents new `auth_required=True` default

### Round 2 — Concurrency, Async I/O, Auth, Cleanup

#### Backend Concurrency & Async

17. **`asyncio.Lock` on compute cache** — `_ANALYSIS_CACHE` and `_ANALYSIS_CACHE_KEYS` in `datasource.py` now protected by `asyncio.Lock`
18. **`asyncio.Lock` on preflight cache** — `_PREFLIGHTS` dict in `preflight.py` now protected; functions made async
19. **`asyncio.Lock` on namespace engines** — `_namespace_engines` OrderedDict in `database.py` now protected; SQLite WAL/busy_timeout pragmas enabled on new connections
20. **Sync file I/O → `asyncio.to_thread()`** — Upload handlers in `datasource/routes.py` no longer block the event loop

#### Backend Auth & Security

21. **Stronger password validation** — `validate_password()` now requires uppercase, lowercase, and digit
22. **`_validate_default_user_password` field validator** — Config rejects weak default passwords at startup
23. **Async SMTP** — Blocking SMTP calls in `auth/service.py` wrapped in `asyncio.to_thread()`; failures now log ERROR and propagate
24. **Iceberg symlink check fixed** — Removed blanket `is_symlink()` rejection that broke `/tmp` paths on macOS; path containment check already resolves symlinks

#### Frontend Memory Leak Fixes

25. **`audit-log.ts` cleanup** — `installAuditListeners()` now returns a cleanup function that removes all 5 global event listeners
26. **Layout audit listener cleanup** — `+layout.svelte` effect captures and returns audit listener cleanup
27. **`ChatStore.destroy()` cleanup** — Layout effect calls `chatStore.destroy()` on unmount
28. **`StepNode.svelte` copy timer** — Timer stored and cleared on unmount
29. **`IndexedDbButton.svelte` copy timer** — Timer stored and cleared on unmount
30. **`flashTabError` timer** — Analysis page timer stored and cleared on unmount

#### E2E Test Infrastructure

31. **`justfile` e2e recipe** — Fixed to properly source `e2e.env` with `--no-env-file` to prevent `.env` override
32. **`e2e.env` updated** — Added `ENV_FILE=e2e.env`; password updated to meet new strength requirements
33. **E2e heading selector** — `analysis-crud.test.ts` selectors updated to `{ level: 1 }` to avoid strict mode violations

---

## Remaining Findings

### CRITICAL

#### Arbitrary code execution via `exec()` in UDF handler

- **File:** `backend/modules/compute/operations/with_columns.py:72`
- User-supplied UDF code is passed directly to `exec()`. While a restricted `_SAFE_BUILTINS` dict is provided and `validate_no_reflection_escape()` performs string-level blocklist checks, this is a blocklist-only defense. Blocklist bypasses for Python sandboxes are well-documented.
- **Recommendation:** Execute UDF code in a sandboxed subprocess with restricted OS-level permissions (nsjail, gVisor), or replace `exec()` with a safe expression DSL.

#### Arbitrary code execution via `eval()` in expression parser

- **File:** `backend/modules/compute/operations/expression.py:54`
- User-supplied expression strings are evaluated via `eval()` with `{'__builtins__': {}, 'pl': pl}`. The `pl` (Polars) namespace itself can be used as an escape vector.
- **Recommendation:** Replace with a safe expression evaluator such as `asteval`, `simpleeval`, or a custom AST walker that only permits whitelisted node types.

#### Shared mutable state with no locking in compute cache [FIXED]

- **Status:** Fixed — `asyncio.Lock` added to protect `_ANALYSIS_CACHE` and `_ANALYSIS_CACHE_KEYS`.

#### Silent schema cache error swallowing

- **File:** `backend/modules/datasource/service.py:907`
- Catches bare `Exception` when validating schema cache and silently sets `cached = None`. Corrupted cache or unexpected errors become invisible.
- **Recommendation:** Re-raise as a domain-specific exception or return a structured error.

#### `analysis.svelte.ts` save() returned wrong type [FIXED]

- **Status:** Fixed — replaced `err()` with `errAsync()`.

#### ChatStore missing `destroy()` method [FIXED]

- **Status:** Fixed — added `destroy()` method for `beforeunload` listener cleanup.

#### ChatPanel code copy buttons memory leak [FIXED]

- **Status:** Fixed — added cleanup return to `$effect`.

### HIGH

#### Backend Security

##### WebSocket endpoint has no authentication

- **File:** `backend/modules/compute/routes.py:279-324`
- The `/ws` WebSocket endpoint accepts connections without any authentication check. Even if `AUTH_REQUIRED=True`, this endpoint bypasses it entirely.
- **Recommendation:** Authenticate WebSocket connections before accepting them (validate session token from query params or cookies before calling `websocket.accept()`).

##### No authentication on most route modules

- `compute/routes.py` — no auth
- `scheduler/routes.py` — no auth
- `telegram/routes.py` — no auth
- `datasource/routes.py` — `get_optional_user`
- `analysis/routes.py` — `get_optional_user`
- `udf/routes.py` — `get_optional_user`
- Only `settings/routes.py` and `chat/routes.py` use `get_current_user` (mandatory auth).
- **Recommendation:** All routes should use `get_current_user` when `AUTH_REQUIRED=True`.

##### No rate limiting

- No rate limiting middleware or dependency exists anywhere in the codebase. Login, registration, password reset, and all API endpoints are unprotected against brute force and abuse.
- **Recommendation:** Add `slowapi` or a custom `Depends`-based limiter at minimum on authentication endpoints.

##### Default user password is weak and hardcoded [MITIGATED]

- **File:** `backend/core/config.py:198`
- `default_user_password` defaults to `'ChangeMe123'`. Now validated at startup via field validator requiring uppercase, lowercase, and digit.
- **Recommendation:** Require the default user password to be set explicitly via environment variable with no hardcoded fallback.

##### Encryption key defaults to empty string [MITIGATED]

- **File:** `backend/core/config.py:175`
- `settings_encryption_key` defaults to `''`. Now emits a startup warning when auth is enabled.
- **Recommendation:** Fail startup if `SETTINGS_ENCRYPTION_KEY` is empty in non-debug mode.

##### No security headers middleware [FIXED]

- **Status:** Fixed.

#### Frontend Security

##### No CSRF protection

- **Files:** `frontend/src/lib/api/client.ts`, all auth form pages
- No CSRF tokens are used anywhere. The API client sends `Content-Type: application/json` headers which provides CORS preflight protection, but this relies entirely on CORS being configured correctly.
- **Recommendation:** Implement explicit CSRF protection. Verify backend sets `SameSite=Lax` or `Strict` on session cookies.

##### API key stored in reactive state

- **File:** `frontend/src/lib/stores/chat.svelte.ts:90`
- OpenRouter API key is stored in Svelte reactive state. Accessible in browser DevTools.
- **Recommendation:** Backend should always return masked keys. Frontend should send keys for configuration only, never store them in persistent state.

##### No CSP headers configured

- No SvelteKit `hooks.server.ts` file exists and no CSP meta tag in the layout. The app uses `adapter-static` so CSP needs to be configured at the reverse proxy / CDN level.
- **Recommendation:** Add CSP headers at the deployment layer. At minimum: `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src 'self'; img-src 'self' data:; frame-src 'none'`.

##### Backend .env files committed to repo

- **Files:** `backend/.env`, `backend/.prod.env`
- **Recommendation:** Verify these are in `.gitignore` (they are). Check git history for past secret exposure.

#### Backend Code Quality

##### SMTP failures silently swallowed [FIXED]

- **Status:** Fixed — SMTP calls wrapped in `asyncio.to_thread()`, failures now log ERROR and propagate.

##### Synchronous file writes in async endpoints [FIXED]

- **Status:** Fixed — replaced with `asyncio.to_thread()` calls.

##### Missing `response_model` on chat, MCP, and analysis routes

- **Files:** `backend/modules/chat/routes.py`, `backend/modules/mcp/routes.py`, `backend/modules/analysis/routes.py`, `backend/main.py`
- 20+ endpoints across these modules still lack `response_model` definitions. OpenAPI docs for those routes fall back to untyped/default response schemas.
- **Recommendation:** Define Pydantic response models for every endpoint.

##### Shared mutable state without locking [FIXED]

- **Status:** Fixed — `asyncio.Lock()` added to `_PREFLIGHTS` dict, `_namespace_engines` OrderedDict, and `_engine_override`.

#### Frontend Code Quality

##### Unsafe double-casts in key production paths [MITIGATED]

- **Status:** The most problematic `as unknown as` double-casts were removed from high-risk production paths: `compression.ts`, `StepConfig.svelte`, `StepNode.svelte`, `InlineDataTable.svelte`, `chat.svelte.ts`.
- Some casts may still remain in lower-traffic or config-heavy paths (e.g. `DatasourceConfigPanel.svelte`).
- **Recommendation:** Continue migrating toward discriminated union types keyed on `step.type` / `source_type` to eliminate remaining casts.

##### Hardcoded color palette in ChartPreview

- **File:** `frontend/src/lib/components/pipeline/ChartPreview.svelte:32-39`
- `PALETTE` array with 8 hardcoded hex colors bypasses the design system.
- **Recommendation:** These are chart data colors for D3 visualizations. Already extracted to a named constant. Acceptable for chart palettes but could be moved to a shared theme configuration.

#### Dependencies & Config

##### Test dependencies in production deps [FIXED]

- **Status:** Fixed — moved `pytest`, `ruff`, `mypy`, `types-openpyxl` to dev group.

##### Dockerfile uses npm instead of bun [FIXED]

- **Status:** Fixed — switched to `oven/bun:1` image.

##### No dependency vulnerability scanning in CI

- Neither GitHub CI nor GitLab CI runs `pip audit`, `bun audit`, or similar vulnerability scanners.
- **Recommendation:** Add vulnerability scanning to CI pipeline.

### MEDIUM

#### Backend Security

##### Weak password validation [FIXED]

- **Status:** Fixed — now requires uppercase, lowercase, and digit in addition to 8-char minimum.

##### User-supplied database connection strings (SSRF risk)

- **File:** `backend/modules/datasource/routes.py`
- The `_connect_database` endpoint accepts user-supplied connection strings.
- **Recommendation:** Validate against an allowlist of schemes. Block localhost, internal IP ranges, and `file://` schemes.

##### Session cookie secure flag tied to debug mode

- **File:** `backend/modules/auth/routes.py:52-61`
- `secure=not settings.debug` means misconfiguring debug mode disables secure cookies.
- **Recommendation:** Use a separate `COOKIE_SECURE` setting.

##### CORS default origins include localhost

- **File:** `backend/core/config.py:93`
- Default CORS origins include `localhost:3000`, `localhost:5173`.
- **Recommendation:** Ensure production config explicitly overrides with production domain(s) only.

##### WebSocket error handler leaks exception messages [FIXED]

- **Status:** Fixed.

##### Development server binds to all interfaces

- **File:** `backend/main.py:344`
- `host='0.0.0.0'` binds to all network interfaces.
- **Recommendation:** Default to `127.0.0.1` in `__main__`. Use proper deployment config for production.

#### Frontend Security

##### Sensitive tokens in URL query parameters

- **Files:** `frontend/src/routes/(auth)/verify/+page.svelte:12`, `frontend/src/routes/(auth)/reset-password/+page.svelte:14`
- Email verification and password reset tokens passed via URL query parameters.
- **Recommendation:** Ensure tokens are single-use, short-lived, and consumed immediately.

##### No 401 interceptor / token refresh

- **Files:** `frontend/src/lib/api/client.ts`, `frontend/src/lib/stores/auth.svelte.ts`
- No token refresh or session renewal mechanism. When session expires, user gets silent errors.
- **Recommendation:** Add a 401 interceptor in `apiFetch` that redirects to `/login`.

##### WebSocket and SSE auth relies on cookies

- **Files:** `frontend/src/lib/api/websocket.ts`, `frontend/src/lib/api/chat.ts`
- No explicit auth header; relies on cookie auto-send for same-origin.
- **Recommendation:** Verify backend validates session cookies during WebSocket upgrade and SSE endpoint.

##### AI step config API key exposure

- **File:** `frontend/src/lib/components/operations/AIConfig.svelte:20`
- API key becomes part of the analysis JSON that gets saved/loaded.
- **Recommendation:** Ensure backend masks this field in GET responses.

##### Vite dev server binds to 0.0.0.0 with `allowedHosts: true`

- **File:** `frontend/vite.config.ts:17-19`
- Development only. Disables DNS rebinding protection.
- **Recommendation:** Restrict `allowedHosts` to specific hostnames in dev.

##### E2E test credentials hardcoded

- **File:** `frontend/tests/global-setup.ts:8-9`
- **Recommendation:** Move to environment variables or a test-specific `.env` file.

#### Backend Code Quality

##### Missing return type annotations

- `core/database.py` — `set_engine_override`, `clear_engine_override`, `get_db`, `get_settings_db`
- `modules/compute/service.py` — `list_iceberg_snapshots`, `delete_iceberg_snapshot`
- `modules/mcp/router.py` — `MCPRouter` methods
- `modules/mcp/pending.py` — `PendingStore` methods
- `modules/compute/operations/plot.py` — plot helpers
- **Recommendation:** Add explicit return type annotations to all public functions.

##### Missing SMTP timeout [FIXED]

- **Status:** Fixed.

##### `sqlite3.connect()` without `with` statement

- **Files:** `backend/modules/compute/operations/datasource.py:129`, `backend/modules/datasource/service.py:983`
- **Recommendation:** Use `with sqlite3.connect(...)` context managers.

##### Entire exported file read into memory

- **File:** `backend/modules/compute/service.py:1328`
- **Recommendation:** Consider streaming large file exports.

##### Magic numbers/strings not in config

- `chat/routes.py:33` — `HEARTBEAT_INTERVAL = 15`
- `chat/sessions.py:19-20` — `MAX_EVENTS = 500`, `MAX_MESSAGES = 100`
- `mcp/pending.py:13` — `TTL = 300`
- `telegram/bot.py:74,77` — `max_consecutive_errors = 10`
- **Recommendation:** Centralize into `core/config.py` Settings model.

#### Frontend Code Quality

##### Inline `style=""` attributes [MITIGATED]

- **Status:** Audited production inline-style hotspots converted to Svelte `style:` directives and dynamic styling patterns. Remaining inline styles are limited to dynamic pixel/percentage values that Panda CSS cannot express statically.

##### `role="button"` on non-interactive elements [MITIGATED]

- **Status:** Audited fake-button usages corrected in key production paths: `AnalysisCard`, `FileBrowser`, `DatasourceConfigPanel`, `PipelineCanvas`, `DataTable`. Replaced `role="button"` `<div>`s with native `<button>` elements or added proper `tabindex`/`onkeydown` handlers where appropriate.

##### `audit-log.ts` listeners never removed [FIXED]

- **Status:** Fixed — `installAuditListeners()` now returns cleanup function; called from `+layout.svelte` effect.

##### `EnginesStore` polling interval not reactive

- **File:** `frontend/src/lib/stores/engines.svelte.ts:51-53`
- `setInterval` captures polling interval at call time. Config updates don't adjust it.
- **Recommendation:** Make polling interval reactive.

##### Analysis page draft timer [FIXED]

- **Status:** Fixed.

#### Dependencies & Config

##### No upper bounds on any backend dependency

- Every pinned dependency uses `>=` with no upper bound. Lockfile mitigates for reproducible installs.
- **Recommendation:** Add upper bounds for major version protection.

##### 13 completely unpinned backend packages

- `uvicorn`, `fastapi`, `polars`, `duckdb`, `requests`, `httpx`, etc.
- **Recommendation:** Add minimum version pins.

##### `e2e.env` tracked in git

- **File:** `backend/e2e.env`
- Contains default password `ChangeMe123`. Not a real secret but normalizes tracking env files.
- **Recommendation:** Add to `.gitignore`.

##### `PROD_MODE_ENABLED` read outside Settings [FIXED]

- **Status:** Fixed — moved to `settings.prod_mode_enabled`.

##### `reload=True` unconditional in `__main__` [FIXED]

- **Status:** Fixed — gated on `settings.debug`.

##### No database connection pooling configuration [MITIGATED]

- **Status:** Mitigated — SQLite connections now enable WAL and busy_timeout, but explicit SQLAlchemy pool sizing/configuration is still absent.

##### Synchronous SQLAlchemy, not async

- The codebase uses synchronous `create_engine` and `Session`, not `create_async_engine`/`AsyncSession`. For SQLite this is acceptable.

##### No production build optimization in Vite config

- No `build.rollupOptions`, manual chunk splitting, or sourcemap configuration.
- **Recommendation:** Consider manual chunking for `d3`, `codemirror`, and `marked`.

##### `d3` full library imported

- `d3` (~500KB minified). If only specific modules are used, importing sub-packages would reduce bundle size.

##### `@types/d3` in production deps

- **File:** `frontend/package.json:54`
- Type-only package should be in `devDependencies`.

##### Root `.gitignore` is minimal

- Only 10 lines. Relies on subdirectory `.gitignore` files. Missing `.env` at root level.
- **Recommendation:** Add common patterns at root level as fallthrough protection.

##### CI backend `uv sync` without `--frozen`

- Backend CI step just runs `uv sync` without `--frozen`, so CI could resolve different versions.

### LOW

#### Backend Security

- Session tokens are UUID4 hex (128 bits entropy) — meets OWASP minimum. Consider `secrets.token_urlsafe(32)` for 256 bits.
- IP addresses partially anonymized in logs — review against GDPR.

#### Frontend Security

- `{@html}` usage with DOMPurify sanitization — properly mitigated.
- `innerHTML` for static SVG icons — no user data flows into assignments.
- Chat session ID in localStorage — not an auth session, low risk.
- Debug flag in localStorage (`debug:prefer-http`) — minimal risk.
- Open redirect potential in OAuth flow — currently hardcoded to `'google'`/`'github'`, safe.

#### Backend Code Quality

- Helper functions missing return types in `filter.py`, `type_casting.py`, `plot.py`, `engine.py`.
- Manual temp file cleanup with `os.path.exists`/`os.remove` instead of `tempfile` context managers.
- `MCP PendingStore` returns `None` for expired/missing tokens with no distinction.

#### Frontend Code Quality

- `setTimeout` cleaned up on unmount in `StepNode.svelte` and `IndexedDbButton.svelte`.
- Borderline `$effect` blocks that could be `$derived.by()` in analysis page and ChartPreview.

#### Dependencies & Config

- Docker-compose `version: "3.8"` key deprecated.
- Docker-compose healthcheck commented out.
- `LOG_MAX_BODY_SIZE=0` (unlimited) in prod config.
- `precompress: false` in static adapter.
- `server.allowedHosts: true` in Vite dev config.
- CORS defaults include localhost.
- `SETTINGS_ENCRYPTION_KEY` optional (empty default).

---

## Positive Security Practices Already in Place

| Practice | Location |
|---|---|
| Password hashing with PBKDF2 (200k iterations) | `auth/service.py:31-46` |
| Timing-safe password comparison | `auth/service.py:67` |
| Error handler sanitizes HTTP responses | `core/error_handlers.py:190-196` |
| Sensitive field redaction in logs | `core/logging.py:31-43` |
| File upload validation (size, type, magic bytes) | `datasource/routes.py` |
| Path traversal protection | `datasource/routes.py:336-338` |
| Secrets encrypted at rest (AES-GCM) | `core/secrets.py` |
| Session cookies are httponly | `auth/routes.py:56` |
| SameSite=lax on cookies | `auth/routes.py:58` |
| OAuth state validation (constant-time) | `auth/routes.py` |
| ORM used throughout (no raw SQL injection) | All modules |
| CORS configured from settings (no wildcard) | `main.py:226` |
| DOMPurify for `{@html}` sanitization | `utils/markdown.ts` |
| Audit log redacts sensitive fields | `utils/audit-log.ts:70` |
| Non-root Docker user | `Dockerfile:38,59` |
| Docker resource limits | `docker-compose.yml:74-81` |
| `neverthrow` Result types for typed error handling | All API modules |
| No frontend environment variable exposure | Entire frontend |
