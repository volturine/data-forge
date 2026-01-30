# Compute Module Refactor Plan

## Summary

Refactor the backend compute module to use declarative registries instead of if-elif chains, making the codebase more maintainable, extensible, and self-documenting. This introduces layered registries for operations, sub-operations (filters, aggregations, etc.), data loaders, export formats, and a plugin system for custom operations.

**Decisions confirmed:**
- Pydantic validation for operation params: Yes
- Plugin system for custom operations: Yes
- Unify timeseries add/subtract into a single offset operation: Yes

---

## Files to Modify/Create

### New Files (Registries)

| File | Purpose |
|------|---------|
| `modules/compute/registries/__init__.py` | Export all registries |
| `modules/compute/registries/operators.py` | Filter comparison operators (`==`, `!=`, `>`, `contains`, etc.) |
| `modules/compute/registries/aggregations.py` | Aggregation functions (`sum`, `mean`, `count`, etc.) |
| `modules/compute/registries/timeseries.py` | DT extractors, duration builders, unified offset operation |
| `modules/compute/registries/strings.py` | String transformation methods |
| `modules/compute/registries/fill_strategies.py` | Null-filling strategies |
| `modules/compute/registries/types.py` | Type casting mappings |
| `modules/compute/registries/datasources.py` | Datasource/file type loaders (consolidates duplicated logic) |
| `modules/compute/registries/exports.py` | Export format definitions (extension, content-type, writer) |

### New Files (Operations)

| File | Purpose |
|------|---------|
| `modules/compute/operations/__init__.py` | Export `get_operation_handlers()`, plugin registration |
| `modules/compute/operations/base.py` | `OperationHandler` protocol, Pydantic param schemas |
| `modules/compute/operations/filter.py` | Filter operation using operators registry |
| `modules/compute/operations/groupby.py` | Groupby operation using aggregations registry |
| `modules/compute/operations/timeseries.py` | Unified timeseries operation (extract, offset, diff) |
| `modules/compute/operations/strings.py` | String transform using strings registry |
| `modules/compute/operations/fill_null.py` | Fill null using fill_strategies registry |
| `modules/compute/operations/join.py` | Join operation |
| `modules/compute/operations/union.py` | Union by name operation |
| `modules/compute/operations/pivot.py` | Pivot operation |
| `modules/compute/operations/simple.py` | Simple operations (select, drop, sort, rename, limit, sample, etc.) |

### New Files (Utilities)

| File | Purpose |
|------|---------|
| `modules/compute/utils.py` | Common utilities: `find_step_index()`, `await_engine_result()`, `build_datasource_config()` |

### Modified Files

| File | Changes |
|------|---------|
| `modules/compute/polars_functions.py` | Delete - replaced by `operations/` |
| `modules/compute/engine.py` | Use registries for datasource loading and export writing |
| `modules/compute/service.py` | Use utilities for common patterns, remove duplicated code |
| `modules/compute/step_converter.py` | Minor cleanup - converters already registry-based |
| `modules/datasource/service.py` | Use shared datasource registry for schema extraction |

---

## Implementation Steps

### Phase 1: Foundation (Registries)

1. Create `registries/` directory structure with `__init__.py`
2. Implement `registries/operators.py` - filter operators mapping
3. Implement `registries/aggregations.py` - aggregation functions mapping
4. Implement `registries/timeseries.py` - DT extractors + duration builders
5. Implement `registries/strings.py` - string method mapping
6. Implement `registries/fill_strategies.py` - fill null strategies
7. Implement `registries/types.py` - type casting mapping
8. Implement `registries/datasources.py` - unified file/source type loaders
9. Implement `registries/exports.py` - export format definitions

### Phase 2: Operations Refactor

10. Create `operations/base.py` - define `OperationHandler` Protocol + Pydantic param schemas
11. Create `operations/simple.py` - migrate select, drop, sort, rename, limit, sample, view, explode, unpivot, deduplicate, topk, null_count, value_counts, export
12. Create `operations/filter.py` - refactor filter using operators registry
13. Create `operations/groupby.py` - refactor groupby using aggregations registry
14. Create `operations/timeseries.py` - unified operation (extract, offset, diff)
15. Create `operations/strings.py` - refactor using strings registry
16. Create `operations/fill_null.py` - refactor using fill_strategies registry
17. Create `operations/join.py` - extract join logic
18. Create `operations/union.py` - union_by_name operation
19. Create `operations/pivot.py` - pivot operation
20. Create `operations/__init__.py` - export unified registry + plugin API

### Phase 3: Engine & Service Refactor

21. Create `utils.py` - extract common patterns from service.py
22. Refactor `engine.py` - use datasources/exports registries, remove if-elif dispatch
23. Refactor `service.py` - use utils, remove duplication
24. Update `datasource/service.py` - use shared datasource registry

### Phase 4: Cleanup & Testing

25. Delete `polars_functions.py`
26. Run existing tests, fix any regressions
27. Add new registry unit tests
28. Add operation handler unit tests
29. Update imports across the codebase

---

## Operation Handler Design

### Base Protocol (`operations/base.py`)

```python
from typing import Protocol
from pydantic import BaseModel
import polars as pl

class OperationParams(BaseModel):
    class Config:
        extra = 'forbid'

class OperationHandler(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def params_schema(self) -> type[OperationParams] | None: ...

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame: ...
```

### Plugin System (`operations/__init__.py`)

```python
from typing import Callable

_OPERATION_REGISTRY: dict[str, OperationHandler] = {}

def register_operation(name: str, handler: OperationHandler) -> None:
    if name in _OPERATION_REGISTRY:
        raise ValueError(f'Operation already registered: {name}')
    _OPERATION_REGISTRY[name] = handler

def get_operation_handlers() -> dict[str, OperationHandler]:
    return dict(_OPERATION_REGISTRY)
```

---

## Registry Designs

### Filter Operators (`registries/operators.py`)

```python
from typing import Any, Callable
import polars as pl

FILTER_OPERATORS: dict[str, Callable[[pl.Expr, Any], pl.Expr]] = {
    '=': lambda c, v: c == v,
    '==': lambda c, v: c == v,
    '!=': lambda c, v: c != v,
    '>': lambda c, v: c > v,
    '<': lambda c, v: c < v,
    '>=': lambda c, v: c >= v,
    '<=': lambda c, v: c <= v,
    'contains': lambda c, v: c.str.contains(v),
    'starts_with': lambda c, v: c.str.starts_with(v),
    'ends_with': lambda c, v: c.str.ends_with(v),
    'is_null': lambda c, _: c.is_null(),
    'is_not_null': lambda c, _: c.is_not_null(),
    'in': lambda c, v: c.is_in(v),
    'not_in': lambda c, v: ~c.is_in(v),
}

def get_operator(name: str) -> Callable[[pl.Expr, Any], pl.Expr]:
    op = FILTER_OPERATORS.get(name)
    if not op:
        raise ValueError(f'Unsupported filter operator: {name}')
    return op
```

### Aggregation Functions (`registries/aggregations.py`)

```python
from typing import Callable
import polars as pl

AGG_FUNCTIONS: dict[str, Callable[[str], pl.Expr]] = {
    'sum': lambda c: pl.col(c).sum(),
    'mean': lambda c: pl.col(c).mean(),
    'count': lambda c: pl.col(c).count(),
    'min': lambda c: pl.col(c).min(),
    'max': lambda c: pl.col(c).max(),
    'first': lambda c: pl.col(c).first(),
    'last': lambda c: pl.col(c).last(),
    'median': lambda c: pl.col(c).median(),
    'std': lambda c: pl.col(c).std(),
    'var': lambda c: pl.col(c).var(),
    'collect_list': lambda c: pl.col(c).implode(),
    'collect_set': lambda c: pl.col(c).implode().list.unique(),
}

def get_aggregation(name: str) -> Callable[[str], pl.Expr]:
    agg = AGG_FUNCTIONS.get(name)
    if not agg:
        raise ValueError(f'Unsupported aggregation function: {name}')
    return agg
```

### Timeseries Registry (`registries/timeseries.py`)

```python
from typing import Callable
import polars as pl

DT_EXTRACTORS: dict[str, str] = {
    'year': 'year',
    'month': 'month',
    'day': 'day',
    'hour': 'hour',
    'minute': 'minute',
    'second': 'second',
    'quarter': 'quarter',
    'week': 'week',
    'dayofweek': 'weekday',
}

DURATION_BUILDERS: dict[str, Callable[[int], pl.Expr]] = {
    'seconds': lambda v: pl.duration(seconds=v),
    'minutes': lambda v: pl.duration(minutes=v),
    'hours': lambda v: pl.duration(hours=v),
    'days': lambda v: pl.duration(days=v),
    'weeks': lambda v: pl.duration(weeks=v),
}

def get_extractor(component: str) -> str:
    method = DT_EXTRACTORS.get(component)
    if not method:
        raise ValueError(f'Unsupported time component: {component}')
    return method

def get_duration(unit: str, value: int) -> pl.Expr:
    builder = DURATION_BUILDERS.get(unit)
    if not builder:
        raise ValueError(f'Unsupported duration unit: {unit}')
    return builder(value)
```

### String Methods (`registries/strings.py`)

```python
from typing import Callable
import polars as pl

STRING_METHODS: dict[str, Callable[[pl.Expr], pl.Expr]] = {
    'uppercase': lambda c: c.str.to_uppercase(),
    'lowercase': lambda c: c.str.to_lowercase(),
    'title': lambda c: c.str.to_titlecase(),
    'strip': lambda c: c.str.strip_chars(),
    'lstrip': lambda c: c.str.strip_chars_start(),
    'rstrip': lambda c: c.str.strip_chars_end(),
    'length': lambda c: c.str.len_chars(),
}

def get_string_method(name: str) -> Callable[[pl.Expr], pl.Expr] | None:
    return STRING_METHODS.get(name)
```

### Fill Strategies (`registries/fill_strategies.py`)

```python
from typing import Callable
import polars as pl

FILL_STRATEGIES: dict[str, Callable[[pl.Expr], pl.Expr]] = {
    'forward': lambda c: c.forward_fill(),
    'backward': lambda c: c.backward_fill(),
    'mean': lambda c: c.fill_null(c.mean()),
    'median': lambda c: c.fill_null(c.median()),
    'zero': lambda c: c.fill_null(0),
}

def get_fill_strategy(name: str) -> Callable[[pl.Expr], pl.Expr] | None:
    return FILL_STRATEGIES.get(name)
```

### Type Casting (`registries/types.py`)

```python
from typing import Any, Callable
import polars as pl

TYPE_CASTERS: dict[str, tuple[Callable[[Any], Any], pl.DataType]] = {
    'Int64': (int, pl.Int64),
    'Float64': (float, pl.Float64),
    'Boolean': (bool, pl.Boolean),
    'String': (str, pl.Utf8),
    'Date': (None, pl.Date),
    'Datetime': (None, pl.Datetime),
}

def cast_value(value: Any, type_name: str | None) -> Any:
    if not type_name or value is None:
        return value
    spec = TYPE_CASTERS.get(type_name)
    if not spec:
        return value
    caster, _ = spec
    return caster(value) if caster else value

def get_polars_type(type_name: str) -> pl.DataType | None:
    spec = TYPE_CASTERS.get(type_name)
    return spec[1] if spec else None
```

### Datasource Loaders (`registries/datasources.py`)

```python
from typing import Callable
import polars as pl

FILE_LOADERS: dict[str, Callable[..., pl.LazyFrame]] = {
    'csv': lambda path, opts: pl.scan_csv(path, **_csv_opts(opts)),
    'parquet': lambda path, _: pl.scan_parquet(path),
    'json': lambda path, _: pl.read_json(path).lazy(),
    'ndjson': lambda path, _: pl.scan_ndjson(path),
    'excel': lambda path, _: pl.read_excel(path).lazy(),
}

def _csv_opts(opts: dict | None) -> dict:
    if not opts:
        return {}
    return {
        'separator': opts.get('delimiter', ','),
        'quote_char': opts.get('quote_char', '"'),
        'has_header': opts.get('has_header', True),
        'skip_rows': opts.get('skip_rows', 0),
        'encoding': opts.get('encoding', 'utf8').lower(),
    }

def load_file(path: str, file_type: str, options: dict | None = None) -> pl.LazyFrame:
    loader = FILE_LOADERS.get(file_type)
    if not loader:
        raise ValueError(f'Unsupported file type: {file_type}')
    return loader(path, options)
```

### Export Formats (`registries/exports.py`)

```python
from typing import Callable
from dataclasses import dataclass
import polars as pl

@dataclass(frozen=True)
class ExportFormat:
    extension: str
    content_type: str
    writer: Callable[[pl.DataFrame, str], None]

EXPORT_FORMATS: dict[str, ExportFormat] = {
    'csv': ExportFormat('.csv', 'text/csv', lambda df, p: df.write_csv(p)),
    'parquet': ExportFormat('.parquet', 'application/octet-stream', lambda df, p: df.write_parquet(p)),
    'json': ExportFormat('.json', 'application/json', lambda df, p: df.write_json(p)),
    'ndjson': ExportFormat('.ndjson', 'application/x-ndjson', lambda df, p: df.write_ndjson(p)),
}

def get_export_format(name: str) -> ExportFormat:
    fmt = EXPORT_FORMATS.get(name)
    if not fmt:
        raise ValueError(f'Unsupported export format: {name}')
    return fmt
```

---

## Pydantic Param Validation Strategy

Each operation will define a dedicated Pydantic schema that validates its parameters before execution. The handler will be responsible for calling `schema.model_validate(params)`.

Example:

```python
from pydantic import BaseModel

class FilterCondition(BaseModel):
    column: str
    operator: str
    value: object | None = None

class FilterParams(BaseModel):
    conditions: list[FilterCondition]
    logic: str = 'AND'
```

---

## Unified Timeseries Operation

Replace `add` and `subtract` with a single `offset` operation:

```json
{
  "operation_type": "offset",
  "unit": "days",
  "value": 3,
  "direction": "add" | "subtract"
}
```

Implementation uses the same registry for durations, and only applies a sign to the offset.

---

## Plugin System Design

A plugin system allows registering new operations dynamically:

```python
def register_operation(name: str, handler: OperationHandler) -> None:
    if name in _OPERATION_REGISTRY:
        raise ValueError(f'Operation already registered: {name}')
    _OPERATION_REGISTRY[name] = handler

# Example plugin usage:
register_operation("my_custom_op", MyCustomHandler())
```

This enables external modules to extend compute without modifying core files.

---

## Testing Strategy

| Test Type | Coverage |
|-----------|----------|
| Unit tests | Each registry entry works correctly |
| Unit tests | Each operation handler validates and executes correctly |
| Integration tests | Full pipeline execution with mixed operations |
| Regression tests | All existing compute tests pass |
| Edge cases | Invalid operators, missing params, nulls, empty pipeline |

Proposed test files:
- `tests/test_registries.py`
- `tests/test_operations.py`
- Update `tests/test_compute.py`

---

## Risks & Considerations

- **Breaking changes**: Internal APIs and step conversion may change; frontend updates may be required.
- **Schema validation errors**: Stricter Pydantic validation could break loosely structured frontend configs.
- **Plugin safety**: Allowing plugins adds risk of unvalidated operations, so registration must validate schemas.
- **Performance**: Slight overhead from schema validation, negligible for typical pipelines.

---

## Approval

Once approved, implementation will start with registry foundation, then operations refactor, then engine/service cleanup, and finally tests.
