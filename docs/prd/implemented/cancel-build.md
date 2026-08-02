# PRD: Cancel Build in Progress

> **Status (audited 2026-08-02): Implemented.**
> **Current truth:** Build cancellation is shipped, but the current API/runtime shape differs from this original design doc. Treat the detailed endpoint/process wording below as historical.
> **Portfolio:** [PRD index](../README.md)


## Overview

Allow users to cancel a running build and record the cancellation durably for auditability. In the current runtime, cancellation is coordinated through durable build/build-run state rather than only by killing an in-process engine.

## Problem Statement

Historically, builds could not be stopped once started. That is no longer true in the current product, but the original problem statement is kept here as the motivation for the shipped feature:

- They realize the pipeline configuration is wrong.
- The build is taking much longer than expected.
- They need to free resources for a more urgent build.
- They accidentally triggered a build on the wrong analysis.

The compute engine runs as a spawned Python process managed by `ProcessManager`. Builds can take minutes to hours depending on data size and pipeline complexity. Without cancellation, resources are wasted and users are blocked.

### Current State

| Capability | Status |
|-----------|--------|
| Start a build | ✅ `POST /compute/build` |
| Monitor build progress | ✅ `progress` field on EngineRun, SSE updates |
| Stop a build | ✅ Supported via active-build cancellation endpoints and UI |
| Runtime cancellation | ✅ Durable cancellation state propagates through worker/runtime lifecycle |
| Build status values | `queued`, `running`, `completed`, `failed`, `cancelled` |
| `cancelled` status | ✅ Shipped |

### Shipped State / Remaining Design Notes

| Capability | Status |
|-----------|--------|
| Start a build | ✅ Shipped |
| Monitor build progress | ✅ Shipped |
| Cancel a running build | ✅ Shipped |
| Build status values | `queued`, `running`, `completed`, `failed`, `cancelled` |
| Partial results cleanup | ⚠️ This doc describes the intended cleanup model; current runtime semantics should be verified against the implementation rather than assumed from this historical design section |

## Goals

| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Users can cancel any running build | Build stops within 5 seconds of cancel request |
| G-2 | Clean resource release | Engine process terminated, memory freed, no orphaned processes |
| G-3 | Auditability | Cancelled builds recorded with `CANCELLED` status, timestamp, and cancelling user |
| G-4 | Partial write safety | Incomplete Iceberg writes do not corrupt the datasource |
| G-5 | UI integration | Cancel button visible during build with confirmation |

## Non-Goals

- Pausing and resuming builds (only cancel)
- Cancelling scheduled/queued builds that haven't started (separate from in-progress)
- Automatic cancellation based on duration (see Build Length Tracking PRD for warnings)
- Partial result preservation (cancelled builds produce no output)

## User Stories

### US-1: Cancel a Running Build

> As a user, I want to stop a build that's taking too long or was started by mistake.

**Acceptance Criteria:**

1. During a running build, a "Cancel" button is visible in the build panel.
2. Clicking "Cancel" shows a confirmation dialog: "Cancel this build? Any partial results will be discarded."
3. On confirmation, the build stops within 5 seconds.
4. The build status changes to `CANCELLED`.
5. A toast notification confirms cancellation.
6. The engine process is terminated and resources freed.

### US-2: Cancel from Build History

> As a user, I want to cancel a build from the build history list.

**Acceptance Criteria:**

1. Running builds in the history list show a cancel icon/button.
2. Clicking the cancel icon triggers the same confirmation and cancellation flow.
3. The status updates in real-time (via SSE) to `CANCELLED`.

### US-3: View Cancelled Build Details

> As a user, I want to see details about a cancelled build.

**Acceptance Criteria:**

1. Cancelled builds appear in the history with a distinct visual treatment (icon + color).
2. Build detail shows: cancelled_at timestamp, cancelled_by user, duration until cancellation, last completed step.
3. No result data is shown (partial results discarded).

## Technical Design

### Backend: Cancel Endpoint

```
POST /api/v1/compute/builds/active/{build_id}/cancel
Response: { status: "cancelled", cancelled_at: "2026-04-08T..." }
```

**Implementation:**

```python
async def cancel_build(engine_run_id: UUID, user: User, db: Session):
    run = get_engine_run(db, engine_run_id)

    if run.status != "running":
        raise HTTPException(400, "Only running builds can be cancelled")

    # 1. Signal the engine process to stop
    analysis_id = run.request_json.get("analysis_id")
    terminated = await process_manager.terminate_engine(analysis_id)

    if not terminated:
        # Force kill if graceful termination fails
        await process_manager.kill_engine(analysis_id)

    # 2. Update engine run status
    run.status = "cancelled"
    run.error_message = f"Cancelled by {user.display_name}"
    run.duration_ms = (datetime.utcnow() - run.created_at).total_seconds() * 1000
    db.commit()

    # 3. Clean up partial Iceberg writes
    await cleanup_partial_writes(run)

    # 4. Notify via SSE
    broadcast_build_update(engine_run_id, status="cancelled")
```

### Engine Process Termination

The `ProcessManager` already has process lifecycle management. Extend it:

```python
class ProcessManager:
    async def terminate_engine(self, analysis_id: str) -> bool:
        """Gracefully terminate (SIGTERM) the engine process."""
        process = self._processes.get(analysis_id)
        if not process:
            return False
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
            return True
        except asyncio.TimeoutError:
            return False

    async def kill_engine(self, analysis_id: str) -> None:
        """Force kill (SIGKILL) the engine process."""
        process = self._processes.get(analysis_id)
        if process:
            process.kill()
            await process.wait()
        self._processes.pop(analysis_id, None)
```

### Partial Write Cleanup

When a build is cancelled mid-write:

1. **Iceberg tables**: PyIceberg transactions are atomic — uncommitted writes are automatically discarded. If the process is killed before `commit()`, no snapshot is created.
2. **Temporary files**: Clean up any temp files created during the build step.
3. **Engine run record**: Update status to `cancelled` with duration up to cancellation point.

### Status Model Update

Add `CANCELLED` to the status enum:

```python
class EngineRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"
```

### Frontend Changes

**Build panel (during running build):**
- "Cancel" button with stop icon next to the progress indicator.
- Confirmation dialog on click.
- Button disabled after click to prevent double-cancel.

**Build history list:**
- `CANCELLED` status shown with a distinct icon (e.g., ⊘) and muted color.
- Running builds show a cancel action in the row.

**SSE handling:**
- Listen for `status: "cancelled"` events.
- Update UI state immediately on receipt.

### API Contract

```
POST /api/v1/compute/builds/active/{build_id}/cancel
Authorization: Bearer <token>

Response 200:
{
  "id": "uuid",
  "status": "cancelled",
  "duration_ms": 45230,
  "cancelled_at": "2026-04-08T10:30:00Z",
  "cancelled_by": "user@example.com"
}

Response 400: { "detail": "Only running builds can be cancelled" }
Response 404: { "detail": "Engine run not found" }
```

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Process doesn't terminate gracefully | Low | Medium | SIGTERM → 5s timeout → SIGKILL escalation |
| Partial Iceberg write left in inconsistent state | Low | High | Iceberg transactions are atomic; uncommitted data is discarded |
| Race condition: build completes while cancel is processing | Medium | Low | Check status before and after termination; idempotent |
| Orphaned child processes | Low | Medium | Process group kill; cleanup on app restart |

## Acceptance Criteria

- [x] The active-build cancellation command fences execution and persists the terminal cancelled transition atomically.
- [x] Cancelled builds have `CANCELLED` status in durable build state.
- [x] The build preview exposes cancellation while a build is running.
- [x] Cancellation is idempotent across terminal-state races.
- [x] Build history distinguishes cancelled runs.
- [x] Claim-specific staged output prevents a cancelled attempt from corrupting published output.
- [x] Worker shutdown waits for active execution before releasing its claim.
- [x] DB-backed websocket replay publishes the cancellation transition.
- [x] `just verify`, `just test`, and `just test-e2e` pass.
