# PRD: Distributed Runtime v2

## Overview

Move Data-Forge from a single-process live-build runtime to a deliberate distributed runtime. API workers must become stateless, build execution must move behind a durable queue, live build state must be persisted, websocket delivery must become a projection of durable state, and event contracts must be schema-enforced end to end.

This plan is intentionally not a quick scaling patch. It defines the architecture required before `WORKERS > 1`, multiple API instances, or multi-node deployment can be treated as supported production modes.

## Problem Statement

The current release branch introduced live build monitoring, engine status websockets, cancellation, and build history improvements. Those features are valuable, but the runtime still relies on process-local state:

- Active build registry lives in memory.
- Websocket watchers live in memory.
- Engine registry watchers live in memory.
- `ProcessManager` engine state lives in memory.
- Build execution is started from an API process using `asyncio.create_task()`.
- Scheduler execution runs inside the API lifespan loop.
- Terminal build events are emitted as raw dicts in several places.
- Frontend websocket types are hand-maintained instead of generated from backend schemas.
- Test logs can contain runtime warnings while still passing.

That design can work for one API process. It is not safe for multiple Uvicorn workers or multiple app containers.

## Goals

| Goal | Description | Success Metric |
|------|-------------|----------------|
| G-1 | Stateless API workers | Starting builds, reading active builds, cancelling builds, and websocket streaming work correctly with `WORKERS > 1`. |
| G-2 | Durable build state | A running or recently completed build can be reconstructed from database rows after API restart. |
| G-3 | Dedicated execution workers | Build execution is owned by worker processes, not by API request handlers. |
| G-4 | Durable queue | Build jobs are claimed through database leases and cannot be run twice by healthy workers. |
| G-5 | Schema-enforced events | Backend code cannot emit an invalid build event payload; frontend types are generated from backend schemas. |
| G-6 | Pub/sub websocket projection | Websockets receive live updates from durable events and can recover missed messages from the database. |
| G-7 | Lease-based scheduler | Multiple scheduler instances may run, but only one can claim a due schedule execution. |
| G-8 | CAS state transitions | Cancellation and terminal states cannot be overwritten by late success/failure writes. |
| G-9 | Warning-clean release gate | Verification fails on unclassified warnings, including e2e runtime warnings. |

## Non-Goals

- Do not add permissive fallback behavior for failed event parsing or build recovery.
- Do not add polling or interval refresh logic to make distributed state appear live.
- Do not enable multi-worker API before durable state ownership is implemented.
- Do not add Redis to this architecture.
- Do not use any broker as the source of truth for build state.
- Do not preserve legacy in-memory active build APIs as an alternate production path.

## Architectural Principles

1. The database is the source of truth.
2. In-memory state is a cache or execution-local detail only.
3. Websockets are delivery channels, not owners of state.
4. Every runtime transition is explicit, validated, and persisted.
5. Missing events are recovered by replaying database state.
6. Workers are horizontally scalable only after job leases and CAS transitions exist.
7. Warning-free verification is part of correctness.

## Target Runtime Topology

```text
Browser
  |
  | HTTP requests and websockets
  v
API worker(s)
  - validate requests
  - create durable build/job rows
  - read snapshots from DB
  - stream DB-backed events over websockets
  - never own build execution
  |
  | SQL, LISTEN/NOTIFY
  v
PostgreSQL
  - build_runs
  - build_events
  - build_jobs
  - engine_runs
  - runtime_workers
  - engine_instances
  - schedules and scheduler leases
  |
  | SKIP LOCKED leases
  v
Build worker(s)
  - claim jobs
  - own local ProcessManager
  - execute Polars engine work
  - persist progress/events/state
  - heartbeat and renew leases
```

## Production Database Decision

### Recommended Production Decision

Postgres should be mandatory for the distributed runtime.

Target PostgreSQL 18 or the newest stable PostgreSQL major available when implementation begins. Do not design the distributed runtime around older PostgreSQL behavior when a newer stable release is available.

Reasons:

- It supports transactional row leases with `FOR UPDATE SKIP LOCKED`.
- It supports durable notification wakeups with `LISTEN/NOTIFY`.
- It supports multiple concurrent API and worker processes safely.
- It provides better observability and backup tooling than file-backed metadata stores.
- It removes per-namespace file-level contention as a production scaling concern.

Local development and tests should follow the same Postgres-backed runtime model rather than preserving a separate legacy file-backed path.

### Runtime Version Policy

The distributed runtime should target current stable infrastructure releases by default.

Rules:

- PostgreSQL target is PostgreSQL 18+.
- Docker examples should use `postgres:18-alpine` or a newer stable major when this work is implemented.
- CI should test against the newest supported PostgreSQL major, not only older compatibility versions.
- Version pins should be explicit and intentional, but should not freeze the architecture on stale runtime assumptions.
- If a dependency has a newer stable major release before implementation, re-check the plan and update examples before coding.

### What Can Be Done Without Postgres

These improvements are safe and valuable without Postgres:

- Schema-enforced backend event models.
- Generated frontend build-stream types.
- Durable `build_runs` and `build_events` tables.
- DB-backed active build snapshots.
- Restart recovery for completed, failed, cancelled, and orphaned running builds.
- CAS-style service functions around terminal transitions.
- Single-process durable job queue shape.
- Warning-fail verification gates.
- Refactoring API code so it enqueues work instead of owning work.

These should not be claimed without Postgres:

- Safe multiple Uvicorn workers.
- Safe multiple app containers.
- Robust queue leasing under concurrent workers.
- Reliable scheduler singleton behavior across processes.
- Durable pub/sub fanout across API workers.
- High-confidence cancellation races under concurrent writers.

## Data Model

### `build_runs`

Parent lifecycle row for a live build.

Suggested fields:

| Field | Purpose |
|-------|---------|
| `id` | Build id returned to frontend. |
| `namespace` | Tenant namespace. |
| `analysis_id` | Analysis being built. |
| `analysis_name` | Denormalized display name at start. |
| `status` | `queued`, `running`, `completed`, `failed`, `cancelled`, `orphaned`. |
| `request_json` | Original validated build request. |
| `starter_json` | User/email/display metadata. |
| `resource_config_json` | Effective engine resource settings. |
| `current_engine_run_id` | Current child engine run, if any. |
| `current_kind` | Current operation kind. |
| `current_datasource_id` | Current datasource being operated on. |
| `current_tab_id` | Current tab id. |
| `current_tab_name` | Current tab name. |
| `current_output_id` | Current output datasource/result id. |
| `current_output_name` | Current output display name. |
| `progress` | Numeric progress 0.0 to 1.0. |
| `elapsed_ms` | Last persisted elapsed duration. |
| `estimated_remaining_ms` | Last computed ETA. |
| `current_step` | Current step label. |
| `current_step_index` | Current step index. |
| `total_steps` | Total expected build steps. |
| `total_tabs` | Total tabs in scope. |
| `duration_ms` | Terminal duration. |
| `error_message` | Terminal failure/cancellation message. |
| `cancelled_at` | Cancellation timestamp. |
| `cancelled_by` | User who cancelled. |
| `created_at` | Build creation timestamp. |
| `started_at` | Worker start timestamp. |
| `completed_at` | Terminal timestamp. |
| `updated_at` | Last state update timestamp. |
| `version` | Monotonic integer for CAS updates. |

### `build_events`

Append-only event log. Websocket snapshots and replay should be built from this table plus `build_runs`.

Suggested fields:

| Field | Purpose |
|-------|---------|
| `id` | Event id. |
| `build_id` | Parent build. |
| `namespace` | Namespace for filtering and authorization. |
| `sequence` | Per-build monotonic event sequence. |
| `type` | Event discriminator. |
| `payload_json` | Validated event payload. |
| `engine_run_id` | Child run when relevant. |
| `emitted_at` | Event timestamp. |
| `created_at` | Insert timestamp. |

Constraints:

- Unique `(build_id, sequence)`.
- Payload must be produced by backend Pydantic event models.
- Terminal events must match the final `build_runs.status`.

### `build_jobs`

Durable queue for execution.

Suggested fields:

| Field | Purpose |
|-------|---------|
| `id` | Job id. |
| `build_id` | Parent build. |
| `namespace` | Namespace. |
| `status` | `queued`, `leased`, `running`, `completed`, `failed`, `cancelled`. |
| `priority` | Optional queue priority. |
| `lease_owner` | Worker id. |
| `lease_expires_at` | Lease timeout. |
| `attempts` | Number of claim attempts. |
| `max_attempts` | Retry cap. |
| `last_error` | Last execution error. |
| `available_at` | Earliest claim time. |
| `created_at` | Job creation timestamp. |
| `updated_at` | Last update timestamp. |

Queue claim query should use Postgres row locking:

```sql
SELECT id
FROM build_jobs
WHERE status = 'queued'
  AND available_at <= now()
ORDER BY priority DESC, created_at ASC
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

### `runtime_workers`

Worker heartbeats and advertised capacity.

Suggested fields:

| Field | Purpose |
|-------|---------|
| `id` | Stable worker instance id. |
| `kind` | `api`, `build_worker`, `scheduler`. |
| `hostname` | Host/container id. |
| `pid` | Process id. |
| `capacity` | Max concurrent jobs. |
| `active_jobs` | Current active jobs. |
| `started_at` | Startup timestamp. |
| `last_seen_at` | Heartbeat timestamp. |
| `metadata_json` | Version, git sha, resource details. |

### `engine_instances`

Worker-local engine state reflected into DB for monitoring.

Suggested fields:

| Field | Purpose |
|-------|---------|
| `id` | Engine instance id. |
| `worker_id` | Owning worker. |
| `namespace` | Namespace. |
| `analysis_id` | Analysis id. |
| `process_id` | OS process id. |
| `status` | `starting`, `idle`, `running`, `stopping`, `stopped`, `failed`. |
| `current_job_id` | Engine job id. |
| `current_build_id` | Parent build id. |
| `current_engine_run_id` | Child engine run id. |
| `resource_config_json` | Requested config. |
| `effective_resources_json` | Actual limits/resources. |
| `last_activity_at` | Last use. |
| `last_seen_at` | Heartbeat. |

### `engine_runs`

Existing durable child run table should be retained, but extended with:

- `build_id`
- `build_sequence` or event linkage if needed
- guarded terminal transition helpers

`engine_runs` should represent individual compute operations. `build_runs` should represent the parent live build lifecycle.

### Scheduler Lease Fields

Either add a separate `schedule_leases` table or fields on `schedules`:

- `lease_owner`
- `lease_expires_at`
- `last_claimed_at`
- `last_successful_build_id`

For clarity and auditability, a separate table is preferable if schedule history expands later.

## Schema-Enforced Event Contracts

### Backend Contract

Current Pydantic event classes already exist in `backend/modules/compute/schemas.py`. They should become the only way to emit build websocket events.

Required changes:

1. Define a discriminated union:

```python
BuildEvent = Annotated[
    BuildPlanEvent
    | BuildStepStartEvent
    | BuildStepCompleteEvent
    | BuildStepFailedEvent
    | BuildProgressEvent
    | BuildResourceEvent
    | BuildLogEvent
    | BuildCompleteEvent
    | BuildFailedEvent
    | BuildCancelledEvent,
    Field(discriminator='type'),
]
```

2. Change the emitter contract from:

```python
BuildEmitter = Callable[[dict[str, object]], Awaitable[None]]
```

to:

```python
BuildEmitter = Callable[[BuildStreamEvent], Awaitable[None]]
```

or a protocol that accepts the discriminated event union.

3. Replace raw dict emissions with constructors:

```python
await emit(
    BuildCompleteEvent(
        build_id=build.id,
        analysis_id=analysis_id,
        emitted_at=now,
        progress=1.0,
        elapsed_ms=elapsed_ms,
        total_steps=total_steps,
        tabs_built=tabs_built,
        results=results,
        duration_ms=elapsed_ms,
        engine_run_id=build.current_engine_run_id,
    )
)
```

4. Persist the event model payload to `build_events`.

5. Publish the serialized model payload to websocket subscribers.

6. Fail tests if any event cannot validate.

### Frontend Contract

Frontend build-stream types should be generated from backend Pydantic schemas.

Target file:

```text
frontend/src/lib/types/build-stream.generated.ts
```

Manual file:

```text
frontend/src/lib/types/build-stream.ts
```

`build-stream.ts` should contain local convenience aliases only, and import generated shapes.

Generation requirements:

- Generate event union types.
- Generate active build snapshot types.
- Generate websocket message types.
- Preserve discriminated unions by `type`.
- Fail `just check` when generated files are stale.
- Add a backend or root command such as `just generate-build-stream-types`.

### Contract Tests

Required tests:

- Every backend event class serializes to frontend-compatible JSON.
- A real successful build emits only valid events.
- A real failed build emits only valid events.
- A cancelled build emits only valid events.
- Terminal events include all required fields.
- Frontend parser rejects or surfaces invalid websocket messages deterministically.
- Generated TypeScript stays in sync with backend schemas.

## Durable Build State

### Snapshot Source

Active build snapshots should be generated from durable rows:

1. Load `build_runs`.
2. Load recent or full `build_events` for the build.
3. Fold events into `ActiveBuildDetail`.
4. Return snapshot.

The in-memory `ActiveBuildRegistry` can temporarily remain as a cache, but the API must not depend on it for correctness.

### Restart Recovery

On API startup:

- Do not recreate in-memory running builds as if they are alive.
- Mark builds with expired worker leases as `orphaned` or `failed`, depending on policy.
- Preserve all completed, failed, and cancelled builds.
- Websocket endpoints should return a DB-derived terminal snapshot for completed builds.

On worker startup:

- Register worker heartbeat.
- Claim only queued jobs or expired leased jobs according to retry policy.
- Do not adopt unknown in-memory work.

### Resource History

Persist resource samples only if they are user-visible after the build. If full history is too noisy, persist downsampled records or keep only last N samples per build.

Recommended v2 behavior:

- Persist latest resource snapshot on `build_runs`.
- Persist sampled resource events in `build_events` with throttling.
- Keep websocket throttling as a delivery concern, not as a persistence concern.

## Job Execution Flow

### Start Build

```text
POST /api/v1/compute/builds/active
  -> validate request
  -> insert build_runs(status='queued')
  -> insert build_jobs(status='queued')
  -> insert build_events(type='log', "Queued build")
  -> NOTIFY build_jobs
  -> return ActiveBuildDetail from DB
```

### Worker Claim

```text
worker loop
  -> heartbeat runtime_workers
  -> claim build_jobs row with FOR UPDATE SKIP LOCKED
  -> set job status='leased', lease_owner=worker_id, lease_expires_at=now()+ttl
  -> transition build_runs queued -> running with CAS
  -> execute build
  -> persist events and state after each transition
  -> terminal CAS update
  -> release/complete job
```

### Websocket Detail Stream

```text
client connects /ws/builds/{build_id}
  -> API authenticates
  -> API sends DB-derived snapshot
  -> API subscribes to build event notification channel
  -> on notification, load events after last sequence
  -> send serialized validated events
  -> on reconnect, client receives snapshot plus future events
```

### Build List Stream

Build list websocket should not depend on an in-memory list watcher. It should:

- Send DB-derived list of running builds.
- Subscribe to namespace build notifications.
- Reload list or apply notified changes from DB.
- Never create history rows except via explicit refresh behavior already required by the UI rules.

## Cancellation and Terminal State

Cancellation must be authoritative.

Required state machine:

```text
queued -> running
queued -> cancelled
running -> completed
running -> failed
running -> cancelled
leased -> queued       # expired lease retry, job table only
running -> orphaned    # worker died after start, build table only
```

Forbidden transitions:

```text
cancelled -> completed
cancelled -> failed
failed -> completed
completed -> failed
completed -> cancelled
```

All terminal writes must use guarded updates:

```sql
UPDATE build_runs
SET status = 'completed',
    completed_at = now(),
    version = version + 1
WHERE id = :build_id
  AND status = 'running'
  AND version = :expected_version;
```

If the update affects zero rows, the writer must reload state and honor the already-terminal status.

Cancellation flow:

1. API validates user and build/run id.
2. API transitions `build_runs` or `engine_runs` to cancellation requested/cancelled using CAS.
3. API inserts `BuildCancelledEvent`.
4. API notifies workers.
5. Worker observes cancellation before final success.
6. Worker shuts down/interrupts local engine job.
7. Worker does not overwrite cancelled terminal state.

## Scheduler Runtime

The scheduler should enqueue jobs, not execute compute inline.

Target flow:

```text
scheduler process
  -> heartbeat runtime_workers(kind='scheduler')
  -> find due schedules
  -> claim schedule lease with CAS
  -> create build_runs/build_jobs for the schedule target
  -> update last_run/next_run only after the scheduled build completes successfully
  -> release schedule lease
```

Schedule completion semantics:

- `last_run` means the scheduled build completed successfully.
- Enqueueing a scheduled build must not advance `last_run`.
- Failed, cancelled, skipped, or orphaned scheduled builds must not advance `last_run`.
- Add explicit `last_triggered_at`, `last_success_at`, and `last_failure_at`.
- Use `last_successful_build_id` to link the schedule to the last successful build.

Lease requirements:

- Only one scheduler instance can claim a due schedule.
- Expired leases can be reclaimed.
- Dependency skips must not advance success timestamps.
- Schedule history should point to the created `build_run_id`.

## Pub/Sub Strategy

### Preferred First Implementation

Use Postgres `LISTEN/NOTIFY` as a wakeup signal only.

Notification payload should be small:

```json
{
  "namespace": "default",
  "build_id": "uuid",
  "latest_sequence": 42
}
```

The API websocket handler must load events from `build_events` after receiving the notification. It should not trust notification payload as the event source of truth.

### Why Not Redis

Redis is intentionally out of scope and should not be added later as part of this runtime architecture. Postgres is the durable state store, queue lease mechanism, and notification source. If fanout pressure eventually exceeds Postgres `LISTEN/NOTIFY`, the architecture should be revisited explicitly rather than adding Redis as an incremental dependency.

## Engine Runtime

The `ProcessManager` remains worker-local in v2. It should not be shared directly across API workers.

Responsibilities:

- Build worker owns `ProcessManager`.
- API worker never calls `manager.get_or_create_engine()` for build execution.
- API may read engine status from `engine_instances`.
- Build worker periodically writes engine snapshots to DB and emits engine notifications.
- Engine cleanup runs in workers, guarded by local ownership and DB state.

Engine status websocket:

- Should stream `engine_instances` projections from DB.
- Should not depend on process-local `EngineRegistry`.
- Should recover after API worker restart by reading current DB state.

## API Changes

### Start Build

Current:

- API creates in-memory build.
- API starts an async task.
- API returns in-memory detail.

Target:

- API creates durable build/job rows.
- API notifies job channel.
- API returns DB-derived detail.

### Get Active Build

Current:

- Reads in-memory registry.

Target:

- Reads `build_runs` and `build_events`.
- Can return running, completed, failed, cancelled, and orphaned recent builds.

### Get Active Build By Engine Run

Current:

- Searches in-memory active builds.

Target:

- Uses `engine_runs.build_id` or `build_runs.current_engine_run_id`.

### Cancel Build

Current:

- Updates `engine_runs`, shuts down engine through local manager, then tries to update in-memory active build.

Target:

- Persists cancellation via CAS.
- Signals worker through DB/NOTIFY.
- Worker performs local shutdown if it owns the engine.
- API does not assume local engine ownership.

## Frontend Changes

Frontend architecture can stay mostly intact if backend snapshots/events keep the same semantic shape.

Required changes:

- Import generated build-stream types.
- Treat websocket detail stream as reconnectable DB-backed projection.
- Continue to show new history rows only after explicit refresh, per monitoring rules.
- Avoid polling for build list/history.
- Keep live websocket use scoped to engine status, build preview/detail, and expanded running build rows.

Frontend parser should:

- Parse JSON.
- Validate event discriminator at minimum.
- Surface invalid messages as connection/protocol errors.
- Never silently coerce missing required event fields.

## Warning-Free Release Gate

### Policy

Any command in the definition of done should fail on unexpected warnings.

This applies to:

- `just verify`
- `just test`
- `just test-e2e`
- release build scripts
- CI jobs

### Current Warnings To Resolve

1. Node warning:

```text
Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
```

Resolution:

- Fix e2e environment variables so only one color policy is set.
- Do not allowlist this unless a tool makes it impossible to avoid.

2. Vite websocket proxy errors:

```text
ws proxy error: Error: write EPIPE
ws proxy socket error: Error: read ECONNRESET
```

Resolution options:

- Determine whether these happen only when Playwright closes pages with active websockets.
- If caused by normal test teardown, classify them with an exact matcher in the e2e harness and document why.
- If they happen during active app flows, fix websocket close handling or Vite proxy handling.
- Do not blanket-suppress all proxy errors.

### Harness Design

Add a verification wrapper that captures command output and fails on warning/error patterns unless allowlisted.

Suggested forbidden patterns:

- `Warning:`
- `Traceback`
- `UnhandledPromiseRejection`
- `DeprecationWarning`
- `ResourceWarning`
- `ERROR`
- `EPIPE`
- `ECONNRESET`

Suggested allowlist format:

```json
[
  {
    "pattern": "ws proxy error: Error: write EPIPE",
    "scope": "just test-e2e",
    "reason": "Playwright closes pages while Vite is proxying websocket teardown; backend sees normal disconnect and tests assert no user-visible failure.",
    "owner": "runtime",
    "expires": "2026-05-31"
  }
]
```

Allowlisted warnings must be narrow, owned, and time-bounded.

## Migration Plan

### Phase 0: Freeze Unsupported Scaling

Purpose:

- Prevent accidental production split-brain while v2 is built.

Tasks:

- Reject `WORKERS > 1` unless distributed runtime flag is enabled.
- Remove auto-worker behavior.
- Document that current release supports one API process.
- Keep `MAX_CONCURRENT_ENGINES` as the concurrency control.

Exit criteria:

- Startup fails clearly for unsupported worker counts.
- Tests assert the guard.

### Phase 1: Schema-Enforced Events

Purpose:

- Eliminate backend/frontend build event contract drift.

Tasks:

- Add discriminated Pydantic event union.
- Change emitters to accept event models.
- Replace raw dict emissions in build stream paths.
- Add event construction helpers to reduce duplication.
- Generate frontend build-stream types from backend schemas.
- Add stale generated file check to `just check`.
- Add backend tests validating real emitted event payloads.
- Add frontend parser/store tests using generated types.

Exit criteria:

- No raw build terminal event dicts are emitted.
- The previous missing `progress` complete event bug is impossible.
- `just verify` fails if generated frontend event types are stale.

### Phase 2: Durable Build State In Single Process

Purpose:

- Move live build truth to DB before introducing multiple processes.

Tasks:

- Add `build_runs` and `build_events` models.
- Add migrations.
- Write repository/service functions for build creation, event append, snapshot folding, and terminal CAS.
- Make current in-process build stream write every event to DB.
- Make active build REST endpoints read from DB.
- Keep in-memory registry only as optional websocket delivery cache.
- Add restart recovery behavior for stale running builds.

Exit criteria:

- Build detail can be returned after API restart.
- Terminal build state is visible without in-memory registry.
- Cancellation cannot be overwritten by late success.

### Phase 3: DB-Backed Websocket Projection

Purpose:

- Remove websocket dependence on process-local registries.

Tasks:

- Add build event sequence numbers.
- Add per-build websocket replay from `build_events`.
- Use DB snapshots on websocket connect.
- Add Postgres `LISTEN/NOTIFY` when Postgres is active.
- For local development, keep runtime delivery aligned with the supported Postgres-backed model.
- Replace build list watchers with DB-backed list projection.
- Replace engine watcher state with DB-backed engine snapshots.

Exit criteria:

- Connecting to any API worker can stream the same build.
- Missed events are recovered by sequence replay.
- API restart does not lose terminal snapshots.

### Phase 4: Dedicated Build Worker

Purpose:

- Remove build execution ownership from API workers.

Tasks:

- Add `build_jobs`.
- Add worker process entrypoint.
- Add worker heartbeat table.
- Implement lease claim and renewal.
- Move `ProcessManager` ownership to worker process.
- Convert `POST /builds/active` to enqueue only.
- Worker persists events/state through the same event service.
- Worker handles cancellation requests.
- Add worker shutdown behavior that marks leases expired without corrupting terminal state.

Exit criteria:

- API can start builds without creating background tasks.
- Build worker can execute queued jobs.
- Worker crash results in retry or orphaned state according to policy.

### Phase 5: Scheduler Leases

Purpose:

- Make scheduler safe with multiple scheduler/API processes.

Tasks:

- Add scheduler lease fields/table.
- Replace lifespan inline scheduler execution with scheduler process or worker role.
- Claim due schedules with CAS/lease.
- Enqueue build jobs instead of executing compute inline.
- Add schedule run history links to `build_runs`.
- Add `last_triggered_at`, `last_success_at`, and `last_failure_at`.

Exit criteria:

- Multiple scheduler instances do not duplicate schedule executions.
- Dependency skips are explicit and do not advance success timestamps.

### Phase 6: Warning-Fail Verification

Purpose:

- Make release output clean and trustworthy before enabling distributed deployment modes.

Tasks:

- Fix color environment warning.
- Investigate Vite websocket proxy warnings.
- Add warning scanner wrapper.
- Add narrow allowlist file if absolutely needed.
- Make CI fail on unexpected warnings.

Exit criteria:

- `just verify` and `just test-e2e` are warning-clean or fail on unclassified warnings.

### Phase 7: Postgres Production Runtime

Purpose:

- Enable actual distributed deployment.

Tasks:

- Complete Postgres metadata backend support.
- Target PostgreSQL 18+ and update examples to the newest stable PostgreSQL major at implementation time.
- Run runtime tables in Postgres.
- Use schema-per-namespace or namespace columns consistently.
- Add connection pool configuration.
- Add DB health checks.
- Add Docker Compose Postgres profile.
- Add migration guide.

Exit criteria:

- Test suite runs against Postgres in CI.
- Distributed runtime integration tests run with at least two API workers and one build worker.

### Phase 8: Enable Multi-Worker API

Purpose:

- Safely allow `WORKERS > 1`.

Tasks:

- Remove startup guard when distributed runtime is enabled.
- Add e2e/integration tests with multiple API workers.
- Test websocket connection to different worker than build-start request.
- Test cancellation from a different API worker.
- Test scheduler and worker under concurrent process count.
- Document supported deployment topologies.

Exit criteria:

- `WORKERS=2` or higher is a supported, tested production mode.
- No in-memory registry is required for correctness.

## Testing Strategy

### Unit Tests

- Event models validate required fields.
- Event union rejects missing discriminator fields.
- Event union rejects missing terminal fields.
- Build snapshot folding from events is deterministic.
- Terminal CAS rejects invalid transitions.
- Queue claim logic handles expired leases.
- Scheduler lease claim rejects duplicate claims.

### Backend Integration Tests

- Start build persists `build_runs`, `build_jobs`, and initial events.
- Worker claims and completes a build.
- Cancellation wins over late success.
- Failed worker lease expires and job is retried or marked orphaned.
- Websocket receives DB-backed snapshot.
- Websocket replay sends missed events after reconnect.
- Active build by engine run works without in-memory registry.

### Frontend Unit Tests

- Generated build event types compile.
- Build stream parser rejects invalid messages.
- Store handles complete, failed, and cancelled generated events.
- Store never produces `NaN` progress from a valid backend event.

### E2E Tests

- Build starts via HTTP and details stream through websocket.
- Build detail works after API restart.
- Cancellation from monitoring row works.
- Build history gains rows only after explicit refresh.
- Multiple API workers: build starts on one worker, websocket connects to another.
- Multiple scheduler instances do not duplicate jobs.

### Release Tests

- `just verify`
- `just test-e2e`
- Postgres integration profile.
- Multi-worker integration profile.
- Warning scanner over all verification logs.

## Deployment Strategy

### Single-Process Transitional Runtime

Supported while phases 1-3 are under construction:

- One API process.
- PostgreSQL.
- Durable build state enabled.
- No claim of multi-worker support.

### Distributed Runtime

Supported only after phases 4-7:

- Postgres required.
- One or more API workers.
- One or more build workers.
- Optional dedicated scheduler process.
- Websocket fanout via DB-backed event replay and Postgres notifications.

### Docker Compose Shape

Recommended services:

```yaml
services:
  api:
    image: data-forge
    command: ["uv", "run", "main.py"]

  worker:
    image: data-forge
    command: ["uv", "run", "python", "-m", "modules.runtime.worker"]

  scheduler:
    image: data-forge
    command: ["uv", "run", "python", "-m", "modules.runtime.scheduler"]

  postgres:
    image: postgres:18-alpine
```

API and worker can share the same image but must have separate entrypoints.

## Observability

Add runtime observability before enabling distribution:

- Worker heartbeat page/API.
- Queue depth metrics.
- Oldest queued job age.
- Active lease count.
- Expired lease count.
- Build event insert failures.
- Websocket connected client count.
- CAS transition conflict count.
- Scheduler claim count and duplicate-prevention count.

For release confidence, add a monitoring tab section or admin endpoint that shows:

- API process id and version.
- Worker ids and heartbeats.
- Queue status.
- Runtime mode: `single_process`, `durable_single_node`, or `distributed`.

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Event volume grows too large | DB bloat and slow snapshots | Use retention, sequence windows, and snapshot folding caches. |
| Worker dies mid-engine job | Stale running builds | Lease expiry and orphan/retry policy. |
| Cancellation races success | Incorrect terminal state | CAS transitions and terminal-state authoritative checks. |
| Websocket misses notification | Stale UI | Replay from `build_events` by sequence. |
| Unsupported runtime topology | Split-brain and lock contention | Startup guard and production docs. |
| Raw dict events reappear | Contract drift | Type signatures, lint/tests, generated frontend types. |
| Warnings become normalized | Release blind spots | Warning scanner and allowlist ownership. |

## Locked Decisions

1. `last_run` means "scheduled build completed successfully".
   - Enqueueing a schedule does not advance `last_run`.
   - Failed, cancelled, skipped, or orphaned scheduled builds do not advance `last_run`.
   - Add `last_triggered_at`, `last_success_at`, and `last_failure_at` to avoid overloading one field.

2. Terminal `build_events` and logs are retained forever.
   - Retain terminal events and build logs as audit/history data.
   - Resource events may be downsampled or retained under a separate retention policy if volume requires it.

3. Redis will not be added.
   - Do not add Redis as a queue, pub/sub layer, cache dependency, or delivery accelerator for this runtime.
   - Postgres remains the runtime coordination substrate.

4. Local development and test runtime behavior should stay aligned with the supported Postgres-backed topology.
   - Do not preserve a separate legacy runtime mode.
   - Single-node convenience must not create a second ownership or delivery model.

5. Build workers run one job at a time.
   - Scale execution by running more worker processes.
   - Do not add internal multi-job concurrency inside a single worker process.

6. Target newest stable infrastructure releases.
   - PostgreSQL target is PostgreSQL 18+.
   - Update implementation examples to the newest stable major releases before coding.
   - Do not preserve stale dependency assumptions for compatibility unless a specific deployment requirement forces it.

## First Implementation Slice

The first non-negotiable slice should be small but architectural:

1. Add event union and typed emitter.
2. Replace complete/failed/cancelled raw dict emissions.
3. Generate frontend build-stream types.
4. Add stale generation check.
5. Add tests proving real backend emitted events validate.
6. Fix the missing `progress` terminal event.
7. Add warning scanner for `just test-e2e`, initially in report-only mode if necessary.

This slice does not require Postgres and directly addresses the release audit bug.

## Definition Of Done For v2

Distributed runtime v2 is done only when:

- API workers do not own build execution.
- Active build state is durable and reconstructable.
- Websocket streams can reconnect and replay from DB.
- Build jobs are claimed through leases.
- Scheduler work is lease-protected.
- Cancellation and terminal states use guarded transitions.
- Frontend event types are generated from backend schemas.
- Multi-worker API is covered by integration tests.
- Postgres is the documented production backend.
- `just verify` and `just test-e2e` pass without unclassified warnings.
