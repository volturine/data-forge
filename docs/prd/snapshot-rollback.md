# PRD: Snapshot Rollback

## Overview

Enable users to rollback datasources to a previous Iceberg snapshot, restoring the data state to an earlier point in time. This provides a transactional undo mechanism for builds that produced incorrect or undesired results.

## Problem Statement

Data-Forge writes build outputs to Iceberg tables, which natively support time-travel via snapshots. Users can already **view** historical snapshots via the `SnapshotPicker` component and read data at specific snapshot IDs via `scan_iceberg_snapshot()`. However, there is no mechanism to **rollback** — to make a previous snapshot the current (latest) state of a datasource. If a build produces bad data, users must re-run a corrected build to overwrite the output; they cannot simply revert to the last known-good snapshot.

### Current State

| Capability | Status |
|-----------|--------|
| List snapshots | ✅ `GET /compute/iceberg/{id}/snapshots` |
| Read data at snapshot | ✅ `scan_iceberg_snapshot(metadata_path, snapshot_id)` |
| Delete individual snapshot | ✅ `DELETE /compute/iceberg/{id}/snapshots/{snapshot_id}` |
| Rollback to snapshot | ❌ Not implemented |
| Compare snapshots | ✅ `BuildComparisonPanel.svelte` (visual diff) |
| Snapshot metadata | ✅ ID, timestamp, schema_id shown in picker |

## Goals

| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Users can rollback a datasource to any previous snapshot | Data state reverts to selected snapshot within 5 seconds |
| G-2 | Rollback is non-destructive | Rolled-back-from snapshots are preserved (new snapshot created) |
| G-3 | Rollback is auditable | Rollback events logged with user, timestamp, source and target snapshots |
| G-4 | Downstream impact is visible | Users see which analyses/datasources depend on the rolled-back datasource |

## Non-Goals

- Partial rollback (e.g., rollback only certain columns or rows)
- Cross-datasource transactional rollback (atomic rollback of multiple datasources)
- Rollback of analysis pipeline definition (that's version history, separate feature)

## Health Check Integration

The platform has a two-tier health check system that interacts with snapshot transactions:

1. **Critical health checks** (`critical: true`) — These **block** the transaction commit. If a critical health check fails during a build, the data write to the Iceberg table is prevented entirely via a `PipelineExecutionError`. The rolled-back data is never persisted. This is enforced in `compute/service.py` where critical failures are evaluated after health check execution and before the Iceberg write.

2. **Warning health checks** (`critical: false`) — These **allow** the transaction to proceed but mark the build status as `'warning'` instead of `'success'`. The data is written, notifications include the health check summary and details, but no blocking occurs.

Health check results are always persisted to the database for audit purposes regardless of whether the build proceeds or is blocked.

**Rollback and health checks:** When a rollback writes a new snapshot (restoring previous data), the same health check pipeline runs against the restored data. A rollback can be blocked by critical health checks if the historical data no longer passes current health check rules. Users should be warned about this in the rollback confirmation dialog.

## User Stories

### US-1: Rollback Datasource to Previous Snapshot

> As a user, I want to select a previous snapshot of my datasource and make it the current state.

**Acceptance Criteria:**

1. On the datasource detail page, snapshot picker shows rollback action per snapshot.
2. Clicking "Rollback to this snapshot" shows a confirmation dialog with:
   - Current snapshot info (ID, timestamp, row count).
   - Target snapshot info (ID, timestamp, row count).
   - Schema diff if schemas differ between current and target.
   - Warning about downstream dependencies.
3. On confirmation, rollback executes and new "current" snapshot matches target data.
4. The rollback creates a new snapshot (not deleting intermediate snapshots).
5. Success notification with option to view the restored data.

### US-2: View Rollback History

> As a user, I want to see a history of rollback operations on a datasource.

**Acceptance Criteria:**

1. Snapshot list marks rollback-created snapshots with a "rollback" badge.
2. Rollback metadata includes: source snapshot ID, target snapshot ID, user, timestamp, reason (optional).
3. Rollback history visible in datasource detail page and lineage graph.

### US-3: Preview Before Rollback

> As a user, I want to compare the current data with the target snapshot before committing to a rollback.

**Acceptance Criteria:**

1. "Preview Rollback" action opens comparison view (leveraging existing `BuildComparisonPanel`).
2. Shows: row count diff, schema diff, sample data diff.
3. User can proceed with rollback or cancel from the preview.

### US-4: Downstream Impact Warning

> As a user, I want to understand what will be affected if I rollback a datasource.

**Acceptance Criteria:**

1. Before rollback, show list of downstream dependencies:
   - Analyses that use this datasource as input.
   - Datasources produced by those analyses.
   - Schedules that depend on this datasource.
2. Warning severity: informational (downstream exists) or critical (scheduled rebuilds will use rolled-back data).
3. User can still proceed after acknowledging the warning.

## Technical Design

### Backend

#### New Endpoint

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/compute/iceberg/{datasource_id}/rollback` | Rollback to a specific snapshot |
| `GET` | `/api/v1/compute/iceberg/{datasource_id}/rollback-preview` | Preview rollback impact |

#### Rollback Implementation

```python
# backend/modules/compute/iceberg_writer.py (or new file)

async def rollback_to_snapshot(
    datasource_id: str,
    target_snapshot_id: int,
    branch: str = "main",
    reason: str | None = None,
    session: AsyncSession,
) -> RollbackResult:
    """Rollback an Iceberg table to a previous snapshot."""
    # 1. Load current table metadata
    datasource = await get_datasource(session, datasource_id)
    table = load_iceberg_table(datasource.metadata_path)

    # 2. Validate target snapshot exists
    target_snapshot = table.snapshot_by_id(target_snapshot_id)
    if target_snapshot is None:
        raise SnapshotNotFoundError(target_snapshot_id)

    # 3. Read data at target snapshot
    target_data = scan_iceberg_snapshot(
        datasource.metadata_path,
        target_snapshot_id,
    ).collect()

    # 4. Write data as new snapshot (overwrite mode)
    # This preserves all existing snapshots and adds a new one
    write_iceberg(
        table=table,
        data=target_data,
        mode="overwrite",
        snapshot_properties={
            "rollback.source_snapshot": str(current_snapshot_id),
            "rollback.target_snapshot": str(target_snapshot_id),
            "rollback.reason": reason or "",
            "rollback.timestamp": datetime.utcnow().isoformat(),
        },
    )

    # 5. Log rollback event
    await log_rollback_event(
        session=session,
        datasource_id=datasource_id,
        source_snapshot_id=current_snapshot_id,
        target_snapshot_id=target_snapshot_id,
        new_snapshot_id=new_snapshot.snapshot_id,
        reason=reason,
    )

    return RollbackResult(
        datasource_id=datasource_id,
        previous_snapshot_id=current_snapshot_id,
        restored_snapshot_id=target_snapshot_id,
        new_snapshot_id=new_snapshot.snapshot_id,
        row_count=len(target_data),
    )
```

#### Rollback Preview

```python
async def preview_rollback(
    datasource_id: str,
    target_snapshot_id: int,
    session: AsyncSession,
) -> RollbackPreview:
    """Preview the impact of a rollback."""
    # 1. Get current and target snapshot metadata
    current = get_current_snapshot_info(datasource_id)
    target = get_snapshot_info(datasource_id, target_snapshot_id)

    # 2. Compare schemas
    schema_diff = compare_schemas(current.schema, target.schema)

    # 3. Get downstream dependencies
    downstream = await get_downstream_dependencies(session, datasource_id)

    # 4. Get row count diff
    current_count = get_row_count_at_snapshot(datasource_id, current.snapshot_id)
    target_count = get_row_count_at_snapshot(datasource_id, target_snapshot_id)

    return RollbackPreview(
        current_snapshot=current,
        target_snapshot=target,
        schema_diff=schema_diff,
        row_count_diff=target_count - current_count,
        downstream_analyses=downstream.analyses,
        downstream_datasources=downstream.datasources,
        downstream_schedules=downstream.schedules,
    )
```

#### Schemas

```python
class RollbackRequest(BaseModel):
    target_snapshot_id: int
    branch: str = "main"
    reason: str | None = None

class RollbackResult(BaseModel):
    datasource_id: str
    previous_snapshot_id: int
    restored_snapshot_id: int
    new_snapshot_id: int
    row_count: int

class RollbackPreview(BaseModel):
    current_snapshot: SnapshotInfo
    target_snapshot: SnapshotInfo
    schema_diff: SchemaDiff | None
    row_count_diff: int
    downstream_analyses: list[AnalysisRef]
    downstream_datasources: list[DatasourceRef]
    downstream_schedules: list[ScheduleRef]

class SnapshotInfo(BaseModel):
    snapshot_id: int
    timestamp: datetime
    schema_id: int
    row_count: int
    is_rollback: bool = False
    rollback_metadata: dict | None = None
```

### Frontend

#### SnapshotPicker Enhancement

Add rollback action to each snapshot row in `SnapshotPicker.svelte`:

```svelte
<!-- Per-snapshot actions -->
<button onclick={() => startRollback(snapshot.id)} title="Rollback to this snapshot">
    <RotateCcw size={14} />
</button>
```

#### Rollback Confirmation Dialog

New component: `RollbackDialog.svelte`

```
┌─────────────────────────────────────────────┐
│ Rollback Datasource                         │
├─────────────────────────────────────────────┤
│ Current State                               │
│   Snapshot: #1234 (2026-03-15 14:30)       │
│   Rows: 150,000 │ Columns: 12              │
│                                             │
│ Restore To                                  │
│   Snapshot: #1230 (2026-03-14 09:15)       │
│   Rows: 142,000 │ Columns: 12              │
│                                             │
│ ⚠ Schema Change                            │
│   + column "region" (Utf8) added            │
│   - column "area_code" (Int32) removed      │
│                                             │
│ ⚠ Downstream Dependencies (3)              │
│   • Analysis: "Sales Report" (uses as input)│
│   • Analysis: "Regional KPIs" (uses as input│
│   • Schedule: "Daily Sales" (triggers build)│
│                                             │
│ Reason (optional)                           │
│ ┌─────────────────────────────────────────┐ │
│ │ Bad data from vendor feed               │ │
│ └─────────────────────────────────────────┘ │
│                                             │
│            [Cancel]  [Rollback]             │
└─────────────────────────────────────────────┘
```

#### Snapshot List Badge

Snapshots created by rollback show a badge:

```svelte
{#if snapshot.properties?.['rollback.target_snapshot']}
    <Badge variant="outline">rollback</Badge>
{/if}
```

### Dependencies

No new dependencies required. Uses existing Iceberg, Polars, and PyArrow libraries.

### Security Considerations

- Rollback requires same permissions as build (write access to datasource).
- Rollback reason is stored as audit metadata — not user-facing content (no XSS risk).
- Downstream dependency check reads only — does not modify downstream datasources.
- Concurrent rollback prevention: lock mechanism to prevent two rollbacks on the same datasource.

## Migration

- No schema migration needed if rollback metadata is stored in Iceberg snapshot properties (native Iceberg feature).
- Optional: Alembic migration to add `rollback_events` table for audit trail if storing outside Iceberg.

## Rollout Plan

| Phase | Scope | Duration |
|-------|-------|----------|
| 1 | Backend: Rollback endpoint and Iceberg write-back | 2 days |
| 2 | Backend: Rollback preview with downstream dependencies | 2 days |
| 3 | Backend: Audit logging for rollback events | 1 day |
| 4 | Frontend: SnapshotPicker rollback action | 1 day |
| 5 | Frontend: RollbackDialog with confirmation and preview | 2 days |
| 6 | Frontend: Rollback badges in snapshot list | 1 day |
| 7 | Testing: Rollback with schema changes, concurrent access, edge cases | 2 days |

## Open Questions

1. Should rollback be branch-aware (rollback only on a specific branch)?
2. Should we support "rollback and rebuild" — automatically trigger rebuilds of downstream analyses after rollback?
3. Should rollback be reversible (i.e., can you rollback a rollback)?
4. What happens to snapshots between current and target — are they preserved, or should there be an option to prune them?
