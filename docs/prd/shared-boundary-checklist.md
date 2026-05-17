# Shared boundary cleanup checklist

Goal: `packages/shared` contains only neutral contracts, persistence primitives, infrastructure, and generic libraries. Owner-specific behavior lives in its owning package. Cross-package coordination happens through PostgreSQL-backed state/notifications, not package imports.

## Rules

- [x] `backend` owns HTTP/API concerns, auth/session wiring, route validation, response shaping, settings CRUD, Telegram CRUD, and websocket delivery state
- [x] `worker-manager` owns execution/runtime behavior, datasource execution/loading, notification execution, and runtime-local build state
- [x] `scheduler` owns schedule orchestration and scheduled-build request construction
- [x] `shared` owns only neutral contracts, DB models, migrations, persistence primitives, runtime IPC transport, config/database/logging/http helpers, and generic libraries
- [x] No production package imports another owner package's internals
- [x] Cross-owner work handoff is persisted in Postgres and observed through DB rows / `pg_notify`

## Shared removals / relocations

### Backend-owned code currently in shared
- [x] Move `packages/shared/core/dependencies.py` into a backend-owned package
- [x] Move `packages/shared/core/error_handlers.py` into a backend-owned package
- [x] Move `packages/shared/core/validation.py` into a backend-owned package
- [x] Move `packages/shared/core/proxy.py` into a backend-owned package
- [x] Move `packages/shared/core/settings_store.py` into a backend-owned package
- [x] Move `packages/shared/core/telegram_store.py` into a backend-owned package

### Worker-manager-owned code currently in shared
- [x] Remove `packages/shared/core/build_live.py` from shared; keep build runtime state local to worker-manager or replace with durable DB-backed flow
- [x] Remove `packages/shared/core/engine_live.py` from shared; backend websocket state must be backend-owned, worker snapshot persistence must be worker-owned
- [x] Move `packages/shared/core/datasource_loading.py` into worker-manager ownership
- [x] Move notification execution out of `packages/shared/core/notification_delivery.py`

### Scheduler-owned / orchestration code currently in shared
- [x] Remove `packages/shared/core/analysis_pipeline_payloads.py` from shared and make scheduled payload construction scheduler-owned

## Architectural replacements

### Build flow
- [x] Starting a build persists durable build/request state in Postgres
- [x] Worker-manager picks up queued build work from Postgres without importing backend package code
- [x] Build websocket updates are driven from persisted build events plus notifications, not shared in-memory registries
- [x] Build cancellation remains durable and worker-visible through persisted state / engine-run state

### Engine flow
- [x] Worker-manager persists engine snapshots to Postgres
- [x] Backend engine websockets wake from notifications and re-read durable snapshot state
- [x] No shared in-memory engine registry is required across owner packages

### Datasource execution flow
- [x] Backend no longer loads datasource frames directly
- [x] Datasource schema extraction runs through worker-manager compute/datasource execution
- [x] Datasource snapshot comparison runs through worker-manager compute/datasource execution
- [x] Datasource column stats run through worker-manager compute/datasource execution

### Settings / Telegram / notifications
- [x] Backend owns settings CRUD/update/bootstrap logic
- [x] Backend owns Telegram subscriber/listener CRUD logic
- [x] Worker-manager reads only persisted runtime-facing settings/subscriber data it needs
- [x] Notification sending is owned by a single package and does not rely on shared app-domain service code

## Dependency cleanup
- [x] Remove `dataforge-worker-manager` dependency from `packages/backend/pyproject.toml`
- [x] Remove `dataforge-worker-manager` dependency from `packages/scheduler/pyproject.toml`
- [x] Ensure backend imports only backend-owned modules + shared neutral modules
- [x] Ensure scheduler imports only scheduler-owned modules + shared neutral modules
- [x] Ensure worker-manager imports only worker-manager-owned modules + shared neutral modules

## Remaining strict-separation tasks
- [x] Remove `packages/backend/modules/compute/routes.py` test-support imports and replace them with a first-class owner-local test/runtime seam or real-runtime-only tests
- [x] Delete `test_support_runtime_compute.py`
- [x] Move/inline `test_support_scheduler.py` into owned test locations and delete the root helper
- [x] Remove shared-owned auth settings from `packages/shared/core/config.py` and re-home them under backend ownership
- [x] Remove auth-only exception classes from `packages/shared/core/exceptions.py` and re-home them under backend ownership
- [x] Remove backend auth table definitions from `packages/shared/database/alembic/versions/0001_runtime_public.py`
- [x] Re-audit non-backend packages so they know nothing about auth/current-user/login/session semantics beyond inert attribution fields
- [x] Re-audit tests so no remaining package test tree imports other owner-package internals except explicit cross-package integration coverage or owner-local runtime harness fixtures
- [x] Remove remaining backwards-compat/legacy paths that are no longer required
- [x] Remove unnecessary glue/support files after the redesign lands

## Verification
- [x] Repo audit shows no owner-specific code left in `packages/shared`
- [x] Repo audit shows no backend -> worker-manager production imports
- [x] Repo audit shows no scheduler -> worker-manager production imports
- [x] Repo audit shows backend-only auth ownership with no auth semantics in shared/worker-manager/scheduler
- [x] Repo audit shows no production imports of test-support modules
- [x] `just verify`
- [x] `just test`
- [x] `just test-e2e`
- [x] Push changes
- [x] Watch CI to green
