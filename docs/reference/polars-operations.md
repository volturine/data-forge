# Polars Operations Reference

Complete reference for all supported Polars operations in the compute engine.

## Overview

The compute engine supports 20+ Polars operations, all executed lazily using `LazyFrame` for optimal performance. Operations are applied in topological order based on dependencies.

## Filtering Operations

### filter

Remove rows based on conditions.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `conditions` | array | Yes | List of filter conditions |
| `logic` | string | No | `AND` or `OR` (default: `AND`) |

**Condition Structure:**
```json
{
    "column": "age",
    "operator": ">",
    "value": 18
}
```

**Supported Operators:**
| Operator | Description | Example |
|----------|-------------|---------|
| `=`, `==` | Equal | `age == 25` |
| `!=` | Not equal | `status != 'inactive'` |
| `>` | Greater than | `price > 100` |
| `<` | Less than | `quantity < 10` |
| `>=` | Greater than or equal | `age >= 18` |
| `<=` | Less than or equal | `score <= 100` |
| `contains` | String contains | `name.contains('John')` |
| `starts_with` | String starts with | `email.starts_with('admin')` |
| `ends_with` | String ends with | `file.ends_with('.csv')` |

**Example:**
```json
{
    "operation": "filter",
    "params": {
        "conditions": [
            {"column": "age", "operator": ">=", "value": 18},
            {"column": "status", "operator": "==", "value": "active"}
        ],
        "logic": "AND"
    }
}
```

### limit

Keep first N rows.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `n` | int | No | 10 | Number of rows to keep |

**Example:**
```json
{
    "operation": "limit",
    "params": {"n": 100}
}
```

### sample

Random sample of rows.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `n` | int | No* | Exact number of rows |
| `fraction` | float | No* | Fraction of rows (0.0-1.0) |
| `shuffle` | bool | No | Shuffle before sampling |
| `seed` | int | No | Random seed for reproducibility |

*One of `n` or `fraction` is required.

**Example:**
```json
{
    "operation": "sample",
    "params": {
        "n": 1000,
        "shuffle": true,
        "seed": 42
    }
}
```

### topk

Get top K rows by column value.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `column` | string | Yes | - | Column to sort by |
| `k` | int | No | 10 | Number of rows |
| `descending` | bool | No | false | Sort descending (highest first) |

**Example:**
```json
{
    "operation": "topk",
    "params": {
        "column": "sales",
        "k": 10,
        "descending": true
    }
}
```

## Selection Operations

### select

Keep specific columns.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `columns` | array | Yes | Column names to keep |

**Example:**
```json
{
    "operation": "select",
    "params": {"columns": ["name", "age", "city"]}
}
```

### drop

Remove columns.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `columns` | array | Yes | Column names to remove |

**Example:**
```json
{
    "operation": "drop",
    "params": {"columns": ["temp_col", "debug_col"]}
}
```

### rename

Rename columns.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `mapping` | object | Yes | Old name to new name mapping |

**Example:**
```json
{
    "operation": "rename",
    "params": {
        "mapping": {
            "old_name": "new_name",
            "another_col": "renamed_col"
        }
    }
}
```

## Aggregation Operations

### groupby

Group by columns and aggregate.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `group_by` | array | Yes | Columns to group by |
| `aggregations` | array | Yes | Aggregation specifications |

**Aggregation Structure:**
```json
{
    "column": "sales",
    "function": "sum"
}
```

**Supported Functions:**
| Function | Description | Output Alias |
|----------|-------------|--------------|
| `sum` | Sum of values | `{col}_sum` |
| `mean` | Average value | `{col}_mean` |
| `count` | Count of values | `{col}_count` |
| `min` | Minimum value | `{col}_min` |
| `max` | Maximum value | `{col}_max` |

**Example:**
```json
{
    "operation": "groupby",
    "params": {
        "group_by": ["category", "region"],
        "aggregations": [
            {"column": "sales", "function": "sum"},
            {"column": "quantity", "function": "mean"},
            {"column": "id", "function": "count"}
        ]
    }
}
```

### value_counts

Frequency count of column values.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `column` | string | Yes | - | Column to count |
| `normalize` | bool | No | false | Return proportions |
| `sort` | bool | No | true | Sort by count |

**Example:**
```json
{
    "operation": "value_counts",
    "params": {
        "column": "category",
        "normalize": false,
        "sort": true
    }
}
```

### null_count

Count null values per column.

**Parameters:** None

**Example:**
```json
{
    "operation": "null_count",
    "params": {}
}
```

## Transformation Operations

### sort

Order rows by columns.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `columns` | array | Yes | - | Columns to sort by |
| `descending` | bool/array | No | false | Sort direction(s) |

**Example:**
```json
{
    "operation": "sort",
    "params": {
        "columns": ["date", "name"],
        "descending": [true, false]
    }
}
```

### deduplicate

Remove duplicate rows.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `subset` | array | No | all | Columns to check for duplicates |
| `keep` | string | No | `first` | Which duplicate to keep: `first`, `last`, `none` |

**Example:**
```json
{
    "operation": "deduplicate",
    "params": {
        "subset": ["email"],
        "keep": "first"
    }
}
```

### fill_null

Handle missing values.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `strategy` | string | Yes | Fill strategy (see below) |
| `columns` | array | No | Columns to apply (null = all) |
| `value` | any | Conditional | Value for `literal` strategy |

**Strategies:**
| Strategy | Description | Requires `value` |
|----------|-------------|------------------|
| `literal` | Fill with constant value | Yes |
| `forward` | Fill with previous value | No |
| `backward` | Fill with next value | No |
| `mean` | Fill with column mean | No |
| `median` | Fill with column median | No |
| `drop_rows` | Remove rows with nulls | No |

**Example:**
```json
{
    "operation": "fill_null",
    "params": {
        "strategy": "literal",
        "value": 0,
        "columns": ["price", "quantity"]
    }
}
```

### with_columns

Add computed columns.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `expressions` | array | Yes | Column expressions |

**Expression Structure:**
```json
{
    "name": "new_col_name",
    "type": "literal",
    "value": 100
}
```

**Expression Types:**
| Type | Description | Required Fields |
|------|-------------|-----------------|
| `literal` | Constant value | `value` |
| `column` | Copy from column | `column` |

**Example:**
```json
{
    "operation": "with_columns",
    "params": {
        "expressions": [
            {"name": "status", "type": "literal", "value": "active"},
            {"name": "name_copy", "type": "column", "column": "name"}
        ]
    }
}
```

## Reshaping Operations

### pivot

Transform to wide format.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `index` | array | Yes | - | Columns to keep as index |
| `columns` | string | Yes | - | Column to pivot |
| `values` | string | Yes | - | Column for values |
| `aggregate_function` | string | No | `first` | Aggregation function |

**Example:**
```json
{
    "operation": "pivot",
    "params": {
        "index": ["date"],
        "columns": "category",
        "values": "sales",
        "aggregate_function": "sum"
    }
}
```

### unpivot

Transform to long format (melt).

**Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `index` | array | No | - | Columns to keep as identifiers |
| `on` | array | No | - | Columns to unpivot |
| `variable_name` | string | No | `variable` | Name for variable column |
| `value_name` | string | No | `value` | Name for value column |

**Example:**
```json
{
    "operation": "unpivot",
    "params": {
        "index": ["id", "name"],
        "on": ["jan", "feb", "mar"],
        "variable_name": "month",
        "value_name": "sales"
    }
}
```

### explode

Expand list columns into rows.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `columns` | string/array | Yes | Column(s) to explode |

**Example:**
```json
{
    "operation": "explode",
    "params": {"columns": ["tags"]}
}
```

## String Operations

### string_transform

Apply string transformations.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `column` | string | Yes | - | Column to transform |
| `method` | string | Yes | - | Transformation method |
| `new_column` | string | No | same as input | Output column name |

**Methods:**
| Method | Description | Extra Parameters |
|--------|-------------|------------------|
| `uppercase` | Convert to uppercase | - |
| `lowercase` | Convert to lowercase | - |
| `title` | Convert to title case | - |
| `strip` | Remove whitespace (both ends) | - |
| `lstrip` | Remove leading whitespace | - |
| `rstrip` | Remove trailing whitespace | - |
| `length` | Get string length | - |
| `slice` | Extract substring | `start`, `end` |
| `replace` | Replace all matching patterns | `pattern`, `replacement` |
| `extract` | Extract with regex | `pattern`, `group_index` |
| `split` | Split and get element | `delimiter`, `index` |

**Example:**
```json
{
    "operation": "string_transform",
    "params": {
        "column": "name",
        "method": "uppercase",
        "new_column": "name_upper"
    }
}
```

**Slice Example:**
```json
{
    "operation": "string_transform",
    "params": {
        "column": "phone",
        "method": "slice",
        "start": 0,
        "end": 3,
        "new_column": "area_code"
    }
}
```

**Replace Example (replaces all occurrences):**
```json
{
    "operation": "string_transform",
    "params": {
        "column": "text",
        "method": "replace",
        "pattern": "[^a-zA-Z]",
        "replacement": "",
        "new_column": "text_clean"
    }
}
```

All matching patterns are replaced globally.

## Time Series Operations

### timeseries

Date/time transformations.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `column` | string | Yes | Datetime column |
| `operation_type` | string | Yes | Operation type (see below) |
| `new_column` | string | Yes | Output column name |

**Operation Types:**

#### extract
Extract date/time component.

| Component | Description |
|-----------|-------------|
| `year` | Year (e.g., 2024) |
| `month` | Month (1-12) |
| `day` | Day of month (1-31) |
| `hour` | Hour (0-23) |
| `minute` | Minute (0-59) |
| `second` | Second (0-59) |
| `quarter` | Quarter (1-4) |
| `week` | Week of year |
| `dayofweek` | Day of week (0-6) |

```json
{
    "operation": "timeseries",
    "params": {
        "column": "created_at",
        "operation_type": "extract",
        "component": "year",
        "new_column": "year"
    }
}
```

#### add / subtract
Add or subtract time duration.

| Unit | Description |
|------|-------------|
| `days` | Calendar days |
| `weeks` | Weeks |
| `months` | Calendar months |
| `hours` | Hours |
| `minutes` | Minutes |
| `seconds` | Seconds |

```json
{
    "operation": "timeseries",
    "params": {
        "column": "date",
        "operation_type": "add",
        "value": 7,
        "unit": "days",
        "new_column": "date_plus_week"
    }
}
```

#### diff
Difference between two datetime columns.

```json
{
    "operation": "timeseries",
    "params": {
        "column": "start_date",
        "operation_type": "diff",
        "column2": "end_date",
        "new_column": "duration"
    }
}
```

## Special Operations

### view

Passthrough for visualization (no transformation).

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `rowLimit` | int | Rows to preview (frontend only) |

**Example:**
```json
{
    "operation": "view",
    "params": {"rowLimit": 100}
}
```

### join

Join with another datasource (self-join only currently).

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `left_on` | array | Yes | Left join columns |
| `right_on` | array | Yes | Right join columns |
| `how` | string | No | Join type: `inner`, `left`, `right`, `outer` |

**Note:** Cross-datasource joins are not yet supported.

## Error Handling

Operations raise `ValueError` for:
- Missing required parameters
- Invalid operator/method names
- Unsupported operation types
- Type mismatches

**Example Error:**
```python
ValueError: Unsupported filter operator: like
```

## See Also

- [Compute Engine](../backend/compute-engine/README.md) - Engine architecture
- [Building Pipelines](../guides/building-pipelines.md) - Using operations in UI
- [Adding Operations](../guides/adding-operations.md) - Extending the engine
