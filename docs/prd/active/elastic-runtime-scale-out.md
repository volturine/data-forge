# PRD: Capacity-First Runtime Optimization

> **Status (2026-09-30): Active — architecture fixes implemented; static/unit gates passed; E2E verification pending. Capacity validation remains open.**
> **Target:** Sustain 2,000 concurrent users with the fewest service replicas that measurements support. The 2,000-user workload profile and SLOs still need validation; this is not yet a capacity claim, and the active PRD records no successful 2,000-user run.
> **Portfolio:** [PRD index](../README.md)

## Objective

Reduce request-path and orchestration overhead before adding replicas, managers,
brokers, or database shards. Start with one API container and one API process
(`WORKERS=1`), the existing dedicated runtime coordinator, one worker manager,
and separate compute-worker containers. Here “1×1” means one API replica × one
Uvicorn process; it does not mean merging the coordinator, worker manager, or
compute containers into the API. Scale only the service whose measured capacity
is saturated.

“2,000 users” is not “2,000 compute jobs.” Connected sessions, HTTP request
rate, unique resource identities, and distinct compute commands are separate
load dimensions. The system should serve a 2,000-session profile with no lost
accepted work or unexplained errors, while compute work may queue fairly within
its configured capacity. A single hot RID remains serialized by design.

## Current topology and constraints

| Role                | Current responsibility                                                                                                                                                                                                                                                                    | Keep or change                                                                                                                                                    |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| API                 | HTTP, frontend assets, auth, WebSocket/SSE delivery, durable enqueue-and-wait paths, and disposable process-local caches/projections/waiters. PostgreSQL owns durable runtime state.                                                                                                      | Start capacity testing at one container × one Uvicorn process. Add API replicas/processes only if API CPU, loop lag, or request latency is the limiting resource. |
| Runtime coordinator | One active fenced owner for runtime gRPC/dispatch, durable chat processing, Telegram polling, and independent durable external email/Telegram delivery lanes; standby is for recovery. External delivery uses durable outbox metadata and performs network calls outside DB transactions. | Keep one active instance while its RPC and DB lanes have headroom. Do not build partitioned coordinators preemptively.                                            |
| Worker manager      | One process owns Docker access, engine-container lifecycle, active identity accounting, and warm workers.                                                                                                                                                                                 | Keep separate from API for stability/security. Do not replicate the current manager without global identity/capacity fencing.                                     |
| Compute workers     | Isolated containers, each assigned to one exact analysis or datasource RID. Identical full commands share durable results; distinct commands on one RID are serialized.                                                                                                                   | Preserve this isolation boundary. Increase worker capacity only when unique-RID compute queueing is the measured bottleneck.                                      |
| PostgreSQL          | Durable application state, requests, leases, outbox, and single-flight results.                                                                                                                                                                                                           | Keep as source of truth. Optimize queries, indexes, transactions, and pool budgets before considering database sharding.                                          |
| Object/data plane   | Blocking object-store/Iceberg work is performed outside API event loops through bounded service-owned lanes.                                                                                                                                                                              | Keep it independent of API lifecycle; scale it only if its own queue/latency is saturated.                                                                        |

Implementation references: [API lifecycle and thread budgets](../../../packages/backend/main.py),
[fenced coordinator and durable actors](../../../packages/backend/runtime_coordinator.py),
[durable external delivery lanes](../../../packages/backend/backend_core/runtime_integration_delivery.py),
and [Docker worker manager](../../../packages/worker/runtime/compute_manager.py).

The current defaults and code do not prove 2,000-user capacity. `WORKERS`
multiplies API processes but does not add coordinator or compute capacity.
`COMPUTE_WORKERS` is the concurrent job/assigned-worker budget, and
`COMPUTE_WARM_WORKERS` is the additional ready-but-unassigned reserve. API
process count remains a separate control. The coordinator, Docker-owning worker
manager, and compute containers remain separate roles.

## Implemented runtime contracts

- **Database/session boundary:** async compute helpers carry no unused session
  or database dependency through a remote wait. Each short synchronous DB unit
  opens, commits/rolls back, and closes its own session in a bounded thread.
  Datasource updates run off the API loop, lock and reread the row, and advance
  the fresh revision atomically; a stale revision cannot overwrite a concurrent
  update.
- **Notification receive/recovery:** each API/coordinator receiver owns one
  dedicated `psycopg.AsyncConnection` and continuous `notifies()` generator.
  Publication remains synchronous DB/thread work. Explicit recovery callbacks
  are wired at both process edges, and subscriptions precede initial snapshots.
  Recovery targets active compute/build/engine/lock/chat projections, reads
  build/lock projections in batches of at most 128, and wakes durable coordinator
  chat/settings consumers. See
  [receiver](../../../packages/backend/backend_core/runtime_ipc.py) and
  [projection recovery](../../../packages/backend/backend_core/runtime_notifications.py).
- **Chat lifecycle:** enqueue and deletion lock the same session row; competing
  enqueue or deletion with an active turn returns HTTP 409. Typed claim revocation within the local
  epoch settles that turn. SQL failures and coordinator-epoch fencing propagate
  and fail closed rather than being treated as local revocation. See
  [chat store](../../../packages/backend/modules/chat/store.py).
- **Engine cancellation:** cancel the exact engine job ID. A request made before
  startup is remembered and applied when the job ID is bound. The owner joins
  the actual execution thread and holds admission until it settles; cancelling
  an async task does not by itself stop blocking work. See
  [execution ownership](../../../packages/worker/runtime/executors.py).
- **SMTP test deadline:** admit one sending thread and observe its owned future
  with an async wait, without a detached shield. A deadline before sending can
  prevent the send; once the thread is running, provider acceptance is uncertain.
  Admission stays occupied and late errors are observed until the thread settles.
  See [SMTP test](../../../packages/backend/modules/settings/routes.py).
- **Health/scheduler progress:** worker/scheduler Docker probes use PID1's
  private Unix socket and require actual registration plus fresh progress on
  every dispatch lane. A registry row or heartbeat cannot hide a stalled lane.
  Scheduler candidates use ordered batches of 100, advancing over non-due
  candidates to preserve fairness and rereading eligibility under row locks.
  See [scheduler claims](../../../packages/backend/modules/scheduler/service.py).

### Private storage GC

The existing durable outbox stores private source intents before staging and
retirement. `TRACKED → PUBLISHED` retains referenced data;
abandoned targets proceed through `TRACKED → AUTHORIZED → DELETED`. An
independent worker I/O lane cleans exact managed objects/prefixes and associated
catalog identifiers idempotently, deferring a busy RID until its writer and job
slot settle. Cleanup is driven by intents and indexed exact source references,
rather than discovery through blob scans. Tenant migration
[0017_compute_source_index](../../../packages/backend/database/alembic/versions/0017_compute_source_index.py)
supplies the exact-source index.

Source ownership transfer advances the generation and invalidates the old
cleanup claim. Authorization locks the owner and intent, rereads references,
and checks fresh PostgreSQL wall-clock time after acquiring the locks. A valid
deletion grant may be acknowledged after its lease deadline if the token and
generation still match; a superseded claim cannot acknowledge it. Published
snapshots keep their existing retention policy. This contract preserves one
Docker-owning manager and adds no service or public tunables. See
[authorization and state transitions](../../../packages/backend/backend_core/storage_cleanup_service.py)
and [worker cleanup lane](../../../packages/worker/runtime/storage_cleanup_runtime.py).

## Why start with 1×1

FastAPI can multiplex many concurrent network waits on one async event loop.
More Uvicorn processes are useful only when the API process itself is the
measured limit; otherwise they multiply memory, database pools, executors,
startup work, local caches, and integration state without adding compute
capacity. The single-process test is the cleanest way to identify the real
limit. It is a benchmark starting point, not an assumption that one process can
serve every workload.

Keep the existing process boundaries that provide real safety: API processes
do not get Docker access, the worker manager owns container lifecycle, and
compute workers remain isolated containers. Minimize orchestration _inside_
those boundaries; do not collapse them merely to reduce service count.

### API topology choices

Notation here is `API replicas × Uvicorn processes per replica`:

| Shape  | Expected effect                                                                                                                                                                                | Policy                                                                                                                                                      |
| ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `1×1`  | One async API event loop and one set of local pools/caches; lowest process and DB-pool overhead.                                                                                               | Default capacity-test baseline. Keep if it meets the measured workload/SLO.                                                                                 |
| `1×4`  | Four processes in one container; can use multiple cores, but multiplies per-process memory, DB pools, executors, listeners, and local state while sharing the same container CPU/memory limit. | Benchmark only when API CPU-bound; do not assume four workers means four times HTTP or compute capacity.                                                    |
| `1×20` | Twenty processes in one container; magnifies pool and startup overhead, competes inside one resource limit, and duplicates process-local listeners and state.                                  | Not a default or a user-count setting. Test only if measurements show process-level API CPU parallelism is the bottleneck and DB/resource budgets allow it. |
| `N×1`  | One event loop per API container behind ingress; adds host/service replicas and their per-process pools, but distributes API CPU/memory.                                                       | Use only after `1×1` is API-bound. It does not scale the coordinator, worker manager, or compute workers.                                                   |

Never scale to 20 API processes just because the target is 2,000 users. First
determine whether load is mostly idle sockets, API/DB requests, or unique-RID
compute work. The runtime coordinator owns Telegram polling and durable
external delivery; account for each API process's PostgreSQL pools when adding
API processes or replicas.

## Correctness invariants

1. One active worker belongs to one exact analysis RID or datasource RID in a
   namespace. Similar transforms on different RIDs are not the same work.
2. Within that RID, the deterministic full command—including transform,
   pagination, resource settings, and source revision—defines single-flight.
   Identical commands share one durable result; different commands are
   serialized on that RID's worker.
3. A viewer disconnect cannot cancel work still needed by other viewers. A
   stale request/worker lease cannot publish an accepted result or overwrite a
   newer lifecycle state.
4. PostgreSQL is authoritative. Notifications only wake consumers; durable
   rows recover missed notifications. Accepted work is never silently dropped.
   Native async PostgreSQL notification handling is receive-only; publication
   remains synchronous DB/thread work. Both process edges supply explicit
   durable recovery callbacks.
5. Waiting work consumes neither a compute execution permit nor a thread.
   Admission is fair and bounded; overload is explicit rather than hidden by
   browser reloads, random retries, or unbounded executor queues.
6. API workers do not receive Docker access. Compute containers remain the
   isolation/security boundary.
7. Private backend/worker/scheduler implementation imports remain prohibited;
   generated `dataforge_protocol` is the shared service contract.

## Minimize orchestration overhead

- Keep the normal request path to durable enqueue, one directed claim, execution
  on the owning RID worker, durable terminal publication, and notification.
  Avoid adding a broker or another always-on service without evidence that an
  existing stage is saturated.
- Claims target one namespace. Never scan every namespace, engine, or stale
  worker registry per request. Keep wakeups coalesced and use batched recovery
  rather than one polling loop per browser tab.
- Perform command single-flight before engine admission so duplicate viewers
  do not reserve worker capacity. Keep the full-command fingerprint distinct
  from the resource identity.
- Reuse a warm worker for the first cold identity, then replenish the reserve
  asynchronously. Do not start duplicate workers for one RID or repeatedly
  tear down an engine needed by followers.
- Keep API event loops on native async network I/O, WebSocket/SSE delivery, and
  waits. A synchronous SQLAlchemy transaction is one short, session-owned unit
  inside a bounded thread; do not share a live session across threads. Blocking
  Docker, storage/catalog, and SMTP work also stays in bounded threads. Parsing
  and Polars-heavy execution stay in compute containers.
- `COMPUTE_WORKERS` is job/assigned-worker capacity, not a thread-pool size.
  The worker currently has several independently sized executors; measure their
  aggregate threads and queue occupancy. Keep separate progress lanes where
  they prevent lease/control head-of-line blocking, but do not size every lane
  to the public compute count by default.
- Preserve useful structured logs and sampled timings in E2E/load runs. Logging
  must be bounded and non-blocking; turning off all diagnostics is not an
  acceptable performance optimization.
- Make tests use one stack and avoid repeated image builds, stack restarts, or
  overlapping load probes when those are not part of the measured workload.

## Define and prove the 2,000-user target

Do not infer compute demand from account or tab count. Benchmark these profiles
separately on the minimal topology:

1. **Connected-session profile:** 2,000 authenticated browser sessions with
   realistic idle/heartbeat/WebSocket behavior. Measure memory, open sockets,
   loop lag, reconnects, and API readiness.
2. **Interactive API profile:** 2,000 sessions with a representative mix of
   bootstrap/auth/config reads, navigation, saves, and status subscriptions.
   Derive request rates from available product/E2E traces; publish the assumed
   active-user ratio and request mix with each result.
3. **Compute profile:** vary active unique RIDs and commands independently.
   Include many tabs sharing one RID and identical command, one hot RID with
   distinct commands, and many unique RIDs. Measure queue wait and worker cold
   starts; do not call these dimensions “users.”
4. **Resilience profile:** kill an API process during a request, interrupt
   notifications, restart the coordinator, and kill a compute worker during
   publication. Accepted work must finish or reach an explicit terminal error;
   unrelated RIDs must continue.

Keep the standard 3×5 E2E suite and permanent 50-tab probe in CI. They are
correctness/readiness gates, not substitutes for sustained 2,000-session load
tests. Define p95/p99 latency and error thresholds before claiming the target;
report throughput, queue age, API loop lag, DB checkout/lock waits, coordinator
RPC lane wait, worker starts, executor occupancy, and CPU/memory in the same run.

### Current architecture gate status (2026-09-30)

Recorded gate results: `just verify` and `just test` both exited 0. The test gate
passed 3,369 cases in 376.77s: 1,407 backend unit, 103 integration (plus two
skipped), 581 worker, 11 scheduler, and 1,267 frontend cases.

E2E run `run-20260930104837-9934` is in progress with the 3×5 suite, eight
architecture checks, and the 50-tab probe. The expected full-suite population
is 372 cases; that count and the final result are not yet verified. No final
E2E pass count or new probe latency is recorded pending the run's final result.

### Pre-review regression baseline

The previously proven full E2E baseline passed 371 cases and measured about
36.8s p95 on the 50-tab probe. Those results precede the completed architecture
fixes and remain readiness regression evidence; they do not establish capacity
or verify the current E2E run.

### Historical exploratory 1×1 evidence (2026-09-29)

- With `WORKERS=1`, the full 3×4 Playwright suite passed 362 tests and the
  isolated 50-tab/30-account probe passed. The API container was verified to
  have one Uvicorn process.
- Later concurrency tuning passed the full 3×5 suite (15 Playwright workers)
  and 50-tab probe with both `WORKERS=1` and the checked-in `WORKERS=4`
  default. Probe p95 was 21.8s at `WORKERS=1` and 25.2s at `WORKERS=4`.
  At 3×6, a preview failed under both API process settings (HTTP 500 at
  `WORKERS=1`; inline-preview deadline at `WORKERS=4`). Five workers per shard
  is the highest verified setting on this host, not a universal capacity cap.
- Two clean standalone 50-tab probes at `WORKERS=1` returned 50/50 previews,
  with overall p95 24.8s and 25.8s (mean 25.3s); analysis p95 was 24.9s and
  26.0s. Two clean `WORKERS=4` probes on the same host also passed, with overall
  p95 27.2s and 25.2s (mean 26.2s); analysis p95 was 27.5s and 25.4s. A later
  full-suite-then-probe `WORKERS=1` run measured 24.2s p95. This small sample
  shows no repeatable throughput benefit from four API processes.
- Both settings still showed multi-second API loop/send stalls: the two `1×1`
  runs logged 10/5 and 6/5 watchdog-block/loop-lag samples, with max loop lag
  5.4s and 5.3s. The two `1×4` runs logged 40/32 and 36/30 across four
  processes (max loop lag 3.9s and 4.5s). Counts need per-process normalization;
  neither setting eliminated the tail stalls.
- Running the full 362-test suite first, then the 50-tab probe at `WORKERS=1`,
  passed twice with probe p95 of 35.8s and 24.2s. Keep post-suite and
  clean-stack results separate; the variance requires repeat measurements,
  not a reason to increase every pool.
- Docker exposed 7 CPUs. The probe allowed 32 compute workers, four warm
  workers, and configured one Polars core per engine; its 30 distinct analysis
  RIDs can therefore request roughly 30 compute cores before counting service
  overhead. This intentionally overcommits the local host by about 4×. Engine
  listener readiness reached about 20s in the clean run.
- In one clean `1×1` probe, some `/auth/me` responses spent about 4.8s in
  response streaming while measured SQL time was under 51ms. This is not a
  database-latency explanation; the cause (CPU scheduling, transport
  backpressure, or another synchronous path) is not isolated yet. The prior
  full-suite-then-probe run had larger lag and slower previews, so clean-stack
  and post-suite results must remain separate.

These historical runs show that one API process can pass the regression
workload measured then, not that it meets the 2,000-session SLO. Their cold engine
startup/CPU demand and occasional API response-send stalls remain optimization
leads. Run at least three more paired probes in alternating
`WORKERS=1`/`4` order with clean stacks, and collect per-container CPU before
attributing the loop stalls. Based on the successful 1×1 full E2E and no
repeatable 4-process throughput benefit, `docker/env/prod.env` now defaults to
`WORKERS=1`; E2E retains `WORKERS=4` to keep multi-process safety covered. This
is a low-overhead starting default, not a claim that 1×1 meets the 2,000-session
target.

## Scale only after identifying the saturated layer

1. **Start at 1 API container × 1 API process.** Profile normal requests and the
   2,000-session workload with one coordinator and one worker manager.
2. **If API-bound:** fix synchronous work on async paths, serialization, pool
   contention, or logging first. Add API replicas behind an ingress only when
   CPU/loop lag or HTTP latency still shows API saturation. The runtime
   coordinator owns Telegram polling; account for multiplied API pools when
   adding processes or replicas.
3. **If coordinator-bound:** identify whether the wait is RPC executor queue,
   database checkout/lock, serialization, or dispatch scanning. Optimize that
   path and its pool budget first. Multi-active partitioned coordination is a
   later option only if a single coordinator remains the measured bottleneck.
4. **If compute-bound:** distinguish a full worker-slot queue from saturated
   CPU/memory. Raise `COMPUTE_WORKERS` only when jobs are queued and compute
   resources have headroom. If engine CPU is saturated, add compute resources
   or accept queueing; increasing the worker count alone only oversubscribes
   the host. Preserve exact-RID ownership, warm reserve, and container isolation.
5. **If database-bound:** tune query plans, indexes, transaction scope,
   connections, and recovery batching. Tenant/database sharding is a last step
   after repeatable evidence that one primary is saturated.
6. **If one manager is bound:** first reduce redundant Docker/API calls and
   manager lock contention. Only then design multi-manager identity leases and
   cluster-wide capacity grants; do not horizontally replicate the current
   in-memory `ProcessManager` as-is.

Keep `COMPUTE_WORKERS` and `COMPUTE_WARM_WORKERS` as the user-facing compute
controls. Do not add public build/preview/engine slot variables. Do not remove a
numeric validation bound merely because it exists; replace it only when a
measured supported capacity requires it and a resource-based bound is defined.

For each optimization, change one limiting layer at a time and rerun the same
load profile. Keep a result table for 1×1 and every scaled topology: throughput,
p95/p99 latency, errors, queue age, database waits, event-loop lag, and total
resource use. Do not increase API workers, compute workers, pool sizes, and
timeouts together; that makes both improvements and regressions impossible to
attribute.

## Definition of done

- The 1×1 API topology has repeatable 2,000-session results with the workload
  assumptions, SLOs, and resource profile recorded.
- No avoidable API/coordinator/worker/DB round trips, scans, polls, oversized
  executor fan-out, or repeated container starts dominate measured requests.
- The 50-tab probe and full E2E remain green with deterministic UI state and no
  reload rescue/random retry.
- Compute-worker isolation, exact-RID sharing, and durable single-flight remain
  correct while worker capacity is varied independently from API capacity.
- Any added process/replica is justified by a measured bottleneck and improves
  the relevant p95/throughput without increasing errors or destabilizing other
  services.
