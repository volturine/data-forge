# Polars Compute Engine

Executes data transformation pipelines using Polars LazyFrames in an isolated subprocess.

## Overview

The `PolarsComputeEngine` runs each analysis in a separate subprocess, providing:
- **Isolation**: One process per analysis prevents cross-contamination
- **Parallelism**: Multiple analyses can run simultaneously
- **Resource Management**: Processes can be terminated independently
- **Lazy Evaluation**: Polars LazyFrame for memory-efficient processing

**Location**: `backend/modules/compute/engine.py`

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Main Process (FastAPI)                           │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ PolarsComputeEngine                                            │ │
│  │ - analysis_id: str                                            │ │
│  │ - process: mp.Process | None                                  │ │
│  │ - command_queue: mp.Queue                                     │ │
│  │ - result_queue: mp.Queue                                      │ │
│  └───────────────────────────────────────────────────────────────┘ │
│         │                    IPC (multiprocessing)                │
│         ▼                                                          │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │                    Subprocess (_run_compute)                   │ │
│  │  ┌─────────────────────────────────────────────────────────┐  │ │
│  │  │                    Compute Loop                          │  │ │
│  │  │  while True:                                             │  │ │
│  │  │    cmd = queue.get()                                     │  │ │
│  │  │    if cmd.type == 'shutdown': break                     │  │ │
│  │  │    if cmd.type == 'execute':                             │  │ │
│  │  │      result = _execute_pipeline(...)                     │  │ │
│  │  │      queue.put(result)                                   │  │ │
│  │  └─────────────────────────────────────────────────────────┘  │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

## Public API

### Constructor

```python
engine = PolarsComputeEngine(analysis_id: str)
```

Creates an engine instance (doesn't start the subprocess).

### Methods

```python
def start(self) -> None
```

Start the compute subprocess. Idempotent - safe to call multiple times.

```python
def execute(self, datasource_config: dict, pipeline_steps: list[dict]) -> str
```

Execute a pipeline. Returns job_id for polling.

```python
def get_result(self, timeout: float = 1.0) -> dict | None
```

Get result from result queue. Non-blocking by default.

```python
def shutdown(self) -> None
```

Terminate the subprocess and clean up resources.

## Usage Pattern

```python
from modules.compute.engine import PolarsComputeEngine

# Create engine
engine = PolarsComputeEngine('analysis-uuid')

# Execute pipeline
datasource = {
    'source_type': 'file',
    'file_path': '/data/input.csv',
    'file_type': 'csv',
}
pipeline = [
    {
        'id': 'step-1',
        'type': 'filter',
        'config': {'conditions': [{'column': 'age', 'operator': '>', 'value': 18}]},
        'depends_on': [],
    },
    {
        'id': 'step-2',
        'type': 'select',
        'config': {'columns': ['name', 'age']},
        'depends_on': ['step-1'],
    },
]

job_id = engine.execute(datasource, pipeline)

# Poll for results
while True:
    result = engine.get_result(timeout=1.0)
    if result:
        if result['status'] == 'completed':
            print(result['data'])
            break
        elif result['status'] == 'failed':
            print(f'Error: {result["error"]}')
            break
    # else: continue polling
```

## Pipeline Execution

### Input Format

```python
{
    'datasource_config': {
        'source_type': 'file' | 'database',
        'file_path': str,
        'file_type': 'csv' | 'parquet' | 'json' | 'ndjson' | 'excel',
        # or for database:
        'connection_string': str,
        'query': str,
    },
    'pipeline_steps': [
        {
            'id': str,
            'type': str,  # filter, select, groupby, etc.
            'config': dict,
            'depends_on': list[str],  # step ids
        },
        ...
    ],
}
```

### Output Format

```python
{
    'job_id': str,
    'status': 'completed' | 'running' | 'failed',
    'progress': float,  # 0.0 to 1.0
    'current_step': str | None,
    'data': {
        'schema': {column: dtype},
        'row_count': int,
        'sample_data': list[dict],  # first 5000 rows
    },
    'error': str | None,
}
```

### Progress Updates

During execution, intermediate results are sent:

```python
{
    'job_id': str,
    'status': 'running',
    'progress': 0.25,  # 25% complete
    'current_step': 'Filtering',
    'error': None,
}
```

## Supported Operations

| Operation | Description |
|-----------|-------------|
| `filter` | Filter rows by conditions |
| `select` | Choose columns |
| `groupby` | Group and aggregate |
| `sort` | Sort by columns |
| `rename` | Rename columns |
| `with_columns` | Add/transform columns |
| `drop` | Remove columns |
| `pivot` | Pivot wide to long |
| `unpivot` | Unpivot long to wide |
| `join` | Join dataframe with itself |
| `fill_null` | Fill null values |
| `deduplicate` | Remove duplicate rows |
| `explode` | Explode list columns |
| `sample` | Sample random rows |
| `limit` | Take first N rows |
| `topk` | Get top K rows |
| `null_count` | Count nulls per column |
| `value_counts` | Get value frequencies |
| `timeseries` | Time-based operations |
| `string_transform` | String manipulations |
| `view` | Passthrough for preview |
| `export` | Passthrough (handled by export endpoint) |

### Filter Operators

| Operator | Polars Expression |
|----------|-------------------|
| `=` / `==` | `col == value` |
| `!=` | `col != value` |
| `>` | `col > value` |
| `<` | `col < value` |
| `>=` | `col >= value` |
| `<=` | `col <= value` |
| `contains` | `col.str.contains(value)` |
| `starts_with` | `col.str.starts_with(value)` |
| `ends_with` | `col.str.ends_with(value)` |

### Aggregation Functions

| Function | Description |
|----------|-------------|
| `sum` | Sum of values |
| `mean` | Average value |
| `count` | Count of rows |
| `min` | Minimum value |
| `max` | Maximum value |

## Data Loading

### File Types

```python
# CSV
pl.scan_csv(file_path)

# Parquet
pl.scan_parquet(file_path)

# NDJSON
pl.scan_ndjson(file_path)

# Excel
pl.read_excel(file_path).lazy()

# JSON
pl.read_json(file_path).lazy()
```

### Database

```python
pl.read_database(query, connection_string).lazy()
```

## Datasource Configuration

### File Datasource

```python
{
    'source_type': 'file',
    'file_path': '/path/to/data.csv',
    'file_type': 'csv',  # or parquet, json, ndjson, excel
}
```

### Database Datasource

```python
{
    'source_type': 'database',
    'connection_string': 'sqlite:///data.db',
    'query': 'SELECT * FROM users',
}
```

## Lazy Evaluation Benefits

1. **Memory Efficiency**: Data not loaded until `.collect()`
2. **Query Optimization**: Polars optimizes the full pipeline
3. **Streaming**: Can handle datasets larger than memory

## Dependency Resolution

The engine topologically sorts pipeline steps:

```python
# Input: steps with depends_on
step_a = {'id': 'a', 'depends_on': []}
step_b = {'id': 'b', 'depends_on': ['a']}
step_c = {'id': 'c', 'depends_on': ['a']}

# Sorted execution order: [a, b, c] or [a, c, b]
```

## Result Limiting

- Maximum 5000 rows returned in `sample_data`
- Full schema always included
- `row_count` shows total rows

## Error Handling

### Step Conversion Error

```python
{
    'status': 'failed',
    'error': 'Step conversion failed: ...',
}
```

### Pipeline Cycle Error

```python
{
    'status': 'failed',
    'error': 'Pipeline contains a cycle...',
}
```

### Unsupported Operation

```python
{
    'status': 'failed',
    'error': 'Unsupported operation: ...',
}
```

## Subprocess Communication

### Command Queue

```python
{'type': 'execute', 'job_id': str, ...}
{'type': 'shutdown'}
```

### Result Queue

```python
{'job_id': str, 'status': str, 'progress': float, ...}
```

## Shutdown Behavior

1. Sends shutdown command to subprocess
2. Waits up to 5 seconds for graceful exit
3. Terminates process if still alive
4. Joins process (waits up to 2 seconds)
5. Kills process if still alive

## See Also

- [Manager](./manager.md) - Process lifecycle management
- [Step Converter](./step-converter.md) - Format conversion
- [Operations](./operations.md) - Supported operations reference
- [Pipeline Execution](./pipeline-execution.md) - Execution flow
