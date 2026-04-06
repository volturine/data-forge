# PRD: Build Preview (Live Progress)

## Overview

Add real-time live preview to the build/compute execution flow, enabling users to see the build progressing in real time — which step is executing, how long each step takes, overall progress, query plan visualization, and resource allocation.

## Problem Statement

Currently, builds execute as a black box. Users trigger a build (`POST /compute/build`) and receive results only after completion. The `BuildsManager` shows historical runs with timing breakdowns and query plans, but only **after** the run finishes. There is no live feedback during execution — no progress bar, no step-by-step status, no resource monitoring. For long-running pipelines with many steps or large datasets, users have no visibility into whether a build is stuck, slow, or progressing normally.

### Current State

| Aspect | Status |
|--------|--------|
| Progress calculation in engine | ✅ Computed (`idx/total_steps`) but only logged |
| Step timings | ✅ Collected but returned only on completion |
| Query plans | ✅ Extracted but returned only on completion |
| Resource allocation | ✅ Configurable (`max_threads`, `max_memory_mb`) but not visible during execution |
| WebSocket | ⚠️ Exists but single-shot (send request → receive result) |
| Live streaming | ❌ Not implemented |

### Target State

| Aspect | Status |
|--------|--------|
| Progress calculation | ✅ Streamed in real time to frontend |
| Step-by-step status | ✅ Current step highlighted, completed steps marked |
| Step timings | ✅ Updated live as each step completes |
| Overall progress bar | ✅ Visual percentage with ETA |
| Query plan | ✅ Shown before execution starts |
| Resource monitoring | ✅ CPU, memory, thread usage shown during execution |
| Build log streaming | ✅ Real-time log output |

## Goals

| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Users see which step is currently executing | Step name and index visible within 1 second of step start |
| G-2 | Visual progress bar with percentage and ETA | Progress updates at least every 2 seconds |
| G-3 | Per-step timing shown live as steps complete | Timing appears within 1 second of step completion |
| G-4 | Query plan visible before and during execution | Plan shown within 2 seconds of build start |
| G-5 | Resource usage visible during build | CPU/memory updated every 5 seconds |
| G-6 | Remote build monitoring from any device | Any authenticated user can view currently running builds in the build monitor with filtering for active builds |

## Non-Goals

- Cancelling individual steps mid-execution (cancellation is whole-build only)
- Step-level retry during execution
- Real-time data preview for intermediate steps during build

## User Stories

### US-1: Live Build Progress Bar

> As a user, I want to see a progress bar that fills up as my build executes, with a percentage and estimated time remaining.

**Acceptance Criteria:**

1. When a build starts, a progress panel appears (inline or as an overlay).
2. Progress bar shows: percentage (0–100%), current step name, elapsed time, estimated time remaining.
3. ETA calculated from average step duration so far.
4. Progress updates smoothly (no jumping from 0% to 100%).
5. On completion: progress bar shows 100% with total duration, then transitions to result view.
6. On failure: progress bar stops at failure point, shows error with failed step highlighted.

### US-2: Step-by-Step Build Visualization

> As a user, I want to see each step in my pipeline light up as it executes, so I know exactly where the build is.

**Acceptance Criteria:**

1. Pipeline step list (or minimap) shown alongside progress.
2. States per step: pending (gray), executing (animated/pulsing), completed (green with duration), failed (red with error), skipped (dimmed).
3. Current step has visual emphasis (border highlight, animation).
4. Completed steps show individual duration.
5. Total steps count shown (e.g., "Step 3 of 8").

### US-3: Query Plan Preview

> As a user, I want to see the Polars query plan before and during execution, so I can understand how my pipeline will be optimized.

**Acceptance Criteria:**

1. Query plan tab in the build preview panel.
2. Shows both optimized and unoptimized plans (toggle).
3. Plan available within 2 seconds of build start (computed lazily before execution).
4. Plan rendered as formatted text with syntax highlighting.
5. Nodes in the plan that correspond to current executing step are highlighted.

### US-4: Resource Monitoring During Build

> As a user, I want to see CPU, memory, and thread usage during build execution, so I can understand resource utilization.

**Acceptance Criteria:**

1. Resource panel in build preview showing: CPU usage (%), memory usage (MB/allocated MB), active threads.
2. Updated every 5 seconds during execution.
3. Historical mini-chart (sparkline) showing resource usage over time during build.
4. Warning indicator if memory usage exceeds 80% of allocated.
5. Engine configuration summary shown: `max_threads`, `max_memory_mb`.

### US-5: Build Log Streaming

> As a user, I want to see build log output in real time, for debugging and monitoring.

**Acceptance Criteria:**

1. Log panel with auto-scrolling output.
2. Log entries include: timestamp, step name, level (info/warn/error), message.
3. Filterable by level (show errors only, show warnings + errors, show all).
4. Log auto-scrolls to bottom; user can scroll up to pause auto-scroll.
5. Copy log to clipboard action.

### US-6: Remote Build Monitoring

> As a user, I want to view and monitor currently running builds from any device, with filtering to see active builds started by any user.

**Acceptance Criteria:**

1. Build monitor page shows all currently running builds across all users.
2. Each running build shows: analysis name, user who started it, current step, progress percentage, elapsed time.
3. Filter panel to filter by: status (running, completed, failed), user, analysis, date range.
4. Builds carry the user who started them — visible in the build list and detail view.
5. Live progress updates via WebSocket for all visible running builds (not just the user's own).
6. Accessible from any authenticated session — no restriction to the session that started the build.

## Technical Design

### Backend

#### WebSocket Enhancement

Upgrade the existing single-shot WebSocket (`/compute/ws`) to a streaming protocol:

```python
# backend/modules/compute/routes.py

@router.websocket("/compute/ws/build")
async def build_stream(websocket: WebSocket):
    """Streaming WebSocket for live build progress."""
    await websocket.accept()

    # Receive build request
    request = await websocket.receive_json()

    # Send query plan immediately
    await websocket.send_json({
        "type": "plan",
        "optimized_plan": plan.optimized,
        "unoptimized_plan": plan.unoptimized,
    })

    # Execute with progress callbacks
    async for event in execute_build_with_progress(request):
        await websocket.send_json(event)

    await websocket.close()
```

#### Progress Event Types

```python
class BuildEvent(BaseModel):
    type: Literal[
        "plan",           # Query plan before execution
        "step_start",     # Step begins executing
        "step_complete",  # Step finished
        "step_failed",    # Step failed
        "progress",       # Overall progress update
        "resources",      # Resource usage snapshot
        "log",            # Log message
        "complete",       # Build finished successfully
        "failed",         # Build failed
    ]

class StepStartEvent(BuildEvent):
    type: Literal["step_start"]
    step_index: int
    step_name: str
    step_type: str
    total_steps: int

class StepCompleteEvent(BuildEvent):
    type: Literal["step_complete"]
    step_index: int
    step_name: str
    duration_ms: int
    row_count: int | None

class ProgressEvent(BuildEvent):
    type: Literal["progress"]
    progress: float  # 0.0 to 1.0
    elapsed_ms: int
    estimated_remaining_ms: int | None
    current_step: str

class ResourceEvent(BuildEvent):
    type: Literal["resources"]
    cpu_percent: float
    memory_mb: float
    memory_limit_mb: float
    active_threads: int
    max_threads: int

class LogEvent(BuildEvent):
    type: Literal["log"]
    level: Literal["info", "warning", "error"]
    message: str
    step_name: str | None
```

#### Engine Progress Callbacks

Modify `PolarsComputeEngine` to emit progress events via a callback mechanism:

```python
# backend/modules/compute/engine.py

class PolarsComputeEngine:
    def execute_job_with_progress(
        self,
        job_id: str,
        pipeline_def: dict,
        progress_callback: Callable[[BuildEvent], None],
    ):
        """Execute job with real-time progress reporting."""
        for idx, step in enumerate(steps):
            progress_callback(StepStartEvent(
                step_index=idx,
                step_name=step["name"],
                step_type=step["type"],
                total_steps=len(steps),
            ))

            result = self._execute_step(step)

            progress_callback(StepCompleteEvent(
                step_index=idx,
                step_name=step["name"],
                duration_ms=step_duration,
                row_count=result.row_count,
            ))
```

Since the compute engine runs in a subprocess, progress events are sent via a dedicated `progress_queue` (multiprocessing.Queue) alongside the existing `result_queue`:

```python
class PolarsComputeEngine:
    def __init__(self):
        self._result_queue = mp.Queue()
        self._progress_queue = mp.Queue()  # NEW: progress events
```

#### Resource Monitoring

```python
# backend/modules/compute/monitor.py

import psutil

async def monitor_engine_resources(
    engine: PolarsComputeEngine,
    interval: float = 5.0,
) -> AsyncIterator[ResourceEvent]:
    """Yield resource snapshots at regular intervals."""
    process = psutil.Process(engine.pid)
    while engine.is_process_alive():
        mem = process.memory_info()
        yield ResourceEvent(
            cpu_percent=process.cpu_percent(interval=1.0),
            memory_mb=mem.rss / (1024 * 1024),
            memory_limit_mb=engine.resource_config.max_memory_mb,
            active_threads=process.num_threads(),
            max_threads=engine.resource_config.max_threads,
        )
        await asyncio.sleep(interval)
```

### Frontend

#### Build Preview Component

New component: `BuildPreview.svelte`

```
components/common/
├── BuildPreview.svelte          # Main build preview container
├── BuildProgressBar.svelte      # Animated progress bar with percentage/ETA
├── BuildStepList.svelte         # Step-by-step status list
├── BuildQueryPlan.svelte        # Query plan viewer
├── BuildResourceMonitor.svelte  # Resource usage charts
└── BuildLogViewer.svelte        # Streaming log output
```

#### Layout

Build preview appears as a panel (dockable right or bottom) when a build is in progress:

```
┌─────────────────────────────────────────────────────┐
│ Build: "Sales Analysis" ─ Step 3 of 8 ─ 37% ─ ETA 45s │
│ ████████████░░░░░░░░░░░░░░░░░░░░░░░  37%           │
├─────────────────────────────────────────────────────┤
│ Tabs: [Steps] [Plan] [Resources] [Logs]             │
├─────────────────────────────────────────────────────┤
│ ✓ 1. Load datasource         120ms                  │
│ ✓ 2. Filter (status='active') 340ms                 │
│ ⟳ 3. Group by region         ···                    │
│ ○ 4. Sort by revenue                                │
│ ○ 5. Top-K (10)                                     │
│ ○ 6. With columns (margin)                          │
│ ○ 7. Plot (bar chart)                               │
│ ○ 8. Export to Iceberg                              │
└─────────────────────────────────────────────────────┘
```

#### WebSocket Integration

```typescript
// frontend/src/lib/api/build-stream.ts

export function connectBuildStream(
    buildRequest: BuildRequest,
    onEvent: (event: BuildEvent) => void,
): WebSocket {
    const ws = new WebSocket(`${WS_BASE}/compute/ws/build`);

    ws.onopen = () => ws.send(JSON.stringify(buildRequest));

    ws.onmessage = (msg) => {
        const event: BuildEvent = JSON.parse(msg.data);
        onEvent(event);
    };

    return ws;
}
```

#### State Management

```typescript
// Build progress store
interface BuildProgress {
    status: 'idle' | 'running' | 'completed' | 'failed';
    progress: number;          // 0.0 to 1.0
    currentStep: string | null;
    currentStepIndex: number;
    totalSteps: number;
    elapsedMs: number;
    estimatedRemainingMs: number | null;
    steps: StepProgress[];
    queryPlan: { optimized: string; unoptimized: string } | null;
    resources: ResourceSnapshot | null;
    logs: LogEntry[];
}
```

### Dependencies

| Package | Version | Ecosystem | Purpose |
|---------|---------|-----------|---------|
| `psutil` | `>=5.9.0` | pip | Process resource monitoring |

### Security Considerations

- WebSocket connections authenticated via existing session/token mechanism.
- Resource monitoring limited to the engine's own process (no system-wide access).
- Log streaming sanitizes any sensitive data (API keys, file paths outside DATA_DIR).
- Rate limiting on WebSocket messages (max 10 events/second to prevent flooding).

## Migration

- No database migration required — this is a new WebSocket endpoint and frontend feature.
- Existing `POST /compute/build` endpoint remains unchanged for backward compatibility.
- Existing `BuildsManager` continues to show historical runs (build preview is for live runs only).

## Rollout Plan

| Phase | Scope | Duration |
|-------|-------|----------|
| 1 | Backend: Progress queue in compute engine | 2 days |
| 2 | Backend: Streaming WebSocket endpoint | 2 days |
| 3 | Backend: Resource monitoring | 1 day |
| 4 | Frontend: BuildPreview component with progress bar | 2 days |
| 5 | Frontend: Step list, query plan viewer | 2 days |
| 6 | Frontend: Resource monitor, log viewer | 2 days |
| 7 | Frontend: WebSocket integration and state management | 2 days |
| 8 | Testing: Long-running builds, failure scenarios, reconnection | 2 days |

## Open Questions

1. Should the build preview replace the current `POST /compute/build` flow entirely, or be opt-in (user chooses "Build with Preview")?
2. Should we support reconnecting to an in-progress build if the browser tab is closed and reopened?
3. How do we handle multi-tab builds (pipeline with multiple tabs executed in sequence)? Show a nested progress view?
4. Should resource monitoring include GPU usage if a GPU-accelerated step is running?
