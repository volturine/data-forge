# PRD: Capacity-First Runtime Optimization

> **Status (2026-10-03): Active — `just verify`, the complete containerized test suite, the 1×1 E2E suite, and its permanent 50-tab probe pass. The 2,000-session connected-WebSocket profile and one coordinator-takeover-during-publication case pass; broader active-work chaos, interactive API/compute profiles, and formal SLO validation remain open.**
> **Target:** Sustain a representative 2,000-user workload with the fewest service replicas that measurements support. A connected-session-only profile passed; the interactive API/compute workload mix and SLOs still need validation, so this is not yet a general 2,000-user capacity claim.
> **Portfolio:** [PRD index](../README.md)

## Objective

Reduce request-path and orchestration overhead before adding replicas, managers,
brokers, or database shards. Start with one API container and one API process
(`WORKERS=1`), the existing dedicated runtime coordinator, one worker manager,
and separate compute-worker containers. To avoid overloaded shorthand, API
topology is written as “API replicas × Uvicorn processes per replica,” while
E2E topology is written as “Playwright shards × Playwright workers,” followed
by the API `WORKERS` value. Thus the measured **E2E 1×1** run means one shard ×
one Playwright worker with `WORKERS=1`; the corresponding API shape is one API
replica × one Uvicorn process. Neither notation merges the coordinator, worker
manager, or compute containers into the API. Scale only the service whose
measured capacity is saturated.

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
| Worker manager      | One active process owns Docker access, engine-container lifecycle, active identity accounting, and warm workers; standbys on other machines hold no lease and take over through a PostgreSQL session lease. It can place containers on several Docker daemons (`ENGINE_DOCKER_HOSTS`, least-loaded with health checks and launch failover). | Keep separate from API for stability/security. Add compute machines as hosts of the one active manager; standbys are for availability only. Do not run parallel managers without global identity/capacity fencing. |
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

- **Database/session boundary:** FastAPI routes do not receive synchronous
  SQLAlchemy sessions through dependencies. Each complete DB unit opens,
  commits/rolls back, and closes its own session in the bounded API thread lane
  through `run_db`/`run_settings_db`; async compute waits carry no unused DB
  dependency. Datasource updates run off the API loop, lock and reread the row,
  and advance the fresh revision atomically; a stale revision cannot overwrite
  a concurrent update.
- **Notification receive/recovery:** each API/coordinator receiver owns one
  dedicated `psycopg.AsyncConnection` and continuous `notifies()` generator.
  Publication remains synchronous DB/thread work. Explicit recovery callbacks
  are wired at both process edges, and subscriptions precede initial snapshots.
  Recovery targets active compute/build/engine/lock/chat projections, reads
  build/lock projections in batches of at most 128, and wakes durable coordinator
  chat/settings consumers. See
  [receiver](../../../packages/backend/backend_core/runtime_ipc.py) and
  [projection recovery](../../../packages/backend/backend_core/runtime_notifications.py).
- **Runtime wake admission:** work producers insert append-only rows into the
  public wake journal in the same transaction as their durable work; they never
  update the shared namespace marker. Consumers capture bounded exact wake IDs,
  refresh only the target namespace/kind, CAS the marker projection, and delete
  only those IDs atomically. Namespace discovery unions indexed pending/due
  markers with journal rows. Sequence maxima are not acknowledgement
  watermarks because sequence allocation can commit out of order. Migration
  `0020_runtime_wakes` restores the journal after `0018` while
  retaining the migrated marker state.
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
  The scheduler uses `grpc.aio` for registration, heartbeat, and dispatch; its
  independent heartbeat coroutine continues while a namespace dispatch awaits
  the backend. Scheduler candidates use ordered batches of 100, advancing over
  non-due candidates to preserve fairness and rereading eligibility under row
  locks.
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

## Why start with one API process

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

API topology notation here is `API replicas × Uvicorn processes per replica`;
it is distinct from the E2E shard × Playwright-worker notation above:

| Shape  | Expected effect                                                                                                                                                                                | Policy                                                                                                                                                      |
| ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `1×1`  | One async API event loop and one set of local pools/caches; lowest process and DB-pool overhead.                                                                                               | Default capacity-test baseline. Keep if it meets the measured workload/SLO.                                                                                 |
| `1×4`  | Four processes in one container; can use multiple cores, but multiplies per-process memory, DB pools, executors, listeners, and local state while sharing the same container CPU/memory limit. | Benchmark only when API CPU-bound; do not assume four workers means four times HTTP or compute capacity.                                                    |
| `1×20` | Twenty processes in one container; magnifies pool and startup overhead, competes inside one resource limit, and duplicates process-local listeners and state.                                  | Not a default or a user-count setting. Test only if measurements show process-level API CPU parallelism is the bottleneck and DB/resource budgets allow it. |
| `N×1`  | One event loop per API container behind ingress; adds host/service replicas and their per-process pools, but distributes API CPU/memory. `docker/compose.replicas.yaml` provides this shape; the API holds no authoritative process or disk state. | Use only after `1×1` is API-bound. It does not scale the coordinator, worker manager, or compute workers.                                                   |

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
  do not reserve worker capacity. Active/cached hits are lock-free reads;
  only stale-entry cleanup takes a row lock and refreshes both rows before
  deletion. The per-key advisory lock protects miss/create races, and a busy
  follower retries only after its short DB session closes. Keep the
  full-command fingerprint distinct from the resource identity.
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

### Current architecture gate status (2026-10-03)

`just verify` passed. The latest `just test` passed **3,536 tests** with two
integration skips: 1,529 backend unit, 114 backend integration, 609 worker, 12
scheduler, and 1,272 frontend tests. This includes the PostgreSQL coordinator
takeover-during-publication regression described below.

The latest 1×1 E2E run used `WORKERS=1`, `E2E_API_WORKERS=1`, `E2E_SHARDS=1`,
and `PW_E2E_WORKERS=1`. The isolated enclave had 8 Docker CPUs and 10,751 MiB
total memory. It passed **362 ordinary E2E tests** (6.2m), **9 runtime
architecture regressions** (54.7s), and the permanent **50-tab / 30-account**
probe (52.3s; 50/50 previews). The probe used 30 Chromium processes and was
capped at **3.0 vCPU**. Overall preview p50/p95/max was **10.80s / 17.50s /
18.48s**; analysis preview p50/p95 was **14.07s / 18.04s**; shared-datasource
p50/p95 was **157ms / 714ms**; and an exact completed-command cache hit took
**63ms wall / 52ms server**. This is a readiness result for the measured setup,
not a 50-user or 2,000-user capacity guarantee.

A prior paired single-run comparison (2026-10-02) kept Playwright at **1 shard ×
1 worker** and changed only API `WORKERS` from 1 to 4. Both full suites,
architecture checks, and 50-tab probes passed. The whole command took **15m37s**
versus **12m48s**.
With API `WORKERS=4`, ordinary E2E took **9.2m** instead of **6.4m**; probe
overall p95 was **28.60s** instead of **23.03s**,
analysis p95 **28.77s** instead of **23.11s**, datasource p95 **1.29s** instead
of **426ms**, and a completed shared-command hit took **487ms** instead of
**104ms** wall time. During the API-4 probe, one sample showed the API container
at about **975 MiB / 136 processes**, versus **237 MiB / 35 processes** for
API-1; event-loop lag peaked at **8.69s** and a recovery poll took **3.77s**.
This single pair is not a causal or repeatable benchmark, but it shows no
benefit from four API processes for this workload and warrants profiling their
multiplied pools/listeners before scaling them at small user counts.

One preceding same-config attempt stopped before tests during API-image `uv sync`;
the original quiet build output hid the underlying package-manager error. An
identical retry completed successfully. The E2E harness now retains per-target
BuildKit logs and prints the failing target's log tail, so a recurrence is
diagnosable instead of being misclassified as a browser/runtime failure.

A separate PostgreSQL race test co-starts 20 identical datasource-preview
submissions and verifies one durable request/flight. A new PostgreSQL
integration test blocks terminal preview publication, kills the coordinator,
confirms its process is gone, advances the generation, verifies worker-manager
re-registration, recovers one terminal preview result, and proves an
old-generation completion cannot change it. The test tags coordinator DB
sessions and terminates any sessions left by the nested-Docker published-port
proxy after process death; this is test-enclave cleanup, not a production
coordinator recovery mechanism. Broader worker-failure-during-publication,
unrelated-RID continuity, and sustained interactive capacity remain separate
resilience/load gates.

The subsequent multi-process validation (2026-10-02) used `WORKERS=4`, three
Playwright shards, and five Playwright workers per shard. All **362 ordinary E2E tests**,
**9 runtime architecture regressions**, and the permanent **50-tab / 30-account**
probe passed. The isolated enclave took **14m56s** including setup/image pulls;
the ordinary shards completed in **5.9–7.5m**. Probe overall preview
p50/p95/max was **4.66s / 24.39s / 26.46s**; analysis preview p50/p95 was
**20.34s / 24.72s**, shared-datasource preview p95 was **205ms**, and a completed
cache hit took **64ms wall / 27.4ms server**. This validates multi-process E2E
correctness at this test topology, not a general 2,000-user compute SLO.

This run followed a red 3×5/API4 run that recorded a **26.7s** update to the
shared `(default, outbox)` runtime-work marker, with lease/build RPCs delayed by
roughly the same interval. Outbox producers now append indexed wake-journal rows
instead of updating that shared marker; consumers acknowledge exact captured
IDs, so late or out-of-order commits remain visible. In the green rerun, no slow
outbox-generation update was logged. Some runtime RPCs and scheduler heartbeats
still hit long delays under the local resource limit. A mid-run sample of the
7.5-vCPU DIND enclave showed CPU pressure `some avg10≈71%` and `full avg10≈7%`,
with low memory pressure and no OOM kills. The local 3×5 workload remains
CPU-bound; the remaining slow RPC warnings are not evidence of the fixed
marker-row convoy.

The uncapped comparison run had 362 + 9 tests pass but 2 probe tabs failed with
HTTP 504: their worker hit a hardcoded 5s coordinator-generation assertion
deadline while spawning/replenishing a warm worker. Generation bootstrap and
assertion now use the existing 15s-bounded control timeout. The earlier probe
also exposed fail-fast default-executor admission; API blocking work now waits
asynchronously for bounded executor capacity, and WebSocket error delivery no
longer resubmits through a saturated pool. Engine claim contention now uses
`pg_try_advisory_xact_lock`, rolls back a busy candidate, skips that exact RID
for the current claim pass, and continues to another eligible RID. A PostgreSQL
race test verifies different-RID progress while one RID's claim lock is held.

An earlier 1×1 capped run showed API event-loop lag up to **6.47s**, runtime claim
and datasource-metadata RPCs around **7–9s**, and transient engine-heartbeat
deadlines. The preceding uncapped run's Playwright generator peaked at **780.6%
CPU** inside a **7.5-CPU DIND** enclave; the capped generator peaked at **329.7%**.
This supports generator contention as a major contributor, but the runtime DB
and RPC latency outliers remain and require attribution. The run proves this
scenario can finish at the defined **1×1** setting (one Playwright shard × one
Playwright worker, API `WORKERS=1`); it does not establish stable p95 or
sustained user capacity.

The connected-session profile ran three consecutive repeats against one isolated
stack with one API process and `WORKER_CONNECTIONS=4096`: each repeat registered
2,000 unique accounts and held 2,000 authenticated lock-watch WebSockets for 60
seconds, sending staggered application heartbeats every 10 seconds. All three
repeats passed: 6,000 account/token registrations, 6,000 WebSocket handshakes
and subscriptions, 36,000 heartbeat round trips, and 51/51 readiness checks
succeeded. Across repeats, session-ready p95 was **223–323ms** / p99
**312–342ms**, heartbeat RTT p95 **2.8–3.0ms** / p99 **4.5–5.8ms**, and
WebSocket handshake p95 **39–46ms** / p99 **47–67ms**. Account setup took
16.6–17.2s per repeat; each full profile took 83.3–84.0s. The probe uses
synthetic watched analysis IDs; no saves, navigation mix, previews, or compute
jobs were included.

The 8-CPU, 10.5-GiB enclave's sampled API memory reached about 313MiB after
setup and API CPU stayed about 0.23–0.61 cores during steady heartbeats; API CPU
peaked around 4.8 cores during account registration. PostgreSQL peaked around
113MiB and 0.1 CPU. There were no readiness failures or test-enclave OOM events
in the three measured repeats. The first attempt before correcting
the probe client's keep-alive expiry had two client-side `RemoteProtocolError`s
on readiness polls at the same five-second interval as Uvicorn's idle
keep-alive timeout; the repeat harness now expires that client connection at
two seconds. This connected-session profile is reproducible with
`just test-e2e-capacity sessions=2000 repeats=3`.

#### External delivery guarantee

Telegram part receipts prevent retransmission of parts whose receipt is
durable. The provider send and local receipt commit cannot share a transaction;
if provider acceptance is uncertain at that final boundary, a part may be sent
again. Delivery is therefore at-least-once at that boundary, not exactly-once.

### Historical regression evidence (before the 2026-10-01 fixes)

The earlier pre-fix run used Docker Desktop at 8 CPUs and 10 GiB and finished
with 358/362 ordinary tests passing, all nine architecture tests passing, and
one of 50 probe tabs missing editor readiness. Four ordinary failures involved
two pipeline previews, one column-stats request, and one build deadline. Runtime
evidence showed a worker heartbeat taking 4.9s against its 5s deadline, repeated
lease/RPC delays, and engine listener startup of about 15s; database samples
showed no blocking sessions. The private daemon recorded 520,841 memory-limit
events but zero OOM kills. These observations identify pressure and backend
delay, not a unique cause for each failure.

CI run `36712501309` on commit `81c3ddbe` failed independently in two
areas: six worker tests dialed an unresolvable Mac Tailscale hostname, and the
E2E selector lacked `rg`, started all 124 discovered tests in each of three
ordinary shards, then the harness exited 137. The logs do not establish that
exit 137 was a kernel OOM kill. The worktree now uses in-container loopback for
the worker-local servers, installs `rg`, and makes selection fail closed.

The first E2E failure after the last green CI run (`36580405720`, commit
`8a5e943`) appeared in run `36620347698` after increasing the shard worker count
from four to five. That increased browser concurrency from 12 to 15. Preview
and storage deadlines and editor-lock errors appeared before the coordinator
generation changed; failover was a later symptom, not the initial trigger.
This timing implicates the higher load as a contributor, but does not prove it
caused every failure.

The coordinator database pool no longer scales from `COMPUTE_WORKERS`, and API
blocking/serialization/bootstrap queues have bounded admission independently
from `WORKER_CONNECTIONS`. The 2,000-session connected profile uses 4,096 as
Uvicorn's coarse connection ceiling, not as a thread or database-work budget.
The 1×1 reference run fixes browser and API process concurrency for comparison;
the separate 3×5/API4 run above confirms that four API processes can complete
the full E2E/readiness suite, but does not establish the interactive API or
compute SLOs. Neither E2E profile changes the separate 2,000-session connected
profile above.
The interactive API, compute, and resilience profiles and their SLO thresholds
are still undefined and unmeasured.

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
leads. Based on the successful 1×1 full E2E and no repeatable 4-process
throughput benefit, `docker/env/prod.env` now defaults to `WORKERS=1`; E2E
retains `WORKERS=4` to keep multi-process safety covered. This is a low-overhead
starting default, not a claim that 1×1 meets the 2,000-session target.

#### Prior post-change 1×1 diagnostic run (2026-10-02)

The 2026-10-02 post-change `1×1` validation passed the full containerized E2E
suite: **362 ordinary tests** (6.5m), **9 architecture
regressions** (54.1s), and the permanent **50-tab / 30-account** probe (50/50
previews, 47.5s). The whole `just test-e2e` command took **12m24s** including
builds, bootstrap, and teardown. The probe's overall preview p50/p95/max was
**3.30s / 15.36s / 18.75s**, analysis p50/p95 was **11.81s / 15.39s**,
datasource p50/p95 was **140ms / 3.06s**, and a completed-command cache hit
took **32.5ms wall / 14ms server**. It used 30 Chromium processes and the
existing 3-vCPU probe cap. Routing compute/build WebSocket database,
serialization, object-store RPC, runtime notification, and test-only manager
work through the API's bounded execution lane did not regress the measured
workload. Routes avoid direct dependency-session generators and generic
`run_in_threadpool`; a static test guards that boundary. These timings remain
historical diagnostic evidence, not the latest 1×1 result or a capacity SLO.

That run's `api_blocking_admission_wait_ms` diagnostic recorded **0ms** in all
50 slow-preview records, so preview latency was not waiting for API blocking-lane
admission. Its slowest runtime RPC was `PersistEngineSnapshot` at **6.77s**;
SQL totaled **216ms**, DB checkout **230ms**, and RPC executor queue **1.2ms**.
The remaining handler time was not attributed in that run; snapshot phase
profiling remains open. This is readiness evidence, not a capacity SLO.

#### Latest clean 50-tab API-process comparison (2026-10-02)

Two additional probe-only runs used fresh isolated stacks, one Playwright shard
and one Playwright worker, with no full E2E suite running concurrently. Both
returned all 50 previews successfully. The API1 run (`WORKERS=1`) measured
preview p50/p95/max **8.51s / 16.27s / 18.50s**, analysis p95 **16.32s**,
datasource p95 **8.35s**, and an identical completed-command cache hit at
**61ms wall / 33.9ms server**. The API4 run (`WORKERS=4`) measured overall
preview p50/p95/max **7.43s / 22.59s / 31.02s**, analysis p95 **24.19s**,
datasource p95 **8.08s**, and the same-command hit at **52.7ms wall / 37.6ms
server**. This single alternating pair does not establish a causal API-worker
performance difference. The API4 container used about **881MiB / 115 tasks**
versus **226MiB / 31 tasks** for API1.

The API4 run passed, unlike one earlier clean API4 probe that failed one
analysis tab with an empty response; that failed run had no OOM kill. Both
those runs still logged event-loop lag of several seconds and runtime/database
outliers. In the API4 run, a runtime worker heartbeat checked out a critical
settings connection for about **4.2s**, while unrelated control RPCs took about
**4.2–4.5s**; a claim and a response-recovery poll also took about **5.3s**.
The API1 run logged lease renewal around **3.6s** and completion RPCs around
**3.8s**, with periods of multi-second DB checkout/commit delay. These coincide
with high process load from the 30 Chromium processes and 30 cold analysis
workers, so they do not yet isolate an application-level bottleneck. Peak
container sampling was incomplete: the sampler's Docker CLI timed out during
the burst, so its initial low samples cannot characterize peak CPU.

The identical-command cache hit remaining under **65ms** confirms that already
completed work is shared efficiently. The 16–31s tail is dominated by first
work on distinct analysis RIDs and shared host/control-plane pressure; it is
not the cache-hit path. Next, separate compute cold-start demand from API and
control-plane work using a repeatable service-side request profile and
non-invasive cgroup metrics, then tune only the saturated boundary. Do not
infer that API1 is faster from this pair or raise pool/worker limits from it.

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
   (another Docker host in `ENGINE_DOCKER_HOSTS`) or accept queueing;
   increasing the worker count alone only oversubscribes the host. Preserve
   exact-RID ownership, warm reserve, and container isolation.
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
