## Summary of Exploration

The initial audit analyzed **605 source files** across the four main packages (`backend` 223 files, `frontend` 269 files, `worker` 97 files, `scheduler` 3 files, plus config/scripts). A follow-up scan on 2026-07-04 covered **793 package/script source files** after the protocol rewrite and subsequent cleanup commits, excluding virtualenvs, `node_modules`, package-local generated `dataforge_protocol`, Svelte build output, and other build artifacts.

The original P0 contract problem is resolved. Remaining exact duplicates are now limited to generated third-party protobuf validation files, empty package marker files, empty frontend route loaders, and a small set of deliberately package-local runtime helpers called out below.

---

## Consolidated Cleanup Task List

### ✅ **P0 — Protocol-First Contract Unification**

Status: resolved in the protocol-first rewrite. `packages/protocol` is now the single source of truth for wire contracts; backend, worker, and scheduler generate package-local `dataforge_protocol.*` code from it during install, checks, tests, dev, e2e, CI, and Docker builds. The generated trees are ignored rather than committed. The deleted `backend_contracts` and `worker_models` roots are not shimmed, and `just check` enforces package-boundary failures for the old import roots, deleted generated gRPC compatibility paths, generic protocol JSON payloads, engine-key prefix fossils, and removed backend data-plane facades.

| #   | Task                                     | Files Affected                                                                                                                         | Notes                                                                                                                                                                           |
| --- | ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Protocol-owned generated contracts**   | `packages/protocol/proto/*`, generated `dataforge_protocol/*` in backend/worker/scheduler | Replaced mirrored `backend_contracts`/`worker_models` packages with Buf-generated protobuf, pyi, and gRPC modules generated into each runtime package but not committed. |
| 2   | **Explicit namespace contract**          | `namespace` protocol fields plus package-local runtime helpers | Namespace validation is protocol annotated; package-local runtime helpers remain only where they own runtime behavior. |
| 3   | **Explicit engine identity**             | `EngineIdentity` protobuf plus package-local helpers | Removed prefixed engine-key string semantics. Runtime carries `scope`, `reuse_policy`, and resource IDs explicitly. |
| 4   | **Worker-owned Iceberg operations**      | `IcebergService` RPC and `WorkerDataPlaneClient` | Backend data-plane facades were removed; backend callers use typed worker RPC client operations. |
| 5   | **Worker-owned object-store operations** | `ObjectStoreService` RPC and `WorkerDataPlaneClient` | Backend object-store upload/download/delete/list/existence/URL construction now routes through the worker data-plane client. |
| 6   | **Protocol-coded errors**                | `ErrorCode`, `ErrorInfo`, package-local `AppError` | Boilerplate `*NotFoundError` subclasses were replaced by protocol-code factories and status mapping by generated `ErrorCode`. |

---

### 🟡 **P1 — Repetitive Logic (Backend Services)**

| #   | Task                                        | Files Affected                                                                                                                                                                                                                                                                                                                                                                                                               | Notes                                                                                                                                                                                                                                                                                 |
| --- | ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 7   | ✅ **Extract `_utcnow()` utility**             | `backend_core/time.py`, `worker/runtime/time.py`, formerly duplicated service-local helpers | Resolved with package-local UTC helpers. Backend keeps both aware and naive UTC helpers where DB models require different timestamp shapes; worker keeps its own helper to preserve package boundaries. |
| 8   | ✅ **Extract generic claim/lease helper**      | `backend_core/claiming.py`, `build_jobs_service.py`, `compute_requests_service.py`, `runtime_outbox_service.py`, `scheduler/service.py` | Resolved with shared `with_for_update_skip_locked` and `claim_by_lease_owner` primitives. Services still own their eligibility rules, state transitions, and schedule-specific due checks. |
| 9   | ✅ **Consolidate JSON copy helpers**           | `backend_core/json_utils.py`, `worker/runtime/json_utils.py`, formerly duplicated service-local helpers | Resolved with package-local `copy_json_dict` and `copy_json_object` helpers. Backend and worker stay separate to preserve package boundaries. |
| 10  | ✅ **Fix systemic `# type: ignore[arg-type]`** | Backend, worker, and scheduler SQL/query, framework-boundary, test-fake, and numeric coercion sites | Resolved without a broad mypy override. Backend SQLModel query expressions now use package-local typed SQL helpers, framework/test fakes use explicit boundary casts, and worker Polars numeric narrowing uses explicit casts. No backend/worker/scheduler source file retains `# type: ignore[arg-type]`. |
| 11  | ✅ **Simplify `settings_store.py`**            | `backend_core/settings_store.py` | Resolved with explicit field maps for masked responses, ENV bootstrap, and partial update assignment while preserving secret handling and bootstrap ownership semantics. |
| 12  | ✅ **Simplify `settings_projection.py`**       | `backend_core/settings_projection.py` | Resolved with a typed cached `ResolvedSettingsSnapshot`, named defaults, and package-local projection methods for SMTP, Telegram, AI provider settings, and default model lookup. |

---

### 🟡 **P1 — Repetitive Logic (Frontend Stores)**

| #   | Task                                              | Files Affected                                                                           | Notes                                                                                                                                           |
| --- | ------------------------------------------------- | ---------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| 13  | ✅ **Extract generic `PaginatedStore` base class**   | `paginated-store.svelte.ts`, `builds.svelte.ts`, `engine-runs.svelte.ts` | Resolved with a rune-aware `PaginatedStore` base for shared status, error, params, in-flight, pending refresh, token, load, refresh, close, reset, and fetch lifecycle behavior. |
| 14  | ✅ **Extract `StreamStore` / `ReconnectionManager`** | `reconnection-manager.ts`, `engines.svelte.ts`, `build-stream.svelte.ts` | Resolved with a shared `ReconnectionManager` for reconnect timer scheduling and clearing while keeping stream-specific state transitions in each store. |
| 15  | ✅ **Extract generic API result handler**            | `paginated-store.svelte.ts`, `builds.svelte.ts`, `engine-runs.svelte.ts` | Resolved for the truly repeated list-result lifecycle by `PaginatedStore`; remaining datasource/engine `.match()` calls are command-specific boundary adapters with distinct side effects. |
| 16  | ✅ **Consolidate store lifecycle patterns**          | `paginated-store.svelte.ts`, `reconnection-manager.ts`, `builds.svelte.ts`, `engine-runs.svelte.ts`, `engines.svelte.ts`, `build-stream.svelte.ts` | Resolved by moving list token/in-flight/pending-refresh lifecycle into `PaginatedStore` and reconnect timer lifecycle into `ReconnectionManager`; chat keeps its distinct EventSource retry/backoff flow. |

---

### 🟢 **P2 — Incomplete Abstractions & Orphaned Modules**

| #   | Task                                                    | Files Affected                                                                                                                                                                    | Notes                                                                                                                                              |
| --- | ------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| 17  | ✅ **Audit backend_core for orphaned modules**             | `docker_healthcheck.py`, `public_schema.py`, `proxy.py`, `migrations.py`, `analysis_cycles.py`, `engine_live.py`, `error_handlers.py`, `modules/healthcheck/runner.py` | Resolved by moving `healthcheck_runner.py` into `modules/healthcheck`, folding one-consumer `app_error_status.py` into `error_handlers.py`, confirming `build_live.py` is already absent, and retaining the remaining modules as active infrastructure owners. |
| 18  | ✅ **Merge `healthcheck_schemas` + `healthcheck_runner`**  | `modules/healthcheck/schemas.py`, `modules/healthcheck/runner.py`, `modules/healthcheck/*` | Resolved by moving healthcheck API schemas and runner into the owning `modules/healthcheck` package and updating callers/tests without backend_core compatibility aliases. |
| 19  | ✅ **Consolidate runtime notification modules**            | `backend_core/runtime_notifications.py`, `worker/runtime/runtime_notifications.py`, `worker/runtime/notification_delivery.py`, `worker/operations/notification.py`, `backend_core/live_hubs.py`, `worker/runtime/live_hubs.py` | Reviewed and retained by ownership boundary: backend runtime notifications wake backend live hubs from worker outbox payloads; worker runtime notifications wake job/request loops; worker notification delivery is the operation-facing RPC client. Repeated version-counter live hubs were reduced to package-local `VersionHub`/`KeyedVersionHub` primitives, and unused opposite-side live hubs were removed. |
| 20  | ✅ **Review `backend_core/smtp.py` + `telegram_store.py`** | `backend_core/smtp.py`, `backend_core/telegram_store.py`, `modules/settings`, `modules/auth`, `modules/telegram`, `backend_grpc` | Reviewed and retained: SMTP centralizes TLS/send behavior across settings, auth, and gRPC; Telegram store owns persistence for routes and bot handling. `modules/notification` is currently empty, so there is no duplicate owner to merge into. |

---

### 🟢 **P2 — Meaningless / Outdated Comments**

| #   | Task                                     | Files Affected                                               | Notes                                                                                                                                                                |
| --- | ---------------------------------------- | ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 21  | ✅ **Remove redundant docstrings**          | `backend_core/exceptions.py`, `worker/runtime/exceptions.py` | Resolved by removing low-signal backend exception docstrings; worker exceptions were already using docstring-free classes. |
| 22  | ✅ **Remove copy-pasted SQLModel comments** | `engine_runs_service.py` | Resolved by removing the remaining stale SQLModel/Pydantic explanatory comment; the actionable typing cleanup remains tracked by #10/#23. |
| 23  | ✅ **Audit `# type: ignore` comments**      | Backend, worker, and scheduler `# type: ignore[arg-type]` sites | Audited and then resolved through #10 without a broad mypy override. Follow-up cleanup removed stale `type-arg` suppressions; remaining ignores are narrower issues such as third-party package stubs and SQLModel attribute stubs. |

---

### 🟢 **P2 — Frontend Component Deduplication**

| #   | Task                                                      | Files Affected                                                                                                                   | Notes                                                                                                   |
| --- | --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| 24  | ✅ **Audit `build-stream.svelte.ts` vs `engines.svelte.ts`** | `build-stream.svelte.ts`, `engines.svelte.ts`, `reconnection-manager.ts`, `types/build-stream.ts` | Resolved by #14 for shared reconnection behavior. Build stream types are now protocol-anchored in `types/build-stream.ts`; the old `build-stream.generated.ts` file no longer exists. |
| 25  | ✅ **Review generated type files**                           | `scripts/check_package_boundaries.py`, protocol-anchored frontend types | Resolved by the protocol rewrite: deleted backend-derived TS generators and `*.generated.ts` imports are blocked by package-boundary checks, while frontend build-stream types derive from generated protocol JSON shapes. |

---

### 🟢 **P2 — Worker Operations**

| #   | Task                                      | Files Affected                                                                        | Notes                                                                                                                                                                                                             |
| --- | ----------------------------------------- | ------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 26  | ✅ **Consolidate step converter patterns**   | `worker/operations/step_converter.py`, `worker/operations/template_placeholders.py`, `worker/operations/ai.py`, `worker/operations/notification.py` | Reviewed and retained separately: `step_converter.py` owns protocol config parsing/validation before execution, while `template_placeholders.py` owns row-time string rendering used by AI and notification operations. |
| 27  | ✅ **Review `compute_service.py` in worker** | `worker/runtime/compute_service.py`, worker-owned runtime helpers | Reviewed after P0/P1 cleanup: compute service now uses protocol `EngineIdentity`, package-local time/JSON helpers, and worker-owned object-store/Iceberg/notification/export helpers. Remaining imports are worker runtime ownership points, not cross-package duplicates. |

---

## Follow-Up Scan Results

| #   | Task | Files Affected | Notes |
| --- | ---- | -------------- | ----- |
| 28  | ✅ **Consolidate live hub primitives** | `backend_core/live_hubs.py`, `worker/runtime/live_hubs.py`, `domain/build_jobs/live.py`, `domain/compute_requests/live.py`, deleted `worker/runtime/domain/build_runs/live.py` | Resolved after the original audit closeout. Replaced repeated version-counter hub classes with package-local primitives, removed the unused backend `request_hub`, removed the unused worker `response_hub`, and deleted the unused worker build-run live notification hub. |
| 29  | 🟡 **Retain explicit package-boundary helpers** | `backend_grpc/validation.py` ↔ `worker_grpc/validation.py`, `backend_core/json_utils.py` ↔ `worker/runtime/json_utils.py`, `backend_core/domain/protocol_enums.py` ↔ `worker/runtime/domain/protocol_enums.py` | These remain intentionally package-local because the architecture forbids a runtime `protocol` wrapper package or cross-package shared runtime dependency. Eliminating the last lines of duplication would require generating package-local helper code from protocol tooling, or accepting a new runtime shared package. |
| 30  | ✅ **Remove stale execution-plan language** | `docs/audit.md` | Replaced the pre-implementation "suggested execution order" with the current follow-up scan result so the audit no longer reads like unstarted work. |
| 31  | ✅ **Remove stale type-argument suppressions** | `modules/analysis/service.py` | Removed twenty obsolete type-argument ignore comments from analysis service `Session` annotations. Mypy now accepts the file without those suppressions, and source scans show no remaining type-argument ignores in backend, worker, scheduler, or scripts. |
| 32  | ✅ **Consolidate UDF fetch helpers and query typing** | `modules/udf/service.py` | Replaced repeated UDF select-by-id blocks with a typed `_get_udf_model` helper and switched simple query predicates to the package-local typed SQL helper. This removed all six type suppressions from the UDF service while preserving existing API behavior. |
| 33  | ✅ **Remove healthcheck query suppressions** | `modules/healthcheck/service.py` | Switched healthcheck result sorting and datasource ID lookups to typed SQL helper expressions, removing all inline suppressions from the healthcheck service without changing query behavior. |
| 34  | ✅ **Type Telegram bot database callbacks** | `modules/telegram/bot.py` | Added explicit `Session` annotations to the bot subscribe/unsubscribe database callbacks, removing the local `no-untyped-def` suppressions while keeping the existing `run_db` ownership boundary. |
| 35  | ✅ **Consolidate settings Telegram chat parsing** | `modules/settings/routes.py` | Replaced duplicated Telegram update chat extraction blocks with a typed helper and added a small runtime protocol for bot lifecycle calls. This removed the settings route's local `no-untyped-def` and Telegram chat assignment suppressions. |
| 36  | ✅ **Remove Telegram store query suppressions** | `backend_core/telegram_store.py` | Switched active-subscriber and subscriber-ID filters to typed SQL helper expressions, removing the store's boolean-comparison and `IN`-clause suppressions while preserving notification-listener behavior. |
| 37  | ✅ **Remove scheduler query suppressions** | `modules/scheduler/service.py` | Switched schedule-enabled and analysis dependency filters to typed SQL helper expressions, removing the scheduler service's boolean-comparison and `IN`-clause suppressions while preserving due-schedule and build-order behavior. |
| 38  | ✅ **Remove datasource list query suppressions** | `modules/datasource/service.py` | Switched pending-delete and hidden datasource filters to typed SQL helper boolean expressions, removing the datasource list route's boolean-comparison suppressions while preserving visible/hidden listing behavior. |
| 39  | ✅ **Remove datasource delete query suppression** | `backend_core/datasource_delete_service.py` | Switched pending-delete sweep lookup to a typed SQL helper boolean expression, removing the datasource-delete service's boolean-comparison suppression while preserving deletion queue ordering. |
| 40  | ✅ **Remove auth session query suppression** | `modules/auth/service.py` | Switched revoke-all-sessions filtering to a typed SQL helper boolean expression, removing the auth service's boolean-comparison suppression while preserving active-session revocation behavior. |

The remaining non-generated exact duplicates are deliberate boundary code, not active contract drift. If the project later decides that zero duplicated helper code matters more than strict package independence, the cleanest next step is protocol-owned generation of package-local enum/validation/helper adapters, still without importing `packages/protocol` at runtime.
