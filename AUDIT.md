# Data-Forge Codebase Audit

**Date:** 2026-08-21 · **Scope:** full monorepo, file-by-file (~700 source files across `packages/{backend,scheduler,worker,frontend,protocol}`, `scripts/`, `docker/`, `config/env/`, `Justfile`)
**Method:** 20 parallel audit units, one per package/directory slice. Every file was read and assessed for security, correctness, error handling, concurrency, and maintainability. Findings cite file paths and line numbers. Read-only — no code was changed.

---

## Remediation log (2026-08-21)

The following easy, surgical fixes were applied after this audit. Verification: `just verify`, `just test`, and `just test-e2e` all pass (backend 99 passed, worker 4 passed, frontend unit 1216 passed, e2e 353 passed).

### E2E reliability follow-up

Initial post-fix e2e runs failed with a 600s timeout. Root causes found and fixed:

1. **Stale local timeout cap** — `scripts/test_e2e.sh` capped non-CI runs at 600s ("never more than ten minutes"), but the Docker-engine cutover (#91) pushed the suite past that on loaded machines. Local ceiling raised to 900s (CI keeps its explicit 1500s budget).
2. **Load-flaky stats test** — `datasources.test.ts:390` asserted engine-computed column stats within 5s; under 4 parallel workers the first compute can exceed that. Assertion window raised to 20s.
3. Transient "engine container health" errors in one early run did not reproduce once host load settled (0 occurrences across subsequent full runs); they were environmental, not caused by the fixes.

Final result: `just test-e2e` → **353 passed (7.3m)**, exit 0.

---

## Remediation log — batch 2 (2026-08-21)

Seven audit workstreams implemented. Verification: `just verify`, `just test` (backend 1062, scheduler 99, worker 4, frontend unit 1221), and `just test-e2e` (353 passed) all green.

**#3 Credential leakage**
- Datasource API responses now mask `connection_string`/`catalog_uri`/nested source credentials (`modules/datasource/service.py`).
- Platform DB credentials are no longer persisted into analysis-output/clean Iceberg datasource configs: removed `catalog_uri` producers in `compute/routes.py`, `worker/runtime/compute_service.py`, `worker/datasources/execution.py`; the worker prefers its own `DATABASE_URL` for snapshot list/delete and backend cleanup falls back to `settings.database_url`.

**#5 MCP** — pending tokens are bound to the creating user (completion rejects mismatched presenters); all MCP tool results redact `connection_string`/`api_key`/`bot_token`.

**#6 SSRF** — AI provider endpoint URLs validated against the configured-provider allowlist (client-supplied arbitrary endpoints rejected).

**#2 Secrets at rest** — Telegram bot tokens encrypted via the existing `secrets.py` mechanism (settings were already encrypted); Alembic `0003_encrypt_secrets_at_rest` backfills existing rows idempotently; keyless deployments keep prior behavior; responses stay token-free.

**#7 Worker resource hygiene** — data-plane clients gained close/context-manager support; ~8 worker runtime modules now close or reuse channels instead of leaking per call; trivial gRPC calls use shorter timeouts; export staged-column stripping streams record batches instead of full-file reads (remaining full-materialization sites documented as pyiceberg API / download-protocol constraints).

**#8 Concurrency** — notification hubs prune dead waiters and cap entries with oldest eviction; `release_worker_jobs` uses `FOR UPDATE SKIP LOCKED` in one transaction; settings cache is weakref-keyed (no more `id()` reuse hazards); resource locks use compare-and-set takeover/heartbeat keyed on owner+token.

**#9 Robustness** — form-encoded login bodies are redacted in request logs; too-short XFF chains fall back to peer address (shared helper); Telegram delivery and outbox errors redact tokens before persisting; timeseries TIMESTAMP units produce correct magnitudes; build-stream parse failures route through WebSocket onError; locks WS reconnect uses exponential backoff with jitter (cap 30s).

### Deferred to backlog PRDs
- Authorization/ownership gaps → [Authorization, Ownership, and Collaboration](docs/prd/backlog/authorization-ownership-and-collaboration.md) (audit findings appended)
- UDF execution boundary → [UDF Execution Sandbox](docs/prd/backlog/udf-execution-sandbox.md)
- Component decomposition → [Frontend Component Decomposition](docs/prd/backlog/frontend-component-decomposition.md)

| # | Fix | Severity | Where |
|---|-----|----------|-------|
| 1 | Path traversal guard on static catch-all (`resolve()` + `is_relative_to` containment) | high | `packages/backend/main.py` |
| 2 | `PersistEngineSnapshot` gRPC now requires internal token (added threaded auth decorator); token compare via `hmac.compare_digest` | high / medium | `packages/backend/backend_grpc/server.py` |
| 3 | `bot_token` removed from `SubscriberResponse` API schema and frontend `Subscriber` type | high | `backend_core/telegram_schemas.py`, `frontend/src/lib/api/settings.ts` |
| 4 | `AUTH_REQUIRED=true` default for source-based production path | high | `config/env/prod.env` |
| 5 | Prod-mode validation rejects default `rustfsadmin` object-store credentials | medium | `backend_core/config.py` |
| 6 | Engine list dedup key typo (`latest[row.analysis_id]` → `latest[key]`) | medium | `backend_core/engine_instances_service.py` |
| 7 | Lost-wakeup race in `wait_for_namespace` (version check + waiter registration now atomic under one lock); dead watcher stubs removed | medium / low | `backend_core/engine_live.py`, `modules/compute/routes.py` |
| 8 | Alembic autogenerate table filter now includes `analysis_favorites`, `notification_delivery_receipts` | medium | `database/alembic/env.py` |
| 9 | Malformed `Content-Length` header no longer crashes request logging middleware | low | `backend_core/logging.py` |
| 10 | Readiness endpoints no longer leak raw exception text; startup bot-settings DB read moved off the event loop | low | `packages/backend/main.py` |
| 11 | `queued_job_count` / `queued_request_count` / `pending_event_count` now use SQL COUNT instead of hydrating all rows | low ×3 | `build_jobs_service.py`, `compute_requests_service.py`, `runtime_outbox_service.py` |
| 12 | Audit-log dedupe checks before buffering; flush failures re-queue unsent payload instead of dropping it | medium | `frontend/src/lib/utils/audit-log.ts` |
| 13 | Tab delimiter option now yields a real tab character (was literal `\t`) in both CSV-config surfaces | medium | `routes/datasources/new/+page.svelte`, `DatasourceConfigPanel.svelte` |

Remaining findings (authorization gaps on CRUD/WebSocket surfaces, secret encryption at rest, UDF sandbox, gRPC channel lifecycle, oversized components, etc.) require design-level work and are tracked in the detailed sections below.

---

## Executive summary

| Severity | Count |
|----------|------:|
| Critical | 0 (3 initially reported, retracted — see note below) |
| High | 23 |
| Medium | 117 |
| Low | 514 |

> **Retraction note:** Three units initially reported "critical Python-2-style syntax errors" (`except A, B:`) in `backend_core`. Verified against the project's Python 3.14.2: this is valid PEP 758 syntax (paren-less multi-exception `except`), not an error. Those findings are downgraded to **style nits** (they confuse readers expecting older Python).

### Top themes

1. **Secrets at rest / in responses (highest-impact cluster).** DB connection strings with credentials are persisted into datasource configs and returned unredacted through API/MCP responses (`modules/compute/routes.py:551`, `worker/execution.py:460,489`, Unit 08). AI `api_key` and Telegram `bot_token` values are stored plaintext and exposed via settings/subscriber schemas (Units 03–06). Protocol payloads carry `connection_string`, `api_key`, `bot_token` unredacted (Unit 14).
2. **Authorization gaps on CRUD and realtime surfaces.** Analysis CRUD, engine-run/Iceberg-delete endpoints, namespace/bucket creation, healthcheck CRUD, and `/ws/engines` lack ownership/auth checks (Units 06, 07). Chat sessions have no per-user authorization — any authenticated user can read/delete any session (Unit 05). Frontend route guards are client-side only; no server-side hooks gate data routes (Unit 20).
3. **UDF execution is effectively unrestricted code execution.** `worker/operations/with_columns.py` runs user UDF code via `exec` where the "sandbox" is a substring blacklist; Polars exposes file/network I/O, so the sandbox does not hold (Unit 11). Backend validates UDF syntax only (Unit 08).
4. **Robustness bugs in core flows.** Broken Excel-bounds update path opens `s3://` URLs as local paths (Unit 08); audit-log dedupe sends events it meant to drop and flush failures silently discard payloads (Unit 17); build-stream parse errors bypass WebSocket onError (Unit 15); `BuildStatus.coerce` maps corrupt data to SUCCESS (Unit 10); timeseries TIMESTAMP returns microseconds for SECONDS units (Unit 11).
5. **Resource & concurrency weaknesses.** Full-dataset in-RAM materialization in export/download paths (Unit 09); unclosed per-call gRPC channels across ~8 worker modules; best-effort memory-limit enforcement; sync gRPC on the event loop (Unit 09); unbounded `BuildNotificationHub` growth (Unit 04); fixed 1s no-backoff WebSocket reconnect (Unit 15).
6. **Maintainability debt.** Several 2,000+ line components (ChatPanel 2,640; ScheduleManager 2,043; DatasourceConfigPanel 1,906) and a 2,611-line analysis editor page (Units 18, 20); dead duplicated modules in the worker domain (Unit 10); hand-maintained frontend enum tables that can drift from `enums.proto` (Unit 14).

### What is healthy

- Tenant-schema isolation is sound: validated namespace names → `search_path` (Unit 04).
- No XSS sinks found in the frontend; the sole `{@html}` path is DOMPurify-sanitized; chart teardown is clean (Units 18, 20).
- Docker images are non-root, pinned, multi-stage; prod env templates contain placeholder secrets only (Unit 13).
- Protocol definitions pass `buf lint` with thorough protovalidate rules and reserved-field hygiene (Unit 14).
- Engine subprocess zombie/cleanup handling is strong (Unit 09).

---

## Priority fix list

1. Redact credentials everywhere they are persisted or echoed (datasource configs, API/MCP/settings/subscriber responses); encrypt at rest using `SETTINGS_ENCRYPTION_KEY`.
2. Add ownership/auth checks to analysis CRUD, engine-run delete, namespace/bucket creation, healthcheck CRUD, chat sessions, and `/ws/engines`; add server-side route protection (SvelteKit server hooks).
3. Replace the UDF substring blacklist with real isolation (the containerized engine boundary) or remove `exec` entirely.
4. Fix the Excel-bounds `s3://` local-path bug and the audit-log dedupe/flush logic.
5. Make `AUTH_REQUIRED=true` the default in `config/env/prod.env` (source prod path currently ships auth off).
6. Close gRPC channel leaks; move sync gRPC off the event loop; bound `BuildNotificationHub`.

---

## Detailed findings by unit


---


---


---


---


---


---


---


---


---


---


---


---


---


---


---


---


---


---


---


---

# Unit 01: Backend entry & API surface

### packages/backend/main.py
- **Verdict:** issues found
- **Findings:**
  - [high] Path traversal risk in static file catch-all `serve_static_or_index` (main.py:359-370): `frontend_build_dir / full_path` uses the raw URL path parameter without normalization. A request like `GET /..%2f..%2f..%2fetc%2fpasswd` decodes to `full_path='../../../etc/passwd'`, and `FileResponse` will serve files outside `packages/frontend/build`. Should resolve and verify the final path stays under `frontend_build_dir`.
  - [medium] `namespace_middleware` (main.py:231-239) calls `run_settings_db(register_namespace, raw)` on every request with a client-controlled `X-Namespace` header, doing a synchronous DB write per request via `asyncio.to_thread`. Any unauthenticated client can create arbitrary namespaces by sending random header values (unbounded resource creation), and every request pays a DB round-trip even when the namespace already exists.
  - [low] Readiness endpoint returns raw exception text to clients (`checks['database'] = f'error: {e!s}'`, main.py:315, 325, 337) — minor internal detail disclosure on an unauthenticated endpoint.
  - [low] `_guard_runtime_workers` (main.py:100-105) is only enforced in the `if __name__ == '__main__'` block (main.py:386); launching via `uvicorn main:app --workers N` bypasses the multi-worker safety check entirely.
  - [low] `enabled, token = run_settings_db(_check_bot_enabled)` (main.py:197) blocks the event loop directly while sibling startup calls are correctly wrapped in `asyncio.to_thread` (main.py:169-172).
  - Note: CORS uses explicit origin list + credentials (main.py:242-255) — OK provided `settings.cors_origins_list` never contains `*`.

### packages/backend/api/__init__.py
- **Verdict:** ok

### packages/backend/api/router.py
- **Verdict:** ok

### packages/backend/api/v1/__init__.py
- **Verdict:** ok

### packages/backend/api/v1/router.py
- **Verdict:** issues found
- **Findings:**
  - [low] No global auth dependency on the v1 router (api/v1/router.py:23-44); authentication is delegated entirely to per-module routers. Any module router added without its own `dependencies=[Depends(...)]` is silently public — no defense-in-depth at the API surface. Verify each module applies auth consistently.

### packages/backend/backend_grpc/server.py
- **Verdict:** issues found
- **Findings:**
  - [high] `PersistEngineSnapshot` (server.py:1330-1345) is missing the `@_run_async_handler_in_thread` decorator that every other RPC has, so `_require_internal_token` (server.py:146-151) never runs for it: any client that can reach the insecure gRPC port can write arbitrary engine snapshots (`worker_id`, `namespace`, statuses) into the DB and trigger API notifications without authentication. It also executes blocking DB I/O (`run_settings_db`, server.py:1343) directly on the gRPC aio event loop.
  - [medium] Internal token compared with plain `!=` (server.py:150) instead of `hmac.compare_digest` — timing side channel on the shared internal secret.
  - [medium] Every claim/poll RPC iterates all namespaces and runs `reconcile_expired_build_jobs` + claim query per namespace (server.py:571-594, 626-654, 1205-1234): O(namespaces × queries) DB work per worker poll tick; scales poorly as namespaces/workers grow.
  - [low] `_run_async_handler_in_thread` (server.py:154-171) creates and destroys a fresh asyncio event loop per RPC call in a worker thread; functional but wasteful under load.
  - [low] Non-`_ThreadedRpcAbort` exceptions from threaded handlers escape the wrapper uncaught (server.py:166-169), surfacing as bare `UNKNOWN` gRPC status with no logging of the traceback.
  - [low] `GetEngineRunState` parses `cancelled_at` with `datetime.fromisoformat` (server.py:1155) without guarding against malformed strings persisted in `result_json` — raises and fails the whole RPC.
  - [low] Manual session lifecycle boilerplate (`session_gen = get_db(); session = next(...); ... session.close(); session_gen.close()`) duplicated in ~12 handlers (e.g. server.py:728-754, 941-959, 1251-1275) instead of a context manager; easy to misuse and bypasses any post-yield cleanup in `get_db`.
  - Note: gRPC server binds an insecure port (server.py:1603) protected only by the metadata token sent in plaintext — acceptable only if `internal_grpc_host` is loopback/isolated network.

### packages/backend/database/alembic.ini
- **Verdict:** ok
- **Findings:** boilerplate config; DB URL correctly delegated to `backend_core.config.settings` (alembic.ini:76-80) so no secret in the ini.

### packages/backend/database/README.md
- **Verdict:** ok

### packages/backend/database/alembic/script.py.mako
- **Verdict:** ok

### packages/backend/database/alembic/env.py
- **Verdict:** issues found
- **Findings:**
  - [medium] `_TENANT_TABLES` (env.py:46-65) is missing `analysis_favorites` and `notification_delivery_receipts`, both created by migration 0002_runtime_tenant (0002_runtime_tenant.py:91-96, 273-280). Since `_include_object` filters on this set (env.py:90-94), autogenerate will never diff those two tables — future model drift there goes undetected.
  - [low] Schema name interpolated directly into SQL via f-string (`CREATE SCHEMA IF NOT EXISTS "{schema}"`, `SET search_path TO "{schema}"`, env.py:121-122). Value originates from local config, not user input, but nothing validates it — a quote-bearing value breaks or injects.
  - Note: credentials come from `settings.database_url` at runtime (env.py:35, 115); no hardcoded secrets. Good.

### packages/backend/database/alembic/versions/0001_runtime_public.py
- **Verdict:** issues found
- **Findings:**
  - [medium] `app_settings` stores secrets as plaintext string columns: `smtp_password`, `telegram_bot_token`, `openrouter_api_key`, `openai_api_key` (0001_runtime_public.py:39-44). No encryption at rest; anyone with DB read access (or any backup/dump) obtains live API keys and bot tokens.
  - Scope guard pattern (`_scope() != 'public'` → no-op, 0001_runtime_public.py:30-32) is consistent and correct.

### packages/backend/database/alembic/versions/0002_runtime_tenant.py
- **Verdict:** issues found
- **Findings:**
  - [medium] `telegram_subscribers.bot_token` stored plaintext per subscriber row (0002_runtime_tenant.py:351), same secret-at-rest concern as 0001.
  - [low] `datasources.config` JSON column (0002_runtime_tenant.py:39) holds connection details for data sources (likely credentials) also unencrypted.
  - Otherwise structurally sound: FKs use `ondelete='CASCADE'` consistently, indexes match query patterns, downgrade reverses creation order correctly.


---

# Unit 02: backend_core root files (first half)

### packages/backend/backend_core/__init__.py
- **Verdict:** ok
- Empty init file.

### packages/backend/backend_core/ai_clients.py
- **Verdict:** issues found
- [low] ai_clients.py:78 — 4xx error text from provider response is embedded in AIError message (`exc.response.text[:500]`); may leak provider-side details to end users if surfaced verbatim. Minor.
- [low] ai_clients.py:62-81 — `_retry_request` retries immediately with no backoff/jitter; also `httpx.RequestError` other than ConnectError (e.g. ReadError, RemoteProtocolError) is uncaught and propagates as raw httpx exception instead of AIError, inconsistent error contract.
- [low] ai_clients.py:33-35 — `require_ai_provider` accepts any `int` including bool; `ai_provider_name(True)` would raise ValueError but the isinstance check treats bools as proto enum ints; cosmetic.
- Otherwise clean: no secrets logged, timeouts set, API keys only in headers.

### packages/backend/backend_core/analysis_cycles.py
- **Verdict:** ok
- Cycle detection is DFS with visited-set; correct for self-cycle via explicit check at line 35. Recursion depth bounded by graph size; fine for expected scale.

### packages/backend/backend_core/auth_config.py
- **Verdict:** issues found
- [medium] auth_config.py:84-102 — `_validate_security_requirements` instantiates `SharedSettings()` inside a model validator at import time (module-level `settings = AuthSettings()` at line 105). This couples auth config load to full shared Settings parse; if shared settings are invalid, the failure surfaces as a confusing ValueError from AuthSettings, and shared env is re-parsed on every AuthSettings construction. Maintainability concern.
- [low] auth_config.py:92-99 — inline `import warnings` in validator; minor style.
- Security posture good: placeholder password/key checks enforced in prod mode (lines 89-101).

### packages/backend/backend_core/auth_exceptions.py
- **Verdict:** ok
- Trivial exception definitions, no logic.

### packages/backend/backend_core/build_commands.py
- **Verdict:** ok
- Claim-token/lease-generation guarded transitions with row locking via `lock_active_job_claim`; consistent None-return handling on lost claims.
- [low] build_commands.py:58-104 vs 122-124 — `fail_build_job` synthesizes a failure event when run status is non-terminal while `finalize_build_job` returns None for the same condition; asymmetric but appears intentional (fail path must force terminal state). `FailedBuildResult.latest_sequence` is None when run already terminal — callers must tolerate.

### packages/backend/backend_core/build_jobs_service.py
- **Verdict:** issues found
- [low] build_jobs_service.py:345-355 — `queued_job_count` loads all matching rows into Python and does `len(...all())` instead of `SELECT count(*)`; unbounded memory/latency as queue grows.
- [low] build_jobs_service.py:358-374 — `release_worker_jobs` requeues rows without `FOR UPDATE` locking and commits mid-function (line 372); races with `claim_next_job` are mostly prevented by status conditions in claim's conditional update, but the read-modify-write here can resurrect a job another scheduler just transitioned (lost update window between select at 366 and commit at 372).
- [low] build_jobs_service.py:332 — `session.expire_all()` in `stage_job_cancelled` expires the entire session identity map to re-read one row; heavy-handed, can surprise callers holding other objects.
- [low] build_jobs_service.py:119-121 — `claim_next_job` mixes explicit `rollback()`/`commit()` inside a service function rather than using the `committed` decorator used elsewhere; inconsistent transaction ownership.
- Core lease logic is otherwise sound: conditional updates keyed on owner+token+generation (lines 194-207, 279-298), DB clock via `_database_now`, SKIP LOCKED claiming.

### packages/backend/backend_core/claiming.py
- **Verdict:** issues found
- [low] claiming.py:10-13 — `with_for_update_skip_locked` silently degrades to no lock on non-PostgreSQL dialects; correctness then relies entirely on the conditional-update CAS in `claim_by_lease_owner`. Acceptable given the CAS, but the silent fallback deserves a comment/log.
- Otherwise ok: optimistic claim via conditional UPDATE + rowcount check is race-safe.

### packages/backend/backend_core/time.py
- **Verdict:** ok
- Trivial helpers.

### packages/backend/backend_core/build_runs_service.py
- **Verdict:** issues found
- [medium] build_runs_service.py:675-692 — `mark_running_builds_orphaned` does an unlocked read-modify-write over all RUNNING runs and commits mid-function (line 692); at startup recovery this can race with workers that are still alive and mid-transition. Also line 682 dereferences `run.started_at` without a None check (`run.started_at.tzinfo`) — AttributeError if started_at is nullable.
- [low] build_runs_service.py:305-306 — `list_build_runs` calls `session.refresh(run)` in a loop after fetching → N+1 queries per listing request.
- [low] build_runs_service.py:491-494 — `get_latest_sequence` returns `-1` when `next_event_sequence` is 0 (fresh run with no events) due to the unconditional `- 1`; callers expecting a non-negative latest sequence will see -1.
- [low] build_runs_service.py:342, 363 — repeated `session.expire_all()` calls expire the whole identity map; heavy-handed and can surprise callers holding other pending objects.
- [low] build_runs_service.py:318-338 — `_cas_update_build_run` performs raw `session.rollback()`/`commit()` inside a shared helper; any caller-side pending changes outside `run` are silently discarded on CAS failure (rollback at 328).
- Core event staging is solid: row locked via `with_for_update` + `populate_existing` (line 413), monotonic sequence under lock, generation guards (lines 416-419).

### packages/backend/backend_core/compute_requests_service.py
- **Verdict:** issues found
- [low] compute_requests_service.py:424-426 — `queued_request_count` loads all queued rows to count them in Python instead of `SELECT count(*)`; same pattern as build_jobs_service.queued_job_count.
- [low] compute_requests_service.py:429-437 — `cleanup_completed_requests` loads all expired rows and deletes one-by-one in ORM instead of a bulk `DELETE ... WHERE completed_at < cutoff`; unbounded memory for large backlogs.
- [low] compute_requests_service.py:152-196 — exhausted-request sweep runs on every claim poll and commits mid-function (line 196); if the subsequent claim fails and rolls back (line 234), the rollback is fine because of the earlier commit, but the mixed commit/rollback flow makes partial-failure reasoning hard.
- [low] compute_requests_service.py:352-353 vs 393-395 — in `mark_request_failed`, `error_message` is set before `_validate_response_envelope` may raise ValueError, leaving the session dirty with a half-mutated locked row if validation fails (no rollback in that path); caller's exception handler must roll back. In `mark_request_completed`, status is likewise set before validation.
- Lease/claim logic otherwise mirrors build_jobs_service and is race-safe (conditional CAS at lines 214-232).

### packages/backend/backend_core/build_event_service.py
- **Verdict:** ok
- Thin wrapper: persists event via `append_build_event` (committed) then publishes hub notification after commit. Note the notification is published even though outbox also enqueues one inside staging (build_runs_service.py:458) — potential duplicate notification path, but hub publish is in-process fan-out, likely intentional.

### packages/backend/backend_core/config.py
- **Verdict:** issues found
- [medium] config.py:158-159 — `object_store_access_key`/`object_store_secret_key` default to hardcoded `'rustfsadmin'` dev credentials. Combined with the non-empty validation at lines 327-330, prod deployments that forget to set them silently run on known default credentials. No placeholder check analogous to `_PLACEHOLDER_ENCRYPTION_KEYS` is applied in prod mode.
- [low] config.py:47-49 — default DATA_DIR falls back to a temp directory (`tempfile.gettempdir()/data-forge`); data silently lands in /tmp if DATA_DIR unset — surprising persistence location and shared-host writable-by-all concern.
- [low] config.py:234-237 — `_ensure_dirs` validator creates directories as a side effect of settings parsing; import-time filesystem mutation.
- [low] config.py:343-349 — module-level side effect `_configure_runtime_ipc()` at import; makes importing config non-idempotent in effect and harder to test.
- Good practices elsewhere: DATABASE_URL required + scheme-checked (256-265), numeric bounds table, lock interval sanity checks.

### packages/backend/backend_core/data_plane_client.py
- **Verdict:** issues found
- [medium] data_plane_client.py:54-60, 230-231 — gRPC channel is `insecure_channel` while sending `x-internal-token` auth metadata; on any non-loopback deployment the internal API token traverses plaintext. No TLS option exists.
- [low] data_plane_client.py:49-62 — client never closes `self._channel`; no `close()`/context-manager support → channel leak if clients are created per-request.
- [low] data_plane_client.py:50-53 — default timeout 120s for every call including trivial ones (Exists, ClassifyUrl); no per-call timeout differentiation.
- Error wrapping (`_call`, lines 233-239) is clean; no secrets logged.

### packages/backend/backend_core/database.py
- **Verdict:** issues found
- [verified-safe] database.py:98, 107, 246, 251 — f-string SQL with schema names is safe because `namespace_database_schema` routes through `validate_namespace_name` (namespace_storage.py:26-30), which enforces `[a-z0-9][a-z0-9_-]{1,61}[a-z0-9]` — no quote/injection chars possible.
- [low] database.py:161-166 — `get_db` yields a Session without any commit/rollback in finally; callers must commit explicitly (project convention via `committed` decorator), but an exception mid-request leaves the session to be closed without rollback being explicit — SQLAlchemy handles this on close, so informational only.
- [low] database.py:146-148 — tenant engine's checkout listener calls `get_namespace()` from a ContextVar at connection checkout; connections are pooled across contexts, correctness relies on every checkout happening inside the right context (namespace_connection re-applies search_path explicitly at line 157, which mitigates). Subtle coupling worth documenting.
- [low] database.py:305-312 — `_init_namespace_db` double-checked locking releases `_initialized_namespaces_lock` before running init (line 312), then re-acquires in `_init_namespace_db_unlocked`; concurrent first-access by two threads both run migration path sequentially under advisory lock — correct but only because of the PG advisory lock; non-PG dialects would race.
- Bootstrap/advisory-lock design (`run_settings_connection_locked`, 272-281) is sound.

### packages/backend/backend_core/dependencies.py
- **Verdict:** issues found
- [low] dependencies.py:12 — imports private helper `_resolve_session_token` from `modules.auth.dependencies`; cross-module reach into a private name, fragile coupling.
- [low] dependencies.py:38-45 — `resolve_lock_owner_id` silently falls back to the default user when auth is disabled; correct for local mode, but an invalid token with auth disabled still yields owner identity (token ignored after failed validation) — acceptable given auth_required=False semantics.
- Otherwise ok.

### packages/backend/backend_core/docker_healthcheck.py
- **Verdict:** ok
- Small; heartbeat freshness check. Line 28 assumes `last_heartbeat_at` non-null (AttributeError if nullable and unset) — minor, likely NOT NULL in schema.

### packages/backend/backend_core/engine_live.py
- **Verdict:** issues found
- [medium] engine_live.py:32-45 — lost-wakeup race in `wait_for_namespace`: the version check (lines 33-37) and future registration (lines 40-41) happen in two separate lock acquisitions. A `publish_namespace` occurring between them pops an empty waiter list, so the newly registered waiter misses that update and blocks until the *next* publish. Check-and-register must be atomic.
- [low] engine_live.py:15-19 — `add_watcher`/`remove_watcher` are dead stubs (`del namespace, websocket`); either remove or implement.

### packages/backend/backend_core/engine_instances_service.py
- **Verdict:** issues found
- [medium] engine_instances_service.py:152 — in `list_engine_projection`, when a newer row wins on `last_seen_at` it is stored as `latest[row.analysis_id] = row` instead of `latest[key] = row`. The dedup map is keyed by `_row_identity_key` everywhere else (lines 144-147, 159, 164); this typo pollutes the map with an analysis_id-keyed entry, so (a) the same identity can appear twice in results and (b) later comparisons for that identity key miss the newer row. Correctness bug in engine list deduplication.
- [low] engine_instances_service.py:99-103 — `persist_engine_snapshot` commits once per status upsert plus a final stop-marking commit; a crash mid-snapshot leaves partial state (eventually consistent via next snapshot, but non-atomic).
- Upsert race is well handled: IntegrityError → rollback → re-get → re-apply (lines 85-94).

### packages/backend/backend_core/engine_runs_utils.py
- **Verdict:** issues found
- [critical] engine_runs_utils.py:11 — `except TypeError, ValueError:` is Python 2 syntax and a hard SyntaxError on Python 3; the module fails to import entirely (`SyntaxError: invalid syntax`, verified with `ast.parse`). Should be `except (TypeError, ValueError):`. Anything importing this module (directly or transitively) crashes at import time.

### packages/backend/backend_core/engine_run_commands.py
- **Verdict:** ok
- Thin `committed` wrappers around engine_runs_service staging functions.

### packages/backend/backend_core/json_utils.py
- **Verdict:** issues found
- [low] json_utils.py:4-5 — `copy_json_dict` is a shallow copy (`dict(value)`); nested structures are shared with the source. For "copy" semantics used on persisted JSON blobs (e.g. build_runs_service), later mutation of nested lists/dicts would alias across rows. Also silently returns `{}` for non-dict input instead of raising — masks type errors.

### packages/backend/backend_core/engine_runs_service.py
- **Verdict:** issues found
- [critical] engine_runs_service.py:512 — `except TypeError, ValueError:` — same Python 2-only syntax as engine_runs_utils.py:11; hard SyntaxError, module unimportable (verified via ast.parse). Additionally the module imports the already-broken `engine_runs_utils` at line 29, so it fails regardless.
- [low] engine_runs_service.py:199 — `stage_cancel_engine_run` dereferences `run.created_at.tzinfo` without a None check; AttributeError if created_at is ever NULL.
- [low] engine_runs_service.py:305-308 — when a run is terminal and the requested status differs, the update is silently dropped with only a warning log and the current state returned; callers can't distinguish "applied" from "rejected" except by inspecting the returned status.
- Namespace isolation is consistently enforced (`get_namespace()` filters at lines 167, 239, 299, 409, 454-458, 692, 726) — good multi-tenant hygiene; row locking via `with_for_update` on mutations.

### packages/backend/backend_core/error_handlers.py
- **Verdict:** ok
- Clean design: code→status map, sanitized validation errors, generic handler never leaks internals (lines 167-173).
- [low] error_handlers.py:102-103 — raw `ValueError` messages are passed straight into HTTP detail (`str(exc)`); internal ValueErrors (e.g. from settings or proto parsing) would surface their text to clients. Usually acceptable since ValueErrors here are validation-oriented.

### packages/backend/backend_core/http.py
- **Verdict:** issues found
- [low] http.py:16-21 — process-wide shared `httpx.Client` with no default timeout; any caller that forgets `timeout=` can hang a worker thread indefinitely (ai_clients.py sets its own, but the shared helpers don't enforce one).
- [low] http.py:36-47 — `_ASYNC_CLIENTS` grows per event loop and entries are only removed by `close_clients()`; long-lived processes creating/disposing loops (tests, scripts) leak closed-loop entries until shutdown. The `existing_loop is loop` guard prevents wrong reuse but not accumulation.
- [low] http.py:61-62 — `sync_client.close()` is a blocking call executed inside `async def close_clients()`; blocks the event loop briefly.

### packages/backend/backend_core/exceptions.py
- **Verdict:** ok
- Well-organized hierarchy; error codes coerced/validated against proto enum (lines 8-14). No issues.

### packages/backend/backend_core/iceberg_catalog.py
- **Verdict:** ok
- Bootstrap race handled correctly: per-URI in-process cache + PG advisory lock + duplicate-table retry (lines 37-54).
- [low] iceberg_catalog.py:12-13, 38 — the bootstrapped-URI cache is per-process only and never invalidated on catalog drops; if `iceberg_tables` is dropped at runtime, a process that already bootstrapped will skip the lock but `load_catalog` re-creates tables anyway, so benign.

### packages/backend/backend_core/datasource_delete_service.py
- **Verdict:** issues found
- [medium] datasource_delete_service.py:51-57 — `finalize_delete` runs external storage deletion (`cleanup_datasource_storage`) inside the `@committed` DB transaction. If the DB commit fails after objects were deleted, the row survives pointing at deleted storage; if cleanup raises partway (e.g. FileError from `_delete_managed_prefix`), the DB delete rolls back while some objects are already gone. No two-phase/outbox pattern for this external side effect.
- [low] datasource_delete_service.py:26-39 — `request_delete` is an unlocked read-modify-write, but it's idempotent (flag set), so benign.

### packages/backend/backend_core/datasource_storage.py
- **Verdict:** issues found
- [low] datasource_storage.py:16-29 — `delete()` performs multiple independent remote deletions sequentially with no aggregation; a failure midway leaves partial cleanup and aborts the rest (catalog table dropped but prefix/file retained or vice versa). Mostly recoverable on retry since S3 deletes are idempotent and `table_exists` guards the drop.
- [low] datasource_storage.py:41-47, 59-65 — raw exception text embedded in `FileError.details['error']`; surfaced to API clients via error handler details field — minor info exposure.
- [low] datasource_storage.py:35, 53, 81 — `client_from_settings()` constructs a new gRPC channel per call (see data_plane_client.py finding: channels never closed); three channels leaked per delete of an Iceberg datasource.



---

# Unit 03: backend_core root files (second half)

### packages/backend/backend_core/live_hubs.py
- **Verdict:** ok
- **Findings:**
  - [low] live_hubs.py:22,53,80,108 — `loop.call_soon_threadsafe` raises `RuntimeError` if the target event loop is already closed (e.g. shutdown while waiters pending); exceptions propagate into `publish()`/`clear()` caller thread. Edge case only during shutdown.

### packages/backend/backend_core/logging.py
- **Verdict:** issues found
- **Findings:**
  - [medium] logging.py:599-607 — `redact_logged_body` only redacts JSON bodies on sensitive paths; non-JSON bodies (e.g. form-urlencoded logins) hit the `json.JSONDecodeError` branch and are persisted verbatim to `request_logs.request_json`, so credentials submitted outside JSON are stored in plaintext in the DB.
  - [low] logging.py:445 — `int(request.headers.get('content-length', 0))` raises `ValueError` on a malformed Content-Length header, producing an unhandled exception in middleware before the app runs (client-triggered 500/connection reset).
  - [low] logging.py:146-155 — `_client_ip`: when the XFF list has fewer entries than `trusted_proxy_hops + 1`, it falls back to `parts[0]`, i.e. the client-spoofable leftmost value; also IPv6 addresses bypass the truncation/anonymization at logging.py:551-554 entirely.
  - [low] logging.py:333-334 — with overflow policy `block`, `queue.put` blocks request-handler threads indefinitely if the DB is unreachable and the queue fills; no timeout or circuit breaker.
  - [low] logging.py:188-189 — `DatabaseLogWriter.__init__` connects to Postgres synchronously; if the DB is down at startup, `configure_logging()` raises and blocks app boot (no retry).
  - [low] logging.py:543-546 vs 571-572 — duplicated `if not self.writer` checks in `_log_request`; the second is dead code (maintainability nit).
  - [low] logging.py:494-496,569 — only the first response chunk is captured and `chunk_index` is hardcoded to 0; larger responses are silently truncated in logs without indication beyond missing chunks.

### packages/backend/backend_core/migrations.py
- **Verdict:** ok
- **Findings:**
  - [low] migrations.py:97 — f-string interpolation of `schema` into SQL (`SELECT version_num FROM "{schema}".alembic_version`); safe today because schemas derive from `validate_namespace_name` (strict regex) or the constant `df$tenant$public`, but it is an injection-shaped pattern that breaks silently if validation loosens.
  - [low] migrations.py:71-75 — check-then-create race on `CREATE DATABASE`; concurrent boot of two instances can raise a duplicate-database error. Single-instance assumption.

### packages/backend/backend_core/namespace.py
- **Verdict:** ok
- **Findings:**
  - [low] namespace.py:52-62 — `namespace_paths()` performs filesystem mkdir side effects on every read call; surprising for a getter but harmless (exist_ok).

### packages/backend/backend_core/namespaces_service.py
- **Verdict:** ok

### packages/backend/backend_core/namespace_storage.py
- **Verdict:** ok

### packages/backend/backend_core/notification_delivery.py
- **Verdict:** issues found
- **Findings:**
  - [low] notification_delivery.py:71-76 — Telegram bot token may come from the delivery payload (`payload['bot_token']`) and is embedded in the URL path (`/bot{token}`); any exception/traceback from httpx will include the full URL with the secret. Prefer header/query handling with redaction or drop the payload-token override.
  - [low] notification_delivery.py:51-53 — same string set as both plain-text and HTML alternative parts; HTML entities in plain body are rendered literally in the text part (cosmetic).

### packages/backend/backend_core/object_store_probe.py
- **Verdict:** ok

### packages/backend/backend_core/proxy.py
- **Verdict:** ok
- **Findings:**
  - [low] proxy.py:17-19 — same fallback-to-leftmost-XFF weakness as logging.py:150-152: when the header has fewer entries than `trusted_proxy_hops + 1`, the client-spoofable first entry is trusted. Also duplicated logic with `_client_ip` in logging.py (maintainability).

### packages/backend/backend_core/public_schema.py
- **Verdict:** ok

### packages/backend/backend_core/runtime_ipc.py
- **Verdict:** issues found
- **Findings:**
  - [critical] runtime_ipc.py:97 — `except asyncio.CancelledError, psycopg.Error:` is invalid Python 3 syntax (old-style except clause); verified with `ast.parse` → SyntaxError. The module cannot be imported at all, so every importer of runtime IPC (notify/listen paths) breaks at import time. Must be `except (asyncio.CancelledError, psycopg.Error):`.
  - [low] runtime_ipc.py:187-195 — `pg_notify` payload limit is 8000 bytes; large JSON payloads raise from Postgres on both the initial attempt and the retry, propagating to callers with no size guard.
  - [low] runtime_ipc.py:163-175 — cached notify connection shared across threads without health check beyond `.closed`; a broken-but-open connection is only detected after the first execute fails (retry covers it, acceptable).

### packages/backend/backend_core/runtime_notifications.py
- **Verdict:** ok

### packages/backend/backend_core/runtime_workers_service.py
- **Verdict:** ok
- **Findings:**
  - [low] runtime_workers_service.py:85-91 — `worker_available` iterates all workers in reverse and returns True on the first non-reclaimable one; correct but O(n) with full row hydration where an EXISTS/aggregate query would do (minor).

### packages/backend/backend_core/secrets.py
- **Verdict:** ok
- **Findings:**
  - [low] secrets.py:29-31 — encryption key derived as unsalted SHA-256 of the key material; fine for a locally-provided high-entropy key, but no KDF hardening if someone sets a low-entropy passphrase. Documented behavior, not a bug.
  - [low] secrets.py:50 — `is_masked_secret` treats any all-`*` string as masked; a legitimate secret consisting solely of `*` would be silently treated as "unchanged" on save paths that use this check.

### packages/backend/backend_core/settings_schemas.py
- **Verdict:** ok

### packages/backend/backend_core/settings_projection.py
- **Verdict:** issues found
- **Findings:**
  - [medium] settings_projection.py:108-111,124-132 — resolved-settings cache is keyed by `id(get_settings_engine())`; CPython can reuse memory addresses after an engine is garbage-collected, so a new engine could collide with a stale cache entry and serve decrypted secrets/settings from the previous engine's state. A weakref or explicit generation counter would be safe.
  - [low] settings_projection.py:121-133 — check-then-populate cache race: two threads can both miss and both run `run_settings_db(_load_resolved_snapshot)`; last write wins, benign duplicate DB read.

### packages/backend/backend_core/settings_store.py
- **Verdict:** ok
- **Findings:**
  - [low] settings_store.py:60-61 — `_warn_bootstrap_secret_missing` calls `logging.warning` on the root logger instead of the module `logger` defined at line 20 (inconsistent, bypasses app log config).

### packages/backend/backend_core/smtp.py
- **Verdict:** ok
- **Findings:**
  - [low] smtp.py:18-24 — on non-465 ports without STARTTLS extension, credentials are sent in plaintext with no warning; acceptable fallback but silent.

### packages/backend/backend_core/telegram_store.py
- **Verdict:** issues found
- **Findings:**
  - [medium] telegram_store.py:21,29,48,165 — Telegram bot tokens are stored and queried as plaintext DB columns (`TelegramSubscriber.bot_token`), unlike the encrypted secret handling used for the same class of credential in settings_store.py/secrets.py. Any DB read path or log of these rows exposes live tokens.
  - [low] telegram_store.py:36-55 — `add_subscriber` is check-then-insert with no unique-constraint handling; concurrent webhook events for the same chat can raise IntegrityError.

### packages/backend/backend_core/telegram_schemas.py
- **Verdict:** issues found
- **Findings:**
  - [high] telegram_schemas.py:14 — `SubscriberResponse` includes the raw `bot_token` field and is used directly as an API response model (`response_model=list[SubscriberResponse]` in modules/telegram/routes.py:38), exposing live Telegram bot tokens over the API. Should be masked or omitted from response schemas.

### packages/backend/backend_core/time.py
- **Verdict:** ok

### packages/backend/backend_core/transactions.py
- **Verdict:** ok

### packages/backend/backend_core/transitions.py
- **Verdict:** ok

### packages/backend/backend_core/validation.py
- **Verdict:** ok

### packages/backend/backend_core/websocket.py
- **Verdict:** ok

### packages/backend/backend_core/sqlmodel_typing.py
- **Verdict:** ok

### packages/backend/backend_core/lease_observability.py
- **Verdict:** ok

### packages/backend/backend_core/runtime_outbox_service.py
- **Verdict:** issues found
- **Findings:**
  - [low] runtime_outbox_service.py:164-167 — `pending_event_count` hydrates every matching row and takes `len()` instead of a SQL `count()`; unbounded memory/time as the outbox grows.
  - [low] runtime_outbox_service.py:107-116 — at-least-once delivery: an email/Telegram message is sent before the receipt commit (lines 109-129); a crash between send and receipt commit re-sends on retry. Inherent outbox trade-off, but there is no idempotency key passed to the delivery layer to dedupe downstream.
  - [low] runtime_outbox_service.py:113-114 — `str(exc)` of arbitrary exceptions (which can include connection strings/URLs from httpx errors, e.g. Telegram bot token in URL) is persisted into `last_error` and surfaced via the outbox table.


---

# Unit 04: backend_core domain & persistence

Scope note: all 68 `.py` files under `packages/backend/backend_core/domain/` and `packages/backend/backend_core/persistence/` were read in full. Tenant isolation is implemented as Postgres schema-per-namespace selected via `SET search_path` (`backend_core/database.py:91-157`, `database/alembic/env.py:113-129`); none of the models declare a `schema=`, so isolation correctness depends entirely on that runtime convention. Namespace names used to build schema identifiers are regex-validated (`^[a-z0-9][a-z0-9_-]{1,61}[a-z0-9]$`, `backend_core/namespace_storage.py:9`), so the f-string-interpolated `"SET search_path TO \"{schema}\""` statements are not injectable via user input.

### packages/backend/backend_core/domain/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/domain/analysis/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/domain/analysis/models.py
- **Verdict:** issues found
- **Findings:**
  - [low] Lines 16-19: enum members are assigned after class definition (ClassVar pattern). Properties like `is_active` in sibling enums reference class attributes lazily, which works, but any use of these members inside a class body at definition time would raise `AttributeError`; the pattern is repeated in ~20 files and is fragile but currently consistent.
  - [low] Line 9-13: `AnalysisStatus` has no terminal-state helper (unlike `BuildRunStatus.is_terminal`); status transitions are not modeled anywhere in the domain layer, so invalid transitions (e.g. DRAFT → COMPLETED) are only preventable at call sites.

### packages/backend/backend_core/domain/analysis/pipeline_types.py
- **Verdict:** ok
- **Findings:**
  - [low] Lines 22-23, 101-102: `from_dict` silently coerces missing `id`/`type` to empty strings instead of rejecting malformed persisted pipelines; corrupt rows parse "successfully" into degenerate objects and fail later with confusing errors.

### packages/backend/backend_core/domain/analysis/step_types.py
- **Verdict:** issues found
- **Findings:**
  - [low] Lines 187-192: `_definition_for` does a linear scan over all ~37 fields on every lookup, and helpers like `is_step_type`/`normalize_step_type` (lines 200-218) call it per step during pipeline validation (`compute/schemas.py:136`). O(n) per step per request; a dict index built once would be trivial.
  - [low] Lines 240-247: `timing_key` regex `^(?P<base>.+?)_(?P<index>\d+)$` misparses legitimate base keys ending in `_<digits>` (e.g. a custom key `step_2` becomes base `step`, label `Step 2`); acceptable for its current timing-label use only.

### packages/backend/backend_core/domain/api_enums.py
- **Verdict:** issues found
- **Findings:**
  - [medium] Lines 40-43: `__eq__` returns `False` for any non-str operand, including proto enum numbers, so `member == enums_pb2.X` is silently `False` even when the numbers match; callers must remember to use `.number`. Asymmetric with `require()` which accepts ints (line 75-79).
  - [low] Lines 83-89: `read(value, default=...)` returns the default for *invalid non-None* values too (not just None), silently coercing garbage data to a valid member (relied upon by `BuildStatus.coerce` etc.).
  - [low] Lines 28-34: `__new__` mutates class-level dicts keyed by number/token without duplicate detection; constructing the same member twice (e.g. accidental re-execution of an assignment block) silently overwrites registries rather than erroring.

### packages/backend/backend_core/domain/build_jobs/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/domain/build_jobs/live.py
- **Verdict:** ok

### packages/backend/backend_core/domain/build_jobs/models.py
- **Verdict:** ok

### packages/backend/backend_core/domain/build_runs/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/domain/build_runs/models.py
- **Verdict:** ok

### packages/backend/backend_core/domain/build_runs/live.py
- **Verdict:** issues found
- **Findings:**
  - [medium] Lines 19-20, 26-27: `_latest_by_build` / `_latest_by_namespace` grow without bound — entries are never evicted per build; `clear()` (line 76) is only invoked from tests. Long-running API processes accumulate one entry per build forever.
  - [low] Lines 36-51: double-checked locking is correct (lost-wakeup safe because the future is registered under the same lock re-check), but `wait_for_build` compares `latest_sequence > last_sequence` while `wait_for_namespace` uses version counters maintained separately (line 28); two independent monotonic counters for the same notification stream is easy to misuse.

### packages/backend/backend_core/domain/compute/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/domain/compute/base.py
- **Verdict:** ok

### packages/backend/backend_core/domain/compute/schemas.py
- **Verdict:** issues found
- **Findings:**
  - [low] Lines 502-503, 569-570, 616-617: `coerce()` classmethods map any unknown/garbage value to a default (`SUCCESS`/`QUEUED`/`INFO`) via `ApiEnumValue.read`; combined with the `read()` behavior in api_enums.py this silently masks corrupted persisted statuses instead of surfacing them.
  - [low] Lines 403-411: `ExportRequest.validate_result_id` depends on field-definition order (`info.data` contains `destination` only because `result_id` is declared last); reordering fields breaks validation silently.
  - [low] Lines 545-549: `BuildRequest.pipeline_payload` merges `tab_id` into the pipeline dict post-validation; if a tab payload already contained a `tab_id` key it would be overwritten (currently unreachable given `AnalysisPipelineTab` shape, but implicit).

### packages/backend/backend_core/domain/compute_requests/live.py
- **Verdict:** ok

### packages/backend/backend_core/domain/compute_requests/models.py
- **Verdict:** issues found
- **Findings:**
  - [medium] Lines 459-487: `command_from_payload` falls through every branch for an unmatched kind (e.g. `COMPUTE_REQUEST_KIND_UNSPECIFIED`) and returns an **empty** `ComputeCommand` instead of raising, unlike `_datasource_command` (line 454-455) and `_response_from_payload` (line 616-617) which do raise. An invalid kind can be persisted/dispatched as a blank command envelope.
  - [low] Lines 22-23, 38-39: integer-valued floats are converted to `int` on both encode and decode paths; a genuine float value like `5.0` in configs/results silently changes type across the boundary.
  - [low] Line 14: module imports from `modules.datasource.schema_protocol` (line 14) — domain layer depending on `modules/` inverts the layering the package-boundary checker enforces elsewhere (worker ↛ modules); verify this direction is intentional.

### packages/backend/backend_core/domain/datasource/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/domain/datasource/models.py
- **Verdict:** ok

### packages/backend/backend_core/domain/datasource/source_types.py
- **Verdict:** ok

### packages/backend/backend_core/domain/engine_instances/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/domain/engine_instances/models.py
- **Verdict:** issues found
- **Findings:**
  - [low] Lines 29-35: `from_engine_status` maps any non-HEALTHY status (including unknown-but-required values) to `STOPPED`; combined with `EngineStatus.require` raising for unknown tokens, FAILED/STARTING engine states reported by workers cannot be represented through this path even though the enum defines them (lines 38-55).

### packages/backend/backend_core/domain/engine_runs/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/domain/engine_runs/schemas.py
- **Verdict:** issues found
- **Findings:**
  - [low] Lines 171-186: `RunSummary.extract_result_fields` coerces `row_count` with `int(rc)` for non-int values; a string like `'abc'` in `result_json` raises inside a response model validator, turning a display endpoint into a 500 rather than a null field.
  - [low] Line 98: `EngineRunResultSummary` uses `extra='allow'`, so any typo'd result key passes validation unnoticed.

### packages/backend/backend_core/domain/enums.py
- **Verdict:** ok

### packages/backend/backend_core/domain/healthcheck_models.py
- **Verdict:** ok

### packages/backend/backend_core/domain/runtime/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/domain/runtime/events.py
- **Verdict:** ok

### packages/backend/backend_core/domain/runtime_workers/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/domain/runtime_workers/models.py
- **Verdict:** ok

### packages/backend/backend_core/domain/scheduler/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/domain/scheduler/schemas.py
- **Verdict:** issues found
- **Findings:**
  - [medium] Lines 56-69: `ScheduleUpdate.description` normalizes `''` → `None` and defaults to `None`, making PATCH semantics ambiguous: a client cannot distinguish "clear the description" from "leave unchanged" unless the service treats explicit-None specially (nothing in this model supports that).
  - [low] Lines 33, 55: `cron_expression` is accepted unvalidated here (no cron syntax check); invalid expressions surface only later at `Schedule.compute_next_run` time.

### packages/backend/backend_core/domain/step_config_enums.py
- **Verdict:** issues found
- **Findings:**
  - [low] Lines 354-369: `DurationUnit.every_token` raises `ValueError` for `NANOSECONDS`/`MICROSECONDS`/`MILLISECONDS` even though those members exist (lines 378-380); selecting them in a timeseries step fails at render time with an opaque message instead of being rejected at config validation.
  - [low] Lines 45-79: `FilterValueType.coerce` for BOOLEAN treats any unrecognized string as `False` (line 64) rather than erroring; typos like 'ture' silently filter incorrectly.
  - Trivial otherwise: the bulk of the file (lines 82-833) is repetitive token-wiring boilerplate for ~30 enums; a small factory loop over `(enum_pb2_name, members)` would remove several hundred lines, though the explicit style does mirror the generated protocol layout.

### packages/backend/backend_core/persistence/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/persistence/analysis/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/persistence/analysis/models.py
- **Verdict:** issues found
- **Findings:**
  - [medium] Line 18: `MutableDict.as_mutable(JSON)` only tracks top-level key assignment; nested mutation (e.g. `row['tabs'][0]['steps'].append(...)`) is invisible to change detection and will be silently lost on commit unless something reassigns the attribute. Current writers always reassign whole dicts (`modules/analysis/service.py:1016,1149,...`), so it works today, but the type invites the bug.
  - [medium] Line 18 + consumer `modules/analysis_versions/service.py:91`: `analysis.pipeline_definition = target.pipeline_definition` aliases the *same* MutableDict instance across an `Analysis` row and an `AnalysisVersion` row in one session; any later in-place mutation marks both dirty and can overwrite the historical version snapshot. A copy on assign (or dropping MutableDict) removes the hazard.
  - [low] Lines 15-31: no index on `owner_id` or `created_at`; per-owner listing queries scan the table (single-tenant-schema scale may make this moot).
  - [low] Lines 25, 28: `status` stored as plain String with no CHECK constraint or DB-level enum; invalid values are only caught when `AnalysisStatus.require` happens to be called.

### packages/backend/backend_core/persistence/analysis_versions/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/persistence/analysis_versions/models.py
- **Verdict:** issues found
- **Findings:**
  - [low] Line 18: same `MutableDict.as_mutable(JSON)` caveat as `Analysis.pipeline_definition` — version rows are meant to be immutable history, yet the column type permits tracked in-place mutation; a plain JSON column would better express immutability.
  - [low] Line 11: unique constraint `(analysis_id, version)` exists but nothing in the model allocates `version`; allocation correctness lives entirely in the service layer.

### packages/backend/backend_core/persistence/build_jobs/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/persistence/build_jobs/models.py
- **Verdict:** issues found
- **Findings:**
  - [low] Lines 12-17 vs 30-46: methods are interleaved with column declarations mid-class (fields resume at line 30 after three methods); legal Python but hurts readability — all other models group methods before or after fields consistently.
  - [low] Line 42: `max_attempts` has a Python default but no `server_default`, unlike `ComputeRequest.max_attempts` (`persistence/compute_requests/models.py:27`); raw-SQL inserts omitting the column fail while the compute_requests twin succeeds. Inconsistent queue-table conventions.
  - Positive: lease design is sound — indexed `lease_owner`/`available_at`/`status`, unique nullable `claim_token` (Postgres allows multiple NULLs), `lease_generation` BigInteger for reclaim safety.

### packages/backend/backend_core/persistence/build_runs/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/persistence/build_runs/models.py
- **Verdict:** issues found
- **Findings:**
  - [low] Lines 41-73: `apply_terminal_event` returns `True` for non-terminal events (final fallthrough, line 73) without applying anything — indistinguishable from "terminal applied". Currently safe because the only caller guards with `terminal_status_for_event(...)` first (`build_runs_service.py:420,435`), but the contract is misleading; returning `False` (or asserting terminality) would be safer.
  - [low] Lines 168-180: `BuildEvent` has no FK to `build_runs` (deliberate append-only log presumably) and no retention/TTL mechanism anywhere in the model; the table grows unboundedly with per-event rows including full `payload_json`.
  - [low] Lines 148-149: `progress` Float and `elapsed_ms` Integer are fine, but `next_event_sequence` (line 165) is allocated by read-modify-write in the service under `with_for_update()` (`build_runs_service.py:413,440-441`) — correct only as long as every writer takes the row lock; nothing at the model level enforces it.
  - Positive: `uq_build_events_build_sequence` (line 170) gives idempotent event ordering plus the covering index for ordered reads.

### packages/backend/backend_core/persistence/compute_requests/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/persistence/compute_requests/models.py
- **Verdict:** ok
- **Findings:**
  - [low] Line 14: protobuf envelopes stored as opaque `LargeBinary` — no versioning column beyond the envelope's embedded `version` field; fine, but schema evolution requires reading code, not the table.

### packages/backend/backend_core/persistence/datasource/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/persistence/datasource/models.py
- **Verdict:** issues found
- **Findings:**
  - [medium] Line 96: `config` JSON stores `connection_string` values (see `query_and_connection`, lines 56-71) — database credentials sit in plaintext in a JSON column with no encryption or secret-ref indirection. For a local-first tool this may be accepted, but any DB backup/export leaks credentials.
  - [low] Lines 99, 103: `created_by_analysis_id` and `owner_id` are plain Strings with no FK to `analyses.id`; deleting an analysis leaves dangling references (the `analysis_datasources` join table does cascade, so the two mechanisms are inconsistent).
  - [low] Lines 50-54: `normalize_connection_string` replaces the first occurrence of the driver suffix anywhere in the string (`value.replace(driver_suffix, 'postgresql', 1)`); correct today since the prefix is anchored by the `startswith` guard, but brittle if refactored.
  - [low] Line 101: `server_default='0'` for booleans is Postgres-specific literal style; fine for the declared Postgres-only deployment.

### packages/backend/backend_core/persistence/engine_instances/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/persistence/engine_instances/models.py
- **Verdict:** ok
- Note: this table lives in the shared/public schema (`_SHARED_TABLES`, `alembic/env.py:45`) while carrying a `namespace` column (line 14) — cross-tenant visibility is handled by query filters, not schema isolation; confirm that's intended for engine state.

### packages/backend/backend_core/persistence/engine_runs/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/persistence/engine_runs/models.py
- **Verdict:** issues found
- **Findings:**
  - [low] Lines 20-21: `analysis_id`/`datasource_id` have no indexes despite being the obvious lookup/filter columns (only `namespace` is indexed, line 19); run-history queries by datasource will scan.
  - [low] Line 22-23: `kind`/`status` stored as raw Strings validated only via `require()` on read; bad writes surface far from their origin.

### packages/backend/backend_core/persistence/healthchecks/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/persistence/healthchecks/models.py
- **Verdict:** issues found
- **Findings:**
  - [medium] Lines 152-160: `HealthCheckResult.healthcheck_id` has no FK to `healthchecks.id` and no cascade; deleting a healthcheck orphans its results forever (contrast `datasource_column_metadata.datasource_id`, which does cascade).
  - [low] Lines 100, 133: `self.config_float('threshold') or 0.0` conflates None and 0.0 — intentional default, but a threshold explicitly configured as `0` behaves identically to unset, so the distinction is unrepresentable.
  - [low] Lines 43-47: `metric_int`/`metric_float` cast arbitrary metric values with `int()/float()`; a string metric from the stats query raises `ValueError` deep in evaluation rather than producing a failed-check result.
  - [low] Line 147-148: `enabled`/`critical` rely on SQLModel defaults without `server_default`; consistent with other tables but means non-ORM inserts must supply them.

### packages/backend/backend_core/persistence/locks/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/persistence/locks/models.py
- **Verdict:** issues found
- **Findings:**
  - [low] Lines 25-27: `acquired_at`/`last_heartbeat` default to naive UTC datetimes (`datetime.now(UTC).replace(tzinfo=None)`) into `DateTime(timezone=True)` columns; mixed naive/aware handling is centralized in `as_utc` (lines 11-15), which correctly normalizes both directions — OK but the naive-default pattern recurs across models (`namespaces/models.py:10-11`) and is a latent DST/comparison trap.
  - Positive: composite PK `(resource_type, resource_id)` plus unique `lock_token` gives a clean CAS primitive for lock takeover.

### packages/backend/backend_core/persistence/namespaces/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/persistence/namespaces/models.py
- **Verdict:** issues found
- **Findings:**
  - [low] Lines 10-11: `created_at`/`updated_at` use naive-UTC `default_factory` with no `onupdate` for `updated_at`; stale `updated_at` unless every writer sets it manually.

### packages/backend/backend_core/persistence/runtime_events/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/persistence/runtime_events/models.py
- **Verdict:** ok
- Positive: outbox status uses a real `SAEnum(native_enum=False)` with `values_callable` (lines 22-24) — the only table that constrains its status vocabulary at the DB layer; the pattern would benefit the String-status tables elsewhere.

### packages/backend/backend_core/persistence/runtime_workers/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/persistence/runtime_workers/models.py
- **Verdict:** issues found
- **Findings:**
  - [medium] Lines 28-32: `is_reclaimable` computes `now - heartbeat` where `heartbeat` is force-normalized to tz-aware UTC but `now` is used as passed; a naive `now` raises `TypeError: can't subtract offset-naive and offset-aware datetimes`. The sibling `heartbeat_age_seconds` (lines 12-15) normalizes both sides — this method should too. Current callers pass aware datetimes, so it's latent.

### packages/backend/backend_core/persistence/scheduler/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/persistence/scheduler/models.py
- **Verdict:** issues found
- **Findings:**
  - [low] Lines 13-17: `compute_next_run` lets `croniter` raise on invalid expressions at scheduling time; combined with unvalidated input at the schema layer (`domain/scheduler/schemas.py:33`), a bad cron disables the schedule with an exception rather than a validation error.
  - [low] Line 29 vs 10: `claim_token` is nullable with a named unique constraint — fine — but unlike `build_jobs`/`compute_requests` there is no `index=True` on `lease_owner`+`lease_expires_at` pair used for claim scans; claim queries filter on these columns.
  - [low] Line 23: `enabled` boolean lacks `server_default` (inconsistent with `datasource.models` booleans).

### packages/backend/backend_core/persistence/settings/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/persistence/settings/models.py
- **Verdict:** issues found
- **Findings:**
  - [high] Lines 17, 20, 24, 28: `smtp_password`, `telegram_bot_token`, `openrouter_api_key`, `openai_api_key` are stored as plaintext columns in a singleton row with no encryption or secret-manager indirection. This is the densest secrets-at-rest surface in the schema; any SQL dump, backup, or debug endpoint serializing the model leaks live credentials. At minimum exclude these fields from any serialization path and document the threat model.
  - [low] Line 11: singleton enforced only by convention (`id=1` default); upsert logic lives in services.

### packages/backend/backend_core/persistence/telegram/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/persistence/telegram/models.py
- **Verdict:** issues found
- **Findings:**
  - [medium] Line 17: `bot_token` stored plaintext per subscriber row (same secrets-at-rest concern as AppSettings, duplicated per chat).
  - [low] Line 28: `TelegramListener.subscriber_id` has no FK to `telegram_subscribers.id`; deleting a subscriber orphans listeners.
  - [low] Lines 15, 28-29: no unique constraint on `chat_id` or `(subscriber_id, datasource_id)`; duplicate subscriptions are representable.

### packages/backend/backend_core/persistence/udfs/__init__.py
- **Verdict:** ok

### packages/backend/backend_core/persistence/udfs/models.py
- **Verdict:** issues found
- **Findings:**
  - [low] Lines 11, 16-17: no unique constraint on `name` (per owner or globally); UDF resolution by name elsewhere can be ambiguous. `code` stores executable Python with no integrity metadata (hash/provenance) beyond the free-text `source` column.


---

# Unit 05: AI, chat & telegram modules

### packages/backend/modules/ai/__init__.py
- **Verdict:** ok
- Trivial re-export module; no logic.

### packages/backend/modules/chat/__init__.py
- **Verdict:** ok
- Trivial re-export module.

### packages/backend/modules/chat/models.py
- **Verdict:** issues found
- **Findings:**
  - [low] `messages_json`/`history_json` as opaque JSON text columns (models.py:13-14) lose type safety and prevent DB-level queries; acceptable for local-first scope but worth noting for maintainability.
  - Note: the `api_key` column (models.py:12) holds ciphertext — `SessionStore.create/flush` encrypt via `encrypt_secret` before persisting (sessions.py:179, 214), so no plaintext-at-rest issue in this model itself.

### packages/backend/modules/chat/sessions.py
- **Verdict:** issues found
- **Findings:**
  - [low] `flush()` reaches into `live._history`, a private attribute of `LiveSession` (sessions.py:217) — breaks encapsulation; expose a public accessor.
  - [low] `wait_for_confirm()` overwrites `self._confirm_event` (sessions.py:89); a second concurrent confirm wait would orphan the first waiter forever. Mitigated in practice by `acquire_turn` serialization, but there is no guard tying confirmation to the active turn.
  - [low] `sweep()` evicts idle sessions and calls `close_stream()` (sessions.py:256-263) without flushing pending in-memory state first; any mutation since the last explicit `flush()` is lost, and a connected SSE consumer's `events()` iterator silently terminates on the `None` sentinel (sessions.py:148-153).
  - [low] `_trim_messages()` with `len(system) >= MAX_MESSAGES` computes a negative keep-count; slicing yields an empty non-system list rather than an error, but system messages themselves are never trimmed (sessions.py:101-106) — unbounded growth if a client re-sends large system prompts.
  - [low] `list_sessions()` parses every row's full `messages_json` just to build a 100-char preview (sessions.py:236-244) — O(all messages) per listing call.
  - Note: sync SQLAlchemy DB access (`create/get/flush/delete/list_sessions`) is fine only if called from sync route handlers — verified against routes.py below.

### packages/backend/modules/chat/routes.py
- **Verdict:** issues found
- **Findings:**
  - [high] No object-level authorization: every route accepts `user` via `get_current_user` then immediately discards it (`del user`, routes.py:598, 606, 620, 649, 678, 697, 709, 720, 764). Any authenticated user can read history, hijack (PATCH api_key), stream, or delete any session by ID — sessions are global and unscoped to their creator.
  - [medium] Unbounded agent loop: `while True` at routes.py:387 has no max-turn/tool-call cap; a model that keeps emitting tool calls loops indefinitely, burning tokens and holding the session busy until a manual `/stop`.
  - [medium] Prompt-injection execution surface: assistant text is scraped for `TOOLCALL>[...]` via regex (routes.py:142-143, 291-317) and executed against MCP tools; tool results are fed back into LLM context (routes.py:556-563), so content fetched by one tool can steer subsequent auto-executed SAFE tools. Mitigated only for MUTATING tools by `confirm_required` gate (routes.py:505-526); SAFE tools execute with no confirmation.
  - [medium] Orphaned tool_calls on early break: if `finish_reason` is not in `('tool_calls', 'stop', None, '')` (e.g. `'length'`) while `tool_calls` exist, the loop breaks (routes.py:436-437) after the assistant message with `tool_calls` was already appended (routes.py:422-425) but before any `role:'tool'` responses — the next request sends an invalid message sequence that OpenAI-compatible APIs reject with 400.
  - [low] SSE fan-out is lossy for multiple consumers: events go through a single `asyncio.Queue` consumed by whichever stream reads first (routes.py:727-746); two tabs streaming the same session steal each other's events. Heartbeats are also pushed into the shared queue (routes.py:735), so a heartbeat delivered to consumer A delays consumer B's real event.
  - [low] Private-attribute access from route layer: `session._queue` and `session._closed` in `stream()` (routes.py:728, 734) bypass LiveSession encapsulation.
  - [low] `update_session` mutates provider/model/api_key mid-turn without checking `session.busy` (routes.py:618-637) — a running turn may use half-updated settings (e.g. new model with old key semantics).
  - [low] `_try_parse_json` is O(n²): for each end index it slices and re-parses the whole prefix (routes.py:274-288); pathological long assistant outputs cause CPU spikes on the event-loop thread.
  - [low] `_infer_patch` hard-codes `parts[2]` as resource assuming `/api/v1/{resource}/...` (routes.py:124-126) — silently emits `resource: 'unknown'` for any other path shape.

### packages/backend/modules/chat/chat_http.py
- **Verdict:** issues found
- **Findings:**
  - [low] `list_models` assumes `resp.json()` is a dict (chat_http.py:105-112); a list/scalar JSON body raises `AttributeError`, which `/ai/chat/models` does not catch (routes.py:781 catches only `ChatHttpError, ValueError`) → unhandled 500.
  - [low] `_response_json_object` re-validates that JSON object keys are strings (chat_http.py:32-35) — Python's `json` module can only produce string keys here; dead defensive code.
  - [low] No retry/backoff unlike the sibling clients in `backend_core/ai_clients.py` (`_retry_request`); transient provider failures surface immediately as turn errors. Inconsistent error-resilience between the two chat paths.

### packages/backend/modules/telegram/__init__.py
- **Verdict:** ok
- Trivial re-export module.

### packages/backend/modules/telegram/routes.py
- **Verdict:** issues found
- **Findings:**
  - [low] Redundant double validation in `create_listener` (routes.py:81): `telegram_store.ListenerCreate.model_validate(payload.model_dump())` re-validates an already-validated pydantic body; pick one schema.
  - [low] No auth dependency on any telegram route (unlike chat routes which at least require `get_current_user`); whether this is intentional for MCP-exposed local endpoints should be confirmed — subscribers and listeners are world-readable/deletable for any caller that can reach the API.

### packages/backend/modules/telegram/bot.py
- **Verdict:** issues found
- **Findings:**
  - [medium] Unhandled exceptions kill the polling thread silently: `_poll_loop` catches only `httpx.TimeoutException`, `httpx.HTTPError`, `ValueError` (bot.py:150-152); any other exception raised inside `_handle_update` → `run_db` (e.g. a non-SQLAlchemy DB error, `KeyError`-style bug) propagates out of the thread target, terminating the bot with no log line and `running` flipping to False unnoticed.
  - [medium] Bot token stored in plaintext: `_handle_subscribe` persists `self._token` per subscriber row (bot.py:241; `telegram_store.add_subscriber` stores raw `bot_token`), unlike chat API keys which are encrypted via `encrypt_secret`. Also passed in URL path on every request (bot.py:183, 193, 204, 272 — unavoidable for Telegram API) and can leak into logs via httpx exception messages (bot.py:209, 277 interpolate `exc` which may contain the request URL).
  - [low] `/subscribe` has no allowlist: any Telegram user who discovers the bot can subscribe their chat (bot.py:229-230) and receive build notifications (data-exfiltration channel by design; fine for local use, worth documenting).
  - [low] Stop latency/race: normal long-poll uses `timeout=30` (+10s HTTP timeout) checked once before the request (bot.py:80-85); `stop()` joins with timeout=10 (bot.py:50) so it routinely logs "did not stop before timeout" and leaves a zombie thread. `start()` guards against double-polling by re-checking `running` (bot.py:33-37), but the zombie keeps polling until its current request returns.
  - [low] `get_updates()` public method (bot.py:190-196) duplicates `_do_get_updates` minus the None-on-lock semantics and has no production callers (only tests reference offsets); dead or divergent code.
  - [low] `_offset_by_token` grows unbounded across token rotations (bot.py:22, 215-217); trivial memory leak.

### packages/backend/modules/ai/routes.py
- **Verdict:** issues found
- **Findings:**
  - [medium] SSRF surface: `/ai/models` and `/ai/test` accept an arbitrary client-supplied `endpoint_url` (routes.py:32, 103, 127) and the server makes outbound HTTP requests to it (`backend_core/ai_clients.py` builds clients from that URL). Any authenticated caller can make the backend probe internal network endpoints and read the response body via error details/model lists. Acceptable for a local-first single-user deployment, but unguarded if the API is ever exposed.
  - [low] `api_key` accepted in request bodies (routes.py:33, 104) can end up in server logs/request traces depending on logging middleware; no redaction is applied in this module.
  - [low] `AIProviderStatus.endpoint_url` echoes resolved provider endpoints including any user-configured URL (routes.py:40, 63, 75) — minor info disclosure to other local users; consistent with the trust model above.


---

# Unit 06: analysis, analysis_versions, compute & engine_runs modules

### packages/backend/modules/analysis/service.py
- **Verdict:** issues found
- **Findings:**
  - [medium] No ownership enforcement on any CRUD path: `owner_id` is recorded at create (lines 601–641) but `get_analysis` (644–653), `update_analysis` (996–1032), `delete_analysis` (1063–1090), `list_analyses` (656–683) and `duplicate_analysis` (728–736) never filter by or check owner — any authenticated user can read/mutate/delete any analysis. May be intentional for local-first single-user mode, but nothing in code documents or guards it.
  - [medium] `update_analysis` snapshots a version (line 1006) *before* validating the new payload (line 1015) and holds the `FOR UPDATE` row lock (taken in `revisions.require`) across validation, compile, and AI-free but potentially heavy work; also bumps `revision` even when name/description/tabs are unchanged.
  - [medium] `duplicate_analysis` lines 738–817 re-implement ~80 lines of tab/output/step ID remapping nearly identical to `_rewrite_import_payload` (206–292); two copies will drift.
  - [low] `_validate_analysis_payload` lines 567–570 treat any `right_source`/`sources` value not matching a tab id as an external datasource id; references expressed as another tab's output `result_id` only pass if a placeholder datasource row happens to exist — inconsistent with import rewriting which maps refs to output ids (service.py:273–274).
  - [low] `derive_tab` line 1279 hardcodes `'branch': 'master'` for the derived tab's datasource instead of inheriting the source tab's branch.
  - [low] `delete_analysis` lines 1082–1085 only deletes datasources created by the analysis when `is_hidden`; non-hidden created datasources are silently orphaned with no warning.
  - [low] `generate_analysis_pipeline` lines 933–934 converts `AIError` to `ValueError`, which routes map to HTTP 400 — provider outages/config errors are indistinguishable from client errors.

### packages/backend/modules/analysis/routes.py
- **Verdict:** issues found
- **Findings:**
  - [medium] `preview_analysis` (242–305) accepts an arbitrary unvalidated body and forwards it to the executor without verifying the analysis exists or that the caller has access; line 292 `steps[-1]['id']` raises `TypeError` (→500) when step entries are not dicts, since only `steps` being a list is checked (276–277).
  - [low] `update_step` route lines 419–427: type-only change validates the existing config against the new type but discards the canonicalized result, so the stored config stays non-canonical while sibling paths store compiled configs.
  - [low] Inconsistent auth model: favorites require a user (`get_current_user_id`, lines 191, 207) while create/duplicate/import accept anonymous requests with `owner_id=None` (63, 103, 158).
  - Positive: mutation endpoints consistently use `require_analysis_revision` (If-Match + mutation lock + `FOR UPDATE`) — solid optimistic concurrency.

### packages/backend/modules/analysis/revisions.py
- **Verdict:** ok
- **Findings:** none. Lock → `SELECT ... FOR UPDATE` → If-Match compare (42–57) is ordered correctly against lost updates.

### packages/backend/modules/analysis/schemas.py
- **Verdict:** issues found
- **Findings:**
  - [medium] `AnalysisUpdateSchema.tabs` is required (line 125) although the service supports metadata-only updates (`if data.tabs is not None`, service.py:1014) — a `PUT /analysis/{id}` with only `name`/`description` always fails validation with 422; the service branch is dead code for this schema.
  - [low] `TabDatasourceConfig` uses `extra='allow'` (line 36), letting arbitrary unvalidated keys persist into datasource configs.

### packages/backend/modules/analysis/pipeline_types.py
- **Verdict:** issues found
- **Findings:**
  - [medium] Dead file: nothing imports `modules.analysis.pipeline_types`; all consumers (service.py:19, export/generators.py:10, persistence model) use `backend_core.domain.analysis.pipeline_types`. Duplicate definition invites drift; should be deleted per repo "remove obsolete paths" principle.

### packages/backend/modules/analysis/pipeline_compiler.py
- **Verdict:** ok
- **Findings:** none.

### packages/backend/modules/analysis/templates.py
- **Verdict:** ok
- **Findings:** none.

### packages/backend/modules/analysis/step_schemas.py
- **Verdict:** issues found
- **Findings:**
  - [medium] `AIConfig` includes `api_key` and `endpoint_url` fields (lines 406–407); step configs are persisted verbatim into `pipeline_definition` JSON and returned by `GET /analysis` — provider credentials supplied here are stored in plaintext and exposed over the API with no redaction.
  - [low] `get_config_model` (666–673) double-guards with `is_step_type` then `.get()`; harmless but redundant given `STEP_CATALOG` covers all step types.

### packages/backend/modules/analysis_versions/service.py
- **Verdict:** issues found
- **Findings:**
  - [medium] `restore_version` (78–128) mutates the analysis and inserts the pre-restore snapshot (87) *before* validating the restored definition (96); on validation failure everything depends on request-scoped rollback. Additionally `validate_stored_pipeline_definition` compiles copies parsed from the dict, but the raw (non-canonical) `target.pipeline_definition` is what gets persisted — validated form ≠ stored form.
  - [low] Lines 97–125 re-derive datasource links by hand, duplicating logic already computed inside `_validate_analysis_payload` (which returns `datasource_ids`); drift risk with the create/update path.
  - [low] `list_versions` (44–48) returns `[]` (HTTP 200) for a nonexistent `analysis_id` instead of 404.

### packages/backend/modules/analysis_versions/routes.py
- **Verdict:** issues found
- **Findings:**
  - [medium] `delete_version` (52–60) and `rename_version` (63–76) mutate analysis history without `require_analysis_revision` — no If-Match, no mutation lock — unlike every other analysis mutation; a concurrent restore/delete/rename can interleave unchecked.
  - [low] `delete_version` returns 200 with a `null` body rather than 204 (no `status_code=204`, line 52).

### packages/backend/modules/analysis_versions/schemas.py
- **Verdict:** ok
- **Findings:** none.

### packages/backend/modules/compute/routes.py
- **Verdict:** issues found
- **Findings:**
  - [high] `start_build` lines 549–560 embed `settings.database_url` as `catalog_uri` (i.e., DB credentials) into placeholder Iceberg datasource configs that are persisted via `commands.start_build` and surfaced through datasource APIs — credential leakage into readable config rows.
  - [medium] `start_build` (485–598) fully trusts the client-supplied pipeline: it never verifies `analysis_id` exists, that the pipeline matches the stored analysis, or datasource visibility (unlike previews, which run `_require_active_pipeline_datasources`). Any authenticated user can enqueue builds for arbitrary pipelines.
  - [medium] `/ws/engines` (940–981) performs no authentication — `_require_websocket_user` is not called, unlike `/ws/builds` (990) and `/ws/builds/{id}` (1043); anyone can watch engine status for any namespace supplied via header/query.
  - [medium] `DELETE /compute/iceberg/{id}/snapshots/{snapshot_id}` (467–482) is destructive yet has no ownership check, no lock, and lacks `mcp_confirm_required` used by comparable destructive endpoints.
  - [low] `list_builds` pagination (660–687): `fetch_limit = limit + offset` is applied before namespace filtering, then `[offset:offset+limit]` slicing after filtering — cross-namespace rows consume the fetch budget, producing short pages and an undercounted `total`.
  - [low] `build_stream` (1052) re-checks namespace after already building the message, but `_get_durable_build_detail` already filters by namespace — redundant second check; harmless.

### packages/backend/modules/compute/commands.py
- **Verdict:** ok
- **Findings:** none. `cancel_build` conflict handling (90–107) correctly re-validates job status inside the committed transaction.

### packages/backend/modules/compute/executor_client.py
- **Verdict:** issues found
- **Findings:**
  - [low] `_submit_and_wait` (110–140) busy-polls the DB every 50 ms per in-flight compute request (`expire_all` + query each iteration); under many concurrent previews this is significant load — the notification task exists but is only checked via tiny timeouts.
  - [low] `download_step` (224–232) deletes the artifact immediately after reading bytes; a failed/interrupted transfer cannot be retried without re-running the compute request.

### packages/backend/modules/compute/iceberg_service.py
- **Verdict:** issues found
- **Findings:**
  - [low] `_ingest_run_snapshot_ids` (101–124) attributes to each unresolved ingest run the latest snapshot whose timestamp ≤ run end; with overlapping runs or clock skew this misattributes snapshots (acknowledged heuristic, but no comment marks it as approximate).
  - [low] `delete_iceberg_snapshot` (198–210) validates snapshot id format locally but passes deletion straight to the worker with no existence/ownership pre-check; errors surface as opaque worker failures.

### packages/backend/modules/compute/representations.py
- **Verdict:** issues found
- **Findings:**
  - [low] `engine_run_summary` line 55 sets `analysis_name=run.analysis_id` — build lists show raw UUIDs as names for engine-run-backed entries.
  - [low] `engine_run_status_filter` line 24 maps `QUEUED → EngineRunStatus.RUNNING`; queued-but-not-started runs appear as RUNNING in filtered listings.

### packages/backend/modules/engine_runs/routes.py
- **Verdict:** issues found
- **Findings:**
  - [medium] No authentication on any endpoint (no `get_current_user` dependency, unlike all `/compute` routes); `GET /{run_id}` (90–97) returns full `request_json`/`result_json` unauthenticated.
  - [low] `limit` parameters (47, 70) are unbounded — a client can request arbitrarily large pages.


---

# Unit 07: platform modules (auth, config, locks, namespaces, settings, ...)

### packages/backend/modules/auth/__init__.py
- **Verdict:** ok
- Trivial re-export of the auth router.

### packages/backend/modules/auth/models.py
- **Verdict:** ok
- **Findings:**
  - [low] models.py:50-51,107,126 — Boolean columns use `server_default='0'`, which is not valid on PostgreSQL (`false` expected); harmless only if inserts always supply values, but raw SQL defaults would fail.
  - [low] models.py:119 — `VerificationToken.token` is stored plaintext and uniquely indexed; acceptable for opaque random tokens, but no hash-at-rest.

### packages/backend/modules/auth/schemas.py
- **Verdict:** ok
- **Findings:**
  - [low] schemas.py:8-11,40-42,53-55 — `email`, `password`, `display_name` are unvalidated free-form `str` (no email format, no max length, no password policy at the schema layer). Password policy is enforced later in `service.validate_password` (service.py:129), but register/login accept arbitrarily large strings (DoS surface for PBKDF2 at service.py:103 with attacker-controlled multi-MB passwords).

### packages/backend/modules/auth/dependencies.py
- **Verdict:** issues found
- **Findings:**
  - [medium] dependencies.py:42-50 — `get_optional_user_id` opens a brand-new settings-DB session via `run_settings_db` on every call even though the request usually already has one from `get_settings_db`; extra connection/transaction per request. Also duplicates the fallback logic of `get_current_user` instead of reusing it.
  - [low] dependencies.py:20-28 vs routes.py:248-257 — auth resolution logic duplicated between `get_current_user` and `_resolve_me`; they can drift (the `/me` cache path already behaves differently).

### packages/backend/modules/auth/commands.py
- **Verdict:** ok
- Thin transactional command layer over `service`; `revoke_all_user_sessions` (commands.py:125-129) revokes all then re-revokes current session redundantly but harmlessly.

### packages/backend/modules/auth/service.py
- **Verdict:** issues found
- **Findings:**
  - [medium] service.py:438-462 — `stage_validate_session` mutates `user.last_login_at`/`updated_at` and flushes+commits (via `committed`) on *every* authenticated request. This is a DB write per request (write amplification, row contention on hot users) and corrupts the meaning of both `last_login_at` (it is "last request", not login) and `updated_at`.
  - [medium] service.py:525-562 — `stage_find_or_create_oauth_user` auto-links an OAuth identity to an existing local account purely by email match (lines 546-562) without verifying that the provider has verified the email. Google/GitHub callbacks pass whatever email the provider returns; GitHub path filters to verified emails (routes.py:472-479), but Google userinfo email is trusted blindly (routes.py:389-391), enabling account takeover of a pre-created account by an unverified Google email in edge configurations.
  - [low] service.py:63-67 — default-user creation uses a PG advisory lock only when dialect is postgresql; on SQLite concurrent first requests can race and hit the unique-email constraint as `EmailAlreadyExistsError`.
  - [low] service.py:706-716 — resend cooldown picks `max(rows, key=created_at)` over all historical tokens and compares naive datetimes; correct today because `_utcnow()` is naive, but fragile mixing with tz-aware columns elsewhere (`DateTime(timezone=True)` columns storing naive values).
  - [low] service.py:667-696, 735-761 — `send_verification_email`/`send_password_reset_email` raise on SMTP failure after the registration/reset transaction already committed, so the user gets a 500 even though the account/token exists; token is burned with no retry record.
  - [low] service.py:268 — default-user password check runs PBKDF2 (200k iterations) inside `_ensure_default_user_locked`, which executes on the settings DB path used by `get_current_user` fallback when `auth_required=False` — adds ~100ms per request in that mode.

### packages/backend/modules/auth/routes.py
- **Verdict:** issues found
- **Findings:**
  - [medium] routes.py:48-68,260-279 — `_me_cache` is keyed by raw session tokens and only evicts expired entries once size exceeds 200 (`_evict_me_cache` removes only expired keys); with many distinct valid tokens inside the 10s TTL it can grow unbounded. When `auth_required=False`, arbitrary junk `X-Session-Token` values get cached (routes.py:250-256 falls through to default user), letting clients pollute the cache at will.
  - [low] routes.py:269-271 — revoked sessions remain served from cache up to 10s after logout/revocation (TTL window); logout does invalidate the exact token, but admin-side revocation paths rely on the full-cache clear.
  - [low] routes.py:62-68 — cache invalidation is process-local; in multi-worker deployments other workers keep serving cached `/me` after password change/session revocation.
  - [low] routes.py:355-364,427-436 — OAuth callback ignores provider error returns (`?error=...&error_description=...`); `OAuthCallbackParams.code` being required turns those into a 422 JSON error instead of redirecting the user to the frontend callback with a readable message.
  - [low] routes.py:145-166 — open registration with no rate limiting/Captcha; combined with unthrottled `/auth/login` (routes.py:169-185) there is no brute-force protection anywhere in the module.

### packages/backend/modules/config/__init__.py
- **Verdict:** ok
- Trivial re-export.

### packages/backend/modules/config/routes.py
- **Verdict:** issues found
- **Findings:**
  - [medium] routes.py:86-90 — `GET /config` has no authentication dependency (unlike `/settings` which requires `get_current_user`). It exposes `auth_required`, `verify_email_address`, SMTP/Telegram enabled flags and default namespace to anonymous callers. If global auth enforcement was intended, this endpoint bypasses it.
  - [low] routes.py:48-61 — `FrontendConfigCache` is not thread-safe (unsynchronized read-modify-write); benign under GIL for a single object swap, but two threads can both run `_build_frontend_config`.

### packages/backend/modules/healthcheck/__init__.py
- **Verdict:** ok
- Re-exports router and service functions.

### packages/backend/modules/healthcheck/commands.py
- **Verdict:** ok
- Trivial committed wrapper adding result rows.

### packages/backend/modules/healthcheck/routes.py
- **Verdict:** issues found
- **Findings:**
  - [high] routes.py:20-103 — none of the healthcheck CRUD endpoints require authentication (`get_db` session only, no `get_current_user`). With `auth_required=True` any anonymous client can create/update/delete healthchecks and read results. Same pattern applies to config/namespaces/locks/runtime routes (see per-file notes); if this is by design it should be documented, but it contradicts the authenticated `/settings` module two directories away.
  - [low] routes.py:50-57 — redundant UUID validation: `parse_datasource_id` already parses, then `uuid.UUID(parsed_id)` re-parses; inconsistent with `list_healthchecks` (line 32) which skips the second check.

### packages/backend/modules/healthcheck/service.py
- **Verdict:** issues found
- **Findings:**
  - [medium] service.py:70-85 — `create_healthcheck` never verifies the datasource exists; relies on a DB FK error surfacing as an unhandled IntegrityError → 500 instead of a 404/400. Also uses ad-hoc `session.commit()` instead of the codebase's `committed()` transaction helper used everywhere else.
  - [low] service.py:96-100 — `update_healthcheck` applies `payload.model_dump(exclude_none=True)` verbatim, so a client cannot clear an optional field (e.g. reset `name`) — `None` means "not provided" and there is no way to unset.
  - [low] service.py:31-44,54-64 — outer join to DataSource for search exists but `list_healthchecks` already returned early when the datasource is missing (lines 27-29), making the join dead weight; duplicated search-building logic between the two list functions.

### packages/backend/modules/locks/__init__.py
- **Verdict:** ok
- Trivial re-export.

### packages/backend/modules/locks/schemas.py
- **Verdict:** ok
- Well-constrained pydantic models; `LockWebsocketRequest` validator only enforces resource fields for WATCH, which matches route handling.

### packages/backend/modules/locks/routes.py
- **Verdict:** issues found
- **Findings:**
  - [medium] routes.py:209-217 — the lock websocket derives namespace from a client-supplied `X-Namespace` header/query param and performs no authorization that the owner may operate in that namespace; any connected peer can watch/acquire/release locks in every namespace. Namespace isolation here is by convention only (consistent with the app-wide namespace middleware, but worth flagging given locks guard concurrent edits).
  - [low] routes.py:342-343 — inner `except HTTPException` swallows the exception and continues the loop, but the outer `try` also catches `Exception` broadly; a bug raising HTTPException outside the inner try (e.g. in `finally` release at line 358) becomes a logged 500 path rather than a targeted error.
  - [low] routes.py:235-251 — WATCH-with-lock_token heartbeats before registering the watcher; if the heartbeat 409s (lock lost), the socket is not registered and the client receives only an error message with no status payload, forcing a reconnect cycle.
  - [low] routes.py:354-360 — `finally` releases the watched lock on disconnect using `watch_token`; correct, but if the same socket acquired via ACQUIRE and then WATCHed another resource without a token, stale-token cleanup depends on the WATCH branch resetting `watch_token` (it does, lines 255-257) — fragile implicit state machine spread across ~150 lines of if/continue.

### packages/backend/modules/locks/service.py
- **Verdict:** issues found
- **Findings:**
  - [critical] service.py:85 — `except IntegrityError, StaleDataError:` is Python 2 syntax; this is a SyntaxError on any Python 3 runtime (verified with `ast.parse`). The module — and therefore the whole locks router and every importer of `modules.locks.service` — cannot be imported; the app fails to boot. Must be `except (IntegrityError, StaleDataError):`.
  - [medium] service.py:69-104 — acquire race: `ResourceLock` has no version column (persistence/locks/models.py), so `StaleDataError` can never fire; two owners concurrently acquiring the same expired/free lock both pass the `lock is None`/`is_expired` checks and last-commit-wins silently. The loser believes it holds a lock whose token was overwritten; mutual exclusion is only restored at the next heartbeat (service.py:127-128 rejects the stale token). Consider `SELECT ... FOR UPDATE` or an atomic UPDATE-guarded insert.
  - [low] service.py:47-53,157-163,180-186 — lazy expiry deletion on read paths commits mid-request from arbitrary sessions; on SQLite (no row-level locking) concurrent delete+acquire can still raise non-StaleData errors that are not caught.
  - [low] service.py:175-188 — `ensure_mutation_lock` deletes an expired lock and commits inside what callers may treat as a read-only check; side-effecting commit buried in a validation helper is surprising.

### packages/backend/modules/locks/watchers.py
- **Verdict:** ok
- Correctly synchronized in-process registry (asyncio.Lock around all mutations); note it is per-process only, so watchers on other workers never get notified — acceptable for single-node, a gap for distributed mode.

### packages/backend/modules/logs/__init__.py
- **Verdict:** ok
- Trivial re-export.

### packages/backend/modules/logs/routes.py
- **Verdict:** issues found
- **Findings:**
  - [low] routes.py:10-17 — log ingestion endpoint is unauthenticated and unthrottled; anyone can flood the log store with arbitrary events (no batch size limit beyond pydantic parsing, no rate limit).

### packages/backend/modules/logs/schemas.py
- **Verdict:** ok
- **Findings:**
  - [low] schemas.py:33-45 — `to_log_payload` serializes `meta_json` via `json.dumps(self.meta)` with no size bound; client-controlled meta of arbitrary size is persisted verbatim.

### packages/backend/modules/logs/service.py
- **Verdict:** ok
- Thin pass-through to the log writer.

### packages/backend/modules/namespaces/__init__.py
- **Verdict:** ok
- Trivial re-export.

### packages/backend/modules/namespaces/routes.py
- **Verdict:** issues found
- **Findings:**
  - [high] routes.py:76-87 — `POST /namespaces` creates an S3 bucket and registers a namespace with no authentication dependency. Any anonymous caller (when reachable) provisions cloud resources. Combined with the missing auth on healthcheck/config/locks routes this looks like a systemic gap rather than an oversight in one file.
  - [low] routes.py:83-87 — bucket provisioning happens before `register_namespace`; if registration fails the bucket is left created (orphaned external resource) with no compensation/rollback.

### packages/backend/modules/runtime_overview/__init__.py
- **Verdict:** ok
- Trivial re-export.

### packages/backend/modules/runtime_overview/routes.py
- **Verdict:** issues found
- **Findings:**
  - [medium] routes.py:15-17 — `GET /runtime/overview` exposes worker PIDs, hostnames, container IDs, image digests, engine exit codes and queue internals with no authentication dependency; infrastructure reconnaissance surface for anonymous callers.

### packages/backend/modules/runtime_overview/schemas.py
- **Verdict:** ok
- Plain response models; nothing suspicious.

### packages/backend/modules/runtime_overview/service.py
- **Verdict:** issues found
- **Findings:**
  - [low] service.py:40-46 — `api_process` does `int(worker_id.split(':')[-1])` without guarding format; an unexpected `api_worker_id` value raises ValueError inside the overview endpoint → 500.
  - [low] service.py:133-146 — `_queue_namespace_summary` calls `run_settings_db` + `run_db` sequentially per namespace; N+1 round trips on the overview endpoint, and `reclaimable_worker_ids` is recomputed identically for every namespace.
  - [low] service.py:156-161 — loads *all* BuildJob rows per namespace into memory to count statuses; aggregate in SQL instead.

### packages/backend/modules/settings/__init__.py
- **Verdict:** ok
- Trivial re-export (file contains only router import).

### packages/backend/modules/settings/routes.py
- **Verdict:** issues found
- **Findings:**
  - [high] routes.py:68-75 — `GET /settings` returns `smtp_password`, `telegram_bot_token`, `openrouter_api_key`, `openai_api_key` in cleartext (SettingsResponse fields confirmed in backend_core/settings_schemas.py:12-17) to *any* authenticated user. There is no admin role: in multi-user mode any self-registered account can read all integration secrets.
  - [high] routes.py:78-103 — `PUT /settings` likewise lets any authenticated user overwrite SMTP/OpenAI/Telegram credentials and toggle the bot runtime — no privilege separation between users.
  - [medium] routes.py:88-101 — telegram bot restart happens after the settings transaction commits; on failure the API returns 502 while the new settings are already persisted, leaving persisted-vs-runtime state divergent with no retry mechanism.
  - [low] routes.py:177-210,228-261 — `detect_telegram_chat` pauses the globally shared bot singleton while inspecting updates; two concurrent detections interleave pause/resume (second resume while first still paused), and consuming updates with `offset=get_offset(token)` can race the bot's own polling loop.
  - [low] routes.py:128-129,156-157,206-207,257-258 — raw exception strings from smtplib/httpx are surfaced verbatim in 502 details; can leak internal hostnames/network topology to the client.


---

# Unit 08: datasource, export, mcp, scheduler & udf modules

### packages/backend/modules/datasource/routes.py
- **Verdict:** issues found
- **Findings:**
  - [high] Database connection strings (containing credentials) flow unredacted into API responses: `create_remote_database_datasource` / `connect` (lines 642–653) persist the raw `connection_string`, and `GET /datasource`/`GET /datasource/{id}` (`service.get_datasource`, `list_datasources`) return the full `config` dict including it. No masking exists anywhere in this module (contrast: `backend_core/settings_store.py` masks SMTP secrets). Any authenticated user — and any MCP client via the `mcp=True` tools at lines 600, 720, 766 — can read every stored DB credential.
  - [medium] `_local_excel_source` (lines 99–111) performs a synchronous object-store download (`download_object_bytes`, line 105) directly inside an async context manager without `asyncio.to_thread`, blocking the event loop for the duration of large-file downloads.
  - [medium] `_stage_upload_to_object_store` (line 92) buffers the entire uploaded file into memory via `temp_path.read_bytes()` before upload; combined with `upload_max_file_size_bytes` this is a bounded but avoidable memory spike per concurrent upload.
  - [low] `preflight_excel` (lines 387–409): if `build_excel_preview` raises, the preflight entry created at line 387 stays in the in-memory store (with `delete_source=True`) until TTL cleanup; only the local temp file is removed.
  - [low] `upload_bulk` (lines 226–343) has no cap on the number of files per request and stages them sequentially; each failure path repeats the same 4-line cleanup block (lines 317–338) — a cleanup helper would remove ~30 duplicated lines.
  - [low] `get_lineage` (lines 747–752): on `parse_datasource_id` failure the raw unvalidated string is used as the datasource id, silently degrading validation to a no-op lookup.
  - Note: `except AppError, HTTPException, ValueError:` (line 213) and `except AppError, HTTPException:` (line 588) are PEP 758 unparenthesized multi-except — valid on the project's Python 3.14 target, not a bug.

### packages/backend/modules/datasource/service.py
- **Verdict:** issues found
- **Findings:**
  - [medium] `update_datasource` Excel re-validation (lines 986–1024) opens `Path(file_path)` directly with openpyxl, but `file_path` for managed uploads is an `s3://` object-store URL (enforced by `FileDataSourceConfig._validate_file_path`). Unlike the routes (which use `_local_excel_source` to download first), this path can never succeed for object-store-backed Excel datasources — updating Excel bounds always fails with a wrapped "not found"-style error. The routes' download-then-preview step is missing here.
  - [low] Stale guard key: line 916 blocks config key `'column_schema'`, but the actual schema cache field/column is named `schema_cache`; the protected-key name does not match anything in the current model (legacy naming), so the intended protection may be misdirected.
  - [low] `InternalPostgresOnboarding.matching_datasources` (lines 87–102) loads every `DataSource` row into memory and compares in Python on every call; `list_tables` (line 116) calls it once per table → O(tables × datasources) full scans.
  - [low] `delete_datasource` (lines 1050–1057) deletes storage then commits the row delete non-atomically; a crash between `cleanup_datasource_storage` and commit leaves data deleted but the row alive.
  - Correctness otherwise solid: identifier quoting in `InternalPostgresOnboarding._quote_identifier` (line 51) plus strict regex `_INTERNAL_POSTGRES_QUERY_RE` (line 42) and system-schema/table blocklists (lines 107, 122–125) properly prevent SQL injection through internal-Postgres onboarding.

### packages/backend/modules/datasource/publication_service.py
- **Verdict:** ok
- **Findings:** none. Fenced revision update with rollback on lost claim (lines 101–105) is correct; description stripping from cache payload (lines 39–40) is consistent with the column-metadata table ownership.

### packages/backend/modules/datasource/preflight.py
- **Verdict:** issues found
- **Findings:**
  - [medium] `_PREFLIGHTS` is a module-global in-process dict (line 23). With multiple backend workers/processes, a preflight created in one worker is invisible in another, breaking `/preflight/{id}/preview` and `/confirm`. No shared store or sticky-session note.
  - [low] Expired-preflight source deletion only runs opportunistically inside `get_preflight` (line 53); entries whose preview/confirm are never revisited leak their object-store files until some unrelated request triggers `_cleanup_expired`.
  - [low] `create_preflight` (line 29) loads the whole workbook with `read_only=False` into memory just to enumerate sheets/tables/named ranges.

### packages/backend/modules/datasource/commands.py
- **Verdict:** ok
- **Findings:** none. Claim fencing before staging (lines 40–50) and outbox enqueueing are clean.

### packages/backend/modules/datasource/schemas.py
- **Verdict:** issues found
- **Findings:**
  - [medium] `DatabaseDataSourceConfig.connection_string` (line 216) accepts any string with no scheme/format validation; combined with plaintext storage/response exposure this is the credential entry point. At minimum a scheme allowlist would limit accidental misuse.
  - [low] `ColumnStatsRequest.datasource` (line 137) is an unrestricted `dict` that is forwarded verbatim to the compute engine by `routes._handle_column_stats` (routes.py:896–908); nothing constrains its shape or keys before it leaves the backend.
  - [low] `CSVOptions.delimiter`/`quote_char`/`encoding` (lines 185–189) accept arbitrary strings; invalid values surface only as compute-time failures rather than 400s.

### packages/backend/modules/datasource/schema_protocol.py
- **Verdict:** ok
- **Findings:** none. Defensive parsing of cache payloads degrades gracefully as documented.

### packages/backend/modules/datasource/service_lineage.py
- **Verdict:** issues found
- **Findings:**
  - [low] `build_lineage` (lines 44–46) loads all datasources, analyses, and dependency rows into memory on every request with no namespace filtering except for the single targeted datasource (lines 60–63); graph size grows unbounded with tenant count. Fine today, worth watching.
  - Namespace check applies only when `target_datasource_id` is given; the unfiltered `mode='full'` graph leaks node names across namespaces (lines 144–169).

### packages/backend/modules/export/__init__.py
- **Verdict:** ok
- **Findings:** trivial re-export module.

### packages/backend/modules/export/models.py
- **Verdict:** ok
- **Findings:** trivial enum + extension mapping.

### packages/backend/modules/export/utils.py
- **Verdict:** ok
- **Findings:** none. Slug sanitization produces safe filenames.

### packages/backend/modules/export/service.py
- **Verdict:** ok
- **Findings:** none. Clean orchestration; walrus-based dict comprehension (line 39) is correct.

### packages/backend/modules/export/generators.py
- **Verdict:** issues found
- **Findings:**
  - [low] `render_polars_expression` (line 552) and `render_sql_expression` (line 770) interpolate the user-authored expression string verbatim into generated Python/SQL output. This is inherent to a code-export feature (the user exports their own pipeline), but the SQL variant can also emit syntactically broken SQL with no warning since the expression is never validated.
  - [low] `_sql_filter_expr` membership branch (lines 297–299): an empty list value renders `IN ()`, which is invalid in PostgreSQL/DuckDB.
  - [low] Cycle handling in `select_tabs` (lines 180–182) appends cycle members in arbitrary relative order rather than warning; exported code for cyclic tabs will reference undefined variables.
  - Positive: identifiers are sanitized via `_identifier` (line 75), string literals escaped via `_safe_py`/`_sql_quote`/`_sql_literal` (lines 84–114), and UDF steps are deliberately excluded from export with a warning (line 572).

### packages/backend/modules/mcp/__init__.py
- **Verdict:** ok
- **Findings:** trivial docstring-only init.

### packages/backend/modules/mcp/router.py
- **Verdict:** ok
- **Findings:** none. Metadata capture at registration time is consistent across decorator/wrapper chains (`inspect.unwrap` handling).

### packages/backend/modules/mcp/decorators.py
- **Verdict:** ok
- **Findings:** none. Marker propagation to both wrapper and root is handled; cycle-guarded unwrap walk in `_iter_wrapped`.

### packages/backend/modules/mcp/models.py
- **Verdict:** issues found
- **Findings:**
  - [low] `CONFIRM_REQUIRED_PATTERNS` (lines 176–181) covers DELETE on datasource/scheduler/healthchecks/analysis paths only. All mutating methods do route through the pending flow (`routes.py:105–107`), but `confirm_required` is the signal UIs use to warn before confirming; destructive non-DELETE mutations such as `POST /datasource/connect`, `PUT /datasource/{id}`, and UDF create/update/delete (all `mcp=True`) default to `confirm_required=False`.
  - [low] `MCPToolDefinition.__getitem__`/`get` (lines 169–173) run a full `model_dump(mode='json')` per access — O(n) repeated serialization in hot loops like `capabilities` filtering.

### packages/backend/modules/mcp/pending.py
- **Verdict:** issues found
- **Findings:**
  - [low] `sweep()` (lines 67–71) is never called anywhere; expired entries are only evicted lazily on `pop`/`get` of their exact token, so abandoned tokens accumulate in memory indefinitely (unbounded growth under automated tool-call traffic).
  - [medium] Tokens are not bound to the creating user: `PendingEntry` stores no user identity, and `/mcp/confirm` (routes.py:118–135) executes with the *creator's* forwarded session headers (`entry.context`). Any authenticated user who learns/guesses nothing more than the token can confirm — and the action executes with the original caller's credentials. Token is `secrets.token_urlsafe(24)` so guessing is impractical, but the missing binding means a leaked token is a credential-hijack primitive, and there is no revocation on logout.

### packages/backend/modules/mcp/registry.py
- **Verdict:** issues found
- **Findings:**
  - [low] `build_tool_registry` (lines 267–269) raises for the *entire* registry if any single onboarded route has an unsupported schema — one bad route breaks `/mcp/tools`, `/mcp/call`, and `/mcp/capabilities` for all tools with a 500.
  - [low] `_openapi_to_json_schema` (lines 53–79) mutates nothing but resolves `$ref` without cycle detection; a self-referential component would recurse infinitely (FastAPI-generated schemas don't produce this today).

### packages/backend/modules/mcp/validation.py
- **Verdict:** ok
- **Findings:** none. Keyword allowlisting, recursive issue detection, and default application are coherent; jsonschema used idiomatically.

### packages/backend/modules/mcp/executor.py
- **Verdict:** issues found
- **Findings:**
  - [low] A new `httpx.AsyncClient` + `ASGITransport` is constructed per tool call (lines 57–58); a shared transport would avoid repeated setup. Minor.
  - [low] For POST/PUT/PATCH with `payload=None` an empty body with `Content-Type: application/json` is sent (lines 70–77); form/multipart endpoints will fail with opaque 422s instead of a clear validation error.
  - Header forwarding (lines 61–66) copies arbitrary caller headers into the internal request — intentional for session/namespace propagation, but it also forwards e.g. `Host`/`Content-Length` if present in context; only `X-Session-Token`/`X-Namespace` are ever set by `build_tool_context`, so currently safe.

### packages/backend/modules/mcp/routes.py
- **Verdict:** issues found
- **Findings:**
  - [medium] Authorization is binary: every endpoint requires *a* logged-in user (`get_current_user`) but then discards identity (`del user`, lines 79, 87, 98, 120, 142). There is no per-tool or per-resource authorization, so any authenticated user can invoke any MCP-exposed tool — including creating database datasources with arbitrary connection strings, deleting datasources, and reading configs containing other users' DB credentials. Combined with the credential exposure above this is the main MCP risk.
  - [medium] `/mcp/confirm` executes with the pending entry's captured creator headers (see pending.py finding) and does not verify the confirming user matches the creator (lines 118–135).
  - [low] `get_registry` (lines 33–43) re-coerces and reassigns the cached registry on every request even when already valid — wasted work per call; also the `isinstance(registry, list)` reset branch is dead in practice.

### packages/backend/modules/mcp/tool_output.py
- **Verdict:** ok
- **Findings:** none.

### packages/backend/modules/scheduler/__init__.py
- **Verdict:** ok
- **Findings:** trivial router re-export.

### packages/backend/modules/scheduler/routes.py
- **Verdict:** issues found
- **Findings:**
  - [low] `list_schedules` (lines 20–38): `limit`/`offset` are unbounded ints; `limit=10_000_000` is accepted. Minor DoS surface.
  - No ownership checks on create/update/delete — consistent with the rest of the app's single-namespace model, but any authenticated user can delete any schedule.

### packages/backend/modules/scheduler/commands.py
- **Verdict:** ok
- **Findings:** none. Transactional staging + IPC notify pattern is consistent.

### packages/backend/modules/scheduler/service.py
- **Verdict:** issues found
- **Findings:**
  - [low] `enqueue_schedule_run`: the RAW and DATASOURCE branches (lines 827–839 vs 841–853) are byte-for-byte duplicates — collapse them.
  - [low] `mark_schedule_run` (lines 781–794) recomputes `next_run` from the cron expression even for trigger-based schedules (`depends_on`/`trigger_on_datasource_id`), which can make `next_run` drift from actual trigger semantics; harmless because `get_due_schedules` short-circuits trigger schedules (line 696), but confusing state.
  - [low] `get_due_schedules` (lines 669–704) issues per-schedule queries (`_is_triggered_by_schedule`/`_is_triggered_by_datasource`) — N+1 pattern; acceptable at current scale.
  - [low] `stage_update_schedule` (lines 548–550) blindly `setattr`s every `exclude_unset` field from the payload onto the ORM model; pydantic schema currently gates this, but any new writable-looking field added to `ScheduleUpdate` silently becomes persisted.
  - [low] `should_run` (line 618) treats a schedule with `last_run=None` as immediately due regardless of cron start alignment — first-run semantics may fire earlier than users expect.
  - Positive: lease claim/fencing logic (`claim_due_schedules`, `enqueue_schedule_run` staleness checks at lines 813–820) is thorough and correctly uses `FOR UPDATE SKIP LOCKED` + generation counters.

### packages/backend/modules/udf/__init__.py
- **Verdict:** ok
- **Findings:** trivial router re-export.

### packages/backend/modules/udf/routes.py
- **Verdict:** issues found
- **Findings:**
  - [high] UDF CRUD is fully exposed as MCP tools (`mcp=True` on all routes, lines 15–104) with no ownership checks: any authenticated user can read, modify, or delete any UDF by ID, and — critically — replace its `code`. Since UDF code is later executed by the worker sandbox (packages/worker/operations/with_columns.py:101), write access to UDFs is effectively arbitrary-code-injection-into-other-users'-pipelines. A user who inserts malicious code into a shared/popular UDF gets it executed whenever anyone else's pipeline runs that step.
  - [low] Route ordering: `/match` and `/export` are declared before `/{udf_id}` (lines 43–58 vs 71) — correct today, but fragile if reordered.

### packages/backend/modules/udf/schemas.py
- **Verdict:** issues found
- **Findings:**
  - [low] `UdfCreateSchema.code` (line 25) has no length limit; combined with syntax-only validation, arbitrarily large payloads are stored. Add `max_length`.
  - [low] `UdfImportItemSchema.name` (line 62) unconstrained; import can create names colliding with seeded defaults and overwrite them when `overwrite=True`.

### packages/backend/modules/udf/service.py
- **Verdict:** issues found
- **Findings:**
  - [high] `_validate_code` (lines 22–28) performs *only* an `ast.parse` syntax check — no import blocking, no AST allowlist, no static analysis. All execution-safety enforcement lives exclusively in the worker sandbox (`_SAFE_BUILTINS` + `validate_no_reflection_escape` in worker/operations/with_columns.py). The backend is the trust boundary where untrusted code enters the system, yet applies zero semantic restrictions; defense rests entirely on one downstream layer. At minimum mirror the reflection-escape check here so obviously malicious code is rejected at ingestion.
  - [medium] No ownership model: `update_udf`/`delete_udf`/`clone_udf` (lines 91–138) act on any UDF by ID regardless of `owner_id`; `owner_id` is recorded on create (line 57) but never enforced. `clone_udf` also drops the owner entirely (no `owner_id` passed), orphaning clones from attribution.
  - [low] `import_udfs` (line 160) uses `scalar_one_or_none()` on a name lookup — if duplicate names ever exist (no visible unique constraint verified here), it raises `MultipleResultsFound` → 500 for the whole import.
  - [low] `import_udfs` skips existing UDFs silently when `overwrite=False` (line 163) while the route docstring says "skipped" — behavior matches, but skipped items are not reported in the response, so callers cannot tell which were applied.
  - [low] `seed_defaults` (lines 195–199) seeds only if *any* UDF exists — adding a fourth default later will never seed for existing installs.


---

# Unit 09: worker runtime core

### packages/worker/runtime/__init__.py
- **Verdict:** ok
- **Findings:** empty file (package marker).

### packages/worker/runtime/time.py
- **Verdict:** ok
- **Findings:** trivial 5-line UTC-now helper.

### packages/worker/runtime/runtime_notifications.py
- **Verdict:** ok
- **Findings:** trivial payload-kind dispatch to live hubs; no issues.

### packages/worker/runtime/iceberg_snapshot_reader.py
- **Verdict:** issues found
- **Findings:**
  - [low] L21: `table.scan(snapshot_id=...).to_arrow()` loads the entire snapshot into memory eagerly before Polars laziness begins — for large snapshots this defeats LazyFrame streaming; consider `.to_arrow_batch_reader()`/scan-level pushdown if supported by StaticTable.
  - [low] L19: fallback `schema_by_id(schema_id) or table.schema()` silently masks a missing schema id mismatch; acceptable but worth a debug log since column set may not match snapshot data.

### packages/worker/runtime/engine_notifications.py
- **Verdict:** issues found
- **Findings:**
  - [medium] L35-44: `notify` runs synchronous network I/O (`persist_engine_snapshot` → gRPC/HTTP via `WorkerRuntimeClient`) and is invoked with only an `is_closed()` guard; any exception from persist propagates into whatever thread/timer calls notify (typically an engine status callback), potentially killing status reporting loops. No try/except + log around the persist call.
  - [low] L36: `loop.is_closed()` check is racy (loop can close between check and use), but harmless here because the sync client doesn't use the loop directly.

### packages/worker/runtime/iceberg_catalog.py
- **Verdict:** issues found
- **Findings:**
  - [low] L48-49: if the body raised and `pg_advisory_unlock` also fails (e.g. connection dropped), the unlock exception masks the original error; consider suppressing unlock failures.
  - [low] L13-15: bootstrap-once cache is per-process only and never invalidated; a dropped/recreated catalog schema within the same process lifetime would skip re-bootstrap. Acceptable for worker lifetime but undocumented.
  - Note L39: advisory lock is session-scoped on a dedicated autocommit connection — correct usage; duplicate-table race retry (L43-47) is sound.

### packages/worker/runtime/namespace.py
- **Verdict:** issues found
- **Findings:**
  - [medium] L52-54: `namespace_paths()` performs `mkdir` as a side effect on every call, including pure-read call sites; any code path that merely resolves paths mutates the filesystem. Also creates dirs for namespaces that may never be used (leak of empty dirs).
  - [low] L46: passing `namespace=""` explicitly normalizes to default rather than using context — slightly surprising API (`None` vs `""` mean different things); documented nowhere.

### packages/worker/runtime/datasource_delete_runtime.py
- **Verdict:** issues found
- **Findings:**
  - [medium] L19-32: loop creates a new `WorkerRuntimeClient()` (L36) on every `_run_once` iteration — a fresh channel/connection per poll tick (2/sec idle). Channel churn and FD pressure under long worker uptime; the client should be constructed once outside the loop.
  - [low] L37-44: `_run_once` processes at most one delete per iteration then returns True, causing immediate re-poll with another new client; fine functionally but amplifies the churn above.
  - [low] L62: engine considered busy if `current_job_id` is set AND alive — correct guard; shutdown of dead engines before finalize (L64-65) avoids leaks. OK.
  - Note L25-28: broad exception catch with retry + backoff sleep is appropriate for a background loop.

### packages/worker/runtime/engine_credentials.py
- **Verdict:** ok
- **Findings:** solid validation of static credential map; prod-mode reuse checks (L58-61, L74-77) are good defense-in-depth. No verifiable issues.

### packages/worker/runtime/export_formats.py
- **Verdict:** issues found
- **Findings:**
  - [low] L17-19: `SinkFormat.write` re-scans the written file (`scanner(path).select(pl.len()).collect()`) just to count rows after every sink — doubles I/O on export path; acceptable trade-off but notable for large exports.
  - [low] L43-50: duckdb writer registers `df` implicitly via replacement scan; fine, but table name fixed to `data` and file not fsynced — acceptable.

### packages/worker/runtime/compute_monitor.py
- **Verdict:** issues found
- **Findings:**
  - [low] L27: `except psutil.Error, OSError:` uses PEP 758 unparenthesized multi-exception syntax — valid only on Python ≥3.14 (verified parses under the project's 3.14 interpreter; rejected by ≤3.13 parsers). Given the stack pins 3.14 this works today, but any tooling or contributor environment on an older interpreter cannot even import the module (`runtime.resource_observation` imports it at resource_observation.py:7). Parenthesized form costs nothing.
  - [medium] L21-36: monitoring loop samples every second forever while the engine lives, but nothing bounds it against engine replacement — if the consumer task leaks, one sampler per leaked consumer keeps polling a live process indefinitely. Minor given `stop_stream_task` usage at call sites.
  - [low] L16: no existence handling for `psutil.Process(pid)` construction — raises `NoSuchProcess` synchronously if the engine dies between reading `process_id` and here (only in-loop errors are guarded).
  - Note L31: CPU normalization against configured `max_threads` capacity is correct and clamped.

### packages/worker/runtime/resource_observation.py
- **Verdict:** ok
- **Findings:**
  - Note: earlier draft flagged an import-chain SyntaxError via compute_monitor.py — retracted; the file uses PEP 758 syntax valid on the project's Python 3.14.
  - Note L47-52: `observe_stream_task` correctly swallows lease-loss; good task-lifecycle hygiene.

### packages/worker/runtime/live_hubs.py
- **Verdict:** issues found
- **Findings:**
  - [low] L22, L53: `loop.call_soon_threadsafe` raises `RuntimeError` if the waiter's loop closed between registration and publish; publish() is called from notification paths (runtime_notifications.py) so a dead SSE client's closed loop can make `publish()` raise. No suppression of that race.
  - [low] L55-57: `_discard_waiter` acquires a threading.Lock inside async code — brief event-loop blocking; negligible at this scale.
  - Note L28-43: double-checked version read before/after registering the future is correct; no lost-wakeup race.

### packages/worker/runtime/config.py
- **Verdict:** ok
- **Findings:**
  - [low] L95-96: insecure default object-store credentials (`rustfsadmin`/`rustfsadmin`) baked into code; acceptable for local dev but nothing warns when defaults are used with prod_mode disabled.
  - Note: env parsing with min/max validation and fail-fast RuntimeErrors is clean.

### packages/worker/runtime/build_events.py
- **Verdict:** ok
- **Findings:** pure dataclass/context assembly + emit helpers; no I/O or concurrency. No verifiable issues.

### packages/worker/runtime/compute_utils.py
- **Verdict:** issues found
- **Findings:**
  - [medium] L121-136: `await_engine_result` is an unbounded synchronous busy-poll loop (0.1s `get_result` timeout, no deadline). Callers are sync service functions run on pool threads (not the event loop), so nothing stalls asyncio — but a wedged-yet-alive engine polls forever at 10 Hz per request with no timeout, tying up a compute-request worker slot indefinitely.
  - [low] L36-52: only the first dependency (`deps[0]`, L43/L92) is honored — single-parent assumption is implicit and undocumented.

### packages/worker/runtime/exceptions.py
- **Verdict:** ok
- **Findings:** clean error taxonomy with protobuf error-code mapping; `_coerce_error_code` validates int codes against the enum (L12). No issues.

### packages/worker/runtime/json_values.py / json_utils.py
- **Verdict:** ok
- **Findings:** small pure helpers (protobuf Struct conversion, JSON-safe coercion, shallow dict copy). Note json_utils `copy_json_dict` is a *shallow* copy despite the name — [low] misleading naming only.

### packages/worker/runtime/worker_runtime.py
- **Verdict:** issues found
- **Findings:**
  - [medium] L40-46, L98, L102, L117-125, L130, L132-139: synchronous `WorkerRuntimeClient` network calls (`register_worker`, `claim_build_job`, `heartbeat_worker`, `fail_build_job`, `finalize_build_job`) execute directly on the event loop inside async coroutines — a slow/hung data-plane call stalls the entire worker loop and any co-hosted tasks. Only lease renewal (L199) correctly uses `asyncio.to_thread`.
  - [medium] L82-86: shutdown path joins the heartbeat thread with no timeout; if a heartbeat gRPC call hangs, `build_worker_loop` never exits and `stop_worker` never runs. A bounded `join(timeout=...)` would prevent the hang.
  - [low] L74-77: idle-exit path returns immediately after one idle window without polling for new jobs in between — a job claimed by another worker during the window isn't picked up locally until restart; acceptable given external distribution but subtle.
  - Note L145-178: lease lifecycle is well done — pre-execution expiry check (L154), renewal task raced against execution (L169), cancellation + gather cleanup in finally (L174-178). Solid.
  - Note L192: initial delay derived from remaining TTL/3 avoids renewing too early. Good.

### packages/worker/runtime/healthchecks.py
- **Verdict:** issues found
- **Findings:**
  - [medium] L233: single aggregated `lazy_frame.select(expressions).collect()` materializes aggregate expressions over the full dataset with default (in-memory) engine — for large exports this can exceed memory; no streaming/sink path or row cap. Also runs on whatever thread calls it (sync collect).
  - [low] L205: NULL_PERCENTAGE guard only checks `threshold >= 0`; negative thresholds pass `_evaluate`'s `or 0.0` fallback silently... actually negative threshold would make check fail-all rows; minor validation gap.
  - [low] L144/L174: `threshold = _config_float(...) or 0.0` treats an explicitly configured threshold of 0.0 same as missing — harmless here since result identical.
  - [low] L65: `pl.read_json` loads whole JSON file into memory eagerly (unlike scanner paths); acceptable but inconsistent.
  - Note L180-222: invalid checks correctly degrade to `_missing_column` results instead of raising; good error containment.

### packages/worker/runtime/object_store.py
- **Verdict:** issues found
- **Findings:**
  - [medium] L294-311: `delete_prefix` never inspects `DeleteResult.Errors` from `delete_objects` responses — partial deletion failures are silently ignored, so a "deleted" datasource can leave orphaned objects behind. Also no guard that the prefix is under `_MANAGED_KEY_ROOTS` here; safety depends entirely on callers using `is_managed_object_store_url`.
  - [low] L205-214: `presigned_put_url` constructs a brand-new boto3 client per call when the endpoint differs (no caching); repeated presigning churns connection pools.
  - [low] L280: `list_metadata_files` prefix heuristic (`"/metadata" not in prefix and "/metadata/" not in prefix`) misbehaves for keys that merely contain "metadata" elsewhere in the path (e.g. `metadata-backups/x`) — would append `/metadata` incorrectly... actually appends only when neither substring present; keys like `a/metadatadir` pass through unmodified. Fragile string surgery.
  - Note L151-174: bucket-existence double-checked locking is correct; 404-tolerant head_bucket handling is sound.
  - Note L21, 51-69: strict namespace==bucket validation is a good injection-safety boundary.

### packages/worker/runtime/engine_server.py
- **Verdict:** issues found
- **Findings:**
  - [medium] L300-343: `WatchJob` yields gRPC events *while holding* `state.condition` (the `with` block spans all yields). While the generator is suspended between yields the lock stays held, so worker-side `emit_progress`/`complete` (L44-54) block on a slow event-stream consumer; a stalled client effectively freezes progress reporting and job completion signaling for that job.
  - [low] L265-272: engine token compared with `==` instead of `hmac.compare_digest` — timing side channel; low risk given the token is per-engine-launch on a private network.
  - [low] L160-163: `artifact_upload_url` accepted from job payload and PUT unrestricted (SSRF surface limited to trusted worker, but no host allowlist).
  - [low] L365: 128 MB gRPC message limits configured but preview results (`data_json`, L211) can still be large; memory spike potential bounded only by row_limit.
  - Note L255-263: heartbeat watchdog correctly self-terminates orphaned engines (zombie-prevention at engine level); L368-369 stop-server thread avoids deadlock calling `server.stop` from within an RPC. Good.
  - Note L78-81: completed-job LRU eviction keeps last 8 results; pop-on-fetch (L87-92) prevents leaks.

### packages/worker/runtime/compute_manager.py
- **Verdict:** issues found
- **Findings:**
  - [medium] L555-585: `get_engine_status` calls `engine.check_health()` (Docker daemon RPC) *while holding* `_engines_lock`; a slow/hung Docker call stalls every other engine lookup/spawn/shutdown in the process. Health probing should run outside the lock.
  - [medium] L650-691: `shutdown_all` waits on in-flight spawn events with no timeout (L677-678); a single hung `engine.start()` (e.g. Docker daemon wedged) makes worker shutdown hang forever. Reaper join is bounded (L653) but spawn waits are not.
  - [low] L744-747: reaper deletes engines from the map then `suppress(Exception)` around `shutdown()` — if container stop fails the engine is forgotten by the manager and only recovered later via `reconcile_deployment_containers`; failure is invisible.
  - [low] L360-362: same-identity spawn waiters park on `threading.Event.wait()` with no timeout — serialized by design, but inherits any hang of the spawning thread.
  - [low] L496-508: `acquire_engine` releases the reservation only if the engine is still the mapped one; if a concurrent config restart replaced it, the old `EngineInfo` keeps `active_reservations > 0` forever (harmless post-shutdown, but stale state).
  - Note: overall capacity-admission design (FIFO spawn queue reserving tickets outside the runner pool, idle-eviction under load, ticket transfer start→live at L407-414, cancellation-safe release at L293-301) is careful and race-aware — the strongest file in this unit alongside compute_manager's peers.

### packages/worker/runtime/docker_engine.py
- **Verdict:** issues found
- **Findings:**
  - [medium] L282-381: `start()` holds `self._lock` across the whole container launch including `_await_health()`'s up-to-`engine_start_timeout_seconds` (default 30s) poll loop. Every other call that takes the same lock (`is_process_alive` L433, `_submit`, `get_result`) blocks for the full launch — including the idle reaper and status-snapshot threads iterating all engines.
  - [medium] L643-667: `get_result`'s poll loop calls `is_process_alive()` (a Docker `container.reload()` RPC) roughly 20×/sec per waiting caller for the entire duration of a job — sustained Docker daemon load proportional to number of pollers × job length.
  - [low] L191-193: engine credentials are delivered as an *exec* environment variable (`ENGINE_BOOTSTRAP_JSON`); docker stores exec-create config (incl. env) inspectable via the Docker API until the exec is cleaned up, and it is briefly visible in the container's `/proc`. Better than long-lived env, but not secret-free delivery.
  - [low] L473: one watcher thread per submitted job, unbounded; combined with per-job `WatchJob` streams a burst of submissions creates many concurrent gRPC streams/threads per engine.
  - [low] L363: `grpc.insecure_channel` to the engine — transport unencrypted; per-launch bearer token over the private Docker network only (documented trade-off, worth noting).
  - Note: strong hygiene elsewhere — hardened container defaults (cap_drop ALL, read-only rootfs, no-new-privileges, pids_limit 256, tmpfs size caps, L328-334), secrets staged to tmpfs instead of container env (L182-196), start-failure container removal (L377-381), bounded `_pending_results`/`_pending_progress` maps (L559-560, L584-585), artifact staging cleanup on every error path (L523-528, L639-641, L732-734), graceful→force shutdown ladder with channel/client close (L700-726), and engine-side watchdog env sized off worker heartbeat (L321-323) to prevent orphaned containers.

### packages/worker/runtime/compute_request_runtime.py
- **Verdict:** issues found
- **Findings:**
  - [medium] L96/L155: `next_compute_request` performs a synchronous `claim_compute_request` gRPC call directly on the event loop inside async `_run_once`; a slow data plane stalls the whole worker loop (same pattern flagged in worker_runtime.py).
  - [low] L62-63/L208/L431: new `WorkerRuntimeClient` per claim/iteration/renewal instead of sharing one client — connection churn under load.
  - [low] L183-188: on lease loss mid-execution the runner *waits* for the executor job to finish (`gather(execution)`) without cancelling — wasted pool-thread occupancy after the result can no longer be published.
  - Note L165-201: capacity-first admission with zero-runner queuing + FIFO rejoin on `EngineCapacityFull` (L193-196) is a clean design; lease renewal raced against execution mirrors worker_runtime.py correctly.
  - Note L561-568: shutdown-engine treated as idempotent success when engine missing — matches reconciliation semantics, documented inline.
  - Note L571-601: thorough error mapping (lease-lost drain, 412 retired-lease suppression, status-coded logging).

### packages/worker/runtime/worker_runtime_client.py
- **Verdict:** issues found
- **Findings:**
  - [medium] L142-148/L942: every `client_from_env()` call creates a fresh `WorkerRuntimeClient` with its own gRPC channel and never closes it (callers throughout the codebase construct one per request/iteration — e.g. compute_service.py `_datasource_name` L150, `_create_engine_run` L684). Each unclosed channel keeps background I/O threads and sockets alive until GC; under sustained load this is a slow FD/thread leak.
  - [low] L954-962: registration retry loop sleeps up to 90s with blocking `time.sleep(1.0)`; called from async `build_worker_loop` (worker_runtime.py:40) so a flaky data plane freezes the event loop during retries.
  - [low] L147: plaintext channel with bearer token in metadata (`x-internal-token`); same accepted trade-off as engine RPC.
  - Note: exhaustive gRPC→HTTP status mapping (L976-995), consistent payload validation helpers, and FAILED_PRECONDITION→`BuildJobLeaseLost` translation at lease boundaries (L524-527, L575-578) are well done.

### packages/worker/runtime/compute_service.py
- **Verdict:** issues found
- **Findings:**
  - [high] L1978+L2097: `export_data` loads the entire exported parquet into memory twice (`pq.read_table(tmp_output)` for staging-delivery extraction, then again into `arrow_table`) and appends the full in-memory table to Iceberg (L2121/2125/2128/2131). The whole export path is streaming until this point, then materializes everything in worker RAM — large exports can OOM the worker regardless of engine `max_memory_mb` limits (which apply to the engine process only, not this code).
  - [medium] L2109-2119: incremental builds additionally scan the *previous* table fully into memory (`catalog.load_table(...).scan().to_arrow()`) before appending; combined with the new data that's 2× full-table RAM.
  - [medium] L2411-2446: `download_step` fetches up to 10,000,000 rows through the engine *preview* path — rows serialized as JSON list-of-dicts over gRPC (128 MB message cap at docker_engine/engine_server) — then rebuilds a Polars DataFrame from dicts (L2439) and re-reads the file into bytes (L2445-2446). Multiple full copies of the dataset; downloads of non-trivial datasets will hit the gRPC size limit or balloon memory. An export-format sink path exists and should be used instead.
  - [low] L1938/L1956/L1969/L2259: `run_response` in `export_data` is initialized to None and never assigned — all run-tracking/cancellation-check branches keyed on it are dead code; cancellation detection silently depends solely on `_raise_if_build_cancelled`.
  - [low] L3190-3191, L3354-3355: `asyncio.run_coroutine_threadsafe(...).result()` from executor threads with no timeout — an unresponsive event loop blocks the compute thread indefinitely.
  - [low] L150, L393-396, L684, L866, L874, L889, L919, L1175, L1913, L1998, L2038, L2250, L3632, L3698: ~15 `client_from_env()` constructions per operation, each leaking a gRPC channel (see worker_runtime_client.py finding).
  - Note: otherwise careful orchestration — per-tab failure isolation with stream-task teardown (L3404-3526), build-engine prewarm with admission queueing (L2901-2920), guaranteed build-engine shutdown after builds (L3611-3620), critical-healthcheck gating (L2017-2032), claim-scoped table names to isolate concurrent publications (L2068-2070).

### packages/worker/runtime/iceberg_metadata.py
- **Verdict:** issues found
- **Findings:**
  - [low] L110/L113-122: "latest" metadata file selection is plain lexicographic sort of `*.metadata.json`. Safe for PyIceberg's zero-padded `%05d` version names, but silently picks an *older* file if any producer writes unpadded versions (`v10` < `v2`). A comment or numeric sort would make the assumption explicit.
  - Note L38-40: local-path resolution enforces containment under the namespace data root via resolved parents — solid path-traversal guard; explicit rejections for `.db`, non-metadata files, missing paths are thorough.

### packages/worker/runtime/logging.py
- **Verdict:** ok
- **Findings:** 15-line basicConfig wrapper with validated LOG_LEVEL; fail-fast on invalid values.

### packages/worker/runtime/notification_delivery.py
- **Verdict:** issues found
- **Findings:**
  - [low] L74-77/L80/90/106: `_api_client()` creates a new `WorkerRuntimeClient` (unclosed gRPC channel) per call when no client injected — same channel-leak pattern as elsewhere.
  - Note L23-39: staged-delivery extraction validates column payload shape and drops staged columns before publication; clean design.

### packages/worker/runtime/protocol_mapping.py
- **Verdict:** issues found
- **Findings:**
  - [low] L28: `optional_timestamp_to_datetime` returns a *naive* datetime (`ToDatetime()` without tz); callers must remember to attach UTC (worker_runtime_client.py L183-184 does, but the helper invites naive-datetime bugs).
  - Note: strict enum round-tripping rejects UNSPECIFIED (L35-40); schema_info proto/payload conversion is symmetric and well-validated.

---

## Unit 09 summary
- **Top issue:** export/download paths in compute_service.py materialize entire datasets in worker RAM multiple times (pq.read_table ×2, incremental previous-table scan, 10M-row JSON preview download), bypassing all engine resource limits.
- **Systemic pattern:** unclosed `WorkerRuntimeClient` gRPC channels created per call/iteration across ~8 modules (slow FD/thread leak), plus synchronous gRPC calls on the asyncio event loop in worker loops.
- **Resource limits:** engine CPU/memory limits are soft — RLIMIT_AS best-effort in subprocess mode (compute_engine.py:534), container mem_limit only in Docker mode, and worker-side export aggregation is unlimited.
- **Cleanup/zombie handling is strong overall:** Docker engine watchdog + reconcile loop, graceful→force shutdown ladders, bounded pending maps, artifact staging cleanup, capacity admission with cancellation-safe release.
- **One correctness landmine:** PEP 758 unparenthesized `except A, B:` (compute_monitor.py:27, compute_service.py:454) requires Python ≥3.14 toolchain everywhere.

### packages/worker/runtime/compute_engine.py
- **Verdict:** issues found
- **Findings:**
  - [medium] L529-537: subprocess memory limit (`RLIMIT_AS`) is best-effort: a failed `setrlimit` only logs a warning and the job runs with **no** memory cap; on macOS RLIMIT_AS is also notoriously ineffective against malloc reservations, so "max_memory_mb" enforcement cannot be relied on cross-platform. No verification the limit took effect.
  - [low] L311-317: `_wait_for_queue_message` reaches into the private `queue._reader` attribute of `multiprocessing.Queue` — implementation detail that can break on CPython upgrades (fallback path exists but changes semantics to blocking `get`).
  - [low] L231-241: `_send_command` assigns `self.current_job_id = command.job_id` *before* `check_health()`/`start()`; if start raises, `current_job_id` references a job that was never enqueued and no process exists (capacity slot held until next successful cycle).
  - [low] L356-361, L387-389, L421-429: `_pending_results`/`_pending_progress` mutated from multiple service threads with no lock — GIL-masked today, fragile pattern.
  - Note: shutdown ladder is exemplary (graceful ShutdownAck → join → terminate → kill → close, L451-491); `_close_queues` properly releases semaphore/resource-tracker state (L492-502, plus `__del__`); dead-process detection resets state and frees capacity notifier (L157-176); pipeline builder validates DAG (multi-dep rejection L742-748, cycle detection L776-777).


---

# Unit 10: worker runtime domain

### packages/worker/runtime/domain/__init__.py
- **Verdict:** ok

### packages/worker/runtime/domain/domain_enums.py
- **Verdict:** issues found
- **Findings:**
  - [low] `read()` at lines 81–87 silently swallows invalid values whenever a `default` is supplied (e.g. `BuildStatus.coerce` maps any garbage string to SUCCESS). This is intentional coercion but masks data corruption; callers get no signal that an unknown enum value was seen.
  - [low] Base class declares `_token_by_number` etc. as `ClassVar` (lines 17–20) but they are only initialized in `__init_subclass__` (lines 22–26); accessing them on `DomainEnumValue` itself raises AttributeError. Harmless in practice since only subclasses are used.
  - [low] `__eq__`/`__hash__` overrides (lines 40–44) just delegate to `str` and are redundant given `str.__new__` subclassing — noise only.

### packages/worker/runtime/domain/enums.py
- **Verdict:** issues found
- **Findings:**
  - [medium] Dead code: `DataForgeStrEnum` here has no importers anywhere in the repo (`rg "runtime\.domain\.enums"` returns nothing); every consumer imports the duplicate copy from `backend_core.domain.enums`. Two divergent copies of the same base class exist; this one should be deleted per the project's no-compat-layer principle.
  - [low] `read()` (lines 23–36) has redundant control flow: the `default is not None` check is duplicated at lines 30–31 and 34–35, and a non-str/non-None invalid value falls through to line 34 rather than raising immediately — correct outcome but confusing to maintain.

### packages/worker/runtime/domain/analysis/__init__.py
- **Verdict:** ok

### packages/worker/runtime/domain/analysis/models.py
- **Verdict:** issues found
- **Findings:**
  - [low] `AnalysisStatus` has zero usages inside the worker package (backend uses its own copy at `backend_core/domain/analysis/models.py`). Dead duplicate in the worker domain.

### packages/worker/runtime/domain/analysis/pipeline_types.py
- **Verdict:** issues found
- **Findings:**
  - [medium] Silent-degradation parsing: `PipelineStep.from_dict` (lines 18–27), `TabDatasource.from_dict` (42–44), and `PipelineTab.from_dict` (86–97) coerce missing/mistyped `id`, `type`, `config`, `depends_on` to empty defaults (`""`, `{}`, `[]`) instead of raising. A corrupted pipeline row round-trips as a structurally valid pipeline with blank step ids/types, deferring failure to execution with poor diagnostics. The pydantic counterpart (`compute/schemas.py:118–147`) correctly rejects these — inconsistent validation contracts between the two parsers of the same JSON shape.
  - [low] This worker copy of `pipeline_types` is unused within the worker package (only `backend_core.domain.analysis.pipeline_types` is imported anywhere, e.g. `packages/backend/modules/analysis/service.py:19`). Duplicated dead module.

### packages/worker/runtime/domain/analysis/step_types.py
- **Verdict:** issues found
- **Findings:**
  - [low] `StepTypes._definition_for` (lines 189–194) does a linear scan over all ~37 fields on every lookup, and it is called repeatedly by `has`/`normalized`/`chart_type`/`label`/`dependency_config_keys` (including inside loops via `dependency_values`, lines 226–234). A dict keyed by value built once in `__init_subclass__`-style setup would be O(1); minor but hot-path adjacent.
  - [low] `timing_key` (lines 242–249): regex `^(?P<base>.+?)_(?P<index>\d+)$` strips any trailing numeric suffix, so a legitimate step type ending in digits would be mis-split into a nonexistent base label. Currently no such type exists, so latent only.
  - [low] Module-level mutable singleton pattern (`STEP_TYPES = StepTypes()` line 252 plus module functions) makes the class methods and free functions redundant dual APIs; maintainability nit.

### packages/worker/runtime/domain/build_jobs/__init__.py
- **Verdict:** ok

### packages/worker/runtime/domain/build_jobs/live.py
- **Verdict:** ok
- Trivial module-level `VersionHub` singleton; consumers import it directly (`runtime_notifications.py:3`).

### packages/worker/runtime/domain/build_jobs/models.py
- **Verdict:** ok
- State set QUEUED→LEASED→RUNNING→terminal with `is_active`/`is_reclaimable` consistent (lines 17–23).

### packages/worker/runtime/domain/build_runs/__init__.py
- **Verdict:** ok

### packages/worker/runtime/domain/build_runs/models.py
- **Verdict:** issues found
- **Findings:**
  - [low] `to_build_lifecycle_status` (lines 22–33) ends with an unconditional fallthrough returning `(FAILED, "Build orphaned during startup recovery")` for anything not matched above — currently only ORPHANED, but adding a new status would silently map it to FAILED with a misleading orphan message instead of failing loudly. An exhaustive match or assertion would be safer.

### packages/worker/runtime/domain/compute/__init__.py
- **Verdict:** ok

### packages/worker/runtime/domain/compute/base.py
- **Verdict:** issues found
- **Findings:**
  - [low] `EngineStatusInfo` (lines 115–138) duplicates field-for-field the pydantic `EngineStatusSchema` in `compute/schemas.py:180–204` (same for command/result types vs. build event schemas). Two parallel definitions of the same wire shape must be kept in sync by hand; drift risk.
  - [low] `OperationHandler.__call__` body `raise NotImplementedError` (line 24) in a `Protocol` is dead — protocol methods are never called on the protocol itself; harmless convention noise.

### packages/worker/runtime/domain/compute/schemas.py
- **Verdict:** issues found
- **Findings:**
  - [medium] `BuildStatus.coerce` (lines 264–266) defaults unknown/unparseable values to SUCCESS — the one fallback direction that can turn corrupt data into a false positive result. Compare `BuildLifecycleStatus.coerce` (313–315) which safely falls back to non-terminal QUEUED. BuildStatus should fall back to WARNING or raise.
  - [low] `AnalysisPipelineTab.validate_steps` (lines 118–147): the `isinstance(value, list)` check at line 121 is unreachable (pydantic already guarantees `list[dict]`), and `validate_output`'s isinstance at 152 likewise; redundant guards obscure the real checks.
  - [low] `BuildRunDetail.cancel_duration_ms` (lines 489–492) assumes naive datetimes are UTC (`replace(tzinfo=UTC)`); if a naive local-time value ever reaches it the elapsed computation is silently wrong. Convention-dependent, unenforced.
  - [low] `BuildStarter.for_user` (lines 378–382) uses `getattr(user, "id", None)` duck-typing against `object`; a typo'd attribute yields silent None instead of an error.
  - [low] `BuildEventType.throttle_seconds` (lines 563–571) embeds transport/presentation throttling policy in a domain enum; belongs in the streaming layer.
  - [low] `BuildRunSummary.progress` (line 459) and `BuildProgressEvent.progress` (line 646) are unconstrained floats — no 0..1 validation despite being used as fractions (e.g. `progress=1.0` default at line 673).

### packages/worker/runtime/domain/compute_requests/live.py
- **Verdict:** ok
- Trivial singleton, same pattern as build_jobs/live.py.

### packages/worker/runtime/domain/datasource/__init__.py
- **Verdict:** ok

### packages/worker/runtime/domain/datasource/models.py
- **Verdict:** ok

### packages/worker/runtime/domain/datasource/source_types.py
- **Verdict:** issues found
- **Findings:**
  - [low] `DataSourceFileType.matches_magic_number` (lines 75–82) returns `True` for CSV/JSON/NDJSON unconditionally — fine for text formats, but EXCEL's `b"PK"` prefix also matches any ZIP-based file (docx, jar), so a mislabeled .xlsx passes magic check. Acceptable heuristic; worth a comment.
  - [low] `upload_suffixes` (lines 36–49) ends with `raise AssertionError` after an exhaustive match over a closed enum — if a new member is added without updating the match, failure surfaces only at runtime. Consistent with project style, noting only.
  - [low] `DataSourceType.category` (lines 109–115) classifies ICEBERG under FILE category; SCHEDULE/ANALYSIS both fall to ANALYSIS. Verified intentional by usage in `operations/datasource.py`, but the implicit default branch means a newly added DataSourceType silently lands in ANALYSIS.

### packages/worker/runtime/domain/engine_instances/__init__.py
- **Verdict:** ok

### packages/worker/runtime/domain/engine_instances/models.py
- **Verdict:** issues found
- **Findings:**
  - [medium] Unreachable states in the state machine: `from_engine_status` (lines 28–35) can only ever return RUNNING, IDLE, or STOPPED — STARTING, STOPPING, and FAILED are never produced anywhere in non-test code (`rg "EngineInstanceStatus\.(STARTING|STOPPING|FAILED)"` outside tests hits only this file and its backend twin). Yet `is_active` (19–20) and `overview_status` (22–26) branch on them, giving the appearance of a richer lifecycle than exists. Either wire the transitions or remove the members.
  - [low] `overview_status` (lines 22–26) returns a bare `str` ("healthy"/"terminated") rather than a domain enum value, inconsistent with every other status mapping in the package.
  - [low] TERMINATED engine status always maps to STOPPED (line 35), conflating clean shutdown with crash/OOM termination; the richer detail lives only in `EngineStatusSchema.lifecycle_status`.

### packages/worker/runtime/domain/engine_runs/__init__.py
- **Verdict:** ok

### packages/worker/runtime/domain/engine_runs/schemas.py
- **Verdict:** issues found
- **Findings:**
  - [low] `RunSummary.extract_result_fields` (lines 171–186): `int(rc)` at line 181 accepts bools (`isinstance(True, int)` is True so bools pass through as-is) and truncates floats; also `row_count` stored as a non-numeric string would raise ValueError mid-validation with an unhelpful message. Minor robustness gap in a best-effort extractor.
  - [low] `blocks_transition_to` (lines 37–38) permits re-setting the same terminal status (`next_status != self`) — idempotent-update convenience, but it also means a run can be "re-failed" with different error content without detection. No transition enforcement exists beyond this helper; correctness depends entirely on call sites.
  - [low] `EngineRunResultSummary.row_count` typed `int | str | None` (line 100) — the `str` arm papers over upstream type inconsistency rather than normalizing at the boundary.

### packages/worker/runtime/domain/healthcheck_models.py
- **Verdict:** ok
- Enum + two classification properties; used by `runtime/healthchecks.py`. No issues verified.

### packages/worker/runtime/domain/runtime/__init__.py
- **Verdict:** ok

### packages/worker/runtime/domain/runtime/events.py
- **Verdict:** ok
- `RuntimePayloadKind.from_payload` (lines 16–24) correctly returns None for missing/unknown kinds; consumed defensively in `runtime_notifications.py`.

### packages/worker/runtime/domain/runtime_workers/__init__.py
- **Verdict:** ok

### packages/worker/runtime/domain/runtime_workers/models.py
- **Verdict:** ok

### packages/worker/runtime/domain/scheduler/__init__.py
- **Verdict:** ok

### packages/worker/runtime/domain/scheduler/schemas.py
- **Verdict:** issues found
- **Findings:**
  - [medium] Validation gap on partial updates: `ScheduleUpdate.validate_trigger` (lines 39–43) only rejects when both fields are present in the same payload. Because pydantic cannot distinguish "field omitted" from "field explicitly None" here (both become None), a client cannot clear `depends_on` or `trigger_on_datasource_id`, and more importantly the service layer applying a partial update onto an existing row can produce a persisted schedule with both triggers set even though each individual payload was valid. The invariant is enforced at the wrong layer.
  - [low] `cron_expression` (lines 16, 33) is a free-form string with no syntax validation in either schema; validity is deferred to `croniter` at scheduling time (`scheduler/service.py:504`), so an invalid cron is accepted at create/update and fails later. An early `ScheduleCreate` validation would give immediate feedback.
  - [low] Neither schema validates that `depends_on` ≠ self or that `datasource_id` is non-empty beyond pydantic's str requirement (no `min_length`).


---

# Unit 11: worker operations

### packages/worker/operations/__init__.py
- **Verdict:** ok
- **Findings:** none — registry wiring consistent between HANDLERS and PARAM_MODELS.

### packages/worker/operations/datasource.py
- **Verdict:** issues found
- **Findings:**
  - [medium] DatasourceParams uses `extra="allow"` (line 19), so arbitrary fields (including secrets like passwords/tokens passed by callers) are silently accepted into params and flow into `model_dump(mode="json")` at lines 75-84 and into analysis-cache key payloads; no redaction or strict schema for credential-bearing configs (`connection_string` line 37).
  - [low] `_resolve_tab_chain` builds `output_map` (lines 205, 212) that is never used — dead code alongside the identical `output_to_tab` map built at 203/220.
  - [low] Module-level `_ANALYSIS_CACHE` (lines 99-102) caches LazyFrames keyed by pipeline JSON hash forever until LRU cap; cached plans can go stale if underlying datasources change, and there is no invalidation hook.
  - [low] `_build_tab_pipeline` reaches into `PolarsComputeEngine._apply_step` private method (line 289) — tight coupling to engine internals, fragile across refactors.

### packages/worker/operations/ai.py
- **Verdict:** issues found
- **Findings:**
  - [medium] `api_key` is accepted as a plain pipeline param (line 121) and forwarded per request (lines 93, 185); credentials embedded in step params risk exposure in logs/persisted pipeline definitions — no redaction anywhere in this module.
  - [medium] Network LLM calls with blocking `time.sleep` retries/backoff run inside `lf.map_batches` (lines 172-271); Polars may execute this on multiple threads/streams concurrently, so the rate limiter (`last_call_ts`, line 189) is per-invocation and does not actually enforce a global RPM limit.
  - [low] Dead code: after a final failed attempt both `results` and `errors` are extended equally (lines 237-238), so the guard at lines 250-251 can never trigger.
  - [low] Broad `except Exception` at line 225 swallows all errors into data values (`[error: ...]` markers), which converts hard failures (auth, quota) into silent data-quality issues; only logged, never surfaced as operation failure.

### packages/worker/operations/deduplicate.py
- **Verdict:** ok
- **Findings:** none — thin wrapper; note `maintain_order=True` (line 22) blocks parallelism but is intentional for determinism.

### packages/worker/operations/download.py
- **Verdict:** ok
- **Findings:** none — pass-through that validates params only.

### packages/worker/operations/drop.py
- **Verdict:** ok
- **Findings:** none.

### packages/worker/operations/explode.py
- **Verdict:** ok
- **Findings:** none.

### packages/worker/operations/export.py
- **Verdict:** issues found
- **Findings:**
  - [low] `iceberg_options` (line 13) is validated but never inspected here; if it carries storage credentials they pass through unvalidated — actual export handling lives elsewhere, so this is a passthrough with no guardrails.

### packages/worker/operations/expression.py
- **Verdict:** issues found
- **Findings:**
  - [medium] AST sandbox permits `getattr` on any object whose type's `__module__` starts with `"polars"` (line 118) and calls of any reachable callable (lines 121-129); safety rests entirely on the polars API surface staying free of escape hatches (e.g. anything reaching `eval`/filesystem/`pl.io`). Combined with `validate_no_reflection_escape` this is defense-in-depth-lite rather than a real capability sandbox — acceptable for a no-code product but worth documenting as trusted-user-only.
  - [low] Attribute check at line 113 blocks leading-underscore access, good; but non-whitelisted third-party objects returned by polars calls would be caught by line 118-119 only after being fully constructed by `target(*args, **kwargs)` at line 129 — side effects of allowed calls execute before validation completes.

### packages/worker/operations/validation.py
- **Verdict:** issues found
- **Findings:**
  - [low] `validate_no_reflection_escape` (lines 29-36) is a naive substring blacklist over raw source text: it false-positives on innocuous content (e.g. a string literal containing `"type("` or `"__"`) and is trivially bypassable in principle (`getattr` spelled via unicode/concatenation won't appear literally). It's only safe because callers (expression.py) do structural AST whitelisting; as a standalone guard it would be inadequate.

### packages/worker/operations/enums.py
- **Verdict:** issues found
- **Findings:**
  - [low] `DurationUnit.every_token` (lines 451-466) raises for NANOSECONDS/MICROSECONDS/MILLISECONDS members that are defined at lines 475-477 — three enum values exist that can never be used in an every-token context; either dead members or a latent crash depending on call path.
  - [low] `OperationEnumValue.__eq__` compares via `int.__eq__` only (lines 42-43); comparing against a token string returns False rather than raising or normalizing — mildly surprising given `.value` returns the token.
  - File is otherwise mechanical token wiring from protobuf descriptors; verbose but consistent.

### packages/worker/operations/filter.py
- **Verdict:** issues found
- **Findings:**
  - [medium] `FilterCondition.normalize_many` silently drops malformed conditions (lines 105-106 when column empty, 122-123 when COLUMN type lacks compare_column) instead of raising — a user's filter is quietly ignored, changing query semantics without any error signal.
  - [low] Regex patterns are compiled for validation (validation.py:24) but Python `re` has no complexity limits; pathological REGEX filter values (line 70, `literal=False`) can cause catastrophic backtracking at execution time.
  - Otherwise well structured: schema-aware datetime coercion (lines 172-193), literal contains by default (lines 66-67), regex validated.

### packages/worker/operations/groupby.py
- **Verdict:** ok
- **Findings:** none — clean table-driven design; `maintain_order=True` (line 80) trades parallelism for determinism, consistent with deduplicate.py.

### packages/worker/operations/join.py
- **Verdict:** issues found
- **Findings:**
  - [low] Column-selection logic at lines 71-87 is convoluted: `selected_columns` starts as `set(left_columns)` and `selected_right_columns` duplicates `set(right_columns)`; the branch at line 80 is effectively unreachable since `column` is drawn from `right_columns`. Works but hard to reason about.
  - [low] Lines 50-51 filter `left_column`/`right_column` independently when building join keys, so a half-populated `JoinColumn` pair silently misaligns `left_on`/`right_on` instead of failing validation.

### packages/worker/operations/limit.py
- **Verdict:** ok
- **Findings:** none (trivial slice wrapper).

### packages/worker/operations/notification.py
- **Verdict:** issues found
- **Findings:**
  - [medium] Telegram `bot_token` accepted as plain pipeline param (line 20) and embedded into staged delivery payloads (line 118); credentials persisted with pipeline definitions/staged outbox rows without redaction.
  - [low] `get_resolved_telegram_settings` (lines 10-11) is a misleading stub that always returns `{"enabled": True}` regardless of actual configuration — dead or dangerous depending on callers.
  - [low] Broad `except Exception` per row (line 124) turns all failures into `[error: ...]` status strings; misconfiguration (e.g. missing recipient) never fails the operation.

### packages/worker/operations/pivot.py
- **Verdict:** issues found
- **Findings:**
  - [low] `_auto_on_columns` (line 20) triggers a full `.collect()` of a unique scan during lazy-plan construction — eager execution inside a supposedly lazy pipeline; bounded by the 200-value cap but still forces materialization and can be expensive on large frames.
  - [low] Accepts camelCase fallback `params.get("onColumns")` (line 39) alongside the pydantic field — dual naming convention handled ad hoc outside the schema.

### packages/worker/operations/plot.py
- **Verdict:** issues found
- **Findings:**
  - [medium] `_build_histogram` (lines 412-465) eagerly `.collect()`s the entire cast column into memory (line 416), then computes bin counts with a Python loop of `df.filter(...).height` per bin (lines 445-450) — O(bins × N) repeated scans and full materialization where a single lazy `group_by` on a bucket expression would do; large datasets will be slow/memory-heavy.
  - [low] `compute_overlay_datasets` collects each overlay independently (line 169) — N overlays means N full recomputations of the source pipeline with no shared caching.
  - [low] Coerce validators silently swallow invalid `sort_by`/`group_sort_by` strings to `None` (lines 94-97, 106-109) — user typos in chart config are silently ignored rather than reported.
  - [low] `_apply_date_bucket` line 262 converts Utf8 x-column with `str.to_datetime(strict=False)` producing nulls for unparseable values without warning; those rows then vanish from aggregations.

### packages/worker/operations/rename.py
- **Verdict:** ok
- **Findings:** none.

### packages/worker/operations/sample.py
- **Verdict:** ok
- **Findings:** none — deterministic hash-of-row-index sampling; note it samples by position so results change if upstream ordering changes (documented behavior trade-off, not a bug).

### packages/worker/operations/select.py
- **Verdict:** ok
- **Findings:** none — validates cast_map keys against selected columns before casting.

### packages/worker/operations/sort.py
- **Verdict:** ok
- **Findings:** none.

### packages/worker/operations/step_converter.py
- **Verdict:** issues found
- **Findings:**
  - [low] Params are validated twice per step: once via `PARAM_MODELS[...].model_validate(...)` in `convert_step_format` (lines 260-267) and again inside each handler's `__call__`; redundant work on every pipeline build, though it does keep converter and handler honest.
  - [low] `model_dump(mode="json", exclude_none=True)` (lines 263-266) serializes whatever extras were allowed into params (relevant for `DatasourceParams` extra="allow") — same credential-passthrough concern as datasource.py.
  - Otherwise thorough: strict unknown-field rejection (lines 133-135, 182-184), step-type/config cross-validation (lines 124-126, 157-158).

### packages/worker/operations/template_placeholders.py
- **Verdict:** ok
- **Findings:** none — simple regex substitution; unknown placeholders left verbatim by design.

### packages/worker/operations/strings.py
- **Verdict:** issues found
- **Findings:**
  - [low] Regex patterns validated then used with `replace_all` (lines 63-67); same unbounded-backtracking caveat as filter.py, though input is user-authored transform config.
  - [low] `validated.start or 0` / `group_index or 0` / `index or 0` (lines 59, 73, 79) use truthiness instead of `is not None` — harmless today since 0 is the intended fallback, but fragile if sentinels change.

### packages/worker/operations/timeseries.py
- **Verdict:** issues found
- **Findings:**
  - [medium] TIMESTAMP branch (lines 69-75): any unit other than NANOSECONDS/MILLISECONDS — including explicitly requested SECONDS, MINUTES, HOURS, DAYS, WEEKS, MONTHS — silently returns microseconds (`"us"`), because those fall through to the default. Should reject unsupported units instead of returning wrong-magnitude values.
  - [low] Line 87: `direction == TimeDirection.SUBTRACT` flips ADD/OFFSET into subtraction even when `operation_type` is ADD — direction and operation_type can contradict each other with no validation.

### packages/worker/operations/topk.py
- **Verdict:** ok
- **Findings:** none.

### packages/worker/operations/type_casting.py
- **Verdict:** ok
- **Findings:** none — small, clear mapping; `cast_value` silently no-ops on unknown type names (line 23) but `require_polars_type` covers the strict path.

### packages/worker/operations/unpivot.py
- **Verdict:** ok
- **Findings:** none — alias handling (`id_vars`/`value_vars`) is simple and correct; note `index or id_vars` silently prefers `index` if both given rather than rejecting the conflict.

### packages/worker/operations/view.py
- **Verdict:** ok
- **Findings:** none (pass-through).

### packages/worker/operations/with_columns.py
- **Verdict:** issues found
- **Findings:**
  - [high] UDF path executes arbitrary user Python via `exec(expr.code, ...)` (line 101) with the full `pl` namespace in scope (line 96). The guard is only a substring blacklist (`validate_no_reflection_escape`) plus a builtins allowlist, but polars itself exposes arbitrary file I/O (`pl.scan_csv`/`read_ipc`/`read_database`), network access, and `pl.api`/`SQLContext` — so this is effectively unrestricted code execution on the worker (file read/write, DB connections), not a sandbox. The comment at line 17 overstates the containment. Safe only if UDF authors are fully trusted; dangerous if any multi-tenant/untrusted input reaches `code`.
  - [medium] Substring blacklist also blocks legitimate UDF code containing `"__"` or the word `type(` inside string literals/comments (validation.py lines 5-18) — spurious failures with confusing error messages.
  - [low] Line 118 builds a constant column by calling `fn()` once per row via `map_elements` over `int_range` — O(N) Python calls for a constant; a single call + `pl.lit` would do.
  - [low] `time.sleep` explicitly injected into UDF scope (line 97) lets UDFs stall the compute thread arbitrarily.

### packages/worker/operations/fill_null.py
- **Verdict:** issues found
- **Findings:**
  - [low] `_resolve_statistical_columns` indexes `schema[column]` directly (line 66) without checking membership — a nonexistent column name raises a raw `KeyError` instead of a clear validation error like other handlers produce.
  - [low] Literal fill with no `columns` applies the same value to every column in the frame (line 98) — dtype mismatches surface only as opaque execution errors.

### packages/worker/operations/union.py
- **Verdict:** ok
- **Findings:** none — clean schema-alignment handling for both diagonal and strict vertical concat.


---

# Unit 12: worker datasources, builds, gRPC & tests

### packages/worker/datasources/__init__.py
- **Verdict:** ok
- Trivial re-export module.

### packages/worker/datasources/datasource_loading.py
- **Verdict:** issues found
- **Findings:**
  - [high] `_assert_select_only` (lines 135–138) is a weak guard, not real protection: (a) it only inspects the *first* token, so multi-statement strings like `SELECT 1; DELETE FROM t` pass, and psycopg/`pl.read_database` will execute them (connection opened with `autocommit=True`, line 204); (b) Postgres allows data-modifying CTEs, so `WITH x AS (...) DELETE FROM t` starts with `WITH` and is accepted while being destructive. The check is presented as a security boundary ("Only SELECT queries … are permitted") but does not enforce it.
  - [medium] Same weak check gates DuckDB queries (line 213); DuckDB additionally allows attaching/read functions in queries (`read_csv_auto(...)`) which the token check cannot constrain — arbitrary file access from a user-supplied query depends entirely on this broken gate.
  - [low] `_as_int` (lines 22–23) converts `bool` to `int` (`True` → `1`), so `skip_rows=true` silently becomes 1 instead of being rejected.
  - [low] Line 42: `_as_int(..., default=0) or 0` — the trailing `or 0` is redundant given `default=0`.
  - [low] Lines 168–178 / 183–193: the `match` arms return directly, so the `raise ValueError(f"Unsupported file type…")` at line 194 is unreachable for enum members but reachable if `DataSourceFileType.read` ever yields an unexpected value; control flow relies on exhaustiveness that Python does not enforce (no `case _`). Minor robustness nit.

### packages/worker/datasources/schemas.py
- **Verdict:** ok
- Plain Pydantic DTOs; no logic of concern.

### packages/worker/builds/__init__.py
- **Verdict:** ok
- Empty/trivial package init.

### packages/worker/builds/build_execution.py
- **Verdict:** issues found
- **Findings:**
  - [low] Lines 110–143: `build`, `pipeline`, `starter` are assigned concrete values before the guard at line 142 (`if build is None or pipeline is None or starter is None: return`) — the guard is dead code left over from an earlier structure; misleading.
  - [low] Lines 87, 180, 212: reaches into `service._utcnow()` (private symbol of `runtime.compute_service`) instead of the public `runtime.time.utc_now` used by `build_live.py:17`; inconsistent and couples to a private name.
  - [low] Lines 238–255: `while True:` retry on `EngineCapacityFull` has no backoff or attempt cap; correctness relies entirely on `await_spawn_admission` blocking. A fast-failing admission path would spin.
  - [low] Lines 101 vs 226: internal-error builds emit a generic `"Build failed due to an internal error"` to users, but schedule-ingest failures emit raw `str(exc)` — inconsistent error-surfacing policy between the two paths in the same file.
  - Note (ok): lease fencing is handled consistently — every RPC passes `claim_token` + `lease_generation`, and `None` returns / `BuildJobLeaseLost` are surfaced (lines 44–45, 122–123).

### packages/worker/builds/build_live.py
- **Verdict:** issues found
- **Findings:**
  - [medium] `RuntimeBuildRegistry.publish` / `add_watcher` (lines 508–553) key watchers by `build_id` only, with no namespace scoping or per-socket authorization check inside the registry; any WebSocket that learns a `build_id` receives that build's full event stream (logs, query plans, results). Whether this is exploitable depends entirely on route-level auth outside this unit — flagging as defense-in-depth gap.
  - [low] `_prune_finished_locked` lines 616–619: pruning pops `_tasks[build_id]` without cancelling; if a build reached terminal status while its asyncio task is somehow still running, the task continues untracked (no handle to cancel later via `clear()` either, since entry is gone).
  - [low] `publish` line 549: `publish_list_snapshot` is awaited after *every* published event, including high-frequency LOG/PROGRESS events — each call takes the lock, prunes, sorts builds, and serializes a snapshot. Chatty under load; consider only on state-changing events.
  - [low] `_consume_throttled` (lines 105–118): a throttled event of type X is flushed when the *next* event of the same type arrives, but if no further event of that type ever arrives (e.g. last PROGRESS before COMPLETE), the delayed payload is silently dropped unless a terminal event flushes it (terminal does flush all, line 110–113 — mitigates). Minor.
  - Note (ok): log sanitization (`_sanitize_log_message`, lines 70–80) strips ANSI escapes and control chars and caps length — good hygiene for WebSocket-delivered engine output.

### packages/worker/worker_grpc/__init__.py
- **Verdict:** ok
- Trivial package init.

### packages/worker/worker_grpc/data_plane_server.py
- **Verdict:** issues found
- **Findings:**
  - [medium] Token comparison at line 98 (`metadata.get(_TOKEN_METADATA_KEY) != settings.internal_api_token`) is not constant-time; use `hmac.compare_digest`. Also the whole auth model is a single static shared token over an insecure (plaintext) port (line 322) — acceptable only if the deployment guarantees a private network; nothing enforces or documents that here.
  - [medium] Containment is inconsistent across the ObjectStore surface: `DeleteObject`/`DeletePrefix` verify `is_managed_object_store_url` (lines 161–162, 191–192), but `UploadBytes` (148), `DownloadBytes` (154), `DeleteObject` aside, `Exists` (166), `ListPrefixes` (171), `ListMetadataFiles` (180) accept arbitrary URLs — a caller holding the internal token can read/write/list anywhere the worker's S3 credentials can reach, including outside the managed bucket/prefix.
  - [low] `IcebergServicer.ScanSnapshot` line 280 passes `storage_options=None` while every other Iceberg path in this file/package supplies `object_store.object_store_storage_options()` (cf. line 239, `datasource_loading.py:250–256`); snapshot scans of remote tables relying on explicit storage options will fail or silently behave differently on this RPC path.
  - [low] `ScanSnapshot` lines 280–282: when `limit` is unset the entire snapshot is `.collect().to_dicts()`-ed into memory before serialization; the 128 MB gRPC message cap bounds the response but not the peak memory of the collect.
  - [low] Auth is enforced per-method by remembering to call `_require_internal_token`; the validation interceptor (lines 27–52) wraps all unary-unary handlers but does not participate in auth. A future RPC method that omits the call would be silently unauthenticated — an auth interceptor would remove this footgun.
  - [low] `StorageOptions` RPC (lines 132–141) hands out `s3.secret-access-key` to any token-holder; fine for a strictly internal data plane, but it makes the token equivalent to the worker's cloud credentials — raises the stakes of the static-token design above.
  - Note (ok): fails closed when `INTERNAL_API_TOKEN` is unset (lines 94–95); delete operations are prefix-fenced; protovalidate interceptor applied server-wide.

### packages/worker/main.py
- **Verdict:** issues found
- **Findings:**
  - [medium] Scale-down/stop path blocks the event loop: `_stop_worker_process` (lines 180–201) performs synchronous `stopped_signal.wait` + `process.join` for up to ~8 s per child, and is called from the async manager loop at line 291 and lines 310–311. With several children this stalls heartbeats, request lanes, and the gRPC data plane for tens of seconds.
  - [low] Lines 283–285 + 271: a child that dies immediately (bad env, import error) is reaped and respawned on the next ~0.1 s tick with no backoff or respawn cap — a crash-looping child produces a tight spawn/fail cycle and repeated `reconcile_deployment_containers` calls.
  - [low] Line 75: `_manager_heartbeat_loop` always reports `active_jobs=0`; if the backend uses this field for autoscaling/placement of build work, the manager misreports load whenever its children hold jobs.
  - [low] Lines 141–147: on worker-process exit, `local_stop.set()` then awaits the build-worker task with no timeout (`asyncio.gather(task)`); a hung claim/poll loop would hang process shutdown indefinitely (the manager path has the same shape but at least orders `manager.shutdown_all()` first).
  - [low] Lines 293–303: the idle-wait block ends in `continue` on both branches; the `if stop_task in done` branch is redundant, and the whole block could be a plain sleep-with-stop-race. Cosmetic complexity.
  - Note (ok): escalation ladder (cooperative → terminate → kill) with ack signal is sound; shutdown ordering comment at lines 312–314 documents a real deadlock avoidance.

### packages/worker/engine_main.py
- **Verdict:** issues found
- **Findings:**
  - [low] Lines 21–23: every string key/value in the bootstrap JSON is copied into `os.environ` with no allowlist or name validation; the file is a mounted secret so trust is implicit, but a malformed file silently overrides arbitrary worker env vars. Deletion-after-read (`path.unlink`, line 24) is good credential hygiene.

## packages/worker/tests/ (lighter pass)

Overall: test quality is good — assertions target real behavior (values, call args, error codes), fakes/monkeypatching is used appropriately, and several suites (`test_iceberg_build_modes.py`, `test_data_plane_server.py`, `test_pipeline_disabled_steps.py`, `test_compute_monitor.py`) verify meaningful edge cases rather than mocking everything. Findings:

### packages/worker/tests/conftest.py
- **Verdict:** ok
- Minimal fixture; fine.

### packages/worker/tests/test_fixes.py
- **Verdict:** issues found
- **Findings:**
  - [medium] `TestAssertSelectOnly` (lines 1803–1830) tests only the happy path and trivial rejections; the actual bypasses (`SELECT 1; DROP TABLE t`, `WITH x AS (...) DELETE FROM t`, leading SQL comments) are untested — consistent with the guard being weaker than its docstring claims (see datasource_loading.py finding).
  - [low] File is a 1,882-line grab-bag ("Tests for bug fixes and new features") mixing plot rendering, protocol mapping, runtime regressions, validation, and datetime coercion; once a fix lands, its test should move next to the feature's suite, not accrete here.

### packages/worker/tests/test_performance_baseline.py
- **Verdict:** issues found
- **Findings:**
  - [low] Lines 12–16, 98–106: measures preview/schema/export durations but only `print()`s them — no assertion or budget on timing. It is a correctness smoke test with a misleading name; as a "performance baseline" it can never fail on regression.

### packages/worker/tests/test_data_plane_server.py
- **Verdict:** issues found
- **Findings:**
  - [low] Only the valid-token path is exercised (`_context`, line 22); there is no test for a missing/invalid token aborting with UNAUTHENTICATED, nor for the unset-token fail-closed path — the data plane's entire auth surface is untested.
  - Note (ok): delete-prefix fencing is tested (line 91–95); URL classification/build cases are concrete and meaningful.

### packages/worker/tests/test_worker_grpc_codec.py
- **Verdict:** ok
- Meaningful JSON-boundary normalization and Arrow schema round-trip assertions.

### packages/worker/tests/test_datasource_execution_helpers.py
- **Verdict:** ok
- Small but real behavioral assertions (schema coercion, histogram binning totals, skip_rows int coercion).

### packages/worker/tests/test_download_size.py, test_step_registry.py, test_object_store.py, test_preview_run_logging.py, test_healthchecks.py, test_compute_monitor.py, test_pipeline_disabled_steps.py, test_engine_server.py, test_query_plans.py, test_notification.py, test_ai.py, test_docker_engine.py, test_engine_lifecycle.py, test_runtime_workers.py, test_operations.py, test_protocol_*.py, test_step_converter.py, test_iceberg_build_modes.py
- **Verdict:** ok
- Spot-checked across the set: all assert observable behavior (return values, mock call shapes, raised errors); no assert-free tests found. Coverage gap worth noting: nothing exercises `builds/build_execution.run_queued_build_job` (capacity-retry loop, schedule-ingest branch) directly.

## Summary of top findings
1. `_assert_select_only` (datasources/datasource_loading.py:135) does not stop multi-statement or data-modifying-CTE queries — the DB/DuckDB datasource "read-only" guarantee is not enforced.
2. Worker data-plane gRPC: static shared token compared non-constant-time over an insecure port; object-store read/write/list RPCs lack the managed-prefix fencing that delete RPCs have; StorageOptions RPC distributes S3 credentials.
3. Raw DB connection strings (with credentials) are persisted into datasource Iceberg configs and embedded in error details (datasources/execution.py:460–465, 489).
4. Build manager blocks the asyncio loop during child process stop (main.py:180–201, 291) and respawn has no crash backoff.
5. Tests: security gate under-tested; data-plane auth negative paths untested; performance baseline asserts no performance.


---

# Unit 13: scheduler & infrastructure

### packages/scheduler/main.py
- **Verdict:** issues found
- **Findings:**
  - [medium] `grpc.insecure_channel(target)` (line 71) with the internal API token sent as call metadata (lines 111-112): credentials travel over plaintext gRPC on every register/heartbeat/run_due call. Acceptable only if the network segment is trusted; no TLS option exists at all.
  - [low] `_call_registration` retries on `"UNAVAILABLE" not in str(exc)` (lines 127-129) — string-matching the formatted exception message instead of checking `exc.code() == grpc.StatusCode.UNAVAILABLE`; brittle if message wording changes.
  - [low] Busy-poll risk: when `result.handled` is true the loop immediately re-calls `run_due` with no sleep (lines 168-170). If the backend keeps returning `handled=True` without work completing, this becomes a tight RPC loop against the backend.
  - [low] Dead-code style in `_sleep_until_tick_or_stop` lines 206-208 (`_task_result = task.result()` inside suppress) — result discarded; harmless but obscures intent.
- Notes: cron evaluation itself lives in the backend (`RunDueSchedules` RPC); this process is a thin poller, so no local cron math to audit. Duplicate-build protection depends entirely on backend-side dedup keyed by `worker_id`/registration — single instance assumed, `capacity=1` (line 146).

### packages/scheduler/tests/test_scheduler_runtime.py
- **Verdict:** ok
- One-liner: covers settings validation, loop register/run_due/stop ordering, and backend-restart retry via fake client.

### packages/scheduler/scheduler_grpc/__init__.py
- **Verdict:** ok
- One-liner: docstring-only module.

### packages/scheduler/pyproject.toml
- **Verdict:** ok
- One-liner: standard hatch config; wheel includes generated protocol dirs as expected.


### docker/docker-compose.yml
- **Verdict:** issues found
- **Findings:**
  - [medium] Worker mounts the Docker socket (`docker-compose.yml:176`) with `DF_DOCKER_GID=0` default (`env/dev.env`) — socket access is root-equivalent on the host. Required for containerized engines, but the GID 0 default means the worker's appuser effectively has root-group socket access; document a dedicated docker GID for production.
  - [low] No CPU/memory limits on any service; a runaway engine or API worker can starve the host (engine limits exist only inside Polars config).
  - [low] `rustfs/rustfs:1.0.0-rc.1` pins a release-candidate image for production object storage.
  - [ok] Postgres/RustFS expose no host ports; secrets come from env templates with placeholders, not literals.

### docker/Dockerfile
- **Verdict:** issues found
- **Findings:**
  - [low] Scheduler/worker healthchecks are `python3 -c "import main"` (`Dockerfile:125,141`) — verifies importability only, not that the service loop is alive; API uses a real HTTP readiness probe.
  - [low] Protocol-builder symlinks `bun` as `node` (`Dockerfile:13`) to satisfy tooling — fragile if buf/bun tooling ever checks the binary identity.
  - [ok] Non-root `appuser` everywhere, pinned base images/digests-style tags, multi-stage builds, purged build deps.

### docker/env/dev.env
- **Verdict:** issues found
- **Findings:**
  - [low] Dev-only credentials committed (`dataforge-dev-internal-token`, `dataforge/dataforge` DB password) — acceptable for local dev, clearly namespaced; ensure these never rotate into prod values.
  - [medium] `DF_ENGINE_ALLOW_GLOBAL_OBJECT_STORE_CREDENTIALS=true` in dev hands every engine container global object-store credentials; safe locally, dangerous if copied into a shared deployment.

### docker/env/prod.env
- **Verdict:** ok
- One-liner: placeholder credentials only (`replace-with-*`) — no real secrets committed. Good practice.

### config/env/prod.env
- **Verdict:** issues found
- **Findings:**
  - [high] `AUTH_REQUIRED=false` is the shipped default for the source-based production path (`config/env/prod.env`), while the Docker prod template sets it true — deploying via `just prod` with unedited file exposes the whole API unauthenticated.
  - [medium] `DEFAULT_USER_PASSWORD=ChangeMe123` ships as the bootstrap password and `SETTINGS_ENCRYPTION_KEY=` is empty by default; if unset key falls back to no encryption at runtime, stored SMTP/Telegram/AI credentials are plaintext (corroborates Unit 04 findings).

### scripts/ (all maintenance/validation scripts)
- **Verdict:** ok
- One-liner: hygiene/boundary/e2e helper scripts (~2,100 lines) contain no secret handling, no eval/exec of external input, and enforce useful repo invariants (package boundaries, protocol enum ownership, warning scan). No findings beyond style.

### Justfile
- **Verdict:** ok
- One-liner: recipes use `set -euo pipefail`, pinned tool invocations, and proper process-group shutdown in `prod`; sourcing env files into the shell is standard here. No findings.


---

# Unit 14: protocol package

### packages/protocol/buf.yaml
- **Verdict:** issues found
- **Findings:**
  - [low] buf.yaml:18-20 — breaking rules except `ENUM_VALUE_NO_DELETE_UNLESS_NAME_RESERVED`/`NUMBER_RESERVED`, so enum values can be deleted without reserving their numbers/names. Old clients that persisted a now-deleted value will read it as an unknown number (proto3 keeps it on the wire but JSON/enum-token mapping breaks). Deliberate per the repo's no-back-compat principle, but each deletion should still reserve the number to avoid accidental reuse.
  - [low] buf.yaml:12-14 — `RPC_REQUEST_RESPONSE_UNIQUE`, `RPC_REQUEST_STANDARD_NAME`, `RPC_RESPONSE_STANDARD_NAME` lint rules disabled; consistent with the shared-envelope design, but it means nothing enforces request/response naming discipline going forward.
  - Note: verified `buf lint proto` passes clean (exit 0).

### packages/protocol/buf.lock
- **Verdict:** ok
- **Findings:** (none)

### packages/protocol/buf.gen.yaml
- **Verdict:** issues found
- **Findings:**
  - [low] Only a TS plugin (`protoc-gen-es`) is configured here; Python generation is done separately by the `just generate-protocol` recipe (justfile:157+). Not a defect per se, but the "single source of truth" for codegen is split between this file and the justfile recipe — drift risk if plugin versions diverge (`@bufbuild/protoc-gen-es ^2.12.0` in package.json vs whatever grpcio-tools emits).
  - Note: generated outputs (`../frontend/src/lib/protocol`, per-package `dataforge_protocol/` Python dirs) are NOT committed in this worktree — they are regenerated and diff-checked by `just generate-protocol`. No generated artifacts exist on disk to audit; consistency is enforced by the recipe's `diff -ru` checks.

### packages/protocol/proto/dataforge_protocol/runtime.proto
- **Verdict:** ok
- **Findings:** (none) — reserved field 6/"raw" handled correctly; namespace pattern validated.

### packages/protocol/proto/dataforge_protocol/common.proto
- **Verdict:** issues found
- **Findings:**
  - [low] common.proto:12 — `protocol_version` is an unvalidated `int32` with no range constraint and no documented semantics; nothing prevents a worker registering with version 0 or a negative value. If version negotiation matters, add `(buf.validate.field).int32.gte = 1` or similar.

### packages/protocol/proto/dataforge_protocol/errors.proto
- **Verdict:** issues found
- **Findings:**
  - [low] errors.proto:7-53 — `ErrorCode` mixes several orthogonal taxonomies into one flat enum (auth errors, datasource errors, pipeline errors, file errors). Adding new codes is safe for wire compat (append-only), but the flat list makes it easy to accidentally reuse semantics; grouping by prefix is already done informally — acceptable.
  - Note: `ErrorInfo.details` uses `google.protobuf.Struct` (errors.proto:58) — untyped by design; fine for pass-through details.

### packages/protocol/proto/dataforge_protocol/enums.proto
- **Verdict:** issues found
- **Findings:**
  - [low] enums.proto:572 — `DISPLAY_UNITS_NONE` has `(dataforge_token) = ""`. Verified this is deliberate (frontend `protocol-enum-tokens.ts:290` maps NONE → `''`, backend `api_enums.py` round-trips via descriptor), but an empty token is ambiguous with "token absent/UNSPECIFIED" in any code path that treats empty-string tokens as missing; a distinct token like `"none"` would remove the ambiguity.
  - [low] enums.proto:191-208 — `ComputeRequestKind` is the only functional enum without `dataforge_token` annotations. Verified consumers use name-suffix mapping instead (`compute_requests/models.py:71` `_proto_enum_suffix`), so it works, but two different enum→string mechanisms now coexist; a future consumer assuming tokens everywhere will silently get nothing for these values.
  - [low] enums.proto:429-440 — `DurationUnit` orders units non-monotonically (seconds…months then ns/us/ms appended at the tail). Harmless on wire, but numeric ordering no longer corresponds to magnitude; anyone sorting by enum value gets surprising results.
  - [low] enums.proto:543 — `STACK_MODE_STACKED_100` token is `"100%"`; embedding formatting characters in wire-mapped tokens is fragile if the token is ever used in URLs/identifiers.
### packages/protocol/proto/dataforge_protocol/compute.proto
- **Verdict:** issues found
- **Findings:**
  - [medium] compute.proto:17 — `EngineIdentity` CEL rule hardcodes raw enum numerics (`scope == 1`, `reuse_policy == 2`, etc.) instead of symbolic enum names. If `EngineScope`/`EngineReusePolicy` values are ever renumbered or inserted-before, validation silently changes meaning. Symbolic references (`this.scope == EngineScope.DATASOURCE_PREVIEW`) would be robust.
  - [medium] compute.proto:141 vs 155 — `StepPreviewResult.total_rows` is `int32` while `StepRowCountResult.row_count` is `int64`. A preview over a >2^31-row dataset overflows `total_rows`; inconsistent sizing of the same concept.
  - [low] compute.proto:253-265 — `ComputeCommandEnvelope` reserves 5/"payload" but skips field 6 entirely without reserving it; a future edit could accidentally reuse 6 for an unrelated type. Same pattern is safe in `ComputeResponseEnvelope` (267-283) where 6 is used.
  - [low] compute.proto:181 — `EngineStatusResult.analysis_id` has no validation (not even min_len) while sibling id fields (182, 202-207) do; inconsistent.
  - [low] compute.proto:367 — `BuildStepCompletedEvent.duration_ms` is `int32` ms (wraps at ~24.8 days); `EngineRunExecutionEntry.duration_ms` (334) is `double`. Minor inconsistency; low practical risk.
  - Positive: extensive buf.validate usage (enum defined_only+not_in, patterns, CEL) is unusually thorough; reserved fields used correctly on removals (120-121, 187-188, 238-239, 254-255, 348-349, etc.).
### packages/protocol/proto/dataforge_protocol/analysis.proto
- **Verdict:** issues found
- **Findings:**
  - [medium] analysis.proto:406 (`NotificationConfig.bot_token`), :433 (`AIConfig.api_key`) — plaintext secrets are part of the pipeline payload. These payloads travel inside `ComputeCommandEnvelope` over the wire and are persisted with analysis versions/snapshots; any snapshot export or log of the payload leaks credentials. Consider secret references resolved server-side instead of inline values.
  - [low] analysis.proto:219 — `FillNullConfig.value_type` is a free-form `optional string`, whereas the equivalent concept elsewhere (`FilterCondition.value_type`, :119) is the typed `FilterValueType` enum. Inconsistent typing invites typos that only fail at runtime.
  - [low] analysis.proto:325 — `ChartConfig.bins` is a required `int32 >= 1` for every chart type, including charts where bins are meaningless (line, pie); producers must send a dummy value to pass validation. Same pattern for `area_opacity` (:344) and other always-required fields — validation doesn't discriminate by `chart_type`.
  - [low] analysis.proto:148-152 — `SortConfig` uses parallel arrays `columns`/`descending` with no CEL enforcing equal lengths; mismatched lengths fail only at execution time.
  - [low] analysis.proto:44, :404 — notification recipient strings have no format validation (no `.email = true`) though method can be EMAIL; contrast with `BuildStarter.email` (compute.proto:451) which does validate.
  - Note: `StepConfig` oneof (:483-513) covers all 27 non-plot step configs; plot_* StepTypes reuse `chart` — consistent.
### packages/protocol/proto/dataforge_protocol/datasource.proto
- **Verdict:** issues found
- **Findings:**
  - [medium] datasource.proto:71 — `CreateDatabaseDatasourceCommand.connection_string` carries raw DB credentials (user/password embedded) inside the compute command envelope; same exposure path as the pipeline-payload secrets in analysis.proto (persisted snapshots/logs).
  - [low] datasource.proto:73 — `CreateDatabaseDatasourceCommand.branch` is a required non-empty string for a *database* datasource; `branch` is an Iceberg concept and its meaning here is undocumented — likely copy-paste from the Iceberg command (:81). If unused by workers this forces callers to send dummy data to pass validation.
  - [low] datasource.proto:217 — `ColumnStatsResult.null_percentage` validated `gte: 0` only, no `lte: 100`; malformed producers pass validation.
  - Note: reserved-field hygiene good (:16-17, :129-130, :225-226); row counts consistently int64 here (contrast with compute.proto total_rows int32).

### packages/protocol/proto/dataforge_protocol/worker_runtime.proto
- **Verdict:** issues found
- **Findings:**
  - [low] worker_runtime.proto:14-61 — `WorkerRuntimeService` is a 47-RPC god service spanning job leasing, datasources, health checks, engine runs, notifications, and AI generation. Single interface means every consumer depends on everything; splitting along those concerns would clarify ownership. Wire-compat safe, purely structural.
  - [low] worker_runtime.proto:63-73 — `RuntimeWorkerRegisterRequest` has no `protocol_version`, while `RuntimeWorkerRequest` (common.proto:12) carries one; registration is where version negotiation would matter most.
  - [low] worker_runtime.proto:598 vs analysis.proto:432 — `WorkerGenerateAIRequest.endpoint_url` validates with `.uri = true`, but `AIConfig.endpoint_url` (which feeds the same call) has no URI validation; invalid URLs are caught later than they could be.
  - [medium] worker_runtime.proto:613-620 — `WorkerTelegramTargetsResponse` returns plaintext `bot_token` per target over RPC; combined with tokens in `NotificationConfig`/`WorkerSendTelegramRequest`, bot tokens transit multiple hops. Acceptable internally, but worth documenting as a trust-boundary assumption.
  - Positive: lease/claim discipline is well-modeled (`claim_token` + `lease_generation` + expiry on every mutating RPC); reserved fields used correctly on all removed payloads.

### packages/protocol/proto/dataforge_protocol/engine_runtime.proto
- **Verdict:** issues found
- **Findings:**
  - [medium] engine_runtime.proto:35-40 — `EngineSubmitJobRequest.kind` is a free-form `string` constrained only by an `in` list ("preview"/"export"/"schema"/"row_count") even though a typed `EngineRunKind` enum already exists in enums.proto. Stringly-typed job kinds invite drift between worker and engine; an enum (or reusing EngineRunKind) would be checked at compile time.
  - [low] engine_runtime.proto:41 — `payload_json` validated as `bytes.min_len = 2` (i.e. must be at least `"{}"`); opaque but functional. The whole engine transport is intentionally JSON-bytes over gRPC (comment :9-11) — untyped by design, so schema errors surface only at parse time on the Rust/Python engine side.
  - [low] engine_runtime.proto:65-67 — `EngineJobEvent.event` oneof allows `result` mid-stream and `progress_json` is untyped bytes; no message-level CEL preventing e.g. result followed by more progress events — ordering contract lives only in consumer code.
  - Note: reserved fields used correctly throughout (:30-31, :58-59, :71-72); protocol_version properly validated >=1 (:24, :33).

### packages/protocol/proto/dataforge_protocol/scheduler_runtime.proto
- **Verdict:** ok
- **Findings:** (none) — small, well-validated; consistent with worker registration patterns.

### packages/protocol/proto/dataforge_protocol/object_store.proto
- **Verdict:** issues found
- **Findings:**
  - [medium] object_store.proto:37-38 — `ObjectStoreStorageOptions` carries `access_key_id`/`secret_access_key` in plaintext and is returned by the unauthenticated-shape `StorageOptions(EmptyRequest)` RPC (:77); any client of this internal service receives the S3 credentials. Same secret-over-RPC trust-boundary assumption as the bot tokens; fine inside the trust perimeter, worth documenting.
  - [low] object_store.proto:9 — URL pattern `^s3://[^/]+/.+$` requires a non-empty key; a bare bucket URL (`s3://bucket`) fails validation, which may be intended but makes `ObjectStoreUrl` unusable for bucket-level ops (Exists/DeletePrefix take ObjectStoreUrl directly, :82,:85).
  - [low] object_store.proto:22-28 — `ObjectStorePathParts` allows both `bucket` and `namespace` unset-or-set with no CEL tying them together; resolution precedence lives only in the service implementation.

### packages/protocol/proto/dataforge_protocol/iceberg.proto
- **Verdict:** issues found
- **Findings:**
  - [low] iceberg.proto:64-66 — `IcebergSnapshotScanResponse.rows` is a single `google.protobuf.Struct` while every other row-set in the protocol uses `repeated Struct` + column lists (e.g. datasource.proto:191-196 `SnapshotPreview`). Inconsistent shape forces ad-hoc parsing of whatever structure the producer chose.
  - [low] iceberg.proto:10-15 — `IcebergTableRef` has no CEL requiring exactly one of `datasource_id`/`metadata_path`; under-specified refs pass validation and fail at resolve time.

### Generated code (not present in worktree)
- **Verdict:** ok (with caveat)
- **Findings:**
  - All generated artifacts are gitignored (.gitignore:15-20): `packages/{backend,scheduler,worker}/dataforge_protocol/` (grpcio-tools Python) and `packages/frontend/src/lib/protocol/` (`protoc-gen-es` TS per buf.gen.yaml). Nothing exists on disk to audit in this checkout.
  - Consistency proto↔generated is enforced mechanically by `just generate-protocol` (justfile:157+): regenerates into a temp dir and `diff -ru`s against each package's copy, failing CI on drift. This is a sound guard; the residual risk is plugin-version skew between `@bufbuild/protoc-gen-es ^2.12.0` (package.json:6, caret range → floating minor) and pinned grpcio-tools `<1.82`.

### packages/frontend/src/lib/protocol (generated TS bindings)
- **Verdict:** ok (with caveat)
- **Findings:**
  - Directory does not exist in this worktree (gitignored, regenerated by `just generate-protocol`). Hand-maintained consumers that depend on it were spot-checked instead: `packages/frontend/src/lib/types/protocol-enum-tokens.ts` mirrors the `dataforge_token` annotations (incl. the `DisplayUnits.NONE → ''` empty token at line 290) — this file duplicates proto enum tokens by hand and can silently drift from enums.proto since it is not generated.


---

# Unit 15: frontend API & services layer

### packages/frontend/src/lib/api/in-flight.ts
- **Verdict:** ok
- **Findings:** none — in-flight dedup map correctly deletes only its own entry (identity check at lines 14, 18).

### packages/frontend/src/lib/api/mcp.ts
- **Verdict:** ok
- **Findings:** none.

### packages/frontend/src/lib/api/namespaces.ts
- **Verdict:** ok
- **Findings:** none.

### packages/frontend/src/lib/api/chat.ts
- **Verdict:** issues found
- **Findings:**
  - `[low]` chat.ts:177, 184, 191, 200, 207, 232: `sessionId` interpolated into URL paths without `encodeURIComponent`; IDs are server-generated so risk is minimal, but inconsistent with `datasource.ts:284` which does encode.
  - API keys (`api_key` in payloads) are only sent in POST/PATCH bodies; no browser-side persistence in this file — good.
  - Event stream opened via `createOwnedEventSource(buildBackendUrl(...))` (line 231-233); note EventSource cannot send the `X-Namespace`/identity headers used by REST calls, so namespace must ride the query string handled server-side.

### packages/frontend/src/lib/api/client.ts
- **Verdict:** issues found
- **Findings:**
  - `[medium]` Type-safety hole at client.ts:208 and 222: on HTTP 204, `undefined as T` is returned for any caller-declared `T`, silently violating the `ResultAsync<T, ApiError>` contract whenever a caller declares a non-void type on a 204 endpoint.
  - `[low]` buildHeaders (client.ts:81-82) sets `Content-Type: application/json` even for body-less GET/DELETE requests; harmless but unnecessary preflight surface.
  - Note: `buildBackendUrl` (client.ts:15-20) returns absolute dev origin only in DEV; correct SSR guard at line 17.
  - Namespace epoch/abort handling (client.ts:37-46, 146-157, 182-194) is sound: epoch snapshot + header comparison + AbortController cleanup with identity-checked deletes.

### packages/frontend/src/lib/api/config.ts
- **Verdict:** ok
- **Findings:** none.

### packages/frontend/src/lib/api/auth.ts
- **Verdict:** issues found
- **Findings:**
  - `[low]` auth.ts:83: `provider` interpolated into path without `encodeURIComponent`; a malformed provider value could alter the request path. Server-generated values make this low risk.
  - Credentials are sent only in POST bodies to cookie-based session endpoints; no token storage in this file — good.

### packages/frontend/src/lib/api/builds.ts
- **Verdict:** ok
- **Findings:** none — same sound dedup pattern as engine-runs.ts.

### packages/frontend/src/lib/api/build-stream.ts
- **Verdict:** issues found
- **Findings:**
  - `[medium]` build-stream.ts:67-76 (`toBuildDetailEvent`) throws on unrecognized/malformed protocol events; this throw propagates out of the WebSocket `message` listener inside `createStream` (websocket.ts:155-157), which has no try/catch — so a bad server message becomes an uncaught exception instead of being routed to `callbacks.onError`.
  - `[low]` build-stream.ts:101-103: `getRuntimeBuild` is an exact duplicate of `getBuild` in builds.ts:50-52 — dead/duplicated code path.
  - Parse fallback for invalid JSON correctly yields an error message object rather than throwing (lines 41-54).

### packages/frontend/src/lib/api/ai.ts
### packages/frontend/src/lib/api/ai.ts
- **Verdict:** ok
- **Findings:** none — API keys only ever sent in POST bodies, never stored or placed in URLs here.

### packages/frontend/src/lib/api/websocket.ts
- **Verdict:** issues found
- **Findings:**
  - `[low]` websocket.ts:94-102: `client_id` and `client_signature` are appended to WebSocket URLs as query params. These are browser-fingerprint-derived values (not secrets), but query strings are commonly logged server-side/proxies; header-based transport (as used by `client.ts`) would be more consistent.
  - `[low]` websocket.ts:95: `requireNamespace()` is called unconditionally in `buildWebsocketUrl`; if the namespace store isn't ready this throws synchronously inside URL construction. Callers must guarantee readiness.
  - `[info]` `createStream` (lines 132-179) has no auto-reconnect — close always terminates; acceptable if callers own reconnection policy.
  - Unload cleanup via `pagehide`/`beforeunload` with idempotent binding (lines 46-52) is correct; socket set cleanup on `close` event avoids leaks.

### packages/frontend/src/lib/api/engine-runs.ts
- **Verdict:** ok
- **Findings:** none — in-flight dedup correctly keyed by namespace + endpoint (line 74); abort-signal path intentionally bypasses dedup (line 73).

### packages/frontend/src/lib/api/healthcheck.ts
- **Verdict:** ok
- **Findings:** none — query construction uses URLSearchParams throughout.

### packages/frontend/src/lib/api/settings.ts
- **Verdict:** issues found
- **Findings:**
  - `[low]` settings.ts:64: `Subscriber.bot_token: string` — the type declares a full Telegram bot token per subscriber row returned by `GET /v1/telegram/subscribers`. If the backend actually populates it, secrets are shipped to every client; if not, the field is dead/misleading. Either way worth verifying.
  - Masked-secret handling (`isMasked`, lines 5-9) is reasonable; keys are persisted server-side via PUT, not in browser storage.

### packages/frontend/src/lib/api/udf.ts
- **Verdict:** ok
- **Findings:** none.

### packages/frontend/src/lib/api/lineage.ts
- **Verdict:** ok
- **Findings:** none.

### packages/frontend/src/lib/api/excel.ts
- **Verdict:** ok
- **Findings:** none — FormData bodies correctly skip JSON Content-Type via client.ts:81; query params built with URLSearchParams (line 78).

### packages/frontend/src/lib/api/schedule.ts
- **Verdict:** ok
- **Findings:** none.

### packages/frontend/src/lib/api/locks.ts
- **Verdict:** issues found
- **Findings:**
  - `[medium]` locks.ts:126-133: reconnect uses a fixed 1s delay with no exponential backoff or jitter; a down/unreachable backend produces an infinite 1 Hz reconnect loop per lock session (multiple sessions multiply this).
  - `[low]` locks.ts:220-229 + 209-218: both `error` and `close` handlers run for the same failed socket, so `resetOwnership()` fires twice and `onStatus(null, false)` is invoked twice per disconnect.
  - `[low]` locks.ts:101-107: once `awaitingAcquire` is set it is only cleared by a status/error message or reconnect; if the acquire response is lost without a socket drop, retrying acquire silently no-ops.
  - `[low]` locks.ts:196: `JSON.parse(event.data) as LockWsMessage` — no runtime shape validation; a malformed `status` message would flow into `handleStatus` unchecked.
  - `[info]` locks.ts:252-255: `close()` tears down the socket but never sends `release`, so an owned lock persists until server-side TTL expiry. Appears intentional (release() exists separately) but worth confirming.
  - Heartbeat/ping lifecycle (startPing/clearTimer) and ownership token tracking are otherwise correct.

### packages/frontend/src/lib/api/compute.ts
- **Verdict:** issues found
- **Findings:**
  - `[low]` compute.ts:255-261 + 266-268: `parseEnginesStreamMessage` casts `JSON.parse` result without validation, and `extractSnapshot` casts via `as EnginesSnapshotMessage`; a snapshot message lacking `engines` delivers `undefined` to `onSnapshot(engines: EngineStatusResponse[])`.
  - In-flight dedup for preview/schema/row-count/spawn/shutdown keyed by namespace+endpoint+body (lines 60-73) is correct and prevents duplicate expensive compute POSTs.

### packages/frontend/src/lib/api/analysis.ts
- **Verdict:** ok
- **Findings:** none — optimistic-concurrency handling (ETag / If-Match / X-Analysis-Version, lines 61-131) is consistent; `deleteAnalysis` GET-then-DELETE race fails safely via If-Match 412 rather than deleting stale data.

### packages/frontend/src/lib/api/datasource.ts
- **Verdict:** issues found
- **Findings:**
  - `[low]` datasource.ts:287-293: dead conditional — inside the `payload`-truthy branch, `payload ? { config: payload } : null` always takes the truthy arm; simplify to `{ config: payload }`.
  - Upload FormData handling correctly avoids the JSON Content-Type override (client.ts:81); no other issues.

### packages/frontend/src/lib/services/app-bootstrap.svelte.ts
- **Verdict:** issues found
- **Findings:**
  - `[low]` app-bootstrap.svelte.ts:37-54: `start()` memoizes `this.run` forever; a failed bootstrap attempt can never be retried without a full page reload (no reset/retry path exposed).
  - Phase/error derivation (lines 56-110) is coherent; single-flight orchestration is correct.

### packages/frontend/src/lib/services/app-lifecycle.ts
- **Verdict:** ok
- **Findings:** none.

### packages/frontend/src/lib/services/app-bootstrap.test.ts / app-lifecycle.test.ts
- **Verdict:** ok
- **Findings:** none — unit tests only.

### packages/frontend/src/lib/api/client.test.ts / builds.test.ts / engine-runs.test.ts / locks.test.ts / lock-watcher.test.ts / websocket.test.ts / compute.test.ts / build-stream.test.ts (test files)
- **Verdict:** ok
- **Findings:** none — unit tests only (`lock-watcher.test.ts` exercises `openLockSession` from locks.ts; no separate lock-watcher module exists).


---

# Unit 16: frontend stores, types & nxt

### packages/frontend/src/lib/stores/analysis.svelte.ts
- **Verdict:** issues found
- **Findings:**
  - [medium] analysis.svelte.ts:133 — `isDirty()` compares `JSON.stringify(this.tabs)` vs `JSON.stringify(this.savedTabs)`: O(full pipeline) on every call and sensitive to key insertion order; a server response that reorders keys (or normalizes numbers) yields false "dirty" states. A structural deep-equal would be safer.
  - [low] analysis.svelte.ts:154, 311, 336 — `addStep`/`insertStep`/`addBranchStep` mutate the caller-owned `step.depends_on` before cloning; callers passing a shared/reused step object get silently modified input.
  - [low] analysis.svelte.ts:114, 566 — repeated unchecked casts `(analysis.pipeline_definition as { tabs?: AnalysisTab[] })?.tabs`; malformed payload silently becomes empty pipeline with no validation/type-narrowing.
  - [low] analysis.svelte.ts:359-424 — `updateStepConfig` mixes concerns: config update + audit log + downstream preview invalidation graph walk (~55 lines) in one method; hard to test/maintain, belongs in a helper.
  - [low] analysis.svelte.ts:400, 419 — duplicated magic default `rowLimit ?? 100` and run-key construction (`${analysisId}:${datasourceId}:${snapshotKey}:${rowLimit}:${item.id}`) in two loops; drift risk if one copy changes.
### packages/frontend/src/lib/stores/paginated-store.svelte.ts
- **Verdict:** ok
- **Findings:**
  - [low] paginated-store.svelte.ts:80 — `fetchPage` returns `PaginatedResult<TResponse>` whose `match` returns `unknown`; a structural minimal interface instead of the real `ResultAsync` type weakens inference for subclasses.
  - [low] paginated-store.svelte.ts:52 — `refreshInternal` only guards `params === undefined && status === 'disconnected'`; after an error with no params it will call `fetchPage(undefined)` — subclass-dependent behavior.
  - Token-guard + pending-refresh coalescing (lines 84-117) are correct; no stale-response or leak issues found.
### packages/frontend/src/lib/stores/favorites.svelte.ts
- **Verdict:** ok
- Trivial 46-line localStorage-backed favorites store; no issues found (see notes below after full read).
### packages/frontend/src/lib/stores/overlay.svelte.ts
- **Verdict:** ok
- Clean module-scoped overlay stack; reassignment-based reactivity is correct, action cleans up on destroy. No issues.
### packages/frontend/src/lib/stores/datasource.svelte.ts
- **Verdict:** issues found
- **Findings:**
  - [low] datasource.svelte.ts:21-32, 95-105 — `loadDatasources`/`deleteDatasource` have no request token or in-flight guard: two concurrent `loadDatasources` calls can resolve out of order and the older response overwrites the newer one.
  - [low] datasource.svelte.ts:48, 86 — errors are re-thrown as generic `Error(err.message)`, discarding structured `ApiError` info (status/type) for callers that want it.
  - [low] datasource.svelte.ts:67-70 — schema cache ignores `sheetName`: a sheet-specific fetch is never cached but also never invalidated by `clearSchemaCache(id)` semantics mismatch — actually only non-sheet results are cached, so this is consistent; no bug, just noting cache key is id-only by design.
### packages/frontend/src/lib/stores/config.svelte.ts
- **Verdict:** issues found
- **Findings:**
  - [low] config.svelte.ts:45-49 vs 28-31 — `refresh()` called while an initial fetch is still in flight starts a second request; the first request's `.finally` then nulls `this.pending` and flips `loading` while the second is still running, so a subsequent `fetch()` call can spawn a third duplicate request. Needs a generation token or shared promise.
### packages/frontend/src/lib/stores/engines.svelte.ts
- **Verdict:** issues found
- **Findings:**
  - [low] engines.svelte.ts:60-82 — optimistic removal in `shutdownEngine` is not rolled back on failure: the engine vanishes from `this.engines` immediately and only reappears on the next server snapshot; if the stream is down, the UI shows it gone indefinitely despite the failed shutdown.
  - [low] engines.svelte.ts:20 — `shuttingDown` is a `SvelteSet` but is purely internal bookkeeping never read by templates/derivations; plain `Set` would avoid needless dependency tracking.
  - Refcounting + `holdUntilEmpty` teardown logic (lines 30-54, 140-145) is intricate but coherent; no leak found (connection closed in reset/onClose paths).
### packages/frontend/src/lib/stores/reconnection-manager.ts
- **Verdict:** ok
- Trivial single-timer helper; correct clear/schedule semantics. No issues.
### packages/frontend/src/lib/stores/clientIdentity.svelte.ts
- **Verdict:** issues found
- **Findings:**
  - [medium] clientIdentity.svelte.ts:53-61 — `getClientIdentity()` is synchronous over async state: before `initClientId()`'s IndexedDB read resolves it returns `clientId: ''`; the re-kick at lines 54-56 is fire-and-forget so the caller still gets the empty value. Early API calls are sent with a blank client id.
  - [low] clientIdentity.svelte.ts:48 — `navigator.platform` is deprecated and inconsistent across browsers; fingerprint stability suffers.
  - [low] clientIdentity.svelte.ts:27-35 — 32-bit Java-style string hash for the "signature stored server-side"; trivially collision-prone, though impact depends on server use.
### packages/frontend/src/lib/stores/namespace.svelte.ts
- **Verdict:** ok
- **Findings:**
  - [low] namespace.svelte.ts:149-168 — `useNamespace().value` getter throws when namespace isn't ready; a throwing getter inside a reactive template expression crashes rendering rather than letting the caller branch on `status`. Callers must remember to check `.ready` first.
### packages/frontend/src/lib/stores/auth.svelte.ts
- **Verdict:** issues found
- **Findings:**
  - [low] auth.svelte.ts:25-27 — `resolve()` guards only on settled status; two concurrent calls both pass the `status !== 'unknown'` check and issue duplicate `/me` probes (no shared-promise like configStore uses).
  - [low] auth.svelte.ts:91-96 — `logout()` ignores the result of the API call entirely; a failed server-side logout still clears local state (may be intentional, but silent).
### packages/frontend/src/lib/stores/engine-runs.svelte.ts
- **Verdict:** ok
- Thin PaginatedStore subclass; correct param comparison and page handling. No issues.
### packages/frontend/src/lib/stores/compute-activity.svelte.ts
- **Verdict:** ok
- Lease-count store with idempotent release; `track()` releases on both result paths. Correct.
### packages/frontend/src/lib/stores/builds.svelte.ts
- **Verdict:** ok
- Thin PaginatedStore subclass. No issues.
### packages/frontend/src/lib/stores/favorites.svelte.ts
- **Verdict:** ok
- Trivial immutable-array favorite store; correct namespace-scoped reset. No issues.
### packages/frontend/src/lib/stores/schema.svelte.ts
- **Verdict:** issues found
- **Findings:**
  - [medium] schema.svelte.ts:28, 124-132 — `previewSchemas` grows unbounded within a session: entries are keyed by step id and only removed via explicit `clearPreviewSchema`; steps deleted from the pipeline (removeStep/moveStep across tabs) and stale analyses leave orphaned entries forever unless something calls `reset()`.
  - [low] schema.svelte.ts:27, 92-98 — same for `joinSchemas`: no pruning tied to tab/datasource removal; relies on callers remembering `removeJoinDatasource`.
  - [low] schema.svelte.ts:67 — condition `entry?.hash !== null && entry?.hash === currentHash` is convoluted: for a missing entry it evaluates `undefined !== null` (true) then fails the equality; intent ("entry exists with matching non-null hash") would be clearer as `entry && entry.hash === currentHash`.
### packages/frontend/src/lib/stores/drag.svelte.ts
- **Verdict:** issues found
- **Findings:**
  - [low] drag.svelte.ts:47 — singleton store holds a strong DOM reference (`capturedElement`) in module scope; any path that abandons a drag without `end()`/`commit()`/`cancel()` keeps the element alive. All current paths do call `end()`, so latent rather than active.
  - [low] drag.svelte.ts:62 vs 76 — `start()` lacks the `public` modifier used on every other method; inconsistent visibility style.
  - Global `$effect.root` (lines 177-214) correctly adds/removes window listeners reactively and body class cleanup is symmetric. No leak.
### packages/frontend/src/lib/stores/build-stream.svelte.ts
- **Verdict:** issues found
- **Findings:**
  - [low] build-stream.svelte.ts:257-268 — `refreshBuildDetail` swallows all API errors (`() => false`); during SSE outage the 250ms poll (line 231-255) can fail silently forever and the UI just looks frozen until MAX_RECONNECT_ATTEMPTS trips via onClose.
  - [low] build-stream.svelte.ts:173, 482 — user-initiated cancellation is surfaced through the `error` field ("Cancelled by X"); consumers can't distinguish failure from intentional cancel except via `status`.
  - [low] build-stream.svelte.ts:245-255 — if `startRuntimeBuild` never resolves, `scheduleRefresh` re-arms itself every 250ms with no buildId in an empty loop until generation changes; no overall timeout.
  - Generation-token discipline, bounded logs/resource history (MAX_LOGS/MAX_RESOURCE_HISTORY), and activity-lease release on all terminal paths are correct; no leak or stale-callback bug found.
### packages/frontend/src/lib/stores/chat.svelte.ts
- **Verdict:** issues found
- **Findings:**
  - [high] chat.svelte.ts:148 — `JSON.parse(raw) as Record<string, unknown>` inside `_loadPrefs()`, called from the constructor of the module-level singleton (line 138): one corrupt `chat_prefs` localStorage value throws during module import and crashes the whole app at load. Needs try/catch.
  - [medium] chat.svelte.ts:599-600, 885-886 vs 705-737 — `toolCalls` and `timeline` hold the *same* ToolCall object reference (`item: tc`), yet `_updateToolStatus`, `tool_start` (629-647) and `tool_confirm` (656-670) each run two parallel update loops "to ensure reactivity in both arrays". The second loops are dead weight — mutating `tc` already updates the timeline entry; ~40 lines of duplicated state mutation that can drift.
  - [low] chat.svelte.ts:104-106 — `messages`/`toolCalls`/`timeline` are unbounded for a long-lived session (no MAX_LOGS-style cap unlike build-stream).
  - [low] chat.svelte.ts:948, 959 — `closeSession()` API results ignored (no `.match`), so failed deletes/closes are silent.
  - [low] chat.svelte.ts:189-203, 267-282 — `enabledTools`/`isToolEnabled`/`tagGroups` recompute linear scans on every access; fine at current scale but O(n²)-ish when rendered per-tool.
### packages/frontend/src/lib/nxt/engine.ts
- **Verdict:** ok
- Trivial pure helper functions; no state, no issues.
### packages/frontend/src/lib/types/compute.ts
- **Verdict:** ok
- Types cleanly derived from generated protocol types via helper aliases; no issues.
### packages/frontend/src/lib/types/schema.ts
- **Verdict:** issues found
- **Findings:**
  - [low] schema.ts:35 — `unionByName(schemas, _allowMissing: boolean = true)`: the `_allowMissing` parameter is never used — dead API surface that misleads callers into thinking behavior changes.
  - [low] schema.ts:65 — `intersectSchemas(..., _suffix: string = '')`: underscore-prefix naming implies unused, but it IS used at line 86; misleading convention.
  - [low] schema.ts:62-95 — `intersectSchemas` appends non-overlapping right columns (lines 82-92), which contradicts its name (that's outer-like behavior); only safe if callers rely on it, but the name lies about semantics.
### packages/frontend/src/lib/types/pipeline-step.ts
- **Verdict:** ok
- Type-level alias/canonical step modeling with `satisfies`-checked alias map; clean. No issues.
### packages/frontend/src/lib/types/udf.ts
- **Verdict:** ok
- Plain DTO interfaces; no issues.


---

# Unit 17: frontend utils, styles & test-utils

### packages/frontend/src/lib/utils/audit-log.ts
- **Verdict:** issues found
- **Findings:**
  - `[medium]` Dedupe is ineffective at preventing transmission: `pushLog` pushes the payload into `buffer` (line 123) *before* the dedupe check (lines 125–128). When a duplicate is detected the function returns early but the item remains buffered and is sent on the next flush. The dedupe map only suppresses flush scheduling, not delivery.
  - `[medium]` Silent data loss on consecutive flush failures: `flush()` splices the entire buffer out (line 166); if the fetch fails and `recordFlushFailure` is within its cooldown window it returns without re-queuing (line 149), permanently dropping all payloads removed by that flush.
  - `[low]` `keepalive: true` on the fetch (line 177) caps the body at 64KB in browsers; with `log_queue_max_size` configured large, flush requests can be rejected outright.
  - `[low]` `extractFields` records raw values of all non-sensitive form fields on submit (line 102), including free-text textareas — only name-pattern matching (`SENSITIVE_PATTERNS`, line 71) protects content; fields named e.g. "notes" leak full user input into logs.

### packages/frontend/src/lib/utils/column-types.ts
- **Verdict:** ok
- **Findings:** none — registry/dedupe-by-canonicalName logic is correct; parameterized Polars type stripping via regex (line 428) handles documented formats.

### packages/frontend/src/lib/utils/file-types.ts
- **Verdict:** issues found
- **Findings:**
  - `[low]` Iceberg registry entry uses bare extension `'metadata'` (line 142); `detectFileType` matches with `endsWith` (line 250), so any path ending in "metadata" (e.g. `mymetadata`, or a non-folder path `/data/metadata`) is classified as iceberg. Same pattern for delta `_delta_log` is safe since it's delimiter-distinct.

### packages/frontend/src/lib/utils/transform.ts
- **Verdict:** issues found
- **Findings:**
  - `[low]` `groupbyTransform` hardcodes `dtype: 'Float64'` for every aggregation result (lines 151, 162) regardless of function — count/min/max/first previews show wrong types.
  - `[low]` `unpivotTransform` ignores config and always emits columns named `variable`/`value` (lines 246–247) even though step-config-defaults allows customizing `variable_name`/`value_name`; schema preview diverges from actual output when customized.
  - `[low]` `timeseriesTransform` falls back to `dtype = 'Datetime'` when the source column isn't found (line 296) — arbitrary guess presented as fact in preview.
  - `[low]` `withColumnsTransform` dedupe keeps the *last* duplicate expression's column via reverse-filter-reverse (lines 216–219) — correct but cryptic; a comment or Map-based last-wins would be clearer.

### packages/frontend/src/lib/utils/temporal.ts
- **Verdict:** ok
- **Findings:** none — epoch heuristic threshold (1e10, line 6) is valid until year ~2286; DST-safe offset math; naive datetimes intentionally interpreted in local zone when `normalize=false`.

### packages/frontend/src/lib/utils/datetime.ts
- **Verdict:** ok
- **Findings:** none — thin wrapper over temporal.ts; parse-failure fallback to `String(value)` (line 23) is deliberate display behavior.

### packages/frontend/src/lib/utils/engine-run-build-detail.ts
- **Verdict:** issues found
- **Findings:**
  - `[low]` `analysis_name` is populated with `run.analysis_id ?? ''` (line 231) — the "name" field carries an ID, so any UI rendering it shows a UUID; same for empty `namespace` (line 232). If upstream data lacks names, consumers should handle null instead of fake strings.

### packages/frontend/src/lib/utils/analysis-pipeline.ts
- **Verdict:** issues found
- **Findings:**
  - `[low]` Redundant spread `{ ...rest, branch: rest.branch }` in `normalizeSnapshotConfig` (line 65) — `branch` is already in `rest`; the explicit re-add is dead weight.
  - `[low]` `buildAnalysisPipelinePayload` collects per-tab failures into `null`s then rejects the whole payload if any tab failed (lines 150–152, 167) — the intermediate filter + length compare is convoluted; a simple early-return-in-loop would be equivalent and clearer.

### packages/frontend/src/lib/utils/analysis-tab.ts
- **Verdict:** issues found
- **Findings:**
  - `[low]` Error message claims "expected a UUID v4" (line 81) but `uuidPattern` (line 10) accepts any version nibble, not just v4 — message overstates the validation.

### packages/frontend/src/lib/utils/compression.ts
- **Verdict:** issues found
- **Findings:**
  - `[low]` `arrayBufferToBase64` builds binary string byte-by-byte with `+=` concatenation (lines 72–74) — O(n²)-ish allocation churn on large cached previews; chunked `String.fromCharCode(...chunk)` or `btoa(unescape(...))` alternatives are standard. Acceptable for small payloads only.

### packages/frontend/src/lib/utils/indexeddb.ts
- **Verdict:** issues found
- **Findings:**
  - `[low]` In `withStore`, if `fn(store)` throws synchronously (line 39) the opened `db` is never closed (the close handlers are only wired to transaction events, lines 42–43) — connection leak on sync throw. Also promise resolves on request success (line 40) before transaction completion, so a later tx abort is invisible to callers.

### packages/frontend/src/lib/utils/hash.ts
- **Verdict:** ok
- **Findings:** none — cyrb53 implementation is standard (h1/h2 output order swapped vs. reference but internally consistent); recursive key sort makes hashing deterministic.

### packages/frontend/src/lib/utils/markdown.ts
- **Verdict:** ok
- **Findings:** none — XSS handled correctly: marked output passed through `DOMPurify.sanitize` (line 13); no `dangerouslySetInnerHTML`-style bypass here.

### packages/frontend/src/lib/utils/pipeline.ts
- **Verdict:** ok
- **Findings:** none — cycle detection in `resolve` is correct (`seen` guard, line 17).

### packages/frontend/src/lib/utils/step-config-defaults.ts
- **Verdict:** issues found
- **Findings:**
  - `[low]` `StepConfig` union ends with `| Record<string, unknown>` (line 67), which absorbs every other member — the union provides no type safety; either drop the catch-all or use it alone.

### packages/frontend/src/lib/utils/build-step-label.ts
- **Verdict:** ok

### packages/frontend/src/lib/utils/build-snapshot-map.ts
- **Verdict:** ok

### packages/frontend/src/lib/utils/json.ts
- **Verdict:** ok
- **Findings:** none — `cloneJson` drops `undefined`/Dates by design of JSON round-trip; fine for config cloning.

### packages/frontend/src/lib/utils/analysis-lock-state.ts
- **Verdict:** ok

### packages/frontend/src/lib/utils/async-gate.ts
- **Verdict:** ok

### packages/frontend/src/lib/utils/uuid.ts
- **Verdict:** ok
- **Findings:** none — Math.random fallback (lines 12–14) is non-crypto but acceptable for non-security identifiers; v4 bits set correctly.

### packages/frontend/src/lib/utils/format-duration.ts
- **Verdict:** ok
- **Findings:** none — NaN/negative guarded (line 3); minute/second rounding edge (`59.7s → "1m 0s"` shows sec=0 branch) handled.

### packages/frontend/src/lib/utils/duration-stats.ts
- **Verdict:** ok

### packages/frontend/src/lib/utils/freshness.ts
- **Verdict:** ok

### packages/frontend/src/lib/utils/relative-time.ts
- **Verdict:** ok
- **Findings:** none — future timestamps (negative elapsed) fall into 'just now', reasonable.

### packages/frontend/src/lib/styles/recipes.ts
- **Verdict:** ok
- **Findings:** none — pure Panda recipe definitions, token-based, no hardcoded colors except intentional inset box-shadow (line 97).

### packages/frontend/src/lib/styles/panda.ts
- **Verdict:** ok
- **Findings:** none — re-export barrel of generated styled-system output.

### packages/frontend/src/lib/test-utils/setup.ts
- **Verdict:** ok
- **Findings:** none — global listeners installed once at import; appropriate for a vitest setup file.

### packages/frontend/src/lib/test-utils/temporal-patch.ts
- **Verdict:** ok
- **Findings:** none — offset computation is DST-correct (offset derived at the same instant, lines 37–48); hour-24 quirk handled (line 26); guards prevent double-patching where real APIs exist.

### packages/frontend/src/lib/test-utils/stubs/lucide.ts
- **Verdict:** ok

### packages/frontend/src/lib/test-utils/stubs/app-environment.ts
- **Verdict:** ok

### packages/frontend/src/lib/test-utils/stubs/app-paths.ts
- **Verdict:** ok

### packages/frontend/src/lib/test-utils/stubs/IconStub.svelte
- **Verdict:** ok

### packages/frontend/src/lib/assets/favicon.svg
- **Verdict:** ok
- **Findings:** none — valid SVG (single line, no trailing newline); referenced as icon in `+layout.svelte:280`.

### Test files under packages/frontend/src/lib/utils/
- **Verdict:** ok
- **Findings:** none — transform.test.ts, analysis-pipeline.test.ts, audit-log.test.ts, etc. cover the corresponding source modules; audit-log.test.ts sets `log_client_dedupe_window_ms: 0` which means the push-before-dedupe ordering bug above is untested.


---

# Unit 18: UI components (first half)

### packages/frontend/src/lib/components/auth/AuthProviders.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/common/BranchPicker.svelte
- **Verdict:** ok
- **Findings:**
  - [low] Line 34: `normalizedBranches` is a pointless alias of the `branches` prop (`$derived(branches)`), adding indirection with no value.
  - [low] Line 41: hardcoded `'master'` fallback for `currentValue`; inconsistent with `BuildsManager.svelte:168` which also hardcodes 'master' — magic value duplicated across components.

### packages/frontend/src/lib/components/common/BuildPreview.svelte
- **Verdict:** issues found
- **Findings:**
  - [medium] Oversized component: 1220 lines mixing 7 tab panels (steps/plan/config/resources/logs/results/payload), sparkline snippet, and log filtering logic in one file; strong candidate for extraction per-tab.
  - [low] Line 153: `setTimeout(() => (copied = false), 2000)` in `copyLogs` is never cleared on component destroy — stale timer fires after unmount (harmless in Svelte 5 but an uncleaned timer).
  - [low] Lines 512, 707, 760, 830, 967, 1101, 1141: each `role="tabpanel"` sets `aria-labelledby="tab-steps"` / `"tab-plan"` / etc., but no tab button carries a matching `id` — dangling ARIA references.
  - [low] Lines 404–504: `role="tab"` buttons have no roving tabindex / arrow-key handling expected of a tablist.

### packages/frontend/src/lib/components/common/BuildsManager.svelte
- **Verdict:** issues found
- **Findings:**
  - [medium] Oversized component: 1393 lines containing filtering, sorting, pagination, cancel flow, live detail-store sync (5 interacting `$effect`s at 104, 345, 384, 398, 455, 568, 583, 603, 623, 633) and full table markup.
  - [medium] Line 993: expandable table rows use `<tr onclick>` with `cursor: pointer` but no `tabindex`, `role`, or keyboard handler — row expansion is inaccessible to keyboard users.
  - [low] Lines 944–958: sortable column headers are `<th onclick>` rather than buttons; no keyboard access or `aria-sort` attribute.
  - Note: intervals (390, 404) and detail stores are correctly cleaned up via effect teardown (393, 407, 633–640).

### packages/frontend/src/lib/components/common/ChatPanel.svelte
- **Verdict:** issues found
- **Findings:**
  - [high] Oversized component: 2640 lines — by far the largest in the unit — combining config/tools/sessions panels, model picker, timeline rendering, markdown styling (`<style>` block 2484–2640), resize handles, and ~15 effects. Should be split into subcomponents.
  - [low] Line 1583: `{@html renderMarkdown(msg.content)}` — verified safe: `renderMarkdown` (`src/lib/utils/markdown.ts:13`) pipes through `DOMPurify.sanitize`. The eslint-disable comment's rationale ("not user-supplied") is inaccurate since assistant replies echo user text, but sanitization makes it moot.
  - [low] Lines 199–235: imperative DOM injection of copy buttons into rendered markdown `pre` blocks via `innerHTML` (static SVG strings — not an XSS sink) plus manual listeners; cleanup removes buttons but the pattern fights the framework and re-runs on every timeline length change.
  - [low] Line 414: `copyToClipboard` `setTimeout` not cleared on unmount or superseded copy (unlike `IndexedDbButton` which guards its timer).
  - [low] Lines 476–534: resize handles declare `role="separator"` with `tabindex="-1"` and no keyboard resizing — separators are decorative-only despite the ARIA role.
  - [low] Line 2177: provider `<select>` has only a `title`, no label or `aria-label`.
  - [low] Lines 389–399, 1672: direct mutation of store item properties (`tc.expanded = ...`) from the component; works because the store holds reactive proxies, but ownership of that state belongs in `chatStore`.

### packages/frontend/src/lib/components/common/CodeEditor.svelte
- **Verdict:** ok
- **Findings:**
  - [low] Lines 15–16, 50–55, 74–80: the `skipUpdate`/`programmatic` flags cleared via `queueMicrotask` are fragile against out-of-order dispatches, though CodeMirror usage here (destroy hook at 61–65) is correct.

### packages/frontend/src/lib/components/common/ColumnDropdown.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/common/ColumnTypeBadge.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/common/ColumnTypeDropdown.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/common/ConfirmDialog.svelte
- **Verdict:** ok
- **Findings:**
  - [low] Lines 30–36: global window keydown handler makes Enter on the focused confirm button call `onConfirm()` manually — redundant with native button activation and risks double-firing if behavior of the native path changes.

### packages/frontend/src/lib/components/common/DataTable.svelte
- **Verdict:** issues found
- **Findings:**
  - [medium] Lines 117–154: suspected broken tooltip reactivity. `tipState` is a plain non-reactive object mutated by `tipShow`/`tipHide` (467–492), but the positioning `$effect` (129) only tracks `tipRef` (a `$state`) — plain-object property reads are not reactive dependencies, so the effect cannot re-run on hover events and the tooltip styles are never applied after mount unless `tipRef` itself changes.
  - [medium] Oversized component: 1081 lines covering tanstack-table wiring, drag-reorder hit-testing, column menu, resize, copy, and tooltip concerns.
  - [low] Lines 113–114, 443–448, 488–491: `copyTimers` and `tipState.timer` timeouts are never cleared on component destroy — timers leak per cell copy/hover.
  - [low] Lines 859–861: column-resize handle uses raw `onmousedown`/`ontouchstart` with no keyboard alternative (`aria-label="Resize column"` implies interactivity that keyboard users cannot perform).

### packages/frontend/src/lib/components/common/DatasourcePicker.svelte
- **Verdict:** ok
- **Findings:**
  - [low] Lines 94–102: analysis fetch failure silently swallows the error and marks `analysesLoaded = true` with an empty list — user sees "No analyses available" with no error indication.

### packages/frontend/src/lib/components/common/DatasourceSelectorModal.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/common/DateTimeInput.svelte
- **Verdict:** ok
- **Findings:**
  - [low] Lines 335–406: calendar navigation icon buttons have no `aria-label` (icon-only); lines 572–634 hour/minute inputs rely solely on `placeholder="HH"/"MM"` for accessible naming.

### packages/frontend/src/lib/components/common/DurationTrendChart.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/common/EnginesPopup.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/common/ExcelTableSelector.svelte
- **Verdict:** ok
- **Findings:**
  - [low] Lines 177–222, 388–408: `runPreflight` applies results after `await` with no staleness/cancellation guard — switching `file`/`filePath` mid-request can apply stale preflight data to the new file (the reset effect clears state but an in-flight response still lands).

### packages/frontend/src/lib/components/common/FileTypeBadge.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/common/FreshnessBadge.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/common/HealthChecksManager.svelte
- **Verdict:** issues found
- **Findings:**
  - [medium] Oversized component: 1530 lines; the create-form snippet alone spans ~410 lines (326–737) with seven near-identical per-check-type field blocks that differ only in labels/config keys.
  - [medium] Line 1063: expandable rows use `<tr onclick>` with pointer cursor but no keyboard access (same anti-pattern as BuildsManager/ScheduleManager).
  - [low] Lines 252–254: `openCreateForm` throws on API error (`throw new Error(...)`) from an `onclick` handler — unhandled promise rejection, no user feedback.
  - [low] Lines 348–360: close (X) button in create form lacks `type="button"` and an `aria-label`.

### packages/frontend/src/lib/components/common/IndexedDbButton.svelte
- **Verdict:** ok
- **Findings:**
  - [low] Lines 73–81: `clearAll`/`removeKey` delete IndexedDB data immediately with no confirmation (mitigated: debug-only behind `configStore.publicIdbDebug`, line 94).

### packages/frontend/src/lib/components/common/LineageGraph.svelte
- **Verdict:** issues found
- **Findings:**
  - [medium] Lines 589–621: lineage nodes have `role="button"` and `tabindex="0"` but activation only happens in `stopDrag` (274–287) via pointerup — there is no `onkeydown` handler, so keyboard focus does nothing; the role promises interactivity that isn't keyboard-accessible.
  - [low] Line 496: `a11y_no_static_element_interactions` is suppressed with a svelte-ignore rather than giving the canvas an accessible role/name.

### packages/frontend/src/lib/components/common/MultiSelectColumnDropdown.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/common/NamespacePickerModal.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/common/RelativeTime.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/common/ScheduleManager.svelte
- **Verdict:** issues found
- **Findings:**
  - [high] Oversized component: 2043 lines — largest manager component in the unit.
  - [medium] Substantial duplication between compact-card view and table view: cron edit UI duplicated at 1379–1447 vs 1834–1929, depends-on select at 1452–1464 vs 1936–1948, trigger-datasource select at 1471–1483 vs 1960–1972. Only `descriptionBlock` was extracted as a snippet; the rest should follow.
  - [medium] Line 1612: table rows use `<tr onclick>` with pointer cursor, no keyboard access (compact view at 1284–1292 does it correctly with `role="button"` + keydown — inconsistent).
  - [low] Lines 1721–1745, 1332–1345: enable/disable toggle buttons expose state only via `title` tooltip; no `aria-label`/`aria-pressed`.

### packages/frontend/src/lib/components/common/UdfPickerModal.svelte
- **Verdict:** ok
- **Findings:**
  - [low] Line 18: `search` state is not reset when the modal closes, so a stale filter persists across opens.

### packages/frontend/src/lib/components/datasources/BuildComparisonPanel.svelte
- **Verdict:** ok
- **Findings:**
  - [low] Lines 131–145: `runComparison` has no cancellation/staleness guard; changing selection while a compare request is in flight can attach a stale result to the new selection (selection change does call `resetComparison`, narrowing the window).
  - [low] 1145 lines is at the upper bound of reasonable size for a single panel.

### packages/frontend/src/lib/components/datasources/ColumnStatsPanel.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/datasources/DatasourceConfigPanel.svelte
- **Verdict:** issues found
- **Findings:**
  - [high] Oversized component: 1906 lines spanning general/schema/CSV/Excel/runs/health/schedules tabs, save+ingest orchestration, schema diffing, and per-column description editing — should be decomposed per tab.
  - [low] Lines 186–255: the datasource-switch reset effect writes ~20 separate `$state` variables inline; a single reset function or keyed `{#key datasource.id}` wrapper would be less error-prone.
  - [low] Lines 103, 108–113: `runsRequested` is intentionally non-reactive (used via `untrack`), but nothing resets polling cadence — `silentRefresh()` runs on every Runs-tab activation with no interval guard documented.
  - Note: XSS sinks absent; all output escaped; effects/store cleanup (117–121) correct.

### packages/frontend/src/lib/components/datasources/DatasourcePreview.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/datasources/SnapshotPicker.svelte
- **Verdict:** ok
- **Findings:**
  - [low] Lines 246–262: `loadSnapshots` has no cancellation; rapid open/close/open cycles can let an older response overwrite a newer one (state reset mitigates partially).
  - [low] Lines 741–773: destructive snapshot delete confirmed only by an inline two-button swap (no ConfirmDialog like elsewhere in the codebase) — inconsistent UX for a destructive action.

### packages/frontend/src/lib/components/gallery/AnalysisCard.svelte
- **Verdict:** issues found
- **Findings:**
  - [medium] Lines 62–237: interactive `<input type="checkbox">` and three `<button>` elements are nested inside an `<a>` — invalid HTML (interactive content inside a link) relying on `preventDefault`/`stopPropagation` in every handler (30–38, 99–103, 163–167, 192–196, 221–225) to avoid double navigation; screen readers see a link whose name swallows all children.
  - [low] Line 75: uses deprecated `onkeypress` for keyboard activation — `keypress` does not fire for Space, so the advertised Space-to-open behavior (line 42 checks `' '`) never triggers; should be `onkeydown`.

### packages/frontend/src/lib/components/gallery/AnalysisFilters.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/gallery/EmptyState.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/gallery/GalleryGrid.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/operations/AIConfig.svelte
- **Verdict:** ok
- **Findings:**
  - [low] Lines 31–33, 168–171, 194–197: direct property mutation of the `$bindable` config object (`config.input_columns = ...`) rather than rebinding a new object — consistent with sibling configs but couples the component to the parent's reactivity model.

### packages/frontend/src/lib/components/operations/DeduplicateConfig.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/operations/DownloadConfig.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/operations/DropConfig.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/operations/ExplodeConfig.svelte
- **Verdict:** ok

## Cross-cutting summary
- **XSS:** single `{@html}` sink (ChatPanel.svelte:1583) is sanitized via DOMPurify (`$lib/utils/markdown.ts:13`). The imperative `innerHTML` assignments in ChatPanel (213–222) inject only static SVG strings. No other sinks in this unit.
- **Leaks:** intervals/listeners are consistently cleaned up via `$effect` teardown (FreshnessBadge, RelativeTime, ChatPanel, BuildsManager, BranchPicker, NamespacePickerModal). Remaining leaks are small uncleared `setTimeout`s (ChatPanel:414, BuildPreview:153, DataTable copy/tooltip timers).
- **Accessibility:** systemic issue — clickable `<tr onclick>` rows without keyboard access in BuildsManager:993, HealthChecksManager:1063, ScheduleManager:1612; LineageGraph nodes advertise `role="button"` without keydown; AnalysisCard nests controls in a link and uses deprecated `onkeypress`.
- **Size:** five components exceed ~1000 lines (ChatPanel 2640, ScheduleManager 2043, DatasourceConfigPanel 1906, HealthChecksManager 1530, BuildsManager 1393, BuildPreview 1220, DataTable 1081) and are the main maintainability debt in this unit.


---

# Unit 19: UI components (second half)

### packages/frontend/src/lib/components/operations/ExpressionConfig.svelte
- **Verdict:** ok
- **Findings:**
  - [low] L17-18: `insertColumn` interpolates column name into `pl.col("...")` without escaping embedded quotes/backslashes; a column named `a"b` produces broken/injected expression text. Cosmetic-to-functional only since the expression is user-editable anyway.
  - Note: verbose inline `css({...})` blocks repeated per element (L41-59, L100-107 etc.) hurt maintainability; shared tokens exist (`input()`) but aren't used for the textarea.

### packages/frontend/src/lib/components/operations/FillNullConfig.svelte
- **Verdict:** issues found
- **Findings:**
  - [low] L93 vs L95: `<label for="fill-input-value">` points to id `fill-input-value`, but the input has `id="fill-value"` — label is not associated with its control (a11y).
  - [low] L94-98: fill value input lacks `data-testid` unlike sibling controls; minor test-consistency gap.

### packages/frontend/src/lib/components/operations/SampleConfig.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/operations/FilterConfig.svelte
- **Verdict:** issues found
- **Findings:**
  - [low] L567: token-remove `<X size={12} />` icon lacks `aria-hidden="true"` (all sibling icons at L254, L341 have it); screen readers may announce the SVG.
  - [low] L279: `{#each conditions as cond, i (i)}` keys by index, so removing a middle condition re-keys subsequent rows and can lose per-row DOM state (e.g., in-progress literal-token input text). Keying by a stable condition id would be safer.
  - Note: otherwise clean — no `{@html}`, no manual listeners/intervals, immutable-style updates via `updateCondition` (L87-94), good aria labeling throughout.

### packages/frontend/src/lib/components/operations/GroupByConfig.svelte
- **Verdict:** issues found
- **Findings:**
  - [low] L151-175: alias input has `id="{uid}-agg-alias"` but no associated `<label>`/`aria-label` — announced as unlabeled text field by screen readers.
  - [low] L207: `{#each safeAggregations as agg, i (i)}` keyed by index; fine for append-only but re-keys on removal (minor).
  - Note: otherwise clean; immutable updates, good labels elsewhere.

### packages/frontend/src/lib/components/operations/LimitConfig.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/operations/JoinConfig.svelte
- **Verdict:** issues found
- **Findings:**
  - [low] L339, L359: join-column dropdowns mutate nested fields in place (`joinCol.left_column = val`) while every other handler reassigns `config.*`; relies on Svelte 5 deep-proxy behavior and is inconsistent with the file's own immutable-update style (L129, L134).
  - [low] L379: remove-pair `<X size={14} />` icon lacks `aria-hidden="true"` (inconsistent with FilterConfig's icons).
  - [low] L240: `aria-describedby="join-type-help"` placed on the help `<div>` itself instead of the `<select>` at L217-222 — describes nothing.
  - Note: async schema loading is done well — generation counter (L38, L65, L86, L99) prevents stale-response races; no listener/interval leaks.

### packages/frontend/src/lib/components/operations/NotificationConfig.svelte
- **Verdict:** ok
- **Findings:**
  - Note: L352 suppresses `a11y_label_has_associated_control` for the "Input Column(s)" label wrapping a custom dropdown — acceptable, though an explicit `aria-label` on the dropdown trigger would remove the need. Query usage (L56-65) is properly scoped/enabled; no leaks.

### packages/frontend/src/lib/components/operations/PivotConfig.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/operations/RenameConfig.svelte
- **Verdict:** issues found
- **Findings:**
  - [low] L223: remove-mapping `<X size={12} />` icon lacks `aria-hidden="true"` (sibling ArrowRight at L187 has it).
  - Note: mapping add/remove use clean immutable updates (L30-45); keyed each by stable oldName (L153). Otherwise solid.

### packages/frontend/src/lib/components/operations/SelectConfig.svelte
- **Verdict:** issues found
- **Findings:**
  - [low] L110: `<ArrowRight size={14} />` icon lacks `aria-hidden="true"` (decorative).
  - Note: cast-map pruning on column change (L32-41) is a nice touch; immutable updates throughout.

### packages/frontend/src/lib/components/operations/SortConfig.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/operations/StringMethodsConfig.svelte
- **Verdict:** issues found
- **Findings:**
  - [medium] L208-221, L245-258, L312-325, L349-362, L415-428, L452-465, L518-531, L584-597, L621-634, L676-689: the identical ~13-line visually-hidden-help-span `css({...})` block is copy-pasted 10 times, and the same label style block another ~8 times (L188-199 etc.). A shared recipe/token would cut the file roughly in half — clear maintainability drag.
  - [low] L241: `bind:value={config.end}` on a number input yields `''` when cleared, but the config type declares `end: number | null` — empty string leaks into the pipeline payload instead of null.
  - Note: no XSS/listener/mutation problems; conditional param sections are correct per method.

### packages/frontend/src/lib/components/operations/TimeSeriesConfig.svelte
- **Verdict:** issues found
- **Findings:**
  - [low] L463 vs L465: `<label for="ts-input-new-column">` but the input has `id="ts-new-column"` — label not associated with its control (a11y).
  - [low] L74-84, L124-134, L165-175, L205-215, L254-264, L364-374, L401-411, L449-459: identical `h4` heading style block duplicated 8 times; same maintainability pattern as StringMethodsConfig.

### packages/frontend/src/lib/components/operations/TopKConfig.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/operations/UnionByNameConfig.svelte
- **Verdict:** ok
- **Findings:**
  - [low] L40-71: `loadSourceSchema` has no generation/staleness guard (unlike JoinConfig); a retry fired while the same source is still loading can interleave success/error writes. Low impact since last write wins and errors are per-source keyed.

### packages/frontend/src/lib/components/operations/ViewConfig.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/operations/UnpivotConfig.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/operations/WithColumnsConfig.svelte
- **Verdict:** issues found
- **Findings:**
  - [low] L497, L521, L573: `<Pencil/>` / `<X/>` icons lack `aria-hidden="true"`; buttons do carry aria-labels so impact is minor.
  - [low] L432: `{#each config.expressions ?? [] as expr, index (index)}` keyed by index while rows are removable/editable — same re-key caveat as elsewhere.
  - Note: form state machine (add/edit/save-to-library) is coherent; queries/mutations via svelte-query are properly scoped; no leaks or XSS.

### packages/frontend/src/lib/components/pipeline/ChartPreview.svelte
- **Verdict:** issues found
- **Findings:**
  - [high] File is 4294 lines implementing 9 chart renderers in one component. The overlay-drawing block (scatter/bar/line/area per overlay) is copy-pasted ~6 times (L1243-1316, L1407-1480, L1543-1616, L1789-1862, L1970-2043, L2184-2257, L2330-2403, L2782-2855, L3378-3451), the identical legend `onClick` closure appears 8 times (L1176-1190, L1337-1351, L1721-1735, L1888-1902, L2138-2152, L2279-2293, L2633-2647, L3289-3303), and the zoom `on('zoom')` handler is duplicated wholesale between renderLine (L2857-2968) and renderScatter (L3453-3552). This is the single largest maintainability liability in the unit — extract shared overlay/legend/zoom helpers or split per-chart-type modules.
  - [medium] L4002-4021 and L4271-4290: legend minimize control is a `<div role="button" tabindex="0">` with no accessible name (only a hover-only visual affordance) — keyboard users get an unnamed tab stop; use a real `<button aria-label="Minimize legend">`.
  - [low] L4146/L4148/L4194/L4196: chevron icons lack `aria-hidden="true"`; side-tab buttons rely on `title` alone for their name.
  - [low] L72-73: `selectedKeys`/`hiddenSeries` SvelteSets are never cleared when `data`/chartType change, so stale keys from a previous dataset can linger (harmless visually since opacity lookups miss, but state leaks across renders).
  - Note: no `{@html}`; D3 event handlers are attached inside the `$effect` whose returned `observeChart` teardown removes them (L1050-1067); tooltip rendered via Svelte text interpolation, not innerHTML — no XSS sink.

### packages/frontend/src/lib/components/pipeline/ConnectionLine.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/pipeline/DragPreview.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/pipeline/InlineDataTable.svelte
- **Verdict:** ok
- **Findings:**
  - Note: query keying by hashed pipeline + datasource config (L72-102) is well done; `$effect` at L125-128 resets pagination on key change. No leaks.

### packages/frontend/src/lib/components/pipeline/DatasourceNode.svelte
- **Verdict:** issues found
- **Findings:**
  - [low] L654-706: engine-resources disclosure `<button>` lacks `aria-expanded={engineExpanded}` / `aria-controls`; expanded state is conveyed only visually via chevron rotation (L700).
  - [low] L324-336, L417, L548, L684, L703: decorative lucide icons lack `aria-hidden="true"` (inconsistent with labeled buttons elsewhere in the file).
  - Note: at 882 lines it is large but mostly flat markup; store updates are immutable and read-only mode is consistently guarded.

### packages/frontend/src/lib/components/pipeline/OutputNode.svelte
- **Verdict:** issues found
- **Findings:**
  - [medium] 1783 lines mixing build orchestration, notification config, health checks, schedules, modals and toasts in one component; the three collapsible sections (L1262-1679) are near-identical disclosure patterns that could be one subcomponent.
  - [low] L1264-1297, L1503-1547, L1600-1633: section disclosure `<button>`s lack `aria-expanded`/`aria-controls` (contrast with the mode menu trigger at L967 which does set `aria-expanded`).
  - Note: timer hygiene is correct (`cancelToastTimer` cleared in effect teardown, L572-579); async flows guard against double-submit (`toggling`, `cancelPending`, `buildStarting`); no XSS sinks.

### packages/frontend/src/lib/components/pipeline/PipelineCanvas.svelte
- **Verdict:** issues found
- **Findings:**
  - [low] L81/L362 vs L321: `canvasEl` is bound via `bind:this` but never used — the auto-scroll `$effect` instead does a global `document.querySelector('.pipeline-canvas')`; use the ref.
  - [low] L494-500, L513-515, L645-651, L664-670, L733-760: icon-only buttons rely on `title` alone for their accessible name and their icons lack `aria-hidden="true"`; the scroll-to-output button (L733) is the worst offender since it appears/disappears dynamically.
  - Note: all timers/intervals/observers are created inside `$effect` with proper teardown (L99-103, L292-299, L317-331, `{@attach observeOutput}` at L706); drag/drop dependency validation (L169-199) is careful. No XSS.

### packages/frontend/src/lib/components/pipeline/StepConfig.svelte
- **Verdict:** ok
- **Findings:**
  - Note: 24 near-identical `bindDraftConfig<T>()` bindings (L125-149) plus a 25-branch `{#if step.type === ...}` chain (L425-511) are verbose but explicit; a component map would be tighter without changing behavior. Draft sync via `draftReady` guard (L104-109, L159-172) correctly avoids rendering with stale config.

### packages/frontend/src/lib/components/pipeline/StepLibrary.svelte
- **Verdict:** issues found
- **Findings:**
  - [low] L54-56: touch long-press `setTimeout` is only cleared via pointer handlers (`cancelLongPress`); there is no `$effect` teardown, so unmounting mid-press fires `initiateDrag` on a dead component and starts a drag with no drop surface.
  - [low] L276-297: operations search input has no label or `aria-label` (placeholder-only naming).
  - [low] L118-143: icon imports appear mid-file after function definitions — works, but hurts scanability; move to top.

### packages/frontend/src/lib/components/pipeline/StepNode.svelte
- **Verdict:** issues found
- **Findings:**
  - [low] L135-138: per-instance `rowCounts`/`rowCountLoads`/`rowCountErrors` SvelteMaps are keyed by pipeline hash + config JSON and never pruned — every pipeline edit adds new entries that live for the component's lifetime (unbounded growth in long sessions).
  - [low] L257-259: touch long-press timer has no unmount teardown (same pattern as StepLibrary); `copyTimer` is properly cleaned up at L203-207 but the drag timer is not.
  - [low] L398, L430, L452, L401, L664: decorative icons lack `aria-hidden="true"`; title-only buttons (L388, L428, L448) are acceptable but inconsistent with aria-label usage elsewhere.

### packages/frontend/src/lib/components/shell/Panel.svelte
- **Verdict:** ok

### packages/frontend/src/lib/components/shell/Sidebar.svelte
- **Verdict:** ok
- **Findings:**
  - [low] L577: `title={collapsed ? 'Sign out' : 'Sign out'}` — both branches identical; simplify.
  - Note: strong a11y throughout (`aria-current`, `aria-expanded` on engines trigger, labeled buttons); engines stream lifecycle correctly owned by popup-open effect (L167-171).

### packages/frontend/src/lib/components/udfs/UdfEditor.svelte
- **Verdict:** issues found
- **Findings:**
  - [low] L137-141: the dirty-tracking `$effect` fires once on mount; in `create` mode (`initialized` stays false but the guard only covers edit mode) it sets `dirty = true` immediately, so `beforeunload` (L348-352) warns about leaving a form the user never touched.
  - [low] L293 vs L294-298: `<label for="udf-output">` references an id that doesn't exist — the "Output dtype" control is a custom dropdown button with no matching id.
  - Note: hydration guard via `initialized` (L47-60) is correct; no leaks/XSS.

### packages/frontend/src/lib/components/udfs/UdfSignatureBuilder.svelte
- **Verdict:** ok



---

# Unit 20: charts, editor, representations & routes

### packages/frontend/src/lib/charts/interaction.ts
- **Verdict:** ok

### packages/frontend/src/lib/charts/preparation.ts
- **Verdict:** ok
- **Findings:**
  - [low] `numberValue` (lines 4–8) silently coerces non-numeric strings and `null` to `0` (`Number(value) || 0`), so `"abc"` and `""` are indistinguishable from `0` in chart aggregation — acceptable for charts but masks data errors.

### packages/frontend/src/lib/charts/render-lifecycle.ts
- **Verdict:** ok
- **Findings:** Lifecycle teardown is correct: `observeChart` disconnects the ResizeObserver, cancels the pending rAF, and removes rendered SVGs on cleanup (lines 16–20). No leak.

### packages/frontend/src/lib/chat/panel-layout.svelte.ts
- **Verdict:** issues found
- **Findings:**
  - [low] `trackPointer` (lines 87–96) listens for `pointermove`/`pointerup` but not `pointercancel`; if a resize gesture is interrupted (e.g. alt-tab, touch cancel), listeners stay attached and `isResizing` remains `true`.
  - [low] `restore()` (lines 18–25) does `Math.max(300, Number(height))` with no `NaN` guard; a corrupted `localStorage` value yields `NaN` panel dimensions.

### packages/frontend/src/lib/chat/presentation.ts
- **Verdict:** ok

### packages/frontend/src/lib/editor/preview-state.svelte.ts
- **Verdict:** ok
- **Findings:**
  - [low] `setRun` (lines 18–23) persists every run key ever set to IndexedDB; the map is only cleared on `initialize`/`reset`, so storage grows monotonically per analysis across sessions.

### packages/frontend/src/lib/representations/engine.ts
- **Verdict:** ok

### packages/frontend/src/routes/+layout.svelte
- **Verdict:** issues found
- **Findings:**
  - [medium] Route authorization is client-side only: the unauthenticated redirect is a `$effect` (lines 64–76) and there is no `hooks.server.ts`, `+layout.server.ts`, or server-side `load` guard anywhere under `src/routes` (verified: only `prerender` flags exist in all `+*.ts` files). All protected data lives behind the backend API, so this is defense-in-depth-only UI behavior, but protected route markup/shell renders before the redirect fires on a hard load.
  - [low] Lines 85–95 perform one-shot `idbGet` hydration for theme/sidebar state during component init (outside `$effect`, guarded only by `typeof window`), inconsistent with the effect-based pattern used everywhere else in this file; can cause a theme flash since the `$effect` at lines 79–83 writes the default theme first.
  - [low] Lines 281–286 load JetBrains Mono from fonts.googleapis.com at runtime — external CDN dependency (privacy/offline concern for a local-first product).

### packages/frontend/src/routes/+layout.ts
- **Verdict:** ok (`export const prerender = true`)

### packages/frontend/src/routes/+page.svelte
- **Verdict:** issues found
- **Findings:**
  - [low] `confirmBulkDelete` (lines 190–209) removes *all* selected ids from the query cache even when some deletes failed, then invalidates; until refetch completes the UI hides analyses that still exist.
  - [low] Search text and sort option are persisted under global IDB keys `'analysis-search'`/`'analysis-sort'` (lines 100–108) though the list itself is namespace-scoped — preferences leak across namespaces (cosmetic).
  - XSS: delete/duplicate confirmations interpolate names into plain text bindings only — safe.

### packages/frontend/src/routes/(auth)/+layout.svelte
- **Verdict:** ok

### packages/frontend/src/routes/(auth)/+layout.ts
- **Verdict:** ok (`prerender = false`)

### packages/frontend/src/routes/(auth)/callback/+page.svelte
- **Verdict:** ok
- **Findings:**
  - [low] `$effect` (lines 8–13) navigates to `/` unconditionally after `authStore.resolve()`; `resolve()` swallows errors into `status='failed'` (auth.svelte.ts:41–45), so a failed OAuth callback lands on `/` and relies on the layout's bootstrap-error screen rather than surfacing a callback-specific error.

### packages/frontend/src/routes/(auth)/forgot-password/+page.svelte
- **Verdict:** ok

### packages/frontend/src/routes/(auth)/login/+page.svelte
- **Verdict:** ok

### packages/frontend/src/routes/(auth)/register/+page.svelte
- **Verdict:** ok

### packages/frontend/src/routes/(auth)/reset-password/+page.svelte
- **Verdict:** ok

### packages/frontend/src/routes/(auth)/verify/+page.svelte
- **Verdict:** issues found
- **Findings:**
  - [low] `$effect` (lines 15–30) fires `verifyEmail(token)` with no abort/cleanup and no re-entry guard; the promise result is applied after unmount if the user navigates away mid-verification (harmless today, but a stale-write pattern).

### packages/frontend/src/routes/analysis/[id]/+page.svelte
- **Verdict:** issues found
- **Findings:**
  - [medium] Maintainability: a 2,611-line single component owns lock-session lifecycle (185–224), IDB draft hydrate/persist (243–351), engine prewarm (558–594), inferred-schema hydration (597–647), source-schema loading (670–758), favorites, version history, code export, tab context menu, and three inline modal snippets. Extracting concerns (e.g. a `useAnalysisDraft`/lock module) would materially reduce risk; several effects already need careful token/gate bookkeeping (`draftLoadGate`, `inferredSchemaGate`, `hydratedGates`) to avoid races.
  - [low] Line 2 imports legacy `page` from `$app/stores` (used as `$page.params` at line 90) while the rest of the codebase has migrated to `$app/state` (e.g. `+layout.svelte:3`, `monitoring/+page.svelte:5`) — inconsistent runes-era usage.
  - [low] Draft hydration (304–315) restores a saved draft and unconditionally sets `isDirty = true` (line 314) even when the draft is byte-identical to the server version, forcing the beforeunload guard (2001–2006) and disabling Discard semantics incorrectly.
  - [low] Engine prewarm effect (558–594) spawns an analysis engine 300 ms after mount for any viewer, including users who hold no lock and immediately navigate; cost is bounded by the `alive` flag/timer cleanup but still fires for read-only visitors.
  - XSS: verified clean — the editable `<h1>` uses only `textContent` (1437–1450), export code renders as escaped text in `<pre><code>` (2280–2292), no `{@html}` in the file.

### packages/frontend/src/routes/analysis/[id]/+page.ts
- **Verdict:** ok (`prerender = false`)

### packages/frontend/src/routes/analysis/new/+page.svelte
- **Verdict:** issues found
- **Findings:**
  - [low] Imported pipeline JSON is parsed and shape-checked only ad hoc (lines 493–511, 139–194); correctness relies on server-side `importAnalysis` validation. Client accepts arbitrary nested objects into `importedPipeline` state — safe from XSS (text bindings only) but fragile typing-wise.
  - [low] `goto(resolve(\`/analysis/${analysis.id}\`))` (lines 541, 557, 575) passes dynamic strings through the route-typed `resolve()` helper, bypassing its compile-time route safety (pattern repeated across routes).
  - [low] `handleGenerate` (461–491) has no concurrency guard beyond button `disabled`; double-invocation via rapid Enter is theoretically possible since `generating` is checked only in the template.
  - Template/AI/clone/import flows otherwise validate well (`canProceed`, `validateOutputConfig`, missing-datasource remap detection).

### packages/frontend/src/routes/datasources/+page.svelte
- **Verdict:** issues found
- **Findings:**
  - [low] `branchOptions` `$derived.by` (lines 167–176) reads `activeBranch`, which is declared *below* it (177–181); this works only because Svelte derives evaluate lazily, but the ordering is fragile and confusing.
  - URL-driven selection (`?id=`), stale-selection clearing (100–129), and delete mutation flow are correct; preview remount keyed by config hash (`{#key previewKey}`, 604–610) prevents stale canvas state.

### packages/frontend/src/routes/datasources/[id]/+page.svelte
- **Verdict:** ok (redirect shim)

### packages/frontend/src/routes/datasources/[id]/+page.ts
- **Verdict:** ok — 307 redirect to `/datasources?id=<id>`; fixed path, no open-redirect risk.

### packages/frontend/src/routes/datasources/+page.ts
- **Verdict:** ok (`prerender = false`)

### packages/frontend/src/routes/datasources/new/+page.svelte
- **Verdict:** issues found
- **Findings:**
  - [medium] Line 554: the CSV "Tab" delimiter option is `value="\t"` — a literal two-character backslash-`t` string, not a tab character. Uploading with "Tab" selected sends `delimiter: "\\t"` to the backend and will mis-parse tab-separated files.
  - [low] In `handleFileUpload` the `.xlsx` success path (225–232) returns before `finally { loading = false }`… which is fine, but the non-xlsx error path (241–244) returns without resetting anything else — consistent; actual nit: bulk upload partial failure leaves `selectedFiles` intact with results shown (intended), yet successful bulk upload navigates away discarding the results view (149–154).
  - File-type validation (84–102), connection-string handling (plain text input, sent to backend), and error display are all sound; no XSS surface (all text bindings).

### packages/frontend/src/routes/lineage/+page.svelte
- **Verdict:** ok
- **Findings:**
  - [low] Query key includes `selectedDatasourceId/effectiveBranch/lineageMode/internals` (line 67) so every toggle refetches full lineage with default `staleTime` — acceptable, but no caching tuning for a potentially heavy endpoint.

### packages/frontend/src/routes/monitoring/+page.svelte
- **Verdict:** ok — URL-hash-free tab state via `?tab=`, validated against allowlist (20–25), accessible roving-tabindex keyboard handling.

### packages/frontend/src/routes/profile/+page.svelte
- **Verdict:** ok — lazy tab mounting retained via `activated` SvelteSet (56–61, 115–148); hash-driven tab validated against allowlist.

### packages/frontend/src/routes/profile/AccountTab.svelte
- **Verdict:** issues found
- **Findings:**
  - [low] `disconnect()` (79–101): if unlink succeeds but the follow-up `getMe()` refresh fails, the earlier success message in `linkMessage` is overwritten by the refresh error — misleading feedback; also `getMe()` runs even when unlink failed.
  - Password validation duplicated client-side matches register/reset rules; OAuth connect uses full-page nav to `/api/v1/auth/<provider>` (75–77) — fine.

### packages/frontend/src/routes/profile/AiProvidersTab.svelte
- **Verdict:** ok
- **Findings:**
  - [low] Masked secrets are loaded as empty strings and only sent when dirtied (`*_dirty` flags, 70–71) — good no-clobber design; note `handleTestAIProvider` transmits the currently typed key to test/list endpoints (93–102), which is inherent to the feature.

### packages/frontend/src/routes/profile/NotificationsTab.svelte
- **Verdict:** ok — same masked-secret dirty-flag pattern; subscriber deletion uses mutation + cache invalidation correctly.

### packages/frontend/src/routes/profile/SystemTab.svelte
- **Verdict:** ok — namespace-scoped reload guarded by `aborted` + namespace comparison (50–72); collapse-state sync effect (125–137) is loop-safe (writes only sets not read by the effect's dependencies).

### packages/frontend/src/routes/profile/SystemTab.test.ts
- **Verdict:** ok — focused regression test asserting the switch stays disabled on persisted state until the toggle resolves; mocks are appropriately scoped.

### packages/frontend/src/routes/udfs/+page.svelte
- **Verdict:** issues found
- **Findings:**
  - [low] `search` is bound directly into the query key (lines 34–41): every keystroke creates a new query entry (no debounce, no `placeholderData`), causing spinner flicker and unbounded cache growth while typing.
  - Inline Confirm/Cancel delete buttons (314–330) mutate immediately on confirm without awaiting; errors surface only via invalidated list — acceptable but silent-failure prone compared to the ConfirmDialog pattern used elsewhere.

### packages/frontend/src/routes/udfs/[id]/+page.svelte
- **Verdict:** ok (thin wrapper around `UdfEditor mode="edit"`; id resolution delegated to the component, outside this unit)

### packages/frontend/src/routes/udfs/[id]/+page.ts
- **Verdict:** ok (`prerender = false`)

### packages/frontend/src/routes/udfs/new/+page.svelte
- **Verdict:** ok (thin wrapper around `UdfEditor mode="create"`)

## Cross-cutting notes (verified within scope)
- **XSS:** The only `{@html}` in the frontend is `ChatPanel.svelte:1583` rendering `{@html renderMarkdown(msg.content)}`; `renderMarkdown` (`lib/utils/markdown.ts:10–14`) pipes `marked` output through `DOMPurify.sanitize` and has tests covering `<script>`, `onerror`, and `javascript:` vectors. The `btn.innerHTML` assignments in `ChatPanel.svelte:213/218/221` inject static SVG strings only. No unsanitized HTML sinks found in any audited file.
- **Lifecycle leaks:** Chart teardown (`render-lifecycle.ts`) and all rAF/listener effects in `+layout.svelte` and `analysis/[id]` return proper cleanups. Only gap found is the missing `pointercancel` handling in `panel-layout.svelte.ts`.

