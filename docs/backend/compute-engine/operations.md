# Supported Operations

Complete reference for all Polars operations supported by the compute engine.

## Overview

The compute engine supports 20+ data transformation operations organized into categories. All operations use Polars LazyFrame for optimal performance.

## Operation Categories

| Category | Operations |
|----------|------------|
| **Selection** | select, drop, rename |
| **Filtering** | filter, limit, sample, topk |
| **Aggregation** | groupby, value_counts, null_count |
| **Reshaping** | pivot, unpivot, explode |
| **Joins** | join (self-join) |
| **Transformation** | sort, deduplicate, fill_null |
| **String** | string_transform (20+ methods) |
| **Time Series** | timeseries (extract, add, subtract, diff) |
| **Expressions** | with_columns, view, export |

---

## Selection Operations

### select

Select specific columns from the dataset.

```python
# Backend format
{
    'operation': 'select',
    'params': {
        'columns': ['col1', 'col2', 'col3']
    }
}
```

**Example**: Keep only `name`, `age`, `city` columns.

### drop

Remove columns from the dataset.

```python
{
    'operation': 'drop',
    'params': {
        'columns': ['unwanted_col1', 'unwanted_col2']
    }
}
```

### rename

Rename columns.

```python
{
    'operation': 'rename',
    'params': {
        'mapping': {
            'old_name': 'new_name',
            'another_old': 'another_new'
        }
    }
}
```

---

## Filtering Operations

### filter

Filter rows based on conditions.

```python
{
    'operation': 'filter',
    'params': {
        'conditions': [
            {'column': 'age', 'operator': '>', 'value': 18},
            {'column': 'status', 'operator': '==', 'value': 'active'}
        ],
        'logic': 'AND'  # or 'OR'
    }
}
```

**Supported Operators**:

| Operator | Description | Example |
|----------|-------------|---------|
| `==` or `=` | Equal | `age == 25` |
| `!=` | Not equal | `status != 'inactive'` |
| `>` | Greater than | `price > 100` |
| `<` | Less than | `quantity < 10` |
| `>=` | Greater or equal | `rating >= 4.0` |
| `<=` | Less or equal | `discount <= 0.5` |
| `contains` | String contains | `name contains 'John'` |
| `starts_with` | String starts with | `code starts_with 'US'` |
| `ends_with` | String ends with | `email ends_with '.com'` |

### limit

Limit number of rows.

```python
{
    'operation': 'limit',
    'params': {
        'n': 100
    }
}
```

### sample

Random sample of rows.

```python
# Sample by count
{
    'operation': 'sample',
    'params': {
        'n': 1000,
        'shuffle': True,
        'seed': 42
    }
}

# Sample by fraction
{
    'operation': 'sample',
    'params': {
        'fraction': 0.1,  # 10%
        'shuffle': True,
        'seed': 42
    }
}
```

### topk

Get top K rows by column value.

```python
{
    'operation': 'topk',
    'params': {
        'column': 'sales',
        'k': 10,
        'descending': True  # Highest first
    }
}
```

---

## Aggregation Operations

### groupby

Group by columns and aggregate.

```python
{
    'operation': 'groupby',
    'params': {
        'group_by': ['category', 'region'],
        'aggregations': [
            {'column': 'sales', 'function': 'sum'},
            {'column': 'quantity', 'function': 'mean'},
            {'column': 'id', 'function': 'count'}
        ]
    }
}
```

**Supported Aggregation Functions**:

| Function | Description | Output Column |
|----------|-------------|---------------|
| `sum` | Sum of values | `{col}_sum` |
| `mean` | Average | `{col}_mean` |
| `count` | Count | `{col}_count` |
| `min` | Minimum | `{col}_min` |
| `max` | Maximum | `{col}_max` |

### value_counts

Count occurrences of each unique value.

```python
{
    'operation': 'value_counts',
    'params': {
        'column': 'category',
        'normalize': False,  # True for percentages
        'sort': True
    }
}
```

### null_count

Count null values in each column.

```python
{
    'operation': 'null_count',
    'params': {}
}
```

---

## Reshaping Operations

### pivot

Transform rows to columns (wide format).

```python
{
    'operation': 'pivot',
    'params': {
        'index': ['date'],           # Row identifiers
        'columns': 'category',        # Column to pivot
        'values': 'sales',            # Values to aggregate
        'aggregate_function': 'sum'   # How to aggregate
    }
}
```

**Before**:
| date | category | sales |
|------|----------|-------|
| 2024-01 | A | 100 |
| 2024-01 | B | 200 |
| 2024-02 | A | 150 |

**After**:
| date | A | B |
|------|---|---|
| 2024-01 | 100 | 200 |
| 2024-02 | 150 | null |

### unpivot

Transform columns to rows (long format).

```python
{
    'operation': 'unpivot',
    'params': {
        'index': ['id', 'name'],      # Columns to keep
        'on': ['jan', 'feb', 'mar'],  # Columns to unpivot
        'variable_name': 'month',     # New column for old headers
        'value_name': 'value'         # New column for values
    }
}
```

### explode

Expand list columns into rows.

```python
{
    'operation': 'explode',
    'params': {
        'columns': ['tags']  # Column containing lists
    }
}
```

**Before**:
| id | tags |
|----|------|
| 1 | ["a", "b", "c"] |

**After**:
| id | tags |
|----|------|
| 1 | a |
| 1 | b |
| 1 | c |

---

## Join Operations

### join

Join data (currently self-join only).

```python
{
    'operation': 'join',
    'params': {
        'left_on': ['id'],
        'right_on': ['parent_id'],
        'how': 'inner'  # inner, left, right, full, cross
    }
}
```

**Note**: Cross-datasource joins are not yet supported.

---

## Transformation Operations

### sort

Sort by columns.

```python
{
    'operation': 'sort',
    'params': {
        'columns': ['date', 'name'],
        'descending': [True, False]  # Per-column or single bool
    }
}
```

### deduplicate

Remove duplicate rows.

```python
{
    'operation': 'deduplicate',
    'params': {
        'subset': ['email'],  # Columns to consider (null = all)
        'keep': 'first'       # first, last, any, none
    }
}
```

### fill_null

Handle missing values.

```python
# Literal value
{
    'operation': 'fill_null',
    'params': {
        'strategy': 'literal',
        'value': 0,
        'columns': ['price', 'quantity']  # Optional, null = all
    }
}

# Forward fill
{
    'operation': 'fill_null',
    'params': {
        'strategy': 'forward',
        'columns': ['date']
    }
}

# Backward fill
{
    'operation': 'fill_null',
    'params': {
        'strategy': 'backward'
    }
}

# Mean (requires columns)
{
    'operation': 'fill_null',
    'params': {
        'strategy': 'mean',
        'columns': ['price']
    }
}

# Median (requires columns)
{
    'operation': 'fill_null',
    'params': {
        'strategy': 'median',
        'columns': ['price']
    }
}

# Drop rows with nulls
{
    'operation': 'fill_null',
    'params': {
        'strategy': 'drop_rows',
        'columns': ['required_field']
    }
}
```

---

## String Operations

### string_transform

String manipulation methods.

```python
{
    'operation': 'string_transform',
    'params': {
        'column': 'name',
        'method': 'uppercase',
        'new_column': 'NAME_UPPER'  # Optional, defaults to same column
    }
}
```

**Supported Methods**:

| Method | Description | Parameters |
|--------|-------------|------------|
| `uppercase` | Convert to uppercase | - |
| `lowercase` | Convert to lowercase | - |
| `title` | Title case | - |
| `strip` | Remove whitespace (both ends) | - |
| `lstrip` | Remove leading whitespace | - |
| `rstrip` | Remove trailing whitespace | - |
| `length` | String length | - |
| `slice` | Extract substring | `start`, `end` |
| `replace` | Replace pattern | `pattern`, `replacement` |
| `extract` | Regex extract | `pattern`, `group_index` |
| `split` | Split and get element | `delimiter`, `index` |

**Example - Replace**:
```python
{
    'operation': 'string_transform',
    'params': {
        'column': 'phone',
        'method': 'replace',
        'pattern': '-',
        'replacement': '',
        'new_column': 'phone_clean'
    }
}
```

**Example - Extract**:
```python
{
    'operation': 'string_transform',
    'params': {
        'column': 'email',
        'method': 'extract',
        'pattern': r'@(\w+)',
        'group_index': 1,
        'new_column': 'domain'
    }
}
```

---

## Time Series Operations

### timeseries

Date/time manipulation.

```python
# Extract component
{
    'operation': 'timeseries',
    'params': {
        'column': 'created_at',
        'operation_type': 'extract',
        'component': 'year',  # year, month, day, hour, minute, second, quarter, week, dayofweek
        'new_column': 'year'
    }
}

# Add duration
{
    'operation': 'timeseries',
    'params': {
        'column': 'date',
        'operation_type': 'add',
        'value': 7,
        'unit': 'days',  # days, weeks, months, hours, minutes, seconds
        'new_column': 'date_plus_week'
    }
}

# Subtract duration
{
    'operation': 'timeseries',
    'params': {
        'column': 'date',
        'operation_type': 'subtract',
        'value': 1,
        'unit': 'months',
        'new_column': 'previous_month'
    }
}

# Difference between dates
{
    'operation': 'timeseries',
    'params': {
        'column': 'start_date',
        'operation_type': 'diff',
        'column2': 'end_date',
        'new_column': 'duration'
    }
}
```

---

## Expression Operations

### with_columns
 
Add computed columns.
 
```python
{
    'operation': 'with_columns',
    'params': {
        'expressions': [
            {
                'name': 'constant_col',
                'type': 'literal',
                'value': 'default'
            },
            {
                'name': 'copied_col',
                'type': 'column',
                'column': 'existing_col'
            }
        ]
    }
}
```
 
### view
 
Passthrough operation for visualization checkpoints.
 
```python
{
    'operation': 'view',
    'params': {}
}
```
 
**Note**: View doesn't modify data but allows pipeline previewing at that step.
 
### export
 
Trigger export of pipeline output. The engine returns the lazy frame unchanged; the export is handled via `/compute/export` to either stream a download or write to `data/exports`.
 
```python
{
    'operation': 'export',
    'params': {
        'format': 'csv',            # csv, parquet, json, ndjson
        'filename': 'export',       # base name
        'destination': 'download'   # download or filesystem
    }
}
```
 
---
 
## Data Loading


### Supported File Types

| Type | Function | Notes |
|------|----------|-------|
| CSV | `pl.scan_csv()` | Lazy evaluation |
| Parquet | `pl.scan_parquet()` | Lazy evaluation |
| JSON (newline-delimited) | `pl.scan_ndjson()` | Lazy evaluation |
| Excel | `pl.read_excel().lazy()` | Eager then lazy |

### Database Sources

```python
# Database reads use eager loading then convert to lazy
lf = pl.read_database(query, connection_string).lazy()
```

---

## See Also

- [Architecture](./architecture.md) - Engine architecture
- [Pipeline Execution](./pipeline-execution.md) - Execution flow
- [Step Converter](../modules/compute.md#step-converter) - Frontend to backend conversion
