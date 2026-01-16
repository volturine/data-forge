# Backend: Lazy Polars Evaluation

**Priority:** HIGH  
**Status:** In Progress  
**Depends On:** None  
**Blocks:** backend-compute/preview-endpoint.md

---

## Goal

Convert Polars engine from eager (`read_*`) to lazy (`scan_*`) evaluation for better performance with large datasets.

---

## Changes Required

### File: `backend/modules/compute/engine.py`

#### 1. Update `_load_datasource()` signature (line 201)

**Before:**
```python
def _load_datasource(config: dict) -> pl.DataFrame:
```

**After:**
```python
def _load_datasource(config: dict) -> pl.LazyFrame:
```

#### 2. Change file readers to scanners (lines 209-214)

**Before:**
```python
if file_type == 'csv':
    return pl.read_csv(file_path)
elif file_type == 'parquet':
    return pl.read_parquet(file_path)
elif file_type == 'json':
    return pl.read_ndjson(file_path)
```

**After:**
```python
if file_type == 'csv':
    return pl.scan_csv(file_path)
elif file_type == 'parquet':
    return pl.scan_parquet(file_path)
elif file_type == 'json':
    return pl.scan_ndjson(file_path)
```

#### 3. Fix database reads (line 221)

**After:**
```python
# Database reads must be collected then made lazy
return pl.read_database(query, connection_string).lazy()
```

#### 4. Update `_apply_step()` signature (line 227)

**Before:**
```python
def _apply_step(df: pl.DataFrame, step: dict) -> pl.DataFrame:
```

**After:**
```python
def _apply_step(lf: pl.LazyFrame, step: dict) -> pl.LazyFrame:
```

**Changes throughout:**
- Rename all `df` parameters to `lf` for clarity
- All operations (filter, select, etc.) already work on LazyFrame - no code changes needed!

#### 5. Fix `_execute_pipeline()` (lines 148-198)

**Before:**
```python
df = PolarsComputeEngine._load_datasource(datasource_config)

for idx, step in enumerate(pipeline_steps):
    df = PolarsComputeEngine._apply_step(df, backend_step)

output = {
    'schema': {col: str(dtype) for col, dtype in df.schema.items()},
    'row_count': len(df),
    'sample_data': df.head(100).to_dicts()
}
```

**After:**
```python
lf = PolarsComputeEngine._load_datasource(datasource_config)

for idx, step in enumerate(pipeline_steps):
    lf = PolarsComputeEngine._apply_step(lf, backend_step)

# Only collect at the end
df = lf.collect()

output = {
    'schema': {col: str(dtype) for col, dtype in df.schema.items()},
    'row_count': len(df),
    'sample_data': df.head(100).to_dicts()
}
```

#### 6. Fix fill_null mean/median strategies (lines 481-497)

**Problem:** Computing mean/median requires collection

**Before:**
```python
elif strategy == 'mean':
    exprs = []
    for c in columns:
        mean_val = df.select(pl.col(c).mean()).item()
        exprs.append(pl.col(c).fill_null(mean_val))
    return df.with_columns(exprs)
```

**After:**
```python
elif strategy == 'mean':
    if not columns:
        raise ValueError('Columns must be specified for mean strategy')
    # Compute stats separately
    stats = lf.select([pl.col(c).mean().alias(c) for c in columns]).collect()
    exprs = []
    for c in columns:
        mean_val = stats[c][0]
        exprs.append(pl.col(c).fill_null(mean_val))
    return lf.with_columns(exprs)
```

Same for `median` strategy.

---

## Testing

```python
# Test CSV scan
config = {
    'source_type': 'file',
    'file_type': 'csv',
    'file_path': 'test.csv'
}
lf = PolarsComputeEngine._load_datasource(config)
assert isinstance(lf, pl.LazyFrame)

# Test lazy filter
step = {'operation': 'filter', 'params': {'conditions': [...]}}
result = PolarsComputeEngine._apply_step(lf, step)
assert isinstance(result, pl.LazyFrame)

# Test collect only at end
df = result.collect()
assert isinstance(df, pl.DataFrame)
```

---

## Benefits

- ✅ Large files don't load fully into memory
- ✅ Query optimization by Polars engine
- ✅ Faster initial load (lazy scan vs eager read)
- ✅ Better memory efficiency

---

## Status

- [x] `_load_datasource()` - Changed to scan_*
- [ ] `_apply_step()` - Update signature
- [ ] `_execute_pipeline()` - Collect only at end
- [ ] `fill_null` mean/median - Fix collection
- [ ] Test with real CSV file
