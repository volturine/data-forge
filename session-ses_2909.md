# Unexpected repeated GETs to /api/v1/engine-runs after websocket migration

**Session ID:** ses_2909ff442ffe5P6LxreTdgAP2l
**Created:** 4/9/2026, 1:14:18 AM
**Updated:** 4/9/2026, 1:19:55 AM

---

## User

why are we pooling engine runs? 27.0.0.1:47426 - "GET /api/v1/engine-runs?limit=50&offset=0 HTTP/1.1" 200 OK
INFO:     127.0.0.1:47432 - "GET /api/v1/engine-runs?limit=50&offset=0 HTTP/1.1" 200 OK
INFO:     127.0.0.1:47436 - "GET /api/v1/engine-runs?limit=50&offset=0 HTTP/1.1" 200 OK
INFO:     127.0.0.1:47450 - "GET /api/v1/engine-runs?limit=50&offset=0 HTTP/1.1" 200 OK
INFO:     127.0.0.1:47462 - "GET /api/v1/engine-runs?limit=50&offset=0 HTTP/1.1" 200 OK
INFO:     127.0.0.1:47470 - "GET /api/v1/engine-runs?limit=50&offset=0 HTTP/1.1" 200 OK
INFO:     127.0.0.1:34590 - "GET /api/v1/engine-runs?limit=50&offset=0 HTTP/1.1" 200 OK
INFO:     127.0.0.1:34598 - "GET /api/v1/engine-runs?limit=50&offset=0 HTTP/1.1" 200 OK
INFO:     127.0.0.1:34606 - "GET /api/v1/engine-runs?limit=50&offset=0 HTTP/1.1" 200 OK
INFO:     127.0.0.1:34614 - "GET /api/v1/engine-runs?limit=50&offset=0 HTTP/1.1" 200 OK
INFO:     127.0.0.1:34618 - "GET /api/v1/engine-runs?limit=50&offset=0 HTTP/1.1" 200 OK
INFO:     127.0.0.1:34622 - "GET /api/v1/engine-runs?limit=50&offset=0 HTTP/1.1" 200 OK i though we migrated it to websocket

---

## Assistant (Orchestrator · GPT-5.4 · 76.7s)

_Thinking:_

**Investigating polling engine usage**

I need to find out why the polling engine is running. I'll explore the code and follow the orchestrator using the explorer agent. It seems like there might not be any code changes necessary — just an explanation. So, I might use the explain-code skill too. The user is asking why, so I'll inspect the relevant frontend and backend. I want to check the engine's usage and websockets to provide a progress update.

**Tool: task**

**Input:**
```json
{
  "description": "Inspect engine runs polling",
  "prompt": "Explore the repository to answer: why is the frontend repeatedly requesting GET /api/v1/engine-runs?limit=50&offset=0 even though engine runs were thought to be migrated to WebSocket. Find all frontend/backend references to /api/v1/engine-runs, identify any polling intervals or reactive invalidation causing repeated fetches, and explain whether WebSocket is used for engine run updates, only for some subset, or not at all. Return concise findings with file paths, relevant functions/components/stores, and a short explanation of the current behavior.",
  "subagent_type": "explorer"
}
```

**Output:**
```
task_id: ses_2909fdf30ffem5bW3ZDxITWh4W (for resuming to continue this task if needed)

<task_result>
I now have the complete picture. Here are the findings:

---

### Found

**The primary source of repeated `GET /api/v1/engine-runs?limit=50&offset=0`:**

**`BuildsManager.svelte`** — `frontend/src/lib/components/common/BuildsManager.svelte`, line 80–88:
```ts
const query = createQuery(() => ({
    queryKey: ['engine-runs', params],
    queryFn: async () => { ... listEngineRuns(params) },
    refetchInterval: 1000   // ← polls every 1 second, unconditionally
}));
```
`limit` is hardcoded to `50` (line 61) and `offset` defaults to `0` on page 1 — this is the exact request being seen.

**Other REST callers of `listEngineRuns` (no `refetchInterval`, fire on mount/event only):**

| File | Key | `refetchInterval` |
|---|---|---|
| `DatasourceConfigPanel.svelte` L74–83 | `datasource-runs` | none (fires once on mount) |
| `BuildComparisonPanel.svelte` L26–33 | `engine-runs` | none |
| `SnapshotPicker.svelte` L286–306 | imperative call in `loadBuildRuns()` | called on toggle open |

**Backend REST endpoint:**
- `backend/modules/engine_runs/routes.py`, line 36–60: `GET /engine-runs` — plain synchronous REST handler, no WebSocket involvement.

**WebSocket code:**
- `frontend/src/lib/api/build-stream.ts` — three WS connectors:
  - `connectBuildStream` → `ws/build` — for **launching** a new build and streaming its live events
  - `connectBuildsListStream` → `ws/builds` — for **currently active/in-flight builds**, used by `ActiveBuilds.svelte`
  - `connectBuildDetailStream` → `ws/builds/{buildId}` — for drilling into a single active build
- `frontend/src/lib/stores/build-stream.svelte.ts` — `BuildStreamStore` consumes these WS streams

---

### Context

WebSocket and REST serve **two completely separate use cases** and were never meant to replace each other:

- **WebSocket (`/v1/compute/ws/builds`, `ws/build`, `ws/builds/{id}`)** — streams **live, in-flight** build progress: step events, progress ticks, resource metrics. Used by `ActiveBuilds.svelte` (the live monitoring panel) and `OutputNode.svelte` (analysis pipeline nodes while a build is running). These connections close when the build completes.

- **REST `GET /v1/engine-runs`** — queries the **historical database** of completed (and still-running) engine runs. Used for the Builds history table (`BuildsManager`), the datasource "Runs" tab (`DatasourceConfigPanel`), the build comparison picker (`BuildComparisonPanel`), and the snapshot time-travel picker (`SnapshotPicker`).

The 1-second polling from `BuildsManager.svelte` (`refetchInterval: 1000`) is what generates the flood of `GET /api/v1/engine-runs?limit=50&offset=0`. It is unconditional — it polls regardless of whether any build is running. The `BuildStreamStore.applySnapshot` used in the row expansion of `BuildsManager` is only for rendering the **detail** of an already-fetched run (called in `runDetailStore()` at line 313 — it calls `applySnapshot` with static data from the REST response, not from a live WebSocket).

### Related

- `frontend/src/lib/components/common/ActiveBuilds.svelte` — the component that **does** use WebSocket for live builds; has no polling
- `backend/modules/compute/routes.py` lines 456, 518, 549 — the three WebSocket endpoint handlers on the backend
- No WebSocket endpoint exists on the backend that replaces or supplements the `GET /engine-runs` list endpoint — there is no migration in progress; the REST poll is the **only** mechanism for updating the builds history table
</task_result>
```

---

## Assistant (Orchestrator · GPT-5.4 · 6.6s)

_Thinking:_

**Explaining user question**

I think the user is looking for an explanation without needing code changes. I’ll keep it concise and mention the typo between "pooling" and "polling." If the user wants, I could mention that they can change to conditional polling or subscribe to invalidation as alternatives. But it seems like no additional tools are necessary for this response. I want to make sure I provide exactly what the user needs!

It’s still **polling**, not fully migrated to WebSocket.

### What’s happening
The repeated requests come from:

- `frontend/src/lib/components/common/BuildsManager.svelte`

It uses a query with:

- `queryKey: ['engine-runs', params]`
- `listEngineRuns(params)`
- `refetchInterval: 1000`

So the builds/history table is hitting:

- `GET /api/v1/engine-runs?limit=50&offset=0`

**every second**, unconditionally.

### Why WebSocket didn’t replace this
The WebSocket code is for **live active build streaming**, not for the historical engine-runs list.

Current split:

- **WebSocket**
  - `frontend/src/lib/api/build-stream.ts`
  - used for active/in-flight build updates
  - feeds things like `ActiveBuilds.svelte`
- **REST**
  - `backend/modules/engine_runs/routes.py`
  - `GET /engine-runs`
  - used for build history / run listing / comparisons / snapshot picker

So the migration to WebSocket only covered **live build progress**, not the **engine runs list page**.

### Short answer
You’re seeing those logs because **BuildsManager still polls `/engine-runs` once per second**. There is **no WebSocket replacement** for that endpoint right now.

If you want, I can change it to:
- poll **only while a build is active**, or
- stop polling entirely and **invalidate from the existing WebSocket events** instead.

---

## User

i want it as websocket

---

## Assistant (Orchestrator · GPT-5.4 · 3.7s)

_Thinking:_

**Planning code modification**

I need to modify the code, so I must start by exploring what’s needed before planning and implementing through subagents. I also need to use the "todowrite" function for managing multiple steps. Keeping the user informed throughout this process is important, too. To do this effectively, I’ll inspect the relevant files using the explorer. This approach should help me stay organized and ensure I don’t miss anything crucial!

**Tool: todowrite**

**Input:**
```json
{
  "todos": [
    {
      "content": "Explore current engine-runs REST polling and existing build WebSocket architecture",
      "status": "in_progress",
      "priority": "high"
    },
    {
      "content": "Plan WebSocket-based replacement for engine-runs list updates",
      "status": "pending",
      "priority": "high"
    },
    {
      "content": "Implement backend/frontend changes to serve engine-runs list over WebSocket",
      "status": "pending",
      "priority": "high"
    },
    {
      "content": "Run just verify and fix any issues",
      "status": "pending",
      "priority": "high"
    },
    {
      "content": "Review implementation and summarize behavior changes",
      "status": "pending",
      "priority": "medium"
    }
  ]
}
```

**Output:**
```
[
  {
    "content": "Explore current engine-runs REST polling and existing build WebSocket architecture",
    "status": "in_progress",
    "priority": "high"
  },
  {
    "content": "Plan WebSocket-based replacement for engine-runs list updates",
    "status": "pending",
    "priority": "high"
  },
  {
    "content": "Implement backend/frontend changes to serve engine-runs list over WebSocket",
    "status": "pending",
    "priority": "high"
  },
  {
    "content": "Run just verify and fix any issues",
    "status": "pending",
    "priority": "high"
  },
  {
    "content": "Review implementation and summarize behavior changes",
    "status": "pending",
    "priority": "medium"
  }
]
```

---

## Assistant (Orchestrator · GPT-5.4 · 206.4s)

I’ve confirmed the current behavior. Next I’m mapping the existing WebSocket and engine-runs contracts so I can replace polling cleanly rather than layering another workaround on top.

**Tool: task**

**Input:**
```json
{
  "description": "Map backend engine runs",
  "prompt": "Explore the backend implementation for engine runs and compute WebSocket endpoints. I need a concrete implementation map for migrating the engine-runs list from REST polling to WebSocket. Identify: 1) the current GET /api/v1/engine-runs route and service/repository stack it uses, 2) how engine run state changes are persisted/emitted, 3) existing WebSocket patterns/endpoints/messages for build/builds streaming, 4) any pubsub/event bus/broadcast mechanism already in use, and 5) the minimal backend design that best matches existing conventions for exposing engine-runs list updates over WebSocket. Return file paths, key functions/classes, message shapes, and recommended integration points. Read-only only; do not modify files.",
  "subagent_type": "explorer"
}
```

**Output:**
```
task_id: ses_2909dedefffeBVCa35Y7QUn4GC (for resuming to continue this task if needed)

<task_result>
I now have a thorough picture of the entire system. Here's the complete implementation map:

---

## Implementation Map: Engine-Runs List → WebSocket

---

### 1. Current GET /api/v1/engine-runs Route and Service/Repository Stack

**Route registration:**
- `backend/api/v1/router.py:34` — `router.include_router(engine_runs_router)`
- `backend/modules/engine_runs/routes.py:36-60` — `GET ''` (list), `GET /{run_id}`, `GET /compare`

**List endpoint:**
```
GET /api/v1/engine-runs
  → routes.py:38  list_runs()
  → service.py:592 list_engine_runs(session, analysis_id, datasource_id, kind, status, limit, offset)
  → SQLAlchemy: SELECT engine_runs ORDER BY created_at DESC LIMIT/OFFSET
  → [_serialize_run(run) for run in runs]  →  EngineRunResponseSchema
```

**Model:** `backend/modules/engine_runs/models.py` — `EngineRun` (SQLModel, table `engine_runs`)  
**Schemas:** `backend/modules/engine_runs/schemas.py` — `EngineRunResponseSchema`, `EngineRunStatus`, `EngineRunKind`  
**Service:** `backend/modules/engine_runs/service.py` — all CRUD: `create_engine_run`, `update_engine_run`, `apply_live_event`, `list_engine_runs`, `_serialize_run`

---

### 2. How Engine Run State Changes Are Persisted/Emitted

State transitions happen in `backend/modules/compute/service.py` (imported as `engine_run_service`):

| Event | Call site (line) | What it does |
|---|---|---|
| Run created (status=`running`) | `service.py:1166, 1456, 1658, 2107` | `create_engine_run(session, payload)` |
| Live build events (step/progress/resources/log/plan) | `routes.py:127-144` `_emit_active_build_event()` | `apply_live_event(session, engine_run_id, payload)` — mutates `result_json` + `step_timings` + `progress` + `current_step` in-place, does `session.commit()` |
| Run finished (status=`success`/`failed`) | `service.py:1245, 1296, 1513, 1551, 1938, 2002, 2198, 2236` | `update_engine_run(session, run_id, status=..., result_json=..., ...)` |

**The key routing path for live events** (`routes.py:127-144`):
```
engine (subprocess) → emitter callback → _emit_active_build_event(build_id, analysis_id, payload)
  → if payload['engine_run_id']: apply_live_event(session, engine_run_id, payload)   ← DB write
  → build_registry.apply_event(build_id, payload)   ← in-memory update
  → build_registry.publish(build_id, payload)        ← broadcast to WebSocket watchers
```

The `engine_run_id` is embedded into every progress/step/resource event payload at `service.py:1692, 1819, 2394, 2422, 2480, 2919, 2953, 2982`.

**There is no direct broadcast of engine run changes to WebSocket clients** — the DB write happens synchronously in `_emit_active_build_event`, but no registry for engine-run-list watchers exists today.

---

### 3. Existing WebSocket Patterns/Endpoints/Messages for Build Streaming

**Backend endpoints** (`backend/modules/compute/routes.py`):

| Path | Handler | Pattern |
|---|---|---|
| `WS /api/v1/compute/ws` | `compute_websocket()` | Request/response: send one action, receive `started` + `result` or `error`, socket closed |
| `WS /api/v1/compute/ws/build` | `build_stream()` | Stateful: client sends `BuildRequest` on open; server streams build events; server closes when done |
| `WS /api/v1/compute/ws/builds` | `build_list_stream()` | **Subscription only**: client connects, server sends `BuildListSnapshotMessage` then streams raw events to all namespace list-watchers; client sleeps in `asyncio.sleep(3600)` loop |
| `WS /api/v1/compute/ws/builds/{build_id}` | `active_build_stream()` | Subscribe to a specific build's events |
| `WS /api/v1/locks/ws` | `lock_websocket()` | Bi-directional protocol: `watch`/`ping` actions; server pushes `status` updates |

**Message shapes used by `ws/builds`:**
- **Initial message:** `{ type: 'snapshot', builds: ActiveBuildSummary[] }` — defined in `schemas.py:593` `BuildListSnapshotMessage`
- **Ongoing events:** raw event dicts with `type` from `BuildEventType` enum (plan, progress, step_start, step_complete, step_failed, resources, log, complete, failed)
- **Error:** `{ type: 'error', error: str, status_code: int }` — `BuildWebsocketErrorMessage`

**Frontend client for `ws/builds`:** `frontend/src/lib/api/build-stream.ts:80-112` `connectBuildsListStream()` — sends no request on connect, just listens.

---

### 4. Existing Pubsub/Event Bus/Broadcast Mechanism

**`ActiveBuildRegistry`** (`backend/modules/compute/live.py:258-524`):
- In-process singleton `registry = ActiveBuildRegistry()` (module-level)
- `_watchers: dict[build_id, set[WebSocket]]` — per-build subscribers
- `_list_watchers: dict[namespace, set[WebSocket]]` — namespace-level list subscribers
- `asyncio.Lock()` protects all mutations
- `publish(build_id, payload)` — fans out to both build-specific and list-namespace watchers; removes stale sockets
- `add_list_watcher(namespace, ws)` / `remove_list_watcher(namespace, ws)`

**`LockWatcherRegistry`** (`backend/modules/locks/watchers.py`):
- Similar singleton pattern keyed by `(namespace, resource_type, resource_id)`
- Push-on-change: REST endpoints call `_notify_watchers()` after DB mutations

There is **no separate event bus or message broker** — all broadcast is in-process via these two registries.

---

### 5. Minimal Backend Design That Matches Existing Conventions

The system already has **two clean precedents** to model after:

#### Option A — Mirror `ws/builds` (most minimal, ~60 lines)

Add an `EngineRunListRegistry` in `backend/modules/engine_runs/` and a new WebSocket endpoint `WS /api/v1/engine-runs/ws` on the existing `MCPRouter`. The existing `_emit_active_build_event` in `routes.py` is the natural injection point because it's called on every state change.

**New file: `backend/modules/engine_runs/registry.py`**
```python
class EngineRunListRegistry:
    _list_watchers: dict[str, set[WebSocket]]  # keyed by namespace
    _lock: asyncio.Lock

    async def add_watcher(namespace, ws) / remove_watcher(namespace, ws)
    async def broadcast(namespace, payload)   # fans out to all watchers for namespace
```

**New endpoint in `backend/modules/engine_runs/routes.py`:**
```python
@router.websocket('/ws')
async def engine_runs_stream(websocket: WebSocket) -> None:
    # 1. accept + auth (_require_websocket_user pattern from compute/routes.py)
    # 2. registry.add_watcher(namespace, websocket)
    # 3. Send snapshot: { type: 'snapshot', runs: list_engine_runs(session, ...) }
    # 4. asyncio.sleep(3600) loop (identical to ws/builds pattern)
    # finally: registry.remove_watcher(namespace, websocket)
```

**Injection point in `backend/modules/compute/routes.py:_emit_active_build_event()`** — after `apply_live_event` and after the final `update_engine_run` calls, call `await engine_run_registry.broadcast(namespace, { type: 'run_updated', run: _serialize_run(run) })`. Since `apply_live_event` returns the serialized run, the patch is ~3 lines.

**Message shapes (follow `ws/builds` conventions exactly):**
```ts
// Initial snapshot on connect
{ type: 'snapshot', runs: EngineRun[] }

// Per-update event (pushed on every apply_live_event / update_engine_run)
{ type: 'run_updated', run: EngineRun }

// Error frame
{ type: 'error', error: string, status_code: number }
```

#### Integration Points Summary

| File | Change |
|---|---|
| `backend/modules/engine_runs/registry.py` | **New** — `EngineRunListRegistry` singleton (mirror `live.py` list-watcher section) |
| `backend/modules/engine_runs/routes.py` | **Add** `@router.websocket('/ws')` endpoint |
| `backend/modules/compute/routes.py:137-144` | **Inject** `await engine_run_registry.broadcast(...)` after `apply_live_event()` |
| `backend/modules/compute/service.py` (each `update_engine_run` call site) | **Inject** broadcast for terminal state changes (success/failed) — or route through `_emit_active_build_event` if possible |
| `frontend/src/lib/api/engine-runs.ts` | **Add** `connectEngineRunsStream(params, callbacks)` function |
| `frontend/src/lib/components/common/BuildsManager.svelte:80-88` | **Replace** `createQuery(...refetchInterval: 1000)` with WebSocket subscription + reactive `$state` |

#### Why this matches conventions
- `ws/builds` already does exactly this: snapshot on connect + push updates, `asyncio.sleep(3600)` keep-alive, namespace scoping, `MCPRouter`, stale-socket cleanup in the registry's `publish/broadcast` method
- `LockWatcherRegistry` is the precedent for a focused single-resource watcher (only 40 lines)
- `_safe_close_websocket`, `_require_websocket_user`, namespace context (`set_namespace_context`/`reset_namespace`) are already the established helpers in `compute/routes.py` — copy that pattern verbatim
</task_result>
```

**Tool: task**

**Input:**
```json
{
  "description": "Map frontend build streaming",
  "prompt": "Explore the frontend implementation around BuildsManager, build-stream stores/api, and engine-runs consumers. I need a concrete implementation map for replacing engine-runs REST polling with WebSocket updates. Identify: 1) current components that consume listEngineRuns, 2) how BuildsManager currently queries and renders engine runs, 3) existing frontend WebSocket abstractions/patterns for build/builds streams, 4) what data shape the engine-runs list expects, and 5) the minimal frontend design that best matches existing conventions for a WebSocket-backed engine-runs list with pagination/filter params. Return file paths, key functions/components, message shapes, and recommended integration points. Read-only only; do not modify files.",
  "subagent_type": "explorer"
}
```

**Output:**
```
task_id: ses_2909dede1ffeOCGXwU7aubiA2N (for resuming to continue this task if needed)

<task_result>
I now have a complete picture. Here is the full implementation map:

---

## Found

### 1. Components that consume `listEngineRuns`

| Component | File | How it consumes |
|---|---|---|
| `BuildsManager` | `frontend/src/lib/components/common/BuildsManager.svelte:3,80-88` | `createQuery` with `refetchInterval: 1000` — the primary consumer |
| `DatasourceConfigPanel` | `frontend/src/lib/components/datasources/DatasourceConfigPanel.svelte:10,74-83` | `createQuery` (no refetch interval) — loads runs for datasource detail tabs |
| `BuildComparisonPanel` | `frontend/src/lib/components/datasources/BuildComparisonPanel.svelte:3,26-33` | `createQuery` (no refetch interval) — filters to `datasource_create`/`datasource_update` runs |
| `SnapshotPicker` | `frontend/src/lib/components/datasources/SnapshotPicker.svelte:3,288` | Direct `.match()` call on open — one-shot load for time-travel snapshot filtering |

---

### 2. How `BuildsManager` currently queries and renders

**`frontend/src/lib/components/common/BuildsManager.svelte`**

- **Query** (lines 64-88): `createQuery` calls `listEngineRuns(params)` which is a plain REST GET `/v1/engine-runs` with `analysis_id`, `datasource_id`, `kind`, `status`, `limit=50`, `offset`. Refetches every **1000ms**.
- **`params`** is `$derived` from URL search params + local filter state (`kindFilter`, `statusFilter`, `page`).
- **Filtering/sorting** (lines 151-238): `filteredRuns` is a `$derived` that performs client-side text search, date range, branch filter, and `sortRuns()` on top of the REST page. Branch filter reads from `run.request_json.iceberg_options.branch` or `run.result_json.metadata.branch`.
- **Row expansion** (lines 307-329): Each expanded row creates a `BuildStreamStore` and calls `store.applySnapshot(engineRunBuildDetail(run))` — it **does not** open a live WS for individual rows; it reconstructs a static `ActiveBuildDetail` from `result_json`.
- **Pagination** (lines 259-265): Client-side only — `prevPage`/`nextPage` change `page` state, which shifts the `offset` param for the next REST call.

---

### 3. Existing frontend WebSocket abstractions/patterns

**`frontend/src/lib/api/websocket.ts`** — generic WS utility:
- `buildWebsocketUrl(endpoint)` (line 38): Builds `ws://` URL with `namespace`, `client_id`, `client_signature` query params from stores.
- `websocketRequest()` (line 164): Fire-and-forget request/response pattern (send → wait for `result` message → close).

**`frontend/src/lib/api/build-stream.ts`** — three persistent WS connections:
- `connectBuildStream(request, callbacks)` (line 39): Sends build request on open, dispatches `snapshot` vs `BuildEvent` messages. Endpoint: `ws://.../v1/compute/ws/build`.
- `connectBuildsListStream(callbacks)` (line 80): No initial message — server pushes `BuildsSnapshot` then live `BuildEvent`s. Endpoint: `ws://.../v1/compute/ws/builds`.
- `connectBuildDetailStream(buildId, callbacks)` (line 114): Attach to in-flight build. Endpoint: `ws://.../v1/compute/ws/builds/{buildId}`.

**All three** share the same callback shape:
```ts
{ onSnapshot, onEvent, onError, onClose }
```
and return `{ close() }`.

**`frontend/src/lib/stores/build-stream.svelte.ts`** — `BuildStreamStore` class (Svelte 5 `$state` runes):
- `start(request)` opens a WS via `connectBuildStream`.
- `applySnapshot(build: ActiveBuildDetail)` / `applyEvent(event: BuildEvent)` — stateful updaters.
- `close()` / `reset()`.

**`frontend/src/lib/components/common/ActiveBuilds.svelte`** — the gold-standard example for a WS-backed list with filter UI:
- `connect()` / `disconnect()` called from `$effect` with `untrack()` guard (line 139-142).
- Holds `builds = $state<ActiveBuildSummary[]>([])`.
- `applyProgressToSummary()` updates list items on incoming `BuildEvent`.
- Per-row detail streams opened lazily on expand via `connectBuildDetailStream`.

---

### 4. Engine-runs list data shape

**Backend REST response** (`EngineRunResponseSchema` — `backend/modules/engine_runs/schemas.py:77`):
```python
{
  id: str,
  analysis_id: str | None,
  datasource_id: str,
  kind: "preview"|"row_count"|"download"|"datasource_create"|"datasource_update",
  status: "running"|"success"|"failed",
  request_json: dict,
  result_json: dict | null,
  error_message: str | null,
  created_at: datetime,
  completed_at: datetime | null,
  duration_ms: int | null,
  step_timings: dict[str, float],
  query_plan: str | null,
  progress: float,
  current_step: str | null,
  triggered_by: str | null,
  execution_entries: [{ key, label, category, order, duration_ms, share_pct, ... }]
}
```

**Frontend TypeScript mirror**: `frontend/src/lib/api/engine-runs.ts:17-35` (`EngineRun` interface).

**Filter params** (`ListEngineRunsParams`, line 74): `analysis_id?`, `datasource_id?`, `kind?`, `status?`, `limit?`, `offset?`.

There is **no existing WS endpoint for engine-runs**. The backend `modules/engine_runs/routes.py` has only three REST routes (`GET /compare`, `GET /`, `GET /{id}`). The `apply_live_event()` service function (`service.py:429`) already mutates run DB rows as build WS events arrive, so the DB is being kept live — but no WS endpoint exposes the list.

---

### 5. Recommended minimal design for WS-backed engine-runs list

#### Pattern to follow: `connectBuildsListStream` + `ActiveBuilds.svelte`

**New API function** — `frontend/src/lib/api/engine-runs.ts` (or a new `engine-runs-stream.ts`):

```ts
// Message types matching what the new backend endpoint emits
export type EngineRunsListMessage =
  | { type: 'snapshot'; runs: EngineRun[] }
  | { type: 'run_updated'; run: EngineRun }   // patch on progress/complete/failed
  | { type: 'run_created'; run: EngineRun };  // new run appeared

export interface EngineRunsListCallbacks {
  onSnapshot: (runs: EngineRun[]) => void;
  onUpdate: (run: EngineRun) => void;
  onError: (error: string) => void;
  onClose: () => void;
}

export function connectEngineRunsStream(
  params: ListEngineRunsParams,
  callbacks: EngineRunsListCallbacks
): { close: () => void } {
  const url = buildWebsocketUrl('/v1/engine-runs/ws');
  // append params as query: analysis_id, datasource_id, kind, status, limit, offset
  const socket = new WebSocket(url);
  socket.addEventListener('open', () => {
    socket.send(JSON.stringify(params));  // OR encode params in URL
  });
  socket.addEventListener('message', (event) => { ... });
  ...
}
```

**Integration point in `BuildsManager.svelte`**:

Replace the `createQuery` block (lines 80-88) with a reactive WS store following the `ActiveBuilds.svelte` pattern exactly:

1. Remove `createQuery` and `refetchInterval: 1000`.
2. Add `let runs = $state<EngineRun[]>([])` and `let connected = $state(false)`.
3. Add a `connect()` / `disconnect()` pair.
4. In `connect()`, call `connectEngineRunsStream(params, { onSnapshot, onUpdate, ... })`.
5. Wrap in `$effect`:
   ```ts
   $effect(() => {
     // re-derive params reactively
     const p = params; // $derived
     untrack(() => connect(p));
     return () => disconnect();
   });
   ```
6. `onSnapshot` replaces the full `runs` array (initial load + reconnect).
7. `onUpdate` upserts a single run by `id` — matching `applyProgressToSummary` pattern from `ActiveBuilds.svelte:46-61`.

**Key implementation points**:
- The `params` object is already `$derived` (line 64-78) — reconnect logic should depend on it to resend filter params over WS when filters change (or re-open the socket).
- `SnapshotPicker`, `DatasourceConfigPanel`, `BuildComparisonPanel` consume runs one-shot; they don't need WS. Keep REST for them or make WS optional.
- `buildWebsocketUrl` already handles `namespace`/`client_id`/`client_signature` — no extra auth needed.

---

### Related

- `frontend/src/lib/api/websocket.ts` — `buildWebsocketUrl()` utility, use this for URL construction.
- `frontend/src/lib/types/build-stream.ts` — `BuildsSnapshot`, `ActiveBuildSummary` as structural reference for the new `EngineRunsSnapshot` message type.
- `backend/modules/engine_runs/service.py:592` — `list_engine_runs()` is the DB query the new WS endpoint will wrap.
- `backend/modules/engine_runs/service.py:429` — `apply_live_event()` is already called from `compute/routes.py:_emit_active_build_event()` on every build WS event — this means running engine-run DB rows are already being updated in real-time; the WS backend just needs to push those updates to subscribers.
- `backend/modules/compute/live.py:258` — `ActiveBuildRegistry` with its `_list_watchers` fan-out is the direct structural model for a new `EngineRunRegistry` or a simpler pub/sub in `engine_runs/`.
- `frontend/src/lib/utils/engine-run-build-detail.ts` — `engineRunBuildDetail()` converts `EngineRun → ActiveBuildDetail`; this bridge stays intact regardless of WS vs REST.
</task_result>
```

---

## Assistant (Orchestrator · GPT-5.4 · 3.5s)

**Tool: todowrite**

**Input:**
```json
{
  "todos": [
    {
      "content": "Explore current engine-runs REST polling and existing build WebSocket architecture",
      "status": "completed",
      "priority": "high"
    },
    {
      "content": "Plan WebSocket-based replacement for engine-runs list updates",
      "status": "in_progress",
      "priority": "high"
    },
    {
      "content": "Implement backend/frontend changes to serve engine-runs list over WebSocket",
      "status": "pending",
      "priority": "high"
    },
    {
      "content": "Run just verify and fix any issues",
      "status": "pending",
      "priority": "high"
    },
    {
      "content": "Review implementation and summarize behavior changes",
      "status": "pending",
      "priority": "medium"
    }
  ]
}
```

**Output:**
```
[
  {
    "content": "Explore current engine-runs REST polling and existing build WebSocket architecture",
    "status": "completed",
    "priority": "high"
  },
  {
    "content": "Plan WebSocket-based replacement for engine-runs list updates",
    "status": "in_progress",
    "priority": "high"
  },
  {
    "content": "Implement backend/frontend changes to serve engine-runs list over WebSocket",
    "status": "pending",
    "priority": "high"
  },
  {
    "content": "Run just verify and fix any issues",
    "status": "pending",
    "priority": "high"
  },
  {
    "content": "Review implementation and summarize behavior changes",
    "status": "pending",
    "priority": "medium"
  }
]
```

---

## Assistant (Orchestrator · GPT-5.4 · 22904.8s)

Plan:
1. Add a dedicated engine-runs WebSocket endpoint that sends an initial snapshot and pushes run updates.
2. Reuse existing engine-run persistence points so every create/progress/complete transition broadcasts without adding parallel state.
3. Swap `BuildsManager` from 1s query polling to a WS subscription keyed by the existing filters/pagination params.
4. Keep the other one-shot engine-runs consumers on REST unless they also need live updates.

**Tool: task**

**Input:**
```json
{
  "description": "Implement backend WS engine runs",
  "prompt": "Implement the backend side of migrating the engine-runs list to WebSocket in this repository.\n\nRequirements:\n- Follow existing project conventions and existing WebSocket patterns.\n- Add a WebSocket endpoint for engine runs list updates that sends an initial snapshot and then pushes updates.\n- Reuse existing engine run service serialization/query logic rather than duplicating mapping.\n- Broadcast updates when engine runs are created, updated via live events/progress, and completed/failed.\n- Scope broadcasts consistently with existing namespace behavior.\n- Do not remove the existing REST endpoints unless necessary; this is a replacement for BuildsManager polling, not necessarily for all callers.\n- Add/update backend tests as appropriate for new/changed behavior.\n\nSuggested approach based on repo patterns:\n- Create an engine-runs watcher registry similar to existing list watcher patterns.\n- Add `@router.websocket('/ws')` under engine_runs routes, with auth/namespace handling matching compute websockets.\n- Use existing `list_engine_runs`/serialization for the snapshot.\n- Emit messages like snapshot + upsert/update events (or equivalent consistent shape).\n- Hook broadcasts into the existing engine run lifecycle points (create, apply_live_event, terminal update). Prefer clean shared helper(s) over duplicating logic everywhere.\n\nDeliverables:\n- Make the code changes directly.\n- Return a concise summary of changed files, the message protocol you implemented, and any tests added/updated.\n- Mention any frontend contract assumptions the frontend implementer should rely on.",
  "subagent_type": "backend"
}
```

**Error:**
```
Tool execution aborted
```

**Tool: task**

**Input:**
```json
{
  "description": "Implement frontend WS engine runs",
  "prompt": "Implement the frontend side of migrating BuildsManager from REST polling to WebSocket in this repository.\n\nRequirements:\n- Follow existing frontend WebSocket/client/store/component patterns in the repo.\n- Replace BuildsManager's repeated REST polling of engine-runs with a WebSocket subscription.\n- Use the existing filter/pagination params to drive the subscription; reconnect when those params change.\n- Preserve current BuildsManager behavior and UI as much as possible (filters, pagination, row expansion, derived filtering/sorting/search).\n- Keep other engine-runs consumers on REST unless necessary.\n- Use Svelte 5 runes conventions and existing repo patterns.\n- Do not use polling.\n\nAssumptions you can rely on:\n- Backend will expose a WS endpoint for engine runs list updates with initial snapshot + update events.\n- Build the client in a way that matches existing websocket utilities and build-stream conventions.\n- If exact backend message names differ slightly from your first guess, align with existing patterns in the repo and keep the contract minimal/clear.\n\nDeliverables:\n- Make the code changes directly.\n- Return a concise summary of changed files, how BuildsManager now connects/disconnects, and any noteworthy edge cases handled.",
  "subagent_type": "frontend"
}
```

**Output:**
```
task_id: ses_2909aa155ffe78qhLeK5iSSLP1 (for resuming to continue this task if needed)

<task_result>
All 51 tests pass. Here's the summary:

---

## Summary of Changes

### New Files

1. **`frontend/src/lib/api/engine-runs-stream.ts`** — WebSocket API client for engine runs list streaming
   - `connectEngineRunsStream(params, callbacks)` — opens a WS to `/v1/engine-runs/ws` with filter/pagination params encoded as query string parameters
   - Message protocol: `snapshot` (initial full list), `update` (upsert a single run), `remove` (delete a run by ID)
   - Follows the exact pattern of `connectBuildsListStream` in `build-stream.ts` (error/close handling, graceful close with code 1000)

2. **`frontend/src/lib/stores/engine-runs-stream.svelte.ts`** — Reactive Svelte 5 store wrapping the WS client
   - `EngineRunsStreamStore` class with `$state` fields: `runs`, `connected`, `error`
   - `connect(params)` — disconnects any previous connection, opens a new one with the given params
   - `disconnect()` — cleanly closes the WS and resets connection state
   - Handles snapshot → full replacement, update → upsert (in-place or prepend), remove → filter out
   - 10s initial snapshot timeout (matching `BuildStreamStore`'s pattern)
   - Follows the same class-based `$state`/`$derived` pattern as `BuildStreamStore`

3. **`frontend/src/lib/api/engine-runs-stream.test.ts`** — 10 tests for the API client
4. **`frontend/src/lib/stores/engine-runs-stream.test.ts`** — 13 tests for the store

### Modified Files

5. **`frontend/src/lib/components/common/BuildsManager.svelte`** — Migrated from REST polling to WebSocket
   - **Removed**: `createQuery` with `refetchInterval: 1000` for `listEngineRuns` (the polling mechanism)
   - **Added**: `EngineRunsStreamStore` instantiation + `$effect` that tracks `params` and calls `stream.connect(params)`, with cleanup calling `stream.disconnect()`
   - **Loading state**: shows spinner when `!stream.connected && !stream.error && runs.length === 0`
   - **Error state**: shows `stream.error` when error exists and no cached runs
   - **Data**: `runs` derived directly from `stream.runs`
   - Everything else preserved: filters, pagination, row expansion, derived filtering/sorting/search, detail stores, branch picker

### How Connection/Disconnection Works

- The `$effect` captures `params` (a `$derived` object that changes when filter dropdowns, pagination page, or URL search params change)
- When `params` changes, the effect re-runs: `untrack(() => stream.connect(...))` disconnects the old WS and opens a new one with updated query params
- The effect's cleanup function (`return () => stream.disconnect()`) fires on component destroy or before re-run
- This means: changing a filter → closes old WS → opens new WS with new params → receives fresh snapshot

### Edge Cases Handled

- **Graceful degradation**: If the WS errors/closes but we already have data, the data stays visible (error only shown when `runs.length === 0`)
- **Snapshot timeout**: 10s timeout prevents indefinite "loading" state if the backend never responds
- **New runs during session**: `update` events for unknown run IDs are prepended to the list
- **Run removal**: `remove` events filter the run out of the list
- **Reconnect on param change**: Clean disconnect → reconnect cycle prevents stale connections
- **Other engine-runs consumers untouched**: `listEngineRuns()` REST function and all other consumers (SnapshotPicker, DatasourceConfigPanel, BuildComparisonPanel) remain on REST as requested
</task_result>
```

---

