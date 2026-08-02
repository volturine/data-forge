# Runtime Correctness and Architecture Remediation Plan

## Document Status

- **Status:** In progress
- **Scope:** Concurrency correctness, deterministic behavior, runtime ownership, transaction boundaries, maintainability, and verification
- **Applies to:** Backend API, worker runtime, scheduler, frontend state, protocol contracts, persistence, and CI
- **Supersedes:** Runtime correctness claims in `distributed-runtime-v2-progress.md` where those claims conflict with verified implementation behavior
- **Does not supersede:** Product requirements or user-facing feature PRDs

### Implementation progress — through 2026-07-31

Completed in the first P0 build-job slice:

- build claims now carry a unique token, monotonic generation, attempt, database expiry, and TTL;
- claims renew independently of worker heartbeats, using conservative monotonic worker deadlines and bounded renewal calls;
- stale claims are rejected for start, event append, schedule ingest entry, failure, and finalization;
- finalization and cancellation compose job, build projection/event, and schedule reconciliation into one transaction;
- cancellation revokes queued and running jobs, and terminal jobs are immutable;
- the always-on manager count path reconciles exhausted jobs and exposes retryable expired jobs as pending capacity;
- exhausted scheduled jobs release schedule leases both during runtime recovery and migration;
- the fenced protocol uses an explicit build-claim capability version and rejects incompatible claimants;
- worker shutdown no longer broadly releases claims that may still have executing work;
- adversarial unit and cross-API cancellation coverage has been added.

Completed in the staged-publication P0 slice:

- queued analysis outputs are written to claim-specific Iceberg tables and object-store paths instead of mutating the published table;
- incremental builds copy the previously published table into a claim-specific stage before appending new rows;
- datasource metadata and the build-result summary publish in one claim-locked database transaction;
- stale output claims are rejected without changing the published datasource or build result;
- scheduled datasource ingests write to a claim-specific clean-table location and revalidate ownership immediately before committing datasource metadata;
- queued-build health-check persistence and notifications occur only after fenced output publication succeeds;
- failed build-result summaries are fenced by the same claim token and generation.

Completed in the atomic build-event P0 slice:

- each build run persists `next_event_sequence` directly in the tenant schema creator;
- event producers lock the build row before allocating a sequence or changing the durable projection;
- counter increment, projection fold, event insertion, and runtime-outbox enqueue commit or roll back as one transaction;
- cross-process wakeups use the durable outbox while the committing API process updates its local build hub after commit;
- concurrent Postgres producers are verified to receive one unique total order, with the final projection matching the last committed event;
- rollback coverage verifies that no counter, projection, event, or outbox residue survives a failed transaction.

Completed in the execution-generation and terminal-race P0 slice:

- the migration graph is compacted to the public and tenant schema creators; incremental compatibility revisions and upgrade handling are removed;
- build startup copies the active claim generation into the build projection and advances it when a reclaimed job restarts;
- worker events must match the build execution generation in addition to holding the active job claim;
- cancellation increments the job generation and atomically installs that exact generation with the cancellation event and projection;
- cancellation now rejects missing or concurrently terminalized jobs instead of continuing from stale state;
- finalization locks the active claim first and refuses to terminalize a job before the build projection is terminal;
- worker failure handling now writes the failed build projection, terminal event, outbox entry, job outcome, and schedule reconciliation in one claim-locked transaction;
- a concurrent Postgres cancellation/completion test verifies that exactly one terminal event wins and job/build generations remain consistent.

Completed in the terminal-engine and outbox-claim slice:

- engine-run updates lock the run row, and terminal runs are immutable across status, result, error, progress, and timing fields;
- runtime outbox rows move through a durable `dispatching` claim with a unique token, monotonic generation, and database-visible expiry;
- each outbox claim commits before delivery, delivery occurs without holding a database transaction, and finalization compares the token and generation;
- expired dispatch claims are reclaimable, stale finalizers are rejected, and selection has a stable `available_at`, `created_at`, `id` order;
- delivered internal payloads include the stable outbox event ID for consumer deduplication;
- concurrent Postgres dispatcher coverage verifies that an in-flight claimed row is never selected by another dispatcher.

Completed in the compute-request fencing and worker-drain slice:

- compute-request claims carry a unique token, monotonic generation, database expiry, attempt number, and claim timestamps;
- claim selection has a deterministic kind-priority, creation-time, and ID order and increments generation on reclaim;
- compute requests renew independently through the runtime protocol, and completion/failure lock and validate the active token and generation;
- stale attempts cannot publish a response or response-outbox wakeup after expiry and reclaim;
- the incompatible unfenced protocol and broad shutdown-time request release operation are removed;
- manager shutdown stops accepting requests, drains active executor work while its claim renews, and only then stops the data plane and engines.

Completed in the durable notification-publication slice:

- email and Telegram RPCs enqueue durable delivery records instead of performing external network I/O inline;
- notification delivery shares the claimed outbox lifecycle, including retry, expired-claim recovery, and token/generation compare-and-set finalization;
- email deliveries use the stable outbox event ID as their message ID, and delivery payloads retain that ID across retries;
- output notification commands are typed in the worker protocol and are inserted in the same transaction that publishes datasource metadata and the claimed build-result summary;
- stale output claims cannot enqueue notification deliveries;
- per-row notification commands are staged as internal pipeline columns, stripped from previews and published data, and inserted into the durable outbox in the same transaction as output publication;
- abandoned or stale pipeline attempts therefore cannot leave accepted delivery records, and per-row status reports `staged` until publication commits.

Completed in the scheduler, analysis, and frontend-concurrency slice:

- schedule claims are bounded, totally ordered, tokenized, generation-fenced, expiring, and reclaimable;
- stale schedule owners cannot enqueue work or clear a replacement claim;
- analysis content mutations require an exact `If-Match` revision and return the next revision in `ETag` and `X-Analysis-Version`;
- analysis version allocation locks the parent row and is protected by a database unique constraint;
- namespace changes abort active frontend requests and reject responses crossing the namespace epoch;
- analysis IndexedDB state now has explicit namespace-scoped initialization, and the analysis/schema store cycle is removed.



Completed in the ownership-cleanup polish:

- single worker load entrypoint (`datasources.load_datasource`) used by execution and pipeline ops;
- worker result DTOs documented as protocol/publication payloads, not HTTP API schemas;
- backend no longer owns Polars healthcheck execution or export-format writers;
- backend compute base retains only API-facing engine status snapshots;
- the earlier deferred redesign slices were reduced to consumer idempotency and chaos coverage before those follow-up slices were completed.

Completed in the structural-boundary slice:

- worker runtime event publication, healthcheck execution, resource observation, and protocol conversion have dedicated lifecycle owners;
- frontend chat presentation/layout, chart preparation/interaction/render lifecycle, editor preview state, and app lifecycle have dedicated state owners;
- backend compute and shared frontend engine representations, plus worker protocol representations, use centralized mappers instead of transport-local copies.

Completed in the datasource-execution-ownership slice:

- worker-owned modules execute create/ingest/schema/stats/snapshot-compare Polars and Iceberg work;
- backend worker-runtime RPCs only publish fenced datasource metadata and schema cache;
- schedule ingest executes on the worker and publishes with the build-job claim fence;
- API process-local datasource execution modules are removed.

Completed in the retry, datasource-publication, and verification slice:

- compute requests and outbox deliveries have explicit attempt limits; exhausted work becomes a durable failed or poisoned terminal record;
- datasource ingests write only to claim-specific staging locations and publish metadata with both the active work claim and datasource revision as fences;
- process-local datasource ingest locking is removed;
- verification checks rather than formats, fails if it changes the worktree, validates generated protocol output, and uses pinned Python, uv, Bun, and Just versions in CI;
- runtime composition uses staged operations for multi-write transactions, while explicit command adapters own standalone commits without `commit` flags.

Completed in the external-boundary and lifecycle follow-up:

- external notification deliveries persist a receipt keyed by the stable outbox event ID, and retries skip provider calls after a receipt exists;
- email retains that event ID as its stable `Message-ID`; the provider-acceptance/local-receipt crash window remains an explicit external-system limitation;
- a real dispatcher process is terminated after claiming Postgres outbox work, then a second process proves expired-claim recovery and fenced completion;
- schedule CRUD now uses flush-only persistence operations coordinated by application commands that own commit and post-commit wakeups;
- HTTP and gRPC transports are commit-free and enforced by the code-hygiene check; authentication, build start/cancel/fail/finalize, output publication, health-result recording, datasource deletion, notification enqueue, and expired-job reconciliation delegate to application commands;
- application-command transactions roll back on exceptions; registration commits the user, verification token, and login session together; OAuth commits identity linking and login-session creation together; build cancellation commits its engine-run projection with the build transition; and claimed output publication commits datasource metadata, build-result projection, and notification outbox rows atomically;
- the frontend root owns one lifecycle coordinator that cancels queries, resets every namespace-scoped service, clears cached server state after activation, and destroys process resources at app teardown.

Completed in the concurrency-verification and operational-confidence slice:

- a shared barrier-based concurrent actor harness coordinates real PostgreSQL sessions without timing sleeps;
- simultaneous scheduler claimants prove one due schedule is claimed exactly once through `SKIP LOCKED` and fenced lease predicates;
- claimant transitions use shared typed outcomes, with gRPC handlers explicitly mapping `Applied` and rejected lease outcomes;
- lease claim, reclaim, renewal, loss, and exhaustion paths emit redacted structured context and transition counters;
- forced process exits and restarts cover API, worker manager, scheduler, and an actively claimed dispatcher delivery;
- `just test-runtime-stability 3` repeats the contention, transition, lease, and crash/restart matrix three times.

Follow-up cleanup for staged publication:

- reclaim orphaned claim-specific Iceberg tables and object-store prefixes after rejected or abandoned attempts;
- replace the full-table copy used by fenced incremental publication with an Iceberg-native branch/snapshot promotion mechanism if the selected catalog exposes an atomic promotion primitive.

## 1. Purpose

This document began when the project had the major pieces of a distributed runtime but did not yet apply one enforceable concurrency model across them. The remediation described below is now implemented; the findings are retained as the historical failure model that the completed invariants and tests address.

The baseline paths relied on worker identity, process-local locks, unrestricted status assignments, separately committed service calls, or implicit ordering. Those choices did not establish correctness when:

- a lease expires while its original worker is still running;
- a worker shuts down while executor work is still active;
- two event producers append to one build concurrently;
- cancellation races with success or failure;
- multiple API, worker, scheduler, or outbox processes run at once;
- a frontend request completes after its namespace has changed;
- two writers allocate the next numeric version concurrently.

This plan defines the target invariants, affected surfaces, migration sequence, tests, and release criteria needed to make those cases correct by construction.

## 2. Outcome

After this plan is complete:

1. A claimed unit of work has a unique attempt identity, a renewable lease, and a fencing generation.
2. A stale or replaced worker cannot publish events, complete work, or overwrite terminal state.
3. Build events receive a unique total order in the same transaction that updates the build projection.
4. Cancellation and finalization are atomic, idempotent state transitions.
5. External notifications are explicitly at-least-once and safely deduplicated.
6. Data execution belongs to worker processes; API processes authorize and persist state.
7. Scheduler claims are bounded, ordered, renewable, and fenced.
8. Analysis mutations use mandatory optimistic concurrency rather than optional client cooperation.
9. Frontend namespace changes invalidate all earlier asynchronous work.
10. Transaction ownership and component boundaries are visible from the code structure.
11. Deterministic ordering is part of every query and operation contract where order is observable.
12. Verification detects generated-file drift and does not mutate the worktree.

## 3. Scope and Priority

| Area | Failure mode | Severity | Priority |
|---|---|---:|---:|
| Work leases | Expired owner continues writing after reclaim | Critical | P0 |
| Build event sequencing | Concurrent producers select the same sequence or lose projection updates | Critical | P0 |
| Cancellation/finalization | Partial commits and terminal-state races | Critical | P0 |
| Compute request shutdown | Released claim is reclaimed while old executor thread continues | Critical | P0 |
| Datasource execution | Process-local locking and API-owned execution permit cross-process conflicts | High | P1 |
| Outbox dispatch | Locks are released for an in-memory batch after the first commit | High | P1 |
| Scheduler claims | Broad locking, incomplete lease semantics, nondeterministic selection | High | P1 |
| Analysis editing | Optional revision checks permit lost updates and duplicate versions | High | P1 |
| Frontend state | Late responses can repopulate a previous namespace | High | P1 |
| Transaction boundaries | Internally committing services prevent atomic use cases | High | P1 |
| Deterministic ordering | Equal-priority/equal-time rows and operator ties have unspecified order | Medium | P2 |
| Structural size/coupling | God modules and global service locators obscure ownership | Medium | P2 |
| Verification | Code generation and formatting can hide drift by mutating before checking | Medium | P2 |
| Naming guidance | “Single word names” encourages ambiguous identifiers | Low | P3 |
| Documentation | Progress claims overstate guarantees enforced by code | Medium | P0 |

## 4. Non-Goals

- Adding Redis or another queue/state dependency.
- Preserving the current runtime protocol for backward compatibility.
- Supporting old and new claim models in parallel after migration.
- Treating retries as exactly-once execution. The target is at-least-once execution with fenced state publication.
- Using editor presence locks as a correctness mechanism.
- Splitting files solely to reduce line counts.
- Renaming identifiers without improving ownership or intent.

## 5. Baseline Findings (Remediated)

### 5.1 Work claims originally had expiry but not complete lease semantics

Build jobs and compute requests record a lease owner and expiry. The claim returned to a worker does not contain a unique claim token or generation, and completion methods update rows by ID without verifying the current owner, generation, or expected status.

Consequences:

- a job reclaimed after expiry can still be completed by the earlier owner;
- a late failure can overwrite a newer success;
- cancellation can be overwritten by an unfenced completion;
- two concurrent tasks using the same worker ID cannot be distinguished;
- worker identity incorrectly acts as both process identity and attempt identity.

The default build job has `max_attempts = 1`. Claiming increments `attempts` to one. An expired running job then fails the `attempts < max_attempts` reclaim condition, so an unclean worker loss can leave the default job stranded instead of transitioning through an explicit exhausted-attempt policy.

### 5.2 Heartbeats are not work-lease renewal

Runtime worker heartbeat updates process liveness, but it is not a renewal of each active work lease. Process liveness and claim ownership are different concepts:

- a healthy process can have a stuck task;
- a slow valid task can outlive the lease;
- one task can fail while other tasks in the process remain healthy.

Each active claim needs an independent renewal lifecycle.

### 5.3 Unsafe worker shutdown could create duplicate execution

Compute request loops share a worker ID. Cleanup releases all requests owned by that worker ID. Cancellation of `run_in_executor` does not stop the underlying thread, so cleanup can make a request claimable while the old thread continues executing.

Shutdown must drain active execution or allow leases to expire. It must not broadly release claims that can still have running code behind them.

### 5.4 Build event sequence allocation was racy

The next build event sequence is derived from `MAX(sequence) + 1`. Concurrent event producers can observe the same maximum. They can then:

- collide on a unique constraint;
- apply projection updates from stale build snapshots;
- increment a version from the same previous value;
- lose one producer’s state change.

Worker build progress and resource events are emitted concurrently, making this a real runtime path rather than a theoretical multi-client case.

### 5.5 Cancellation previously spanned independent transactions

Cancellation currently coordinates durable build state, engine state, queue state, and a cancellation event through separately committing calls. A crash or interleaving can leave combinations such as:

- cancelled job with running build projection;
- cancelled engine with no durable cancellation event;
- completed job followed by a late cancellation projection;
- duplicate cancellation events after client retry.

### 5.6 Finalization was not one fenced transition

Build finalization updates build state, job state, and schedule reconciliation in separate commits. The finalization request does not prove that the caller still owns the active claim.

The system can therefore expose partial terminal state, and a stale worker can finalize after ownership has moved.

### 5.7 Outbox batching previously released locks too early

The dispatcher locks a batch, then performs external delivery and commits each row individually. The first commit releases locks for every selected row, including rows still held only in process memory. Another dispatcher can select those remaining rows.

At-least-once notification is acceptable, but it must be intentional:

- each event needs a stable delivery ID;
- consumers need deduplication;
- claim and delivery state need compare-and-set ownership;
- a crashed dispatcher needs recoverable claim expiry.

### 5.8 Datasource mutation locking was process-local

Datasource ingestion uses a `threading.Lock`. With multiple API processes, each process owns a different lock, so the lock does not protect the shared datasource.

The worker also claims datasource-related compute requests and then asks the backend to execute them. This reverses the intended ownership boundary: the API process performs Polars/Iceberg work while the worker acts as a relay.

### 5.9 Scheduler claim selection was broader than the work

The scheduler locks enabled schedules before fully narrowing the set to due work. This reduces the value of `SKIP LOCKED`, increases contention, and has no stable total order. Schedule lease fields and recovery rules also do not use the same renewal and fencing semantics as other work.

### 5.10 Analysis concurrency was optional

Mutation revision validation is conditional when `If-Match` is absent. Editor locks prevent a mutation only when another active lock exists, so clients that omit both mechanisms can update concurrently.

Analysis version allocation also uses `MAX(version) + 1` without a database-enforced unique `(analysis_id, version)` allocation contract.

### 5.11 Frontend asynchronous work could cross namespace boundaries

Some stores use request gates, but this is not a universal contract. A raw request started in namespace A can finish after switching to namespace B and write A’s data into the reset B store.

Module-level singleton stores and circular imports between analysis and schema state obscure lifecycle and make correct teardown harder.

### 5.12 Observable ordering is incomplete

Several queue and history queries order by priority or timestamp without a primary-key tie-breaker. Pipeline operations such as grouping and top-k do not consistently define tie or output-group order.

If users, tests, snapshots, or downstream steps can observe order, the order must be a documented contract.

### 5.13 Transaction ownership is distributed across layers

Routes, gRPC handlers, and services call functions that commit internally. Some services expose a `commit` flag while others always commit. This makes it difficult to tell which set of writes forms one use case and prevents callers from composing atomic operations safely.

### 5.14 Large modules combine unrelated ownership

Large runtime and frontend files currently mix orchestration, protocol conversion, persistence, rendering, state, and lifecycle behavior. Size is a symptom; the structural issue is that independent reasons to change share one unit.

Examples include:

- worker compute service handling orchestration, events, resources, datasource requests, and protocol mapping;
- chart preview handling data shaping, chart-specific behavior, rendering, controls, and interaction;
- chat panel handling transport, conversation state, tools, rendering, and input;
- analysis page coordinating route lifecycle, editor state, locks, builds, panels, and presentation.

## 6. Target Architecture

### 6.1 Runtime ownership

```text
HTTP / gRPC transport
        |
        v
Application use case  ---- owns one database transaction
        |
        +---- domain transition policy
        |
        +---- repositories (flush, never commit)
        |
        +---- durable outbox record
        |
        v
PostgreSQL commit
        |
        v
best-effort wakeup / external delivery
```

Execution ownership is:

```text
API        authorize, enqueue, read projections, request cancellation
Worker     claim, renew, execute, publish fenced progress, finalize
Scheduler  claim due trigger, enqueue scheduled build, reconcile outcome
Postgres   authoritative state, ordering, leases, events, outbox
Frontend   scoped projection cache; never an authority for runtime state
```

### 6.2 Shared fenced-work contract

Build jobs, compute requests, schedule triggers, and outbox deliveries must share a common conceptual contract even if they use separate tables.

Every claim contains:

| Field | Meaning |
|---|---|
| `owner_id` | Process/runtime identity for observability |
| `claim_token` | Random identity unique to this claim attempt |
| `generation` | Monotonically increasing fencing value |
| `lease_expires_at` | Database-clock deadline |
| `attempt` | Execution attempt number |
| `claimed_at` | Claim timestamp |

Every mutating command from a claimant supplies:

- row ID;
- claim token;
- generation;
- expected active status.

The database mutation succeeds only when all supplied values still match. A zero-row update is a typed `LeaseLost` outcome, not a generic failure.

### 6.3 Time and identity

- Database time is authoritative for lease comparisons and persisted transition timestamps.
- Application clocks remain injectable for pure domain calculations and deterministic tests.
- Claim tokens and entity IDs are generated through injected identity providers.
- No correctness rule compares timestamps produced by different process clocks.

### 6.4 State transition contract

State changes use explicit compare-and-set transitions. Direct unrestricted assignments such as generic `mark_completed(id)` are removed.

Canonical outcomes:

- `Applied`
- `AlreadyApplied`
- `AlreadyTerminal`
- `LeaseLost`
- `InvalidTransition`
- `NotFound`

Terminal state is immutable except through a separately designed administrative repair operation.

### 6.5 Build event contract

Add to `build_runs`:

- `next_event_sequence`;
- `execution_generation`;
- explicit projection revision if not represented by the existing version field.

Appending a worker event performs one transaction:

1. lock or compare-and-set the build row;
2. verify build is active;
3. verify the worker execution generation;
4. reserve and increment `next_event_sequence`;
5. validate and apply the event to the durable projection;
6. insert the event with the reserved sequence;
7. insert the outbox wakeup;
8. commit.

API-authored authoritative events, such as cancellation, do not require the old worker claim. They increment `execution_generation`, which fences all earlier worker events.

### 6.6 Outbox delivery contract

The outbox is at-least-once:

```text
pending/failed -> dispatching -> dispatched
                     |
                     +-> failed
```

Claiming a delivery:

- selects a bounded, totally ordered batch;
- records claim token and expiry;
- commits the claim before external delivery.

Delivery occurs outside the claim transaction. Finalization uses compare-and-set on the token. Each payload contains the stable outbox event ID, and every internal consumer stores or otherwise enforces deduplication.

### 6.7 Frontend scope contract

Create an application-scoped service container using typed Svelte context. It owns:

- namespace identity and monotonically increasing namespace epoch;
- API client and abort controllers;
- server-state query client;
- feature stores with explicit `start()` and `stop()` lifecycles.

Every namespace-sensitive request captures the namespace and epoch. It may commit a result only if both still match. Namespace changes abort earlier requests and clear scoped queries.

Server state belongs in the query layer. Local stores hold editor/session state that is not a copy of backend authority.

### 6.8 Implemented ownership boundaries

```text
Worker runtime
  claim lifecycle       worker_runtime.py
  build orchestration   builds/build_execution.py + compute_service.py
  event publication     runtime/build_events.py
  healthcheck execution runtime/healthchecks.py
  resource observation  runtime/resource_observation.py
  datasource execution  datasources/execution.py
  protocol mapping      runtime/protocol_mapping.py

Frontend application
  app/namespace lifecycle  services/app-lifecycle.ts
  editor preview state     editor/preview-state.svelte.ts
  chart preparation        charts/preparation.ts
  chart render lifecycle   charts/render-lifecycle.ts
  chart interaction        charts/interaction.ts
  chat transport           api/chat.ts
  chat conversation state  stores/chat.svelte.ts
  chat presentation/layout chat/presentation.ts + chat/panel-layout.svelte.ts

Representation boundaries
  backend compute API      modules/compute/representations.py
  worker protobuf payloads runtime/protocol_mapping.py
  frontend engine display  representations/engine.ts
```

## 7. Required Data and Protocol Changes

### 7.1 Build jobs

Add:

- `claim_token` non-null while active;
- `lease_generation` non-null with a monotonic default;
- `claimed_at`;
- `last_renewed_at`;
- explicit exhausted-attempt outcome or status.

Change claim ordering to:

```text
priority DESC, available_at ASC, created_at ASC, id ASC
```

Define retry policy explicitly:

- whether `max_attempts` includes the first execution;
- which failures consume an attempt;
- whether lease loss consumes an attempt;
- terminal behavior when attempts are exhausted.

### 7.2 Compute requests

Add the same claim fields and a defined attempt policy. Do not use a shared worker ID as the release boundary.

### 7.3 Worker protocol

Claim responses include:

- claim token;
- generation;
- expiry;
- attempt.

Add renewal operations:

- `RenewBuildJobLease`
- `RenewComputeRequestLease`

Progress, completion, failure, and build event requests include the token and generation. Old request shapes are removed in the same release.

### 7.4 Build runs and events

Add:

- `build_runs.next_event_sequence`;
- `build_runs.execution_generation`;
- unique `(build_id, sequence)` constraint if not already present;
- optional unique producer event ID for idempotent retry.

### 7.5 Scheduler

Prefer durable schedule trigger rows over locking schedule definitions. A trigger records:

- schedule ID;
- due time;
- claim fields;
- resulting build ID;
- terminal reconciliation state.

Enforce one logical trigger per `(schedule_id, due_at)` and one active build per trigger.

### 7.6 Datasource mutations

Represent conflicting work with a durable resource key such as:

```text
datasource:{namespace}:{datasource_id}
```

Enforce one active mutation for a resource through a database constraint or fenced resource-lease row. The worker executes Polars/Iceberg operations and sends fenced persistence commands to the backend boundary only where required.

### 7.7 Analysis revisions

Add or standardize:

- `analyses.revision`;
- mandatory expected revision on every mutation;
- unique `(analysis_id, version)` constraint.

History version allocation occurs while holding the analysis row lock or through an atomic counter.

## 8. Workstreams

### Workstream A — Concurrency test harness

Create tests that coordinate real concurrent database sessions with barriers rather than relying on timing sleeps.

Required failing scenarios before implementation:

- lease expires, a second worker reclaims, first worker completes late;
- stale worker emits a progress event after cancellation;
- two producers append build events simultaneously;
- cancellation races with successful finalization;
- worker shutdown occurs while executor code is still active;
- two outbox dispatchers claim overlapping work;
- two schedulers claim the same due trigger;
- two analysis mutations use the same revision;
- two analysis history writers allocate a version;
- namespace A response resolves after switching to namespace B.

Success criterion: each test fails against the old behavior for the intended reason and passes through a database-enforced invariant after remediation.

### Workstream B — Shared lease and state-machine primitives

- Define typed claim identity and transition outcomes.
- Implement reusable claim, renew, release, complete, fail, and cancel compare-and-set helpers.
- Use database time in claim/renew queries.
- Define legal transition graphs per entity.
- Remove direct terminal status assignment methods.
- Add metrics for claim conflicts, renew failures, lease loss, reclaim, and exhausted attempts.

Success criterion: no claimant-owned mutation can succeed with only a row ID or owner ID.

### Workstream C — Atomic build events

- Move sequence allocation to the locked build row. **Completed.**
- Add execution generation validation. **Completed.**
- Fold event projection and insert event/outbox in one transaction. **Completed.**
- Make producer retries idempotent with a producer event ID where RPC retry can duplicate a call.
- Reject worker events after cancellation or lease replacement. **Completed.**
- Test concurrent resource and progress event streams.

Success criterion: event sequences are gap-tolerant if required but unique and strictly increasing; projection state is equivalent to folding the committed event stream.

### Workstream D — Cancellation and finalization use cases

- Create application-level `CancelBuild` and `FinalizeBuild` commands.
- Make each command the sole transaction owner.
- Lock/compare-and-set all authoritative rows.
- Increment execution generation on cancellation.
- Persist terminal event and outbox entry atomically.
- Perform process signalling only after commit.
- Make client retry idempotent.
- Reconcile schedule trigger state in the same finalization transaction or through a durable follow-up outbox command.

Success criterion: no observed database state combines incompatible build, job, and schedule terminal states.

### Workstream E — Worker lifecycle

- Assign a unique token/generation to every active task.
- Renew each claim independently before a conservative fraction of its TTL.
- Stop accepting new work during shutdown.
- Signal cooperative cancellation where supported.
- Drain active executor work up to a defined shutdown deadline.
- Do not release a claim while associated code can still publish.
- After the deadline, stop renewal and let fencing/expiry handle replacement.
- Treat `LeaseLost` as a command to stop publishing and cancel local execution.

Success criterion: shutdown cannot make still-running work publishable under two active claims.

### Workstream F — Outbox

- Add claim token, claim expiry, attempt count, and delivery timestamps.
- Commit claims before delivery.
- Deliver one claimed record at a time or finalize a bounded claimed batch without releasing unrelated ownership.
- Compare-and-set success/failure.
- Include event IDs in notifications.
- Implement consumer deduplication.
- Add recovery of expired dispatch claims and poison-event handling.

Success criterion: duplicate delivery is harmless and concurrent dispatchers never both hold a valid claim to the same event.

### Workstream G — Datasource execution ownership

- Inventory all datasource compute kinds and their persistence needs.
- Move Polars/Iceberg execution from API gRPC handlers into worker-owned modules.
- Replace process-local mutexes with durable resource fencing.
- Separate pure execution result creation from authoritative metadata commit.
- Ensure cancellation and lease loss stop result publication.
- Remove backend execution dependencies after the last operation moves.

Success criterion: multiple API processes remain stateless with respect to data execution, and conflicting datasource mutations are serialized by the database.

### Workstream H — Scheduler

- Materialize due triggers deterministically.
- Claim only due rows with `ORDER BY due_at, id LIMIT n FOR UPDATE SKIP LOCKED`.
- Apply shared lease renewal and fencing.
- Enforce trigger uniqueness.
- Make enqueue/reconciliation idempotent.
- Define misfire, retry, clock-jump, and exhausted-attempt policy.

Success criterion: parallel scheduler processes neither duplicate nor indefinitely block independent due work.

### Workstream I — Analysis concurrency

- Require expected revision on HTTP, gRPC, MCP, and internal mutation commands.
- Use one database compare-and-set update for the analysis revision.
- Allocate history versions atomically and enforce uniqueness.
- Return a typed conflict containing the current revision.
- Keep editor locks as presence/UX only.
- Add concurrent mutation and lock-expiry tests.

Success criterion: two mutations from one base revision cannot both commit.

### Workstream J — Frontend lifecycle and namespace safety

- Introduce typed app service context.
- Remove module-constructor network I/O.
- Eliminate circular store imports through explicit dependencies.
- Centralize namespace epoch and abort handling.
- Route backend server state through the query client.
- Require every custom async store operation to use the same scoped request gate.
- Ignore results from obsolete namespace epochs.
- Test rapid namespace switching with delayed responses.

Success criterion: no async result can mutate state outside the scope in which it started.

### Workstream K — Transaction boundaries

Adopt this layer rule:

| Layer | Responsibility | Transaction behavior |
|---|---|---|
| Transport | Parse/authenticate/map response | Never commits |
| Application use case | Coordinate one business action | Owns transaction |
| Domain policy | Validate transitions/invariants | No I/O |
| Repository | Query and persist aggregates | Flushes, never commits |
| Delivery adapter | Notify/external side effect | Runs after durable commit |

Tasks:

- inventory every `commit()` and `rollback()` call;
- group them by business use case;
- move ownership to application commands;
- remove boolean `commit` parameters;
- make nested services repository-like;
- prohibit external calls inside open database transactions unless the operation is explicitly designed for it.

Success criterion: each mutating entrypoint has one obvious transaction boundary.

### Workstream L — Deterministic ordering

- Add primary-key tie-breakers to all observable SQL ordering.
- Document whether each pipeline operator preserves input order, creates a new deterministic order, or is explicitly unordered.
- Sort group-by output by group keys where output order is observable.
- Define top-k tie behavior; preserve input order with a temporary row index when required.
- Stabilize scheduler and queue selection.
- Add property tests that repeat operations under different partitioning/concurrency.

Success criterion: identical logical inputs and persisted state produce identical observable ordering.

### Workstream M — Structural decomposition

Decompose by ownership and lifecycle, not arbitrary size.

Worker runtime target categories:

- claim lifecycle;
- build execution orchestration;
- event publication;
- resource observation;
- datasource execution;
- protocol mapping.

Frontend target categories:

- app/namespace lifecycle;
- server-state queries;
- editor session state;
- chart data preparation;
- chart renderers;
- chart interaction;
- chat transport;
- chat conversation state;
- chat tool presentation.

Rules:

- one module has one primary reason to change;
- orchestration depends on interfaces, not module-level singletons;
- transport models do not become domain models by convenience;
- mapping between proto, persistence, domain, and frontend representations is explicit;
- generic dictionary payloads remain only at documented extensibility boundaries.

Success criterion: concurrency policy, transaction policy, and lifecycle ownership can be understood without reading UI/rendering or transport-conversion code.

### Workstream N — Verification and documentation

- Make `just verify` non-mutating.
- Check generated protocol files against generation in a temporary directory before modifying checked-in outputs.
- Run formatting in check mode during verification.
- Pin Bun, Python/uv, and other release tool versions exactly.
- Make CI call canonical `just` targets rather than duplicate partial command lists.
- Fail CI when verification changes the worktree.
- Include package-boundary, dependency, environment, generated-file, and warning checks.
- Update runtime progress documents when each invariant is actually enforced.
- Correct stale package paths in README and architecture docs.

Success criterion: a clean checkout either verifies without changes or fails with a precise drift/error report.

### Workstream O — Naming rule adjustment

Replace the broad “Single word names” instruction with:

> Prefer a concise single-word name for a cohesive category that contains multiple related components. Within that category, use intention-revealing names when one word would be ambiguous. Do not shorten names at the cost of ownership, domain meaning, or searchability.

Replace “Unified functions — don't split unless composable” with:

> Keep behavior together when it shares one invariant and lifecycle. Extract a function or component when it forms a reusable operation, isolates a side-effect boundary, or gives an independently testable policy a clear owner.

Update examples to use domain names rather than placeholders such as `foo` and `bar`.

Success criterion: the style guide supports cohesive categories without encouraging vague identifiers or god functions.

## 9. Implementation Phases

### Phase 0 — Correct the source of truth

- [x] Mark distributed runtime progress guarantees as under remediation.
- [x] Adopt this document as the runtime correctness backlog.
- [x] Record the supported production topology during remediation.
- [x] Define temporary operational limits if any P0 race cannot immediately be contained. No uncontained P0 race remains.

Exit criteria:

- documentation no longer claims guarantees that are not database-enforced;
- operators understand current limitations.

### Phase 1 — Freeze behavior with adversarial tests

- [x] Add concurrent-session backend test utilities.
- [x] Add lease expiry and stale completion tests.
- [x] Add event append collision tests.
- [x] Add cancel/finalize race tests.
- [x] Add shutdown-with-active-executor tests.
- [x] Add outbox contention tests.
- [x] Add scheduler contention tests.
- [x] Add analysis lost-update tests.
- [x] Add frontend stale-namespace tests.

Exit criteria:

- every P0/P1 failure mode has a reproducible test;
- tests identify the invariant, not incidental timing.

### Phase 2 — Introduce fenced claim primitives

- [x] Add schema fields to the compact schema creators.
- [x] Add claim identity to build-job and compute-request protocol contracts.
- [x] Implement build-job and compute-request renew operations.
- [x] Require tokens/generations on build-job and compute-request claimant writes.
- [x] Implement typed transition outcomes.
- [x] Define retry/exhaustion policies.
- [x] Instrument lease behavior.

Exit criteria:

- stale build-job and compute-request owners cannot mutate durable state;
- active work renews independently.

### Phase 3 — Make build state atomic

- [x] Add build event counter and execution generation.
- [x] Replace `MAX(sequence) + 1`.
- [x] Combine event append, projection update, and outbox enqueue.
- [x] Implement atomic cancellation.
- [x] Implement fenced atomic finalization.
- [x] Make build and engine-run terminal transitions idempotent and immutable.

Exit criteria:

- concurrent event producers retain all accepted events in one total order;
- cancellation/finalization races have one valid winner and consistent state.

### Phase 4 — Correct runtime lifecycle services

- [x] Redesign worker drain and lease renewal for build jobs and compute requests.
- [x] Redesign outbox claiming and stable delivery identity.
- [x] Implement persistent consumer deduplication and poison-event handling.
- [x] Introduce durable scheduler triggers and fenced claims.
- [x] Add crash/restart integration tests for each service.

Exit criteria:

- process termination and restart cannot bypass fencing;
- all runtime roles can safely scale horizontally.

### Phase 5 — Move execution to the correct owner

- [x] Move datasource operations into workers.
- [x] Add durable datasource resource fencing.
- [x] Remove API process-local execution locks.
- [x] Remove API-side data execution dependencies.

Exit criteria:

- API processes do not execute claimed data workloads;
- conflicting datasource commits are safely serialized.

### Phase 6 — Enforce application concurrency

- [x] Add mandatory analysis revisions.
- [x] Make version allocation atomic.
- [x] Introduce frontend app-scoped services.
- [x] Enforce namespace epoch/abort behavior.
- [x] Eliminate store cycles and import-time I/O.

Exit criteria:

- analysis writes cannot be lost;
- frontend state cannot cross namespace lifecycles.

### Phase 7 — Simplify boundaries

- [x] Centralize transaction ownership in application commands.
- [x] Remove internal `commit` flags from composable runtime operations.
- [x] Extract runtime categories by invariant/lifecycle.
- [x] Extract frontend categories by state ownership and rendering responsibility.
- [x] Consolidate representation mappers.
- [x] Apply deterministic order contracts to runtime queries and order-sensitive pipeline operators.

The naming guidance in `STYLE_GUIDE.md` now treats a concise single word as a category name, while requiring intention-revealing component names and extraction by invariant, lifecycle, or side-effect boundary.

Exit criteria:

- use-case atomicity and dependency direction are apparent from module structure;
- no decomposition is justified only by file length.

### Phase 8 — Harden verification and declare support

- [x] Make verification non-mutating and reproducible.
- [x] Pin toolchain versions.
- [x] Run canonical checks in CI.
- [x] Run multi-process stress and failure-injection suites.
- [x] Update architecture diagrams and runtime progress status.
- [x] Remove temporary operational limits. No temporary containment limits remain.

Exit criteria:

- all acceptance criteria in this document pass;
- distributed topology support is based on verified invariants rather than component presence.

## 10. Migration Strategy

No backward-compatibility or upgrade layer is supported. The database definition is compacted into two creator revisions: one for shared/public state and one for complete tenant state. Runtime claim fields, revision constraints, retry limits, outbox states, and ordering constraints are defined directly in those creators.

Deployment recreates the database from the creator revisions and deploys backend, worker, scheduler, frontend, and protocol as one versioned unit. There are no compatibility columns, active-row backfills, fabricated claim tokens, or incremental legacy migrations.

## 11. Test Matrix

| Dimension | Required cases |
|---|---|
| Processes | 1 and multiple API, worker, scheduler, dispatcher processes |
| Timing | normal, slow execution, lease expiry, renewal boundary |
| Termination | graceful drain, forced process kill, backend restart |
| Ordering | equal priority, equal timestamps, tied top-k values, concurrent events |
| Terminal races | success/cancel, fail/cancel, stale success/new attempt |
| Delivery | notify succeeds then process dies, notify duplicates, consumer restart |
| Database | lock contention, transaction rollback, unique conflict |
| Frontend | rapid namespace switch, logout, component teardown, delayed response |
| Analysis | same revision concurrent writes, version allocation contention |
| Datasource | same resource conflict, different resource parallelism |

Testing rules:

- use barriers/latches for concurrency tests instead of long sleeps;
- assert final durable state and transition outcomes;
- assert the stale actor is rejected;
- repeat contention tests enough to catch ordering assumptions;
- avoid mocks where PostgreSQL locking behavior is the subject;
- retain unit tests for pure transition policies;
- run end-to-end tests through `just test-e2e`.

## 12. Observability Follow-up

The runtime overview currently exposes runtime mode, API identity, worker heartbeats, engine state, and build-job queue state. The dedicated transition and contention counters below remain optional operational follow-up; they are not represented as implemented by the Phase 8 support declaration.

The follow-up observability slice should expose:

- active claims by kind;
- lease renew success/failure;
- expired and reclaimed claims;
- stale/fenced write rejection count;
- attempt exhaustion count;
- build event append conflict/retry count;
- cancellation/finalization conflict count;
- outbox pending, dispatching, failed, expired, and duplicate-consumer counts;
- scheduler due/claimed/misfire/duplicate-prevented counts;
- datasource resource contention;
- analysis revision conflict count;
- worker drain duration and forced-stop count.

Logs for a unit of work include:

- entity ID;
- owner ID;
- claim token in redacted/short form;
- generation;
- attempt;
- transition;
- outcome.

Metrics and logs must distinguish expected contention (`LeaseLost`, `AlreadyTerminal`) from infrastructure errors.

## 13. Release Acceptance Criteria

The remediation is complete only when all statements below are true:

- [x] A stale worker cannot append an event or finalize work after claim replacement.
- [x] Active claims renew and renewal loss stops publication.
- [x] Default retry behavior cannot strand a running job indefinitely.
- [x] Worker shutdown cannot release work while associated execution can still publish.
- [x] Build event sequence allocation is atomic under concurrent producers.
- [x] Build projection equals a fold of committed events.
- [x] Cancellation and finalization are atomic and idempotent.
- [x] Terminal states cannot be overwritten by late writers.
- [x] Outbox dispatch is recoverable and duplicate delivery is harmless outside the documented provider-acceptance/local-receipt crash window.
- [x] Datasource execution occurs in workers and uses durable resource fencing.
- [x] Multiple schedulers claim only due, bounded, totally ordered triggers.
- [x] Analysis mutations require a revision and versions are unique.
- [x] Frontend results cannot cross namespace epochs.
- [x] Every mutating entrypoint has one application-owned transaction.
- [x] Observable queries and pipeline operators define tie ordering.
- [x] Runtime/frontend modules align with invariant and lifecycle ownership.
- [x] Verification is non-mutating and detects generated drift.
- [x] `just verify`, `just test`, and `just test-e2e` pass without warnings.
- [x] Multi-process failure-injection tests pass repeatedly.
- [x] Runtime documentation and architecture diagrams match the implementation.

## 14. Review Gates

Each implementation phase requires:

1. schema/protocol review for invariants and migration safety;
2. concurrency review focused on stale actors, crash points, and transaction boundaries;
3. test review proving the old failure and new enforcement;
4. observability review ensuring conflicts can be diagnosed;
5. documentation update before the phase is marked complete.

Review questions:

- What happens if the process dies before this line?
- What happens if it dies after the external side effect but before commit?
- Which database predicate proves the caller still owns the work?
- Can two actors choose the same next value?
- Is terminal state immutable?
- Does shutdown actually stop execution, or only stop awaiting it?
- Is the order total when primary sort keys tie?
- Can an old frontend request write into a new scope?
- Which layer owns the transaction?
- Is this module cohesive by invariant and lifecycle?

## 15. Recommended Delivery Order

The critical dependency chain is:

```text
adversarial tests
    -> fenced claim primitives
        -> atomic build events
            -> cancellation/finalization
                -> worker lifecycle
                    -> outbox/scheduler/datasource ownership
```

Analysis revisions and frontend namespace safety can proceed after the shared concurrency vocabulary is fixed. Structural decomposition should follow correctness changes so extraction preserves the final invariants instead of moving flawed behavior into more files.

Verification hardening can begin early, but the final distributed-runtime support claim must wait for the complete failure-injection matrix.
