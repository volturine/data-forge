# Process Manager

Manages lifecycle of Polars compute engines for each analysis.

## Overview

The `ProcessManager` is a singleton that tracks and manages `PolarsComputeEngine` instances. Each analysis gets its own isolated compute subprocess, allowing parallel execution and proper resource cleanup.

**Location**: `backend/modules/compute/manager.py`

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      ProcessManager (Singleton)              │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  _engines: dict[str, EngineInfo]                        ││
│  │  - Key: analysis_id                                     ││
│  │  - Value: EngineInfo {engine, last_activity, status}    ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
         │
         ├── spawn_engine(analysis_id) ──→ EngineInfo
         ├── get_engine(analysis_id) ────→ PolarsComputeEngine
         ├── shutdown_engine(analysis_id)
         └── cleanup_idle_engines()
```

## EngineInfo Class

Tracks state for a single engine:

```python
class EngineInfo:
    engine: PolarsComputeEngine      # The compute engine
    last_activity: datetime          # Last activity timestamp
    status: EngineStatus             # IDLE, RUNNING, or TERMINATED

    def touch(self) -> None:
        """Update last_activity to now."""

    def is_idle_for(self, seconds: int) -> bool:
        """Check if idle duration exceeds threshold."""
```

## ProcessManager Methods

### Lifecycle Management

```python
def spawn_engine(self, analysis_id: str) -> EngineInfo
```

Creates a new engine or returns existing one.

```python
def shutdown_engine(self, analysis_id: str) -> None
```

Terminates engine and removes from tracking.

```python
def shutdown_all(self) -> None
```

Terminates all active engines (used on server shutdown).

### Engine Access

```python
def get_or_create_engine(self, analysis_id: str) -> PolarsComputeEngine
```

Get existing engine or create new one.

```python
def get_engine(self, analysis_id: str) -> PolarsComputeEngine | None
```

Get existing engine (returns None if not found).

```python
def list_engines(self) -> list[str]
```

List all active analysis_ids with engines.

### Status & Monitoring

```python
def get_engine_status(self, analysis_id: str) -> dict
```

Returns status information:

```python
{
    'analysis_id': 'uuid',
    'status': 'idle' | 'running' | 'terminated',
    'process_id': 12345 | None,
    'last_activity': '2024-01-18T12:00:00Z',
    'current_job_id': 'uuid' | None,
}
```

```python
def list_all_engine_statuses(self) -> list[dict]
```

Get status for all engines.

### Keepalive

```python
def keepalive(self, analysis_id: str) -> EngineInfo | None
```

Update last_activity timestamp (called periodically by frontend).

### Cleanup

```python
def cleanup_idle_engines(self) -> list[str]
```

Shutdown engines idle longer than `engine_idle_timeout`. Returns list of cleaned up analysis_ids.

```python
def mark_running(self, analysis_id: str) -> None
```

Mark engine as executing a job.

```python
def mark_idle(self, analysis_id: str) -> None
```

Mark engine as idle after job completion.

## EngineStatus Enum

```python
class EngineStatus(Enum):
    IDLE = 'idle'
    RUNNING = 'running'
    TERMINATED = 'terminated'
```

## Usage

```python
from modules.compute.manager import get_manager

manager = get_manager()

# Get or create engine for analysis
engine = manager.get_or_create_engine('analysis-uuid')

# Check status
status = manager.get_engine_status('analysis-uuid')
print(status['status'])  # 'idle' | 'running'

# List all engines
for aid in manager.list_engines():
    print(aid)

# Cleanup idle engines
cleaned = manager.cleanup_idle_engines()
print(f'Cleaned up: {cleaned}')

# Shutdown all on server close
manager.shutdown_all()
```

## Integration Points

### Called by Compute Routes

| Route | Method | Purpose |
|-------|--------|---------|
| `POST /compute/execute/{id}` | `get_or_create_engine` | Get engine for execution |
| `GET /compute/status/{id}` | `get_engine_status` | Poll job status |
| `POST /compute/shutdown/{id}` | `shutdown_engine` | Terminate engine |
| `POST /compute/keepalive/{id}` | `keepalive` | Extend engine lifetime |

### Configuration

Uses settings from `core/config.py`:

```python
ENGINE_IDLE_TIMEOUT = 300  # Seconds before idle engine is terminated
```

## Thread Safety

The manager is a singleton. Access is thread-safe within the async context (FastAPI uses event loop, not threads).

## See Also

- [Compute Engine](./engine.md) - PolarsComputeEngine implementation
- [Step Converter](./step-converter.md) - Frontend to backend conversion
- [Compute Routes](./routes.md) - API endpoints
