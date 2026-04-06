# Build Scheduling Architecture

## Overview

The system uses a **polling-based scheduler** running as a background asyncio task within the FastAPI application. It supports three trigger types:

1. **Cron-based** (time-based) — most common
2. **Dependency-based** — run after another schedule completes
3. **Event-based** — run when a trigger datasource is updated

---

## Core Components

### 1. Scheduler Loop

The scheduler runs as an **async background task** within the FastAPI process (defined in `backend/main.py`):

```python
async def scheduler_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        # Wait for scheduler_check_interval (default 60 seconds)
        await asyncio.wait_for(stop_event.wait(), timeout=settings.scheduler_check_interval)
        
        # For each namespace, check for due schedules
        due = scheduler_service.get_due_schedules(session)
        
        # Execute due schedules with dependency ordering
```

**Key characteristics:**

- Runs in the same process as the API server (not a separate worker)
- Polls every `SCHEDULER_CHECK_INTERVAL` seconds (default: 60s)
- Processes all namespaces on each iteration
- Uses topological sorting to respect analysis dependencies

### 2. Schedule Model

Located in `backend/modules/scheduler/models.py`:

```python
class Schedule(SQLModel, table=True):
    id: str                           # UUID
    datasource_id: str                # Target output datasource
    cron_expression: str              # Cron syntax (e.g., "0 * * * *")
    enabled: bool = True
    depends_on: str | None           # Dependency on another schedule
    trigger_on_datasource_id: str | None  # Event trigger datasource
    last_run: datetime | None         # When it last ran
    next_run: datetime | None        # When it next runs
```

### 3. Cron Evaluation

Uses the `croniter` library to evaluate cron expressions (`backend/modules/scheduler/service.py`):

```python
def should_run(cron_expr: str, last_run: datetime | None) -> bool:
    if last_run is None:
        return True  # Never run = always due
    naive_last = last_run.replace(tzinfo=None)
    cron = croniter.croniter(cron_expr, naive_last)
    next_run = cron.get_next(datetime)
    now = datetime.now(UTC).replace(tzinfo=None)
    return next_run <= now
```

---

## Trigger Types Explained

### Cron Trigger

- Standard cron expressions (e.g., `0 * * * *` = hourly at minute 0)
- Stored in `cron_expression` field
- Computes `next_run` at creation/update time using `croniter`

### Dependency Trigger (`depends_on`)

- Schedule B can depend on Schedule A
- If B's dependency is due in the same batch but hasn't completed, B is **skipped** and marked as run (to prevent retry storms)
- Example: Run `analytics_export` after `raw_data_refresh`

### Event Trigger (`trigger_on_datasource_id`)

- Triggers when a **source Iceberg datasource** gets updated
- Checks `EngineRun` table for successful `datasource_update` or `datasource_create` events
- Compares event timestamp vs `last_run`

---

## Execution Flow

1. **Polling**: Every 60s, the scheduler loop wakes up
2. **Due Detection**: `get_due_schedules()` returns all enabled schedules where:
   - Cron is due (`should_run()`), OR
   - Trigger datasource has new runs (`_is_triggered_by_datasource()`)
3. **Build Order**: Topological sort respects:
   - Analysis dependencies (upstream tabs run before downstream)
   - Schedule dependencies (`depends_on`)
4. **Execution**: For each due schedule:
   ```python
   result = scheduler_service.run_analysis_build(
       session, 
       analysis_id, 
       datasource_id=target_datasource_id
   )
   ```
5. **Completion**: `mark_schedule_run()` updates `last_run = now` and recomputes `next_run`

---

## Technical Implications

### Advantages

- **Simple**: Single async task, no external dependencies (no Celery/Redis)
- **Self-contained**: Runs within FastAPI lifecycle
- **Flexible**: Three trigger types cover most use cases
- **Namespace-aware**: Iterates over all namespaces per poll

### Limitations & Risks

| Issue | Impact | Mitigation |
|-------|--------|------------|
| **Same-process blocking** | Long-running builds block the scheduler loop, delaying other schedules | Build execution is synchronous — if one build takes 10 minutes, no other schedule runs during that time |
| **No parallelism** | Only one schedule executes at a time | Single-threaded — no concurrent builds |
| **Polling latency** | Max 60s delay between due time and execution | Configurable via `SCHEDULER_CHECK_INTERVAL` |
| **Process-bound** | If FastAPI crashes/loses, scheduler stops | No HA — scheduler only runs in main process |
| **Retry storm risk** | Failed schedules without `depends_on` retry every 60s | Marks as run even on failure to prevent this |
| **No distributed locking** | Multiple instances = duplicate executions | Not designed for multi-instance deployment |

---

## Configuration

In `backend/core/config.py`:

```python
scheduler_check_interval: int = Field(default=60, alias='SCHEDULER_CHECK_INTERVAL')
```

- **Default**: Check every 60 seconds
- **Lower values**: Reduces latency but increases CPU/DB load
- **Higher values**: Better for low-frequency schedules, reduces load

---

## How Schedules Target Analyses

The critical design: **schedules target datasources, not analyses directly**.

1. User creates a schedule for an **output datasource** (one created by an analysis tab)
2. At execution time, the scheduler resolves:
   - Which analysis produced this datasource (`created_by_analysis_id`)
   - Which tab in that analysis produces it (`output.result_id` matches the datasource id)
3. Builds the **latest version** of the analysis (not a stored version)

This means:

- Schedule always uses the current pipeline definition
- Changing an analysis's pipeline automatically affects the next scheduled run
- No need to recreate schedules when analysis changes

---

## Summary

This is a **lightweight, in-process polling scheduler** suitable for single-instance deployments. It's simple to operate but has clear scaling limitations:

- Not designed for high-frequency schedules
- Not designed for distributed processing
- Single point of failure (no HA)

For those requirements, you would need an external queue (Celery/RQ) or a dedicated scheduler service.
