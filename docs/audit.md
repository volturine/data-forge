## Summary of Exploration

I analyzed the **605 source files** across the four main packages (`backend` 223 files, `frontend` 269 files, `worker` 97 files, `scheduler` 3 files, plus config/scripts). I used a combination of direct file inspection, `grep` pattern analysis, and a delegated deep-dive agent to identify systemic duplication and structural repetition.

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
| 10  | **Fix systemic `# type: ignore[arg-type]`** | 30+ files, 100+ instances (top: `build_runs_service.py` 35, `healthcheck/service.py` 16, `analysis/service.py` 16)                                                                                                                                                                                                                                                                                                           | This is a systemic SQLModel/Pydantic v2 typing mismatch. Instead of 100+ inline ignores, either: (a) add a single `pyproject.toml` `[tool.mypy.overrides]` for SQLModel query patterns, or (b) fix the underlying type annotations.                                                   |
| 11  | ✅ **Simplify `settings_store.py`**            | `backend_core/settings_store.py` | Resolved with explicit field maps for masked responses, ENV bootstrap, and partial update assignment while preserving secret handling and bootstrap ownership semantics. |
| 12  | ✅ **Simplify `settings_projection.py`**       | `backend_core/settings_projection.py` | Resolved with a typed cached `ResolvedSettingsSnapshot`, named defaults, and package-local projection methods for SMTP, Telegram, AI provider settings, and default model lookup. |

---

### 🟡 **P1 — Repetitive Logic (Frontend Stores)**

| #   | Task                                              | Files Affected                                                                           | Notes                                                                                                                                           |
| --- | ------------------------------------------------- | ---------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| 13  | ✅ **Extract generic `PaginatedStore` base class**   | `paginated-store.svelte.ts`, `builds.svelte.ts`, `engine-runs.svelte.ts` | Resolved with a rune-aware `PaginatedStore` base for shared status, error, params, in-flight, pending refresh, token, load, refresh, close, reset, and fetch lifecycle behavior. |
| 14  | **Extract `StreamStore` / `ReconnectionManager`** | `engines.svelte.ts`, `build-stream.svelte.ts`                                            | Both implement SSE reconnection logic with timers (`reconnectTimer`, `shouldReconnect`, `scheduleReconnect`, `clearReconnectTimer`).            |
| 15  | **Extract generic API result handler**            | `datasource.svelte.ts`, `builds.svelte.ts`, `engine-runs.svelte.ts`, `engines.svelte.ts` | Repeated `.match(okHandler, errHandler)` with identical error assignment.                                                                       |
| 16  | **Consolidate store lifecycle patterns**          | `builds.svelte.ts`, `engine-runs.svelte.ts`, `engines.svelte.ts`, `chat.svelte.ts`       | Token/counter race prevention, `inFlight`/`pendingRefresh`, `close()`/`reset()` are copy-pasted.                                                |

---

### 🟢 **P2 — Incomplete Abstractions & Orphaned Modules**

| #   | Task                                                    | Files Affected                                                                                                                                                                    | Notes                                                                                                                                              |
| --- | ------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| 17  | **Audit backend_core for orphaned modules**             | `docker_healthcheck.py`, `healthcheck_runner.py`, `app_error_status.py`, `public_schema.py`, `proxy.py`, `migrations.py`, `analysis_cycles.py`, `engine_live.py`, `build_live.py` | Many have 0–2 consumers. Determine if they are truly needed or if they can be merged into their callers.                                           |
| 18  | **Merge `healthcheck_schemas` + `healthcheck_runner`**  | `backend_core/healthcheck_schemas.py`, `backend_core/healthcheck_runner.py`, `modules/healthcheck/*`                                                                              | Healthcheck schemas, runner, and service are split across three locations. Consolidate into `modules/healthcheck` or a single backend_core module. |
| 19  | **Consolidate runtime notification modules**            | `backend_core/runtime_notifications.py`, `worker/runtime/runtime_notifications.py`, `worker/runtime/notification_delivery.py`, `worker/operations/notification.py`                | Notification logic is fragmented across backend and worker. Check for overlap.                                                                     |
| 20  | **Review `backend_core/smtp.py` + `telegram_store.py`** | These are thin wrappers around external APIs. Ensure they are not duplicating what `modules/notification` or `modules/telegram` already do.                                       |

---

### 🟢 **P2 — Meaningless / Outdated Comments**

| #   | Task                                     | Files Affected                                               | Notes                                                                                                                                                                |
| --- | ---------------------------------------- | ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 21  | ✅ **Remove redundant docstrings**          | `backend_core/exceptions.py`, `worker/runtime/exceptions.py` | Resolved by removing low-signal backend exception docstrings; worker exceptions were already using docstring-free classes. |
| 22  | ✅ **Remove copy-pasted SQLModel comments** | `engine_runs_service.py` | Resolved by removing the remaining stale SQLModel/Pydantic explanatory comment; the actionable typing cleanup remains tracked by #10/#23. |
| 23  | **Audit `# type: ignore` comments**      | All 30+ files with `# type: ignore[arg-type]`                | Replace individual ignores with a module-level or project-level mypy override if the pattern is universal.                                                           |

---

### 🟢 **P2 — Frontend Component Deduplication**

| #   | Task                                                      | Files Affected                                                                                                                   | Notes                                                                                                   |
| --- | --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| 24  | **Audit `build-stream.svelte.ts` vs `engines.svelte.ts`** | Already covered in #14, but also check if `build-stream` types (`build-stream.ts` + `build-stream.generated.ts`) can be unified. |
| 25  | **Review generated type files**                           | `step-schemas.generated.ts`, `build-stream.generated.ts`                                                                         | Ensure the generation scripts (`scripts/generate_ts_*.py`) are not producing redundant or stale output. |

---

### 🟢 **P2 — Worker Operations**

| #   | Task                                      | Files Affected                                                                        | Notes                                                                                                                                                                                                             |
| --- | ----------------------------------------- | ------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 26  | **Consolidate step converter patterns**   | `worker/operations/step_converter.py` vs `worker/operations/template_placeholders.py` | Check if these are doing overlapping work.                                                                                                                                                                        |
| 27  | **Review `compute_service.py` in worker** | `worker/runtime/compute_service.py`                                                   | This file is a nexus: it imports `object_store`, `iceberg_metadata`, `engine_identity`, `export_formats`, `notification_delivery`, `_utcnow`, `_copy_json`. It will be a major beneficiary of the P0/P1 cleanups. |

---

## Suggested Execution Order

1. **Start with P0** (shared contracts package). This is the biggest architectural win and unblocks everything else.
2. **Parallel**: P1 utilities (`_utcnow`, JSON copy, claim/lease helper) — these are low-risk, high-impact.
3. **Then**: Fix the `# type: ignore` systemic issue (either via mypy config or by fixing SQLModel annotations).
4. **Then**: Frontend store consolidation and backend service consolidation.
5. **Finally**: Comment cleanup and orphaned module audit.

This task list is ready to be converted into individual issues or PRs. Would you like me to begin executing any of these tasks?
