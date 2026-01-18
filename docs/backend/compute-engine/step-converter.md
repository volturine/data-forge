# Step Converter

Converts frontend pipeline step format to backend engine format.

## Overview

The `step_converter` module handles schema translation between the frontend UI and backend Polars engine. Frontend uses camelCase and nested structures; backend uses snake_case and flat parameters.

**Location**: `backend/modules/compute/step_converter.py`

## Format Conversion

### Frontend Format

```python
{
    'id': 'step-uuid',
    'type': 'filter',
    'config': {
        'conditions': [{'column': 'age', 'operator': '>', 'value': 18}],
        'logic': 'AND',
    },
    'depends_on': [],
}
```

### Backend Format

```python
{
    'name': 'step-uuid',
    'operation': 'filter',
    'params': {
        'conditions': [{'column': 'age', 'operator': '>', 'value': 18}],
        'logic': 'AND',
    },
}
```

### Key Differences

| Aspect | Frontend | Backend |
|--------|----------|---------|
| Step type key | `type` | `operation` |
| Config wrapper | Direct in `config` | Flattened to `params` |
| Field naming | camelCase | snake_case |
| Group by key | `groupBy` | `group_by` |
| Column rename | `column_mapping` | `mapping` |

## Main Function

```python
def convert_step_format(frontend_step: dict) -> dict
```

Converts a complete step from frontend to backend format:

```python
frontend_step = {
    'id': 'filter-1',
    'type': 'filter',
    'config': {'conditions': [...], 'logic': 'AND'},
    'depends_on': [],
}

backend_step = convert_step_format(frontend_step)
# {
#     'name': 'filter-1',
#     'operation': 'filter',
#     'params': {'conditions': [...], 'logic': 'AND'},
# }
```

## Converter Functions

### Filter Config

```python
def convert_filter_config(config: dict) -> dict
```

Frontend:
```python
{'conditions': [...], 'logic': 'AND'}
```

Backend: Same format (no conversion needed).

### GroupBy Config

```python
def convert_groupby_config(config: dict) -> dict
```

Frontend:
```python
{
    'groupBy': ['city', 'state'],
    'aggregations': [
        {'column': 'age', 'function': 'mean', 'alias': 'avg_age'},
    ],
}
```

Backend:
```python
{
    'group_by': ['city', 'state'],
    'aggregations': [
        {'column': 'age', 'function': 'mean'},  # alias removed
    ],
}
```

### Sort Config

```python
def convert_sort_config(config: dict) -> dict
```

Frontend (array format):
```python
[{'column': 'name', 'descending': False}]
```

Backend (object format):
```python
{'columns': ['name'], 'descending': [False]}
```

Also handles already-converted format.

### Join Config

```python
def convert_join_config(config: dict) -> dict
```

Frontend:
```python
{
    'rightDataSource': 'ds-uuid',
    'leftOn': ['id'],
    'rightOn': ['user_id'],
    'how': 'inner',
}
```

Backend:
```python
{
    'right_source': 'ds-uuid',
    'left_on': ['id'],
    'right_on': ['user_id'],
    'how': 'inner',
}
```

Supports both camelCase and snake_case input.

### Pivot Config

```python
def convert_pivot_config(config: dict) -> dict
```

Frontend:
```python
{
    'index': ['date'],
    'columns': 'product',
    'values': 'sales',
    'aggregateFunction': 'sum',
}
```

Backend:
```python
{
    'index': ['date'],
    'columns': 'product',
    'values': 'sales',
    'aggregate_function': 'sum',
}
```

### Rename Config

```python
def convert_rename_config(config: dict) -> dict
```

Frontend:
```python
{'column_mapping': {'old_name': 'new_name'}}
```

Backend:
```python
{'mapping': {'old_name': 'new_name'}}
```

### Timeseries Config

```python
def convert_timeseries_config(config: dict) -> dict
```

Frontend:
```python
{
    'column': 'created_at',
    'operationType': 'extract',
    'newColumn': 'year',
    'component': 'year',
}
```

Backend:
```python
{
    'column': 'created_at',
    'operation_type': 'extract',
    'new_column': 'year',
    'component': 'year',
}
```

### String Transform Config

```python
def convert_string_transform_config(config: dict) -> dict
```

Frontend:
```python
{
    'column': 'email',
    'method': 'extract',
    'pattern': r'@(.+)',
    'groupIndex': 1,
}
```

Backend:
```python
{
    'column': 'email',
    'method': 'extract',
    'pattern': r'@(.+)',
    'group_index': 1,
}
```

### Fill Null Config

```python
def convert_fillnull_config(config: dict) -> dict
```

Frontend and backend use same structure (passthrough).

### Deduplicate Config

```python
def convert_deduplicate_config(config: dict) -> dict
```

Frontend:
```python
{'columns': ['email'], 'keep': 'first'}
```

Backend:
```python
{'subset': ['email'], 'keep': 'first'}
```

### Sample Config

```python
def convert_sample_config(config: dict) -> dict
```

Passthrough (same format).

### Limit Config

```python
def convert_limit_config(config: dict) -> dict
```

Passthrough (same format).

### TopK Config

```python
def convert_topk_config(config: dict) -> dict
```

Passthrough (same format).

### Value Counts Config

```python
def convert_value_counts_config(config: dict) -> dict
```

Passthrough (same format).

### Export Config

```python
def convert_export_config(config: dict) -> dict
```

Passthrough (same format).

## Converter Registry

```python
def get_converters() -> dict
```

Returns mapping of operation types to converter functions:

```python
{
    'filter': convert_filter_config,
    'select': lambda c: c,  # No conversion
    'groupby': convert_groupby_config,
    'sort': convert_sort_config,
    'rename': convert_rename_config,
    'drop': lambda c: c,
    'join': convert_join_config,
    'with_columns': lambda c: c,
    'deduplicate': convert_deduplicate_config,
    'fill_null': convert_fillnull_config,
    'explode': lambda c: c,
    'pivot': convert_pivot_config,
    'unpivot': lambda c: c,
    'view': lambda c: c,
    'timeseries': convert_timeseries_config,
    'string_transform': convert_string_transform_config,
    'sample': convert_sample_config,
    'limit': convert_limit_config,
    'topk': convert_topk_config,
    'null_count': lambda c: c,
    'value_counts': convert_value_counts_config,
    'export': convert_export_config,
}
```

## Config Conversion

```python
def convert_config_to_params(operation: str, config: dict) -> dict
```

Dispatches to appropriate converter based on operation type:

```python
params = convert_config_to_params('filter', frontend_config)
# Returns backend params dict
```

If converter fails, returns original config (defensive).

## Usage

```python
from modules.compute.step_converter import convert_step_format

# Convert individual step
step = {
    'id': 'group-1',
    'type': 'groupby',
    'config': {
        'groupBy': ['city'],
        'aggregations': [{'column': 'sales', 'function': 'sum'}],
    },
    'depends_on': [],
}

backend_step = convert_step_format(step)
# {
#     'name': 'group-1',
#     'operation': 'groupby',
#     'params': {
#         'group_by': ['city'],
#         'aggregations': [{'column': 'sales', 'function': 'sum'}],
#     },
# }

# Convert entire pipeline
pipeline_steps = [step1, step2, step3]
backend_steps = [convert_step_format(s) for s in pipeline_steps]
```

## Error Handling

Converter errors are logged but don't raise:

```python
try:
    return converter(config)
except Exception as e:
    logger.error(f'Error converting {operation} config: {e}')
    return config if isinstance(config, dict) else {}
```

## See Also

- [Engine](./engine.md) - Where converted steps are used
- [Operations](./operations.md) - Supported operations
- [Frontend Pipeline Steps](frontend/components/pipeline.md) - Frontend step format
