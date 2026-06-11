## Summary of Exploration

I analyzed the **605 source files** across the four main packages (`backend` 223 files, `frontend` 269 files, `worker` 97 files, `scheduler` 3 files, plus config/scripts). I used a combination of direct file inspection, `grep` pattern analysis, and a delegated deep-dive agent to identify systemic duplication and structural repetition.

---

## Consolidated Cleanup Task List

### 🔴 **P0 — Duplicate Types & Cross-Package Duplication**

These are the highest-impact items because every schema change requires manual sync across packages.

| #   | Task                                     | Files Affected                                                                                                                         | Notes                                                                                                                                                                           |
| --- | ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Extract shared contracts package**     | `backend_contracts/*` ↔ `worker_models/*`                                                                                              | 17+ file pairs are byte-for-byte identical except import paths and quote style. Create `packages/common` or `packages/contracts` and have both backend and worker depend on it. |
| 2   | **Deduplicate `namespace` module**       | `backend_core/namespace.py` ↔ `worker/runtime/namespace.py`                                                                            | Nearly identical. Only diff is a `namespace_database_schema()` helper missing in worker.                                                                                        |
| 3   | **Deduplicate `engine_identity` module** | `backend_core/engine_identity.py` ↔ `worker/runtime/engine_identity.py`                                                                | Same pattern: identical logic, only imports and quotes differ.                                                                                                                  |
| 4   | **Deduplicate Iceberg utilities**        | `backend_core/iceberg_metadata.py`, `iceberg_snapshot_reader.py` ↔ `worker/runtime/iceberg_metadata.py`, `iceberg_snapshot_reader.py`  | Same files duplicated.                                                                                                                                                          |
| 5   | **Deduplicate `object_store`**           | `backend_core/object_store.py` ↔ `worker/runtime/object_store.py`                                                                      | Check if these are identical; if so, move to shared package.                                                                                                                    |
| 6   | **Consolidate exception hierarchies**    | `backend_core/exceptions.py` (11 NotFoundError classes), `worker/runtime/exceptions.py` (4 classes), `backend_core/auth_exceptions.py` | Every `*NotFoundError` follows identical boilerplate. Create a `NotFoundError` base/mixin that auto-generates `error_code` and `details`.                                       |

---

### 🟡 **P1 — Repetitive Logic (Backend Services)**

| #   | Task                                        | Files Affected                                                                                                                                                                                                                                                                                                                                                                                                               | Notes                                                                                                                                                                                                                                                                                 |
| --- | ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 7   | **Extract `_utcnow()` utility**             | 16 files: `build_jobs_service.py`, `build_runs_service.py`, `compute_requests_service.py`, `datasource_delete_service.py`, `engine_instances_service.py`, `runtime_outbox_service.py`, `runtime_workers_service.py`, `auth/models.py`, `auth/service.py`, `compute/routes.py`, `locks/service.py`, `runtime_overview/service.py`, `scheduler/service.py`, `worker/builds/build_live.py`, `worker/runtime/compute_service.py` | Move to `backend_core/utils/time.py` or equivalent.                                                                                                                                                                                                                                   |
| 8   | **Extract generic claim/lease helper**      | `build_jobs_service.py`, `compute_requests_service.py`, `runtime_outbox_service.py`, `scheduler/service.py`                                                                                                                                                                                                                                                                                                                  | All implement the same `skip_locked` + `reclaimable_owner_ids` + CAS update pattern. Extract `claim_next_row(session, table, reclaimable_ids)`.                                                                                                                                       |
| 9   | **Consolidate JSON copy helpers**           | `engine_instances_service.py`, `build_runs_service.py`, `worker/runtime/compute_service.py`                                                                                                                                                                                                                                                                                                                                  | `_copy_json`, `_copy_json_dict`, `_copy_result_json` are all `dict(value) if isinstance(value, dict) else None/{}`.                                                                                                                                                                   |
| 10  | **Fix systemic `# type: ignore[arg-type]`** | 30+ files, 100+ instances (top: `build_runs_service.py` 35, `healthcheck/service.py` 16, `analysis/service.py` 16)                                                                                                                                                                                                                                                                                                           | This is a systemic SQLModel/Pydantic v2 typing mismatch. Instead of 100+ inline ignores, either: (a) add a single `pyproject.toml` `[tool.mypy.overrides]` for SQLModel query patterns, or (b) fix the underlying type annotations.                                                   |
| 11  | **Simplify `settings_store.py`**            | `backend_core/settings_store.py`                                                                                                                                                                                                                                                                                                                                                                                             | 34 sequential `if data.xxx is not None` blocks and 16 repetitive `if not row.xxx and app_settings.xxx` blocks. Use Pydantic model iteration or field mapping.                                                                                                                         |
| 12  | **Simplify `settings_projection.py`**       | `backend_core/settings_projection.py`                                                                                                                                                                                                                                                                                                                                                                                        | `_load_resolved_snapshot()` returns a raw `dict[str, object]` with 20+ hardcoded defaults duplicated from `settings_schemas.py`. Seven `get_resolved_*` functions follow identical `if not bool(resolved['exists']): return default_dict` pattern. Use a dataclass or Pydantic model. |

---

### 🟡 **P1 — Repetitive Logic (Frontend Stores)**

| #   | Task                                              | Files Affected                                                                           | Notes                                                                                                                                           |
| --- | ------------------------------------------------- | ---------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| 13  | **Extract generic `PaginatedStore` base class**   | `builds.svelte.ts`, `engine-runs.svelte.ts`                                              | Structurally identical: `status`, `error`, `params`, `inFlight`, `pendingRefresh`, `token`, identical `load/refresh/close/reset/fetch` methods. |
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
| 21  | **Remove redundant docstrings**          | `backend_core/exceptions.py`, `worker/runtime/exceptions.py` | Docstrings like `"""Raised when a datasource is not found."""` for `DataSourceNotFoundError` add zero value.                                                         |
| 22  | **Remove copy-pasted SQLModel comments** | `engine_runs_service.py`, `build_runs_service.py`, etc.      | `# SQLModel type annotations not fully compatible with Pydantic v2` copy-pasted above every `.where()` clause. The `# type: ignore` comment already explains itself. |
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
