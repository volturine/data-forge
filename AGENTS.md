# Data-Forge

Local-first no-code data analysis: visual Polars pipelines, Iceberg storage, scheduled builds.

**Stack:** Python 3.14 + FastAPI + uv · SvelteKit 5 (runes) + Bun · Panda CSS · PostgreSQL · Iceberg · protobuf (`packages/protocol`)

## Commands

```bash
just install              # deps + protocol generation
just dev                  # API, worker, scheduler, frontend
just format               # ruff + prettier
just check                # lint/types/protocol
just verify               # format + static checks
just test                 # backend pytest + frontend unit
just test-e2e             # Playwright only via this recipe
just generate-protocol
```

- Frontend: `bun add` / `bun remove` — never hand-edit `package.json`.
- Python: `uv add` / `uv remove` in the package dir — never hand-edit `pyproject.toml`.
- Prefer `just` recipes over ad-hoc scripts.

## Packages

`packages/{backend,worker,scheduler,frontend,protocol}` — no shared Python package.

- Import boundaries: `scripts/check_package_boundaries.py` (e.g. worker ↛ `backend_core`/`modules`).
- Protocol: edit protos → `just generate-protocol` → commit generated code. Never hand-edit `dataforge_protocol` or `frontend/src/lib/protocol`.
- Env: `docker/env/` — see `docs/ENV_VARIABLES.md`.

## Definition of done

Code/config: `just verify` && `just test` && `just test-e2e` before done or review. Markdown-only: skip unless asked.

- Fix failures and warnings immediately (pre-existing ones when you touch the area). Unfixable third-party stub warnings: inline comment why.
- Add backend tests for new/changed backend behavior.

## Docs

| Doc                                                                                           | Use for                                                               |
| --------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| [`STYLE_GUIDE.md`](STYLE_GUIDE.md)                                                            | Code style                                                            |
| [`README.md`](README.md)                                                                      | Overview, architecture                                                |
| [`docs/prd/`](docs/prd/)                                                                      | Product/architecture by status: `implemented/`, `active/`, `backlog/` |
| [`docs/prd/README.md`](docs/prd/README.md)                                                    | PRD index — update on add/move/material change                        |
| [`CONTRIBUTING.md`](CONTRIBUTING.md)                                                          | PR process                                                            |
| [`docs/ENV_VARIABLES.md`](docs/ENV_VARIABLES.md) · [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Env, deploy                                                           |

PRDs go by delivery status, not topic.

## Principles

- Do not preserve backward compatibility. Remove obsolete paths instead of adding compatibility layers, fallbacks, or migrations.
- Choose the simplest implementation that fully meets the current requirements. Avoid speculative abstractions, configuration, and indirection.
- Grow the system in layers. Start from the smallest version that works end to end, and add each new capability on top of a product that already works. Never trade a working product for unfinished complexity.
- Keep components modular and concerns clearly separated.
- Prefer established, well-maintained libraries when they reduce overall complexity or improve reliability. Do not reimplement common functionality without a clear reason.
- Lean on the dependencies already in the project before writing your own implementation or adding packages. Do not assume a library lacks a capability without checking its documentation and types.
- Make architectural decisions for the long term. Do not accept a stopgap that only works for now and is meant to be replaced later.

## Problem solving

- Start from the intended outcome, then trace the behavior across every relevant layer before changing code.
- Form a causal explanation and actively look for evidence that disproves it.
- Fix the cause where the responsibility belongs. Prefer clear ownership and isolation boundaries over patches at the point where symptoms appear.
- When one fix reveals another failure, investigate it independently instead of forcing it into the previous explanation.
- Before finishing, be able to explain the root cause, why the symptoms were misleading, what now prevents recurrence, and what evidence proves the fix.

## Concurrency and runtime lessons

- Runtime claim RPCs must receive one target namespace. Durable lease expiry is the recovery boundary; scanning every namespace or stale worker registry on each claim multiplies control-plane work during a browser burst.
- Namespace wake rows are updated transactionally with durable work and advance a generation. Refresh reads the generation and queue state in one snapshot, scans without holding the marker lock, and may clear the wake only if the generation is unchanged.
- `COMPUTE_WORKERS` is the single runtime capacity budget for concurrent jobs and assigned compute workers. A worker is bound to one exact analysis/datasource identity; queue fairness and its cross-process lease are internal details, not separate public limits.
- Warm workers are the same worker type in the ready-but-unassigned state. `COMPUTE_WARM_WORKERS` controls the extra prestarted reserve; assigning one binds it to an identity and starts its replacement.
- Active worker starts are bounded by `COMPUTE_WORKERS`; unassigned warm starts are bounded by `COMPUTE_WARM_WORKERS`. Do not add a separate host-CPU-derived startup cap; tune capacity from measured load results.
- Shared previews have two identities: the exact analysis RID or datasource RID owns the shared engine, while the deterministic serialized preview command distinguishes transforms, pagination, and resource settings. Coalesce exact commands before engine admission and let a disconnected leader finish when followers still exist.
- Current topology: API processes own HTTP, WebSocket/SSE delivery, durable enqueue-and-wait request paths, and disposable process-local caches/projections/waiters; they are not authoritative for durable runtime work. One fenced `runtime_coordinator.py` owns runtime gRPC and dispatch, durable chat processing, Telegram polling, and the independent durable external email/Telegram delivery lanes. The outbox stores durable delivery metadata; external network delivery runs after database work, outside its transaction. One Docker-owning worker manager owns exact-RID compute containers and the warm reserve. An assigned worker is bound to one analysis or datasource RID; identical full commands share durable results, while distinct commands on that RID execute serially. `WORKERS` only scales API processes; `COMPUTE_WORKERS` and `COMPUTE_WARM_WORKERS` remain the two compute-capacity controls. Do not horizontally replicate the current worker service. See `docs/prd/active/elastic-runtime-scale-out.md` for scale policy and evidence.
- Async/thread policy: keep native async network I/O and waits on their owning event loop. Run synchronous SQLAlchemy work as a complete, short unit that opens, commits/rolls back, and closes its own session in bounded threads; never move a live session between threads or carry an unused session/DB dependency through async compute waits. Offload blocking Docker, storage/catalog, and SMTP operations to bounded threads. Keep parsing and Polars-heavy execution in the isolated compute containers. Native async PostgreSQL notification handling is receive-only; publication remains synchronous DB/thread work.
- API/coordinator LISTEN receivers own a dedicated `psycopg.AsyncConnection` and continuous `notifies()` generator with explicit recovery callbacks. Subscribe before reading the initial snapshot. Recover active compute/build/engine/lock/chat projections and coordinator chat/settings consumers from durable state; build/lock projection reads use batches of at most 128, rather than scanning inactive resources.
- Mutation and cancellation boundaries: datasource updates lock and reread the row before advancing its revision off the API loop. Chat enqueue/deletion share an atomic session-row lock; competing enqueue or deletion with active work returns 409. Typed local chat revocation settles that turn; real SQL or coordinator-epoch failures fail closed. Engine cancellation targets the exact job ID, remembers cancellation before startup, and joins the actual thread before releasing admission. SMTP tests admit one thread and observe its owned future; a deadline during sending leaves provider acceptance uncertain and retains admission until the thread settles.
- Worker/scheduler health probes query PID1's private Unix socket and require actual registration plus fresh progress on every dispatch lane. Database registry presence or an independent heartbeat cannot make a stalled dispatcher healthy. The API `/health/ready` probe checks API dependencies only. Scheduler candidates are processed in ordered batches of 100 with a cursor that advances over non-due rows and fresh locked eligibility checks.
- Private storage GC reuses the durable outbox: `TRACKED → PUBLISHED` retains referenced data; abandoned targets proceed through `AUTHORIZED → DELETED`. Record durable source intents before staging and retirement. Cleanup uses exact managed objects/prefixes and catalog IDs in an independent worker I/O lane, defers busy RIDs, and uses indexed exact source references rather than blob discovery. Ownership transfer invalidates old claims; authorize with fresh PostgreSQL time after locks, and fence late acknowledgements by token/generation. Published snapshot retention and the single-manager topology remain unchanged; no new service or public tunables are introduced.
- The permanent E2E 50-tab probe is a readiness regression test, not proof of unlimited throughput. Capacity claims still require queue/p95 measurements and logs showing no event-loop, lease, database, or engine-slot starvation.
