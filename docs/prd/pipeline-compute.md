# Pipeline Compute Architecture

## Overview

The pipeline compute system executes data transformation pipelines against analyses. It uses a **multiprocessing engine architecture** with Polars as the compute engine to process lazyframes through a series of transformation steps.

---

## Core Concepts

### Analysis Pipeline Definition

An analysis contains a `pipeline_definition` with the following structure:

```python
{
    'tabs': [
        {
            'id': 'tab-1',
            'name': 'Export Tab',
            'datasource': {
                'id': 'uuid-of-input-datasource',
                'analysis_tab_id': None,
                'config': {'branch': 'master'}
            },
            'output': {
                'result_id': 'uuid4-of-output-datasource',
                'datasource_type': 'iceberg',
                'format': 'parquet',
                'filename': 'output_name',
                'iceberg': {'namespace': 'outputs', 'table_name': 'table_name', 'branch': 'master'},
                'build_mode': 'full'  # or 'incremental' or 'recreate'
            },
            'steps': [
                {
                    'id': 'step-1',
                    'type': 'filter',
                    'config': {'column': 'status', 'operator': 'eq', 'value': 'active'},
                    'depends_on': []
                },
                {
                    'id': 'step-2',
                    'type': 'select',
                    'config': {'columns': ['id', 'name', 'created_at']},
                    'depends_on': ['step-1']
                }
            ]
        }
    ]
}
```

### Example: Two Tabs with Dependency

This example shows an analysis with two tabs where the second tab uses the first tab as its input source:

```python
{
    'tabs': [
        {
            # TAB 1: Raw data → Cleaned data
            'id': 'tab-clean',
            'name': 'Clean Data',
            'datasource': {
                'id': 'uuid-raw-csv',  # External CSV datasource
                'analysis_tab_id': None,
                'config': {'branch': 'master'}
            },
            'output': {
                'result_id': 'uuid-clean-output',
                'datasource_type': 'iceberg',
                'format': 'parquet',
                'filename': 'clean_data',
                'iceberg': {'namespace': 'outputs', 'table_name': 'clean_data', 'branch': 'master'},
                'build_mode': 'full'
            },
            'steps': [
                {
                    'id': 'remove-nulls',
                    'type': 'filter',
                    'config': {'column': 'email', 'operator': 'is_not_null'},
                    'depends_on': []
                },
                {
                    'id': 'standardize-status',
                    'type': 'with_columns',
                    'config': {
                        'expressions': [
                            {'column': 'status', 'expression': 'col("status").str.to_uppercase()'}
                        ]
                    },
                    'depends_on': ['remove-nulls']
                }
            ]
        },
        {
            # TAB 2: Uses TAB 1's output as its input
            'id': 'tab-aggregate',
            'name': 'Aggregation',
            'datasource': {
                'id': 'uuid-clean-output',  # ← References Tab 1's output!
                'analysis_tab_id': 'tab-clean',         # ← Must match Tab 1's ID
                'config': {'branch': 'master'}
            },
            'output': {
                'result_id': 'uuid-agg-output',
                'datasource_type': 'iceberg',
                'format': 'parquet',
                'filename': 'aggregated',
                'iceberg': {'namespace': 'outputs', 'table_name': 'aggregated', 'branch': 'master'}
            },
            'steps': [
                {
                    'id': 'group-status',
                    'type': 'groupby',
                    'config': {
                        'group_by': ['status'],
                        'aggregations': [
                            {'column': 'id', 'function': 'count', 'alias': 'total'}
                        ]
                    },
                    'depends_on': []
                }
            ]
        }
    ]
}
```

**Key points:**

1. **Tab 1** (`tab-clean`) reads from an external datasource and produces an output
2. **Tab 2** (`tab-aggregate`) sets its `datasource.id` to Tab 1's `output.result_id` (required; datasource object is mandatory)
3. Tab 2 sets `analysis_tab_id` to indicate it's an **analysis-to-analysis** dependency
4. Every tab must include `output.result_id` as a valid UUID v4 (no implicit or non-UUID output IDs)
5. At build time, the system resolves Tab 2's source as a lazyframe query (not a separate table read)

**How it works at runtime:**

When building Tab 2, the compute engine doesn't read Tab 1's output as a separate table. Instead, it:

1. Builds the LazyFrame for Tab 1 (filtering + transformations)
2. Uses that LazyFrame as the input source for Tab 2's pipeline
3. Chains them into a single optimized Polars query

This means **no intermediate data materialization** — both tabs execute as one query plan.

---

### Key Terms
|------|------------|
| **Tab** | A single data transformation path within an analysis. Can have input, steps, and output |
| **Step** | A single transformation operation (filter, select, groupby, etc.) |
| **Pipeline** | Ordered sequence of steps executed as a single Polars LazyFrame query |
| **Engine** | A multiprocessing subprocess that executes pipeline computations |
| **Build** | Full execution of a pipeline to produce output (export) |

---

## Architecture Components

### 1. Engine Manager (`modules/compute/manager.py`)

Manages a pool of compute engines with the following characteristics:

```python
class ProcessManager:
    # Singleton pattern - one manager per application
    _instance: 'ProcessManager | None' = None
    _engines: dict[str, EngineInfo]  # analysis_id -> EngineInfo
```

**Key behaviors:**

- **Reuse**: Engines are reused across requests for the same `analysis_id`
- **Idle cleanup**: Background loop cleans up engines idle for > 30 seconds (configurable)
- **Max concurrent**: Default limit of 10 concurrent engines (configurable via `MAX_CONCURRENT_ENGINES`)
- **Config changes**: If resource config changes, engine is restarted

### 2. Polars Compute Engine (`modules/compute/engine.py`)

Each engine is a **multiprocessing subprocess** with its own memory and thread limits:

```python
class PolarsComputeEngine:
    def __init__(self, analysis_id: str, resource_config: dict | None = None):
        self.analysis_id = analysis_id
        self.resource_config = resource_config or {}
        self._mp_context = mp.get_context('spawn')
        self.process: BaseProcess | None = None
        self.command_queue: mp.Queue = self._mp_context.Queue()
        self.result_queue: mp.Queue = self._mp_context.Queue()
```

**Resource limits:**

| Config | Env Variable | Default | Description |
|--------|--------------|---------|-------------|
| `max_threads` | `POLARS_MAX_THREADS` | 0 (auto) | CPU threads |
| `max_memory_mb` | - | 0 (unlimited) | Memory limit in MB |
| `streaming_chunk_size` | `POLARS_STREAMING_CHUNK_SIZE` | 0 (auto) | Streaming batch size |

### 3. Pipeline Builder (`modules/compute/engine.py` - `_build_pipeline`)

The pipeline builder transforms a list of steps into an optimized Polars LazyFrame:

```python
@staticmethod
def _build_pipeline(
    datasource_config: dict,
    pipeline_steps: list[dict],
    job_id: str,
    additional_datasources: dict[str, dict] | None = None,
) -> tuple[pl.LazyFrame, dict[str, float], list[pl.LazyFrame]]:
    # 1. Load source datasource
    lf = load_datasource(datasource_config)

    # 2. Load additional datasources (for joins)
    right_sources: dict[str, pl.LazyFrame] = {}
    for ds_id, ds_config in additional_datasources.items():
        right_sources[ds_id] = load_datasource(ds_config)

    # 3. Topological sort steps
    ordered_steps = _topological_sort(pipeline_steps)

    # 4. Apply each step sequentially
    for step in ordered_steps:
        lf = _apply_step(lf, step, right_sources)

    return lf, step_timings, plan_frames
```

**Key features:**

- **Dependency resolution**: Uses Kahn's algorithm for topological sorting
- **Cycle detection**: Throws error if pipeline has cycles
- **No merge support**: Multiple dependencies (`len(depends_on) > 1`) not supported

### 4. Operation Handlers (`modules/compute/operations/`)

Each step type has a corresponding handler that implements the transformation:

```python
class OperationHandler(Protocol):
    @property
    def name(self) -> str: ...

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame: ...
```

**Supported Operations (25+):**

| Category | Operations |
|----------|------------|
| **Transform** | `select`, `drop`, `rename`, `with_columns`, `expression` |
| **Filter** | `filter`, `fill_null`, `deduplicate` |
| **Aggregate** | `groupby`, `pivot`, `topk`, `value_counts` |
| **Join** | `join`, `union_by_name` |
| **Reshape** | `sort`, `limit`, `sample`, `unpivot`, `explode` |
| **Strings** | `string_transform` |
| **Time** | `timeseries` |
| **AI** | `ai` |
| **IO** | `export`, `download`, `view`, `notification` |
| **Charts** | `chart` |

---

## Execution Flow

### Preview Flow

```
User Request (preview step X)
         │
         ▼
┌─────────────────────────────────────┐
│ compute/service.py: preview_step()  │
├─────────────────────────────────────┤
│ 1. Resolve pipeline for tab/step    │
│ 2. Apply pipeline steps            │
│ 3. Get engine (reuse or create)    │
│ 4. engine.preview() → job_id       │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│ PolarsComputeEngine.preview()       │
├─────────────────────────────────────┤
│ 1. Build LazyFrame pipeline         │
│ 2. Collect rows (row_limit)        │
│ 3. Return as dict with schema      │
└─────────────────────────────────────┘
         │
         ▼
    Result + EngineRun record
```

### Export/Build Flow

```
Scheduler or User Request (export)
         │
         ▼
┌─────────────────────────────────────┐
│ compute/service.py: export_data()    │
├─────────────────────────────────────┤
│ 1. Get/create engine               │
│ 2. Build pipeline up to target step │
│ 3. engine.export() → job_id        │
│ 4. Write to temp file              │
│ 5. Run health checks (if configured)│
│ 6. Move to final destination       │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│ Iceberg: _write_iceberg_table()    │
├─────────────────────────────────────┤
│ build_mode = 'full'|'incremental'  │
│                                     │
│ full:       CREATE TABLE AS SELECT │
│ incremental: APPEND                 │
│ recreate:   DROP + CREATE          │
└─────────────────────────────────────┘
         │
         ▼
    EngineRun + (optional) HealthCheckResults
```

---

## Pipeline Resolution

### `build_analysis_pipeline_payload()`

This function transforms an analysis definition into a payload suitable for execution:

```python
def build_analysis_pipeline_payload(
    session: Session,
    analysis: Analysis,
    datasource_id: str | None = None
) -> dict:
    # 1. Extract tabs
    tabs = pipeline.get('tabs', [])

    # 2. Build source map (output.result_id → source_config)
    sources: dict[str, dict] = {}
    for tab in tabs:
        output = tab.get('output')
        if not isinstance(output, dict):
            raise ValueError('Analysis pipeline tab missing output configuration')
        result_id = output.get('result_id')
        if not result_id:
            raise ValueError('Analysis pipeline tab missing output.result_id')
        if tab.get('id'):
            sources[str(result_id)] = {
                'source_type': 'analysis',
                'analysis_id': analysis.id,
                'analysis_tab_id': tab['id'],
            }

    # 3. Resolve input datasources
    for tab in tabs:
        datasource = tab.get('datasource')
        if not isinstance(datasource, dict):
            raise ValueError('Analysis pipeline tab datasource must be a dict')
        tab_datasource_id = datasource.get('id')
        if not tab_datasource_id:
            raise ValueError('Analysis pipeline tab missing datasource.id')
        datasource_model = session.get(DataSource, str(tab_datasource_id))
        if datasource_model:
            sources[str(tab_datasource_id)] = {
                'source_type': datasource_model.source_type,
                **datasource_model.config,
            }

    return {
        'analysis_id': analysis.id,
        'tabs': tabs,
        'sources': sources,
    }
```

---

## Engine Lifecycle

### Creation

```python
engine = PolarsComputeEngine(analysis_id, resource_config)
# 1. Spawns subprocess with spawn context
# 2. Sets POLARS_MAX_THREADS env var
# 3. Starts command/result queues
# 4. Runs _run_compute loop
```

### Execution

```python
# Main process sends command to subprocess
job_id = str(uuid.uuid4())
command_queue.put({
    'job_id': job_id,
    'operation': 'preview' | 'export',
    'datasource_config': {...},
    'pipeline_steps': [...],
    ...
})

# Subprocess processes and puts result
result_queue.put({
    'job_id': job_id,
    'data': {...},
    'step_timings': {...},
    'query_plan': '...',
})
```

### Cleanup

- **Idle timeout**: Engines are cleaned up after `engine_idle_timeout` seconds of inactivity
- **Manual shutdown**: On app shutdown, all engines are terminated
- **Unexpected death**: Health check detects dead process, resets state

---

## Build Modes

When exporting to Iceberg, three build modes are supported:

| Mode | Behavior | Use Case |
|------|----------|----------|
| `full` | `CREATE TABLE AS SELECT` | Complete rebuild |
| `incremental` | `INSERT INTO` | Append new data |
| `recreate` | `DROP TABLE` + `CREATE` | Full rebuild with fresh snapshot |

```python
def _write_iceberg_table(lazy: pl.LazyFrame, table_path: Path, build_mode: str) -> Table:
    if build_mode == 'recreate' and catalog.table_exists(identifier):
        catalog.drop_table(identifier)
        return catalog.create_table(identifier, lazy)

    if build_mode == 'incremental':
        return catalog.load_table(identifier).append(lazy)

    # full (default)
    return catalog.create_table(identifier, lazy)
```

---

## Technical Implications

### Advantages

1. **Lazy evaluation**: Polars LazyFrames are not executed until data is needed
2. **Query optimization**: Polars optimizes the entire pipeline before execution
3. **Memory efficiency**: Streaming mode processes data in chunks
4. **Process isolation**: Each engine runs in separate process, preventing memory leaks
5. **Engine reuse**: Engines persist across requests, avoiding spawn overhead

### Limitations

| Issue | Impact | Mitigation |
|-------|--------|------------|
| **No merge steps** | Can't have steps with 2+ dependencies | Pre-merge in single step |
| **Same-process scheduler** | Blocking builds block scheduler | Use separate worker process |
| **No parallel tab execution** | Tabs run sequentially | Not designed for this |
| **Limited to Polars** | Can't use Pandas/Spark | Convert if needed |

---

## Configuration

Key settings in `backend/core/config.py`:

```python
# Engine lifecycle
engine_idle_timeout: int = Field(default=60)  # seconds
max_concurrent_engines: int = Field(default=10)

# Resource limits
polars_max_threads: int = Field(default=0)  # 0 = auto
polars_max_memory_mb: int = Field(default=0)  # 0 = unlimited
polars_streaming_chunk_size: int = Field(default=0)  # 0 = auto

# Job execution
job_timeout: int = Field(default=300)  # seconds
```

---

## Summary

The pipeline compute system is a **multiprocessing Polars engine** that:

1. Executes **lazyframe pipelines** defined in analysis tabs
2. Uses **topological sorting** to order steps by dependencies
3. Runs each analysis in an **isolated subprocess** with configurable resources
4. Supports **25+ transformation operations** via a handler registry
5. Provides **preview** (sampled data) and **export** (full build) operations
6. Integrates with **Iceberg** for persistent output storage
