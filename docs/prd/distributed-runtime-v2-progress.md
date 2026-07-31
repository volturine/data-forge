# Distributed Runtime v2 Progress

## Status Summary

This tracker reflects the current repository state after the distributed runtime v2 implementation and the subsequent correctness remediation. The detailed invariant-level source of truth is `runtime-correctness-and-architecture-remediation.md`.

Latest update:

- Build jobs and compute requests now use renewable token-and-generation claims; stale event, completion, failure, and publication writes are fenced.
- Build event allocation, projection updates, terminal transitions, and runtime-outbox enqueueing now use atomic database transactions.
- Scheduler and runtime-outbox dispatch use durable, ordered, expiring claims.
- Analysis mutations require revisions, frontend requests are scoped to namespace epochs, and order-sensitive runtime operations define tie ordering.
- The database history is intentionally compacted to the two complete schema creators; no legacy upgrade path is supported.

Overall status:

- Phase 0: complete
- Phase 1: complete
- Phase 2: complete
- Phase 3: complete
- Phase 4: complete
- Phase 5: complete
- Phase 6: complete
- Phase 7: complete
- Phase 8: complete

Current claim:

- Postgres is the supported distributed runtime backend.
- Local dev/test uses the same Postgres-backed runtime model.
- One supervised app runtime runs API, scheduler, and a worker manager; build workers spawn dynamically from zero.
- Durable build state, renewable fenced leasing, DB-backed websocket replay, and scheduler leasing are implemented.
- `WORKERS > 1` is supported only when distributed runtime is enabled on Postgres.

Residual audit note:

- The implementation covers stale-owner rejection, active lease renewal, atomic build transitions, durable outbox recovery, scheduler claim ordering, analysis lost-update prevention, and frontend namespace isolation.
- The runtime/admin surface exposes runtime mode, API process identity, worker heartbeats, engine rows, and queue status through `/api/v1/runtime/overview`.
- Datasource command orchestration still crosses the API gRPC boundary, external notification consumers do not all provide durable idempotency acknowledgements, and the broad multi-process failure-injection matrix remains follow-up work.
- Lower-level metric counters such as lease renew outcomes, fenced-write rejection, attempt exhaustion, scheduler duplicate prevention, and datasource contention are not yet exposed as dedicated metrics.

## Final Validation Snapshot

Latest canonical validation on 2026-07-31:

- `just verify`: passed without warnings or generated drift
- backend unit suite: `976 passed`
- backend integration suite: `92 passed, 2 skipped`
- worker suite: `306 passed`
- scheduler suite: `3 passed`
- frontend unit suite: `1161 passed`
- `just test-e2e`: `350 passed` without unclassified warnings

Correctness fixes included in this green run:

- token-and-generation fencing for build jobs, compute requests, scheduler triggers, datasource publication, and runtime-outbox dispatch
- atomic build event/projection/finalization/cancellation transactions and bounded retry exhaustion
- analysis revision compare-and-swap and atomic version allocation
- namespace-epoch cancellation and stale-response rejection in frontend state
- deterministic query and tied pipeline-operation ordering
- durable notification staging and poison outbox handling

## Phase Details

### Phase 0: Freeze Unsupported Scaling

Status: complete

Evidence:

- `backend/main.py` rejects unsupported multi-worker startup unless distributed runtime is enabled on Postgres
- `backend/tests/test_main.py` asserts both the rejection path and the explicit allow path

Notes:

- `WORKERS > 1` is still guarded outside Postgres distributed runtime mode
- accidental split-brain outside the supported Postgres runtime remains blocked

### Phase 1: Schema-Enforced Events

Status: complete

Evidence:

- `backend/modules/compute/schemas.py` defines the discriminated build event union
- `backend/modules/build_runs/service.py` persists validated event payloads to `build_events`
- `frontend/src/lib/types/build-stream.generated.ts` is generated from backend schemas
- `Justfile` includes generated build-stream type freshness checks in `just check`

Notes:

- backend build event emission is schema-enforced
- frontend build-stream contracts are generated instead of hand-maintained

### Phase 2: Durable Build State In Single Process

Status: complete

Evidence:

- `backend/modules/build_runs/models.py` defines `build_runs` and `build_events`
- `backend/modules/build_runs/service.py` supports durable build creation, event append, replay, snapshot folding, and guarded terminal transitions
- `backend/modules/compute/routes.py` active build endpoints read durable DB state
- startup recovery marks stale running builds orphaned instead of recreating fake in-memory activity

Notes:

- build detail survives API restart
- cancellation cannot be overwritten by late success finalization

### Phase 3: DB-Backed Websocket Projection

Status: complete

Evidence:

- `backend/modules/compute/routes.py` sends DB-derived snapshots on websocket connect
- `backend/modules/compute/routes.py` replays events from `build_events` by sequence
- `backend/modules/runtime/ipc.py` provides Postgres `LISTEN/NOTIFY` wakeups in distributed mode
- `backend/tests/test_postgres_runtime_integration.py` validates cross-API-worker detail access and websocket replay

Notes:

- websocket delivery is a projection of durable state rather than the owner of state
- local dev/test remains same-node only and is not described as a separate distributed mode

### Phase 4: Dedicated Build Worker

Status: complete

Evidence:

- `backend/modules/build_jobs/models.py` defines the durable queue
- `backend/modules/build_jobs/service.py` implements claim, renew, expire, and finalize operations
- `backend/modules/runtime/worker.py` owns queued build execution and lease renewal
- `backend/worker.py` is the worker entrypoint that spawns one-shot build workers on demand
- `backend/modules/compute/routes.py` enqueues builds instead of running them inline

Notes:

- API workers no longer own build execution
- `ProcessManager` ownership is worker-local as required by the PRD

### Phase 5: Scheduler Leases

Status: complete

Evidence:

- `backend/modules/scheduler/models.py` includes lease and explicit success/failure timestamp fields
- `backend/modules/scheduler/service.py` claims due schedules and enqueues build jobs
- `backend/modules/scheduler/service.py` reconciles schedule success/failure state from terminal build results
- `backend/modules/runtime/scheduler.py` is the scheduler subprocess entrypoint under the supervised app runtime
- `backend/main.py` no longer runs scheduler work inline in API lifespan

Notes:

- `last_run` semantics are explicit and success-only
- scheduled builds are enqueued, not executed inline by the scheduler

### Phase 6: Warning-Fail Verification

Status: complete

Evidence:

- `backend/scripts/scan_warnings.py` scans command output for forbidden warning and error patterns
- `backend/config/warning-allowlist.json` exists and remains empty
- `Justfile` routes `just verify`, `just test`, and `just test-e2e` through the warning scanner
- `just test-e2e-raw` emits the combined runtime/frontend/Playwright stream so warning scanning covers backend, worker, scheduler, frontend, and Playwright output
- `backend/e2e.env` avoids the `NO_COLOR` and `FORCE_COLOR` conflict documented in the PRD

Notes:

- verification is warning-clean by policy instead of relying on silent toleration

### Phase 7: Postgres Production Runtime

Status: complete

Evidence:

- `backend/core/config.py` requires PostgreSQL when `DISTRIBUTED_RUNTIME_ENABLED=true` and adds explicit pool settings
- `backend/core/database.py` separates shared public tables from tenant schema tables and applies Postgres search path handling per namespace
- `backend/core/migrations.py` provides the Postgres-first migration/bootstrap path with `0001_runtime_public` and `0002_runtime_tenant`
- `backend/tests/test_postgres_runtime_integration.py` validates schema bootstrap, advisory-lock-safe startup, Postgres notification delivery, and cross-worker runtime flows
- `docker/docker-compose.yml` is the supported Postgres distributed runtime topology
- `docker/docker-compose.test.yml` provides the Docker validation topology with Postgres plus fixed `api`, `scheduler`, and `worker` role containers, runtime tests, and e2e
- `README.md` documents Postgres-backed deployment with fixed-role release images for API, scheduler, and worker

Notes:

- production topology is now migration-first, Postgres-backed, Docker-native, and split into fixed runtime roles
- examples target `postgres:18-alpine` per the PRD decision

### Phase 8: Enable Multi-Worker API

Status: complete

Evidence:

- `backend/main.py` allows `WORKERS > 1` when distributed runtime is enabled on Postgres
- `backend/tests/test_main.py` covers the new guard behavior
- `backend/tests/test_postgres_runtime_integration.py` validates two API workers plus independent scheduler/worker runtime processes and cross-worker build detail, cancellation, and websocket replay
- `backend/tests/test_docker_bootstrap.py` validates Docker startup with fixed API, scheduler, and worker roles, multiple API workers, dynamic build-worker execution, and scheduler-triggered build execution
- `Justfile` includes `just docker-test` to exercise the distributed topology end to end

## Runtime Claim

The repository currently supports:

- supported Postgres distributed runtime deployment
- fixed API, scheduler, and worker runtime roles from one codebase release
- durable build state and event replay
- DB-backed websocket snapshots and replay
- lease-based build job execution
- lease-based scheduler coordination
- migration-first Postgres bootstrap
- Docker-native runtime validation with the fixed-role image topology
- release-confidence runtime/admin overview endpoint for runtime mode, API process identity, worker heartbeats, engine state, and queue status

The repository still should not claim:

- any non-Postgres distributed runtime claim

## Remaining Work

Distributed runtime v2 implementation is functionally complete enough to run and validate as a Postgres-backed multi-process runtime.

Remaining optional follow-up from the PRD observability section:

- add dedicated metric counters/endpoints for build-event insert failures
- add websocket connected-client counts
- add CAS transition conflict counts
- add scheduler claim and duplicate-prevention counters
