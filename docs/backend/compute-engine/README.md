# Compute Engine Documentation

Complete documentation for the Polars compute engine subsystem.

## Overview

The compute engine handles data transformation execution using isolated multiprocessing. Each analysis gets its own subprocess to ensure stability and enable parallel execution.

## Contents

| Document | Description |
|----------|-------------|
| [Architecture](./architecture.md) | Engine architecture and design |
| [Engine](./engine.md) | PolarsComputeEngine implementation |
| [Manager](./manager.md) | ProcessManager lifecycle management |
| [Step Converter](./step-converter.md) | Frontend to backend format conversion |
| [Operations](./operations.md) | Supported Polars operations |
| [Pipeline Execution](./pipeline-execution.md) | Execution flow and DAG processing |

## Key Components

See individual documentation for each component:

- [Engine](./engine.md) - PolarsComputeEngine subprocess implementation
- [Manager](./manager.md) - ProcessManager singleton for lifecycle management
- [Step Converter](./step-converter.md) - Frontend to backend format conversion

## Engine Lifecycle

```
                    spawn_engine()
    (none) ─────────────────────────► IDLE
                                        │
                        execute()       │    60s timeout
                                        ▼
                                     RUNNING ◄────┐
                                        │         │
                        completed       │    more work
                                        ▼         │
                                      IDLE ───────┘
                                        │
                        shutdown()      │
                                        ▼
                                   TERMINATED
```

## IPC Communication

```
MAIN PROCESS                    SUBPROCESS

service.py
    │
    ▼
ProcessManager
    │
    │ command_queue.put({
    │   type: 'execute',
    │   job_id: '...',
    │   config: {...},
    │   steps: [...]
    │ })
    │
    └──────────────────────────► Event Loop
                                      │
                                      ▼
                                 _execute_pipeline()
                                      │
                                      ▼
    ◄──────────────────────────── result_queue.put({
                                      job_id: '...',
                                      status: 'completed',
                                      data: {...}
                                   })
```

## Supported Operations

20+ Polars operations including:

| Category | Operations |
|----------|------------|
| **Selection** | select, drop, rename |
| **Filtering** | filter, limit, sample, topk |
| **Aggregation** | group_by, value_counts |
| **Reshaping** | pivot, unpivot, explode |
| **Joins** | join (self-join) |
| **Transformation** | sort, deduplicate, fill_null |
| **String** | string_transform (20+ methods) |
| **Time Series** | timeseries operations |
| **Expressions** | with_columns, cast, expression |

## Configuration

```python
# core/config.py
engine_idle_timeout: int = 300  # 5 minutes - engines without keepalive are terminated
```

## See Also

- [Engine](./engine.md) - PolarsComputeEngine details
- [Manager](./manager.md) - ProcessManager details
- [Step Converter](./step-converter.md) - Conversion details
- [Architecture](./architecture.md) - Detailed architecture
- [Operations](./operations.md) - All operations
- [Compute Module](../modules/compute.md) - Routes and service
