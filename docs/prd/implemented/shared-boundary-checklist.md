# Package boundary cleanup checklist

> **Status (audited 2026-08-02): Implemented — archived completed boundary audit.**
> **Portfolio:** [PRD index](../README.md)

Goal: no production package imports another owner package's internals. Owner-specific behavior lives in its owning package, and cross-package coordination happens through PostgreSQL-backed state, notifications, and internal HTTP/RPC boundaries.

## Rules

- [x] `backend` owns HTTP/API concerns, auth/session wiring, route validation, response shaping, settings CRUD, Telegram CRUD, and websocket delivery state
- [x] `worker` owns execution/runtime behavior, datasource execution/loading, healthcheck evaluation over dataframes, notification execution, and runtime-local build state
- [x] `scheduler` owns schedule orchestration and scheduled-build request construction
- [x] No standalone shared package remains; backend owns contracts, persistence, migrations, runtime IPC transport, config/database/logging/http helpers, and API schemas
- [x] No production package imports another owner package's internals
- [x] Cross-owner work handoff is persisted in Postgres and observed through DB rows / `pg_notify`

## Shared removals / relocations

### Backend-owned code relocated from the former shared area
- [x] Move dependencies helpers into a backend-owned package
- [x] Move error handlers into a backend-owned package
- [x] Move validation helpers into a backend-owned package
- [x] Move proxy helpers into a backend-owned package
- [x] Move settings store into a backend-owned package
- [x] Move Telegram store into a backend-owned package

### Worker-owned code relocated from the former shared area
- [x] Keep build runtime state local to worker or replace it with durable DB-backed flow
- [x] Backend websocket state is backend-owned; worker snapshot persistence is worker-owned
- [x] Move datasource loading into worker ownership
- [x] Move notification execution into worker ownership

### Scheduler-owned orchestration code relocated from the former shared area
- [x] Make scheduled payload construction scheduler-owned

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
- [x] Datasource schema extraction runs through worker compute/datasource execution
- [x] Datasource snapshot comparison runs through worker compute/datasource execution
- [x] Datasource column stats run through worker compute/datasource execution

### Settings / Telegram / notifications
- [x] Backend owns settings CRUD/update/bootstrap logic
- [x] Backend owns Telegram subscriber/listener CRUD logic
- [x] Worker-manager reads only persisted runtime-facing settings/subscriber data it needs
- [x] Notification sending is owned by a single package and does not rely on shared app-domain service code

## Dependency cleanup
- [x] Remove `dataforge-worker` dependency from `packages/backend/pyproject.toml`
- [x] Remove `dataforge-worker` dependency from `packages/scheduler/pyproject.toml`
- [x] Ensure backend imports only backend-owned modules + shared neutral modules
- [x] Ensure scheduler imports only scheduler-owned modules + shared neutral modules
- [x] Ensure worker imports only worker-owned modules + shared neutral modules

## Remaining strict-separation tasks
- [x] Remove `packages/backend/modules/compute/routes.py` test-support imports and replace them with a first-class owner-local test/runtime seam or real-runtime-only tests
- [x] Delete `test_support_runtime_compute.py`
- [x] Move/inline `test_support_scheduler.py` into owned test locations and delete the root helper
- [x] Remove shared-owned auth settings and re-home them under backend ownership
- [x] Remove auth-only exception classes and re-home them under backend ownership
- [x] Keep backend auth table definitions under backend-owned migrations
- [x] Re-audit non-backend packages so they know nothing about auth/current-user/login/session semantics beyond inert attribution fields
- [x] Re-audit tests so no remaining package test tree imports other owner-package internals except explicit cross-package integration coverage or owner-local runtime harness fixtures
- [x] Remove remaining backwards-compat/legacy paths that are no longer required
- [x] Remove unnecessary glue/support files after the redesign lands

## Verification
- [x] Repo audit shows no standalone shared package remains
- [x] Repo audit shows no backend -> worker production imports
- [x] Repo audit shows no scheduler -> worker production imports
- [x] Repo audit shows backend-only auth ownership with no auth semantics in shared/worker/scheduler
- [x] Repo audit shows no production imports of test-support modules
- [x] `just verify`
- [x] `just test`
- [x] `just test-e2e`
- [x] Push changes
- [x] Watch CI to green
