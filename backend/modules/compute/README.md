# Compute Engine Module

Backend compute engine module for running Polars transformations in isolated subprocesses.

## Overview

The compute module provides a robust, production-ready system for executing data analysis pipelines using Polars in isolated subprocesses. This architecture ensures:

- **Process Isolation**: Each analysis runs in its own subprocess, preventing crashes from affecting the main application
- **Concurrent Execution**: Multiple analyses can run simultaneously without blocking
- **Progress Tracking**: Real-time status updates and progress monitoring
- **Resource Management**: Clean shutdown and cleanup of compute resources
- **Error Handling**: Comprehensive error catching and reporting

## Architecture

### Components

1. **schemas.py** - Pydantic models for API request/response validation
   - `ComputeExecuteSchema`: Request schema for executing analysis
   - `ComputeStatusSchema`: Job status tracking
   - `ComputeResultSchema`: Job result with data or error

2. **engine.py** - Core compute engine using multiprocessing
   - `PolarsComputeEngine`: Manages subprocess execution
   - Uses `multiprocessing.Process` for isolation
   - IPC via `multiprocessing.Queue` for commands and results
   - Timeout support (default: 300s)

3. **manager.py** - Singleton process manager
   - `ProcessManager`: Tracks all active compute engines
   - Singleton pattern for global state management
   - Engine lifecycle management (create, get, shutdown)

4. **service.py** - Business logic layer
   - `execute_analysis()`: Execute full pipeline
   - `preview_step()`: Preview single step result
   - `get_job_status()`: Poll job status
   - `cancel_job()`: Cancel running jobs
   - In-memory job tracking with `_job_status` and `_job_results`

5. **routes.py** - FastAPI endpoints
   - `POST /api/v1/compute/execute`: Start analysis
   - `POST /api/v1/compute/preview`: Preview step
   - `GET /api/v1/compute/status/{job_id}`: Check status
   - `GET /api/v1/compute/result/{job_id}`: Get result
   - `DELETE /api/v1/compute/{job_id}`: Cancel job

## Supported Operations

The engine supports the following Polars operations:

### 1. Filter

```json
{
  "operation": "filter",
  "params": {
    "expression": {
      "column": "age",
      "value": 18
    }
  }
}
```

### 2. Select

```json
{
  "operation": "select",
  "params": {
    "columns": ["name", "age", "city"]
  }
}
```

### 3. Group By

```json
{
  "operation": "groupby",
  "params": {
    "group_by": ["category"],
    "aggregations": [
      { "column": "value", "function": "sum" },
      { "column": "value", "function": "mean" },
      { "column": "id", "function": "count" }
    ]
  }
}
```

Supported aggregation functions: `sum`, `mean`, `count`, `min`, `max`

### 4. Sort

```json
{
  "operation": "sort",
  "params": {
    "columns": ["value"],
    "descending": true
  }
}
```

### 5. Rename

```json
{
  "operation": "rename",
  "params": {
    "mapping": {
      "old_name": "new_name"
    }
  }
}
```

### 6. With Columns (Add Columns)

```json
{
  "operation": "with_columns",
  "params": {
    "expressions": [
      { "name": "new_col", "type": "literal", "value": 100 },
      { "name": "copy_col", "type": "column", "column": "existing" }
    ]
  }
}
```

### 7. Drop

```json
{
  "operation": "drop",
  "params": {
    "columns": ["col1", "col2"]
  }
}
```

## Usage Example

### 1. Execute Analysis

```bash
curl -X POST http://localhost:8000/api/v1/compute/execute \
  -H "Content-Type: application/json" \
  -d '{
    "datasource_id": "uuid-of-datasource",
    "pipeline_steps": [
      {
        "name": "Filter adults",
        "operation": "filter",
        "params": {
          "expression": {"column": "age", "value": 18}
        }
      },
      {
        "name": "Select columns",
        "operation": "select",
        "params": {
          "columns": ["name", "age", "city"]
        }
      }
    ]
  }'
```

Response:

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "progress": 0.0,
  "current_step": null,
  "error_message": null,
  "process_id": 12345
}
```

### 2. Check Status

```bash
curl http://localhost:8000/api/v1/compute/status/{job_id}
```

Response:

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "running",
  "progress": 0.5,
  "current_step": "Select columns",
  "error_message": null,
  "process_id": 12345
}
```

### 3. Get Result

```bash
curl http://localhost:8000/api/v1/compute/result/{job_id}
```

Response:

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "data": {
    "schema": {
      "name": "String",
      "age": "Int64",
      "city": "String"
    },
    "row_count": 1500,
    "sample_data": [
      { "name": "Alice", "age": 25, "city": "NYC" },
      { "name": "Bob", "age": 30, "city": "LA" }
    ]
  },
  "error": null
}
```

### 4. Preview Step

```bash
curl -X POST http://localhost:8000/api/v1/compute/preview \
  -H "Content-Type: application/json" \
  -d '{
    "datasource_id": "uuid-of-datasource",
    "pipeline_steps": [...],
    "step_index": 0
  }'
```

### 5. Cancel Job

```bash
curl -X DELETE http://localhost:8000/api/v1/compute/{job_id}
```

## Key Design Decisions

### 1. Multiprocessing vs Threading

- **Choice**: `multiprocessing.Process`
- **Reason**: True parallelism, process isolation, no GIL contention
- **Tradeoff**: Higher memory overhead, IPC complexity

### 2. IPC Mechanism

- **Choice**: `multiprocessing.Queue`
- **Reason**: Thread-safe, built-in serialization, simple API
- **Tradeoff**: Limited to pickle-able objects

### 3. Job Tracking

- **Choice**: In-memory dictionaries (`_job_status`, `_job_results`)
- **Reason**: Fast access, no database overhead for transient data
- **Tradeoff**: Lost on server restart (could be enhanced with Redis/DB)

### 4. Engine Lifecycle

- **Choice**: Singleton ProcessManager with per-datasource engines
- **Reason**: Efficient resource reuse, centralized management
- **Tradeoff**: Requires explicit cleanup

### 5. Progress Reporting

- **Choice**: Push updates via result_queue during execution
- **Reason**: Real-time feedback, non-blocking status checks
- **Tradeoff**: Polling required on client side

### 6. Timeout Handling

- **Choice**: 300s default timeout per execution
- **Reason**: Prevent indefinite hangs, resource cleanup
- **Tradeoff**: May need adjustment for large datasets

### 7. Error Strategy

- **Choice**: Catch all exceptions, return error status
- **Reason**: Prevent subprocess crashes, clear error reporting
- **Tradeoff**: Some error context may be lost

## File Structure

```
modules/compute/
├── __init__.py          # Module exports
├── schemas.py           # Pydantic models (44 lines)
├── engine.py            # Core compute engine (269 lines)
├── manager.py           # Process manager singleton (45 lines)
├── service.py           # Business logic (154 lines)
├── routes.py            # API endpoints (100 lines)
├── EXAMPLES.py          # Usage examples and reference
└── README.md            # This file
```

## Integration

The compute router is registered in `main.py`:

```python
from modules.compute import router as compute_router

app.include_router(compute_router)
```

## Future Enhancements

1. **Persistent Job Storage**: Store jobs in database for restart recovery
2. **Distributed Execution**: Support for multi-server compute clusters
3. **Resource Limits**: CPU/memory constraints per job
4. **Advanced Operations**: More Polars operations (join, pivot, window functions)
5. **Streaming Results**: Stream large results instead of buffering
6. **Job Scheduling**: Queue system for managing concurrent jobs
7. **Caching**: Cache intermediate results for repeated steps
8. **Monitoring**: Metrics and logging for job execution

## Notes

- The engine currently uses simple equality filtering - could be extended for complex expressions
- Sample data limited to 100 rows to prevent memory issues
- Each datasource can have one active engine at a time
- Preview mode uses a separate temporary engine that auto-cleans up
- All subprocess communication uses pickle serialization

## Dependencies

- `polars`: DataFrame operations
- `multiprocessing`: Subprocess isolation
- `fastapi`: Web framework
- `pydantic`: Data validation
- `sqlalchemy`: Database access (for datasource metadata)
