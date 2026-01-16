# Missing Polars Operations - Implementation Tasks

**Status**: Planning
**Priority**: High
**Created**: Fri Jan 16 2026

## Overview

This document lists Polars DataFrame operations that are NOT yet implemented in the no-code data analysis platform, prioritized by usefulness for typical data analysis workflows.

**Currently Implemented (14 operations)**:
1. Filter - row filtering with conditions
2. Select - column selection/projection
3. GroupBy - aggregation with group by
4. Sort - sorting rows
5. Rename - rename columns
6. Drop - drop columns
7. Expression - custom Polars expressions
8. Join - merge datasets
9. Pivot - long to wide format
10. TimeSeries - date/time operations
11. StringMethods - string transformations
12. FillNull - handle missing data
13. Deduplicate - remove duplicate rows
14. Explode - expand list/array columns

---

## High Priority Operations

### 1. Unpivot/Melt

**Description**: Transforms wide-format data into long-format by "melting" multiple columns into key-value pairs. This is the inverse of pivot and is essential for reshaping data for analysis, especially when preparing data for visualization or statistical modeling.

**Polars Method**: `df.melt()` / `df.unpivot()`

**Use Cases**: 
- Converting wide sales data (Jan, Feb, Mar columns) into long format (Month, Sales columns)
- Preparing data for time-series analysis
- Reshaping survey data where each question is a column
- Converting multi-metric datasets into single metric column with type indicator

**Backend Implementation** (`backend/modules/compute/engine.py`):
```python
# Add to _apply_step method
elif operation == 'unpivot':
    index_cols = params.get('index', [])
    value_cols = params.get('value_vars', None)
    variable_name = params.get('variable_name', 'variable')
    value_name = params.get('value_name', 'value')
    
    return df.unpivot(
        on=value_cols,
        index=index_cols,
        variable_name=variable_name,
        value_name=value_name
    )
```

**Frontend Component** (`frontend/src/lib/components/operations/UnpivotConfig.svelte`):
```svelte
<script lang="ts">
  import type { PipelineStep } from '$lib/types/analysis';
  
  interface Props {
    step: PipelineStep;
    schema: Record<string, string>;
  }
  
  let { step, schema }: Props = $props();
  
  let config = $state({
    index: [] as string[],
    value_vars: [] as string[],
    variable_name: 'variable',
    value_name: 'value'
  });
  
  let availableColumns = $derived(Object.keys(schema));
</script>

<div class="unpivot-config">
  <div class="field">
    <label>ID Columns (keep as-is)</label>
    <select multiple bind:value={config.index}>
      {#each availableColumns as col}
        <option value={col}>{col}</option>
      {/each}
    </select>
  </div>
  
  <div class="field">
    <label>Value Columns (melt into rows)</label>
    <select multiple bind:value={config.value_vars}>
      {#each availableColumns as col}
        <option value={col}>{col}</option>
      {/each}
    </select>
  </div>
  
  <div class="field">
    <label>Variable Column Name</label>
    <input type="text" bind:value={config.variable_name} />
  </div>
  
  <div class="field">
    <label>Value Column Name</label>
    <input type="text" bind:value={config.value_name} />
  </div>
</div>
```

**Integration Tasks**:
- [ ] Add `unpivot` to operation enum in backend schemas
- [ ] Update `_apply_step` in `engine.py` with unpivot logic
- [ ] Create `UnpivotConfig.svelte` component
- [ ] Add to `StepLibrary.svelte` operations palette
- [ ] Add schema calculation logic in `transformation-rules.ts`
- [ ] Write backend unit tests for unpivot operation
- [ ] Write frontend component tests
- [ ] Update API documentation

**Estimated Effort**: Medium (4-6 hours)

---

### 2. Sample

**Description**: Randomly samples rows from the DataFrame, either by count or fraction. Essential for working with large datasets, creating training/test splits, or quick data exploration without processing entire datasets.

**Polars Method**: `df.sample(n=..., fraction=..., with_replacement=..., seed=...)`

**Use Cases**: 
- Creating training/test splits for machine learning
- Quick preview of large datasets
- Statistical sampling for analysis
- Performance testing with subset of data

**Backend Implementation** (`backend/modules/compute/engine.py`):
```python
# Add to _apply_step method
elif operation == 'sample':
    sample_type = params.get('sample_type', 'n')  # 'n' or 'fraction'
    n = params.get('n', None)
    fraction = params.get('fraction', None)
    with_replacement = params.get('with_replacement', False)
    seed = params.get('seed', None)
    shuffle = params.get('shuffle', True)
    
    if sample_type == 'n' and n is not None:
        return df.sample(n=n, with_replacement=with_replacement, shuffle=shuffle, seed=seed)
    elif sample_type == 'fraction' and fraction is not None:
        return df.sample(fraction=fraction, with_replacement=with_replacement, shuffle=shuffle, seed=seed)
    else:
        raise ValueError('Must specify either n or fraction for sampling')
```

**Frontend Component** (`frontend/src/lib/components/operations/SampleConfig.svelte`):
```svelte
<script lang="ts">
  interface Props {
    step: PipelineStep;
    schema: Record<string, string>;
  }
  
  let { step }: Props = $props();
  
  let config = $state({
    sample_type: 'n' as 'n' | 'fraction',
    n: 100,
    fraction: 0.1,
    with_replacement: false,
    shuffle: true,
    seed: null as number | null
  });
</script>

<div class="sample-config">
  <div class="field">
    <label>Sample Type</label>
    <select bind:value={config.sample_type}>
      <option value="n">By Count</option>
      <option value="fraction">By Fraction</option>
    </select>
  </div>
  
  {#if config.sample_type === 'n'}
    <div class="field">
      <label>Number of Rows</label>
      <input type="number" min="1" bind:value={config.n} />
    </div>
  {:else}
    <div class="field">
      <label>Fraction (0-1)</label>
      <input type="number" min="0" max="1" step="0.01" bind:value={config.fraction} />
    </div>
  {/if}
  
  <div class="field">
    <label>
      <input type="checkbox" bind:checked={config.with_replacement} />
      Sample with Replacement
    </label>
  </div>
  
  <div class="field">
    <label>
      <input type="checkbox" bind:checked={config.shuffle} />
      Shuffle Results
    </label>
  </div>
  
  <div class="field">
    <label>Random Seed (optional)</label>
    <input type="number" bind:value={config.seed} />
  </div>
</div>
```

**Integration Tasks**:
- [ ] Add `sample` operation to backend
- [ ] Create `SampleConfig.svelte` component
- [ ] Add to operations palette
- [ ] Schema calculation (preserves all columns, reduces row count)
- [ ] Write tests
- [ ] Documentation

**Estimated Effort**: Small (2-3 hours)

---

### 3. Cast (Type Conversion)

**Description**: Converts column data types to different types (string to int, float to int, date to string, etc.). Critical for data cleaning, preparing data for operations that require specific types, and fixing type inference issues.

**Polars Method**: `df.cast()` or `df.with_columns(pl.col(...).cast(...))`

**Use Cases**: 
- Converting string columns to numeric for calculations
- Converting numeric IDs to strings
- Changing date formats or precision
- Fixing type inference errors from CSV imports

**Backend Implementation** (`backend/modules/compute/engine.py`):
```python
# Add to _apply_step method
elif operation == 'cast':
    casting = params.get('casting', {})  # {column_name: target_type}
    strict = params.get('strict', True)
    
    cast_exprs = []
    for col_name, target_type in casting.items():
        # Map string types to Polars types
        dtype_map = {
            'Int64': pl.Int64,
            'Int32': pl.Int32,
            'Float64': pl.Float64,
            'Float32': pl.Float32,
            'String': pl.String,
            'Boolean': pl.Boolean,
            'Date': pl.Date,
            'Datetime': pl.Datetime,
        }
        
        if target_type in dtype_map:
            polars_dtype = dtype_map[target_type]
            cast_exprs.append(pl.col(col_name).cast(polars_dtype, strict=strict))
        else:
            raise ValueError(f'Unsupported target type: {target_type}')
    
    return df.with_columns(cast_exprs)
```

**Frontend Component** (`frontend/src/lib/components/operations/CastConfig.svelte`):
```svelte
<script lang="ts">
  interface Props {
    step: PipelineStep;
    schema: Record<string, string>;
  }
  
  let { step, schema }: Props = $props();
  
  let config = $state({
    casting: {} as Record<string, string>,
    strict: true
  });
  
  let availableColumns = $derived(Object.keys(schema));
  let selectedColumn = $state('');
  let targetType = $state('Int64');
  
  const availableTypes = [
    'Int64', 'Int32', 'Float64', 'Float32', 
    'String', 'Boolean', 'Date', 'Datetime'
  ];
  
  function addCast() {
    if (selectedColumn) {
      config.casting[selectedColumn] = targetType;
      config.casting = { ...config.casting };
    }
  }
  
  function removeCast(col: string) {
    delete config.casting[col];
    config.casting = { ...config.casting };
  }
</script>

<div class="cast-config">
  <div class="field">
    <label>Add Column Conversion</label>
    <div class="add-cast">
      <select bind:value={selectedColumn}>
        <option value="">Select column...</option>
        {#each availableColumns as col}
          <option value={col}>{col} ({schema[col]})</option>
        {/each}
      </select>
      <select bind:value={targetType}>
        {#each availableTypes as type}
          <option value={type}>{type}</option>
        {/each}
      </select>
      <button onclick={addCast}>Add</button>
    </div>
  </div>
  
  <div class="field">
    <label>Conversions</label>
    <ul class="cast-list">
      {#each Object.entries(config.casting) as [col, type]}
        <li>
          {col}: {schema[col]} → {type}
          <button onclick={() => removeCast(col)}>Remove</button>
        </li>
      {/each}
    </ul>
  </div>
  
  <div class="field">
    <label>
      <input type="checkbox" bind:checked={config.strict} />
      Strict Mode (fail on invalid conversions)
    </label>
  </div>
</div>
```

**Integration Tasks**:
- [ ] Add `cast` operation to backend
- [ ] Create `CastConfig.svelte` component
- [ ] Add to operations palette
- [ ] Schema calculation (update types for casted columns)
- [ ] Handle casting errors gracefully
- [ ] Write comprehensive tests for type conversions
- [ ] Documentation with type compatibility matrix

**Estimated Effort**: Medium (5-7 hours)

---

### 4. Head/Tail/Limit

**Description**: Returns the first N rows (head), last N rows (tail), or limits output to N rows. Essential for quick data preview, pagination, and working with subsets of data.

**Polars Method**: `df.head(n)`, `df.tail(n)`, `df.limit(n)`

**Use Cases**: 
- Quick preview of dataset structure
- Testing transformations on small subset
- Pagination in data viewers
- Limiting output size for performance

**Backend Implementation** (`backend/modules/compute/engine.py`):
```python
# Add to _apply_step method
elif operation == 'limit':
    limit_type = params.get('limit_type', 'head')  # 'head', 'tail', or 'limit'
    n = params.get('n', 10)
    
    if limit_type == 'head':
        return df.head(n)
    elif limit_type == 'tail':
        return df.tail(n)
    elif limit_type == 'limit':
        return df.limit(n)
    else:
        raise ValueError(f'Unsupported limit type: {limit_type}')
```

**Frontend Component** (`frontend/src/lib/components/operations/LimitConfig.svelte`):
```svelte
<script lang="ts">
  interface Props {
    step: PipelineStep;
  }
  
  let { step }: Props = $props();
  
  let config = $state({
    limit_type: 'head' as 'head' | 'tail' | 'limit',
    n: 10
  });
</script>

<div class="limit-config">
  <div class="field">
    <label>Operation</label>
    <select bind:value={config.limit_type}>
      <option value="head">Head (first N rows)</option>
      <option value="tail">Tail (last N rows)</option>
      <option value="limit">Limit (first N rows, alias)</option>
    </select>
  </div>
  
  <div class="field">
    <label>Number of Rows</label>
    <input type="number" min="1" bind:value={config.n} />
  </div>
</div>
```

**Integration Tasks**:
- [ ] Add `limit` operation to backend
- [ ] Create `LimitConfig.svelte` component
- [ ] Add to operations palette
- [ ] Schema calculation (preserve schema, update row count)
- [ ] Write tests
- [ ] Documentation

**Estimated Effort**: Small (2-3 hours)

---

### 7. Rank

**Description**: Assigns rank values to rows based on column values. Essential for finding top-N items, percentile calculations, and competitive rankings.

**Polars Method**: Expression-based with `pl.col().rank()`

**Use Cases**: 
- Top 10 products by sales
- Student rankings by score
- Percentile calculations
- Dense vs standard ranking

**Backend Implementation** (`backend/modules/compute/engine.py`):
```python
# Add to _apply_step method
elif operation == 'rank':
    column = params.get('column')
    new_column = params.get('new_column')
    method = params.get('method', 'average')  # 'average', 'min', 'max', 'dense', 'ordinal', 'random'
    descending = params.get('descending', False)
    
    rank_expr = pl.col(column).rank(method=method, descending=descending).alias(new_column)
    return df.with_columns(rank_expr)
```

**Frontend Component** (`frontend/src/lib/components/operations/RankConfig.svelte`):
```svelte
<script lang="ts">
  interface Props {
    step: PipelineStep;
    schema: Record<string, string>;
  }
  
  let { step, schema }: Props = $props();
  
  let config = $state({
    column: '',
    new_column: '',
    method: 'average',
    descending: false
  });
  
  let availableColumns = $derived(Object.keys(schema));
  
  const rankMethods = [
    { value: 'average', label: 'Average (ties get average rank)' },
    { value: 'min', label: 'Min (ties get minimum rank)' },
    { value: 'max', label: 'Max (ties get maximum rank)' },
    { value: 'dense', label: 'Dense (no gaps in ranking)' },
    { value: 'ordinal', label: 'Ordinal (all unique ranks)' },
    { value: 'random', label: 'Random (ties broken randomly)' }
  ];
</script>

<div class="rank-config">
  <div class="field">
    <label>Column to Rank</label>
    <select bind:value={config.column}>
      <option value="">Select column...</option>
      {#each availableColumns as col}
        <option value={col}>{col}</option>
      {/each}
    </select>
  </div>
  
  <div class="field">
    <label>Rank Method</label>
    <select bind:value={config.method}>
      {#each rankMethods as method}
        <option value={method.value}>{method.label}</option>
      {/each}
    </select>
  </div>
  
  <div class="field">
    <label>New Column Name</label>
    <input type="text" bind:value={config.new_column} 
           placeholder={`${config.column}_rank`} />
  </div>
  
  <div class="field">
    <label>
      <input type="checkbox" bind:checked={config.descending} />
      Descending (highest value gets rank 1)
    </label>
  </div>
</div>
```

**Integration Tasks**:
- [ ] Add `rank` operation to backend
- [ ] Create `RankConfig.svelte` component
- [ ] Add to operations palette
- [ ] Schema calculation (add Int64 rank column)
- [ ] Write tests for different rank methods
- [ ] Documentation with examples

**Estimated Effort**: Medium (4-5 hours)

---

### 8. With Columns (Add/Transform Columns)

**Description**: Adds new columns or transforms existing ones using expressions. More flexible than the current "Expression" operation, allowing multiple columns to be added/modified at once with simple operations.

**Polars Method**: `df.with_columns()`

**Use Cases**: 
- Calculate profit = revenue - cost
- Create full_name = first_name + last_name
- Convert units (celsius to fahrenheit)
- Create indicator/flag columns

**Backend Implementation** (`backend/modules/compute/engine.py`):
```python
# Add to _apply_step method  
elif operation == 'add_columns':
    columns = params.get('columns', [])
    
    exprs = []
    for col_config in columns:
        col_name = col_config['name']
        expr_type = col_config['type']
        
        if expr_type == 'literal':
            expr = pl.lit(col_config['value']).alias(col_name)
        elif expr_type == 'column':
            expr = pl.col(col_config['source_column']).alias(col_name)
        elif expr_type == 'arithmetic':
            # Support basic arithmetic between columns and literals
            left = col_config['left']
            right = col_config['right']
            operator = col_config['operator']  # '+', '-', '*', '/', '//', '%', '**'
            
            left_expr = pl.col(left) if isinstance(left, str) else pl.lit(left)
            right_expr = pl.col(right) if isinstance(right, str) else pl.lit(right)
            
            if operator == '+':
                expr = (left_expr + right_expr).alias(col_name)
            elif operator == '-':
                expr = (left_expr - right_expr).alias(col_name)
            elif operator == '*':
                expr = (left_expr * right_expr).alias(col_name)
            elif operator == '/':
                expr = (left_expr / right_expr).alias(col_name)
            elif operator == '//':
                expr = (left_expr // right_expr).alias(col_name)
            elif operator == '%':
                expr = (left_expr % right_expr).alias(col_name)
            elif operator == '**':
                expr = (left_expr ** right_expr).alias(col_name)
            else:
                raise ValueError(f'Unsupported operator: {operator}')
        elif expr_type == 'concat':
            # String concatenation
            parts = col_config['parts']
            separator = col_config.get('separator', '')
            
            part_exprs = []
            for part in parts:
                if isinstance(part, str) and part in df.columns:
                    part_exprs.append(pl.col(part))
                else:
                    part_exprs.append(pl.lit(str(part)))
            
            if separator:
                expr = pl.concat_str(part_exprs, separator=separator).alias(col_name)
            else:
                expr = pl.concat_str(part_exprs).alias(col_name)
        else:
            raise ValueError(f'Unsupported expression type: {expr_type}')
        
        exprs.append(expr)
    
    return df.with_columns(exprs)
```

**Frontend Component** (`frontend/src/lib/components/operations/AddColumnsConfig.svelte`):
```svelte
<script lang="ts">
  interface Props {
    step: PipelineStep;
    schema: Record<string, string>;
  }
  
  let { step, schema }: Props = $props();
  
  interface ColumnDef {
    name: string;
    type: 'literal' | 'column' | 'arithmetic' | 'concat';
    value?: any;
    source_column?: string;
    left?: string | number;
    right?: string | number;
    operator?: string;
    parts?: (string | any)[];
    separator?: string;
  }
  
  let config = $state({
    columns: [] as ColumnDef[]
  });
  
  let availableColumns = $derived(Object.keys(schema));
  
  function addColumn() {
    config.columns.push({
      name: '',
      type: 'literal',
      value: ''
    });
    config.columns = [...config.columns];
  }
  
  function removeColumn(index: number) {
    config.columns.splice(index, 1);
    config.columns = [...config.columns];
  }
</script>

<div class="add-columns-config">
  <button onclick={addColumn}>Add Column</button>
  
  {#each config.columns as col, i}
    <div class="column-def">
      <div class="field">
        <label>Column Name</label>
        <input type="text" bind:value={col.name} />
      </div>
      
      <div class="field">
        <label>Type</label>
        <select bind:value={col.type}>
          <option value="literal">Literal Value</option>
          <option value="column">Copy Column</option>
          <option value="arithmetic">Arithmetic</option>
          <option value="concat">Concatenate</option>
        </select>
      </div>
      
      {#if col.type === 'literal'}
        <div class="field">
          <label>Value</label>
          <input type="text" bind:value={col.value} />
        </div>
      {:else if col.type === 'column'}
        <div class="field">
          <label>Source Column</label>
          <select bind:value={col.source_column}>
            {#each availableColumns as c}
              <option value={c}>{c}</option>
            {/each}
          </select>
        </div>
      {:else if col.type === 'arithmetic'}
        <div class="arithmetic-builder">
          <input type="text" bind:value={col.left} placeholder="Column or value" />
          <select bind:value={col.operator}>
            <option value="+">+</option>
            <option value="-">-</option>
            <option value="*">×</option>
            <option value="/">÷</option>
            <option value="//">// (floor div)</option>
            <option value="%">% (modulo)</option>
            <option value="**">** (power)</option>
          </select>
          <input type="text" bind:value={col.right} placeholder="Column or value" />
        </div>
      {:else if col.type === 'concat'}
        <div class="field">
          <label>Parts (comma-separated columns/values)</label>
          <input type="text" placeholder="first_name, ' ', last_name" />
        </div>
        <div class="field">
          <label>Separator</label>
          <input type="text" bind:value={col.separator} />
        </div>
      {/if}
      
      <button onclick={() => removeColumn(i)}>Remove</button>
    </div>
  {/each}
</div>
```

**Integration Tasks**:
- [ ] Add `add_columns` operation to backend
- [ ] Create `AddColumnsConfig.svelte` component
- [ ] Add to operations palette
- [ ] Schema calculation (add new columns with inferred types)
- [ ] Write tests for different expression types
- [ ] Add expression builder UI
- [ ] Documentation

**Estimated Effort**: Large (10-12 hours)

---

## Medium Priority Operations

### 9. Unique (Get Unique Rows)

**Description**: Returns unique rows based on specified columns, similar to SQL DISTINCT. Different from deduplicate as it's specifically for getting distinct values.

**Polars Method**: `df.unique(subset=...)`

**Use Cases**: 
- Get unique customer IDs
- Find distinct product categories
- Remove exact duplicate rows
- Get unique combinations of columns

**Backend Implementation** (`backend/modules/compute/engine.py`):
```python
# Note: This is similar to deduplicate but included for completeness
# Current deduplicate implementation already uses df.unique()
# Could enhance to make it more explicit or combine into one operation
```

**Integration Tasks**:
- [ ] Evaluate if separate from deduplicate or enhance existing operation
- [ ] Update documentation to clarify unique vs deduplicate

**Estimated Effort**: Small (1-2 hours if separate operation)

---

### 13. Transpose

**Description**: Flips rows and columns (transpose matrix). Useful for restructuring data, converting row-based to column-based format.

**Polars Method**: `df.transpose()`

**Use Cases**: 
- Convert time-series from rows to columns
- Restructure summary statistics
- Pivot tables alternative
- Matrix operations

**Backend Implementation** (`backend/modules/compute/engine.py`):
```python
# Add to _apply_step method
elif operation == 'transpose':
    include_header = params.get('include_header', True)
    header_name = params.get('header_name', 'column')
    column_names = params.get('column_names', None)
    
    return df.transpose(
        include_header=include_header,
        header_name=header_name,
        column_names=column_names
    )
```

**Frontend Component** (`frontend/src/lib/components/operations/TransposeConfig.svelte`):
```svelte
<script lang="ts">
  interface Props {
    step: PipelineStep;
  }
  
  let { step }: Props = $props();
  
  let config = $state({
    include_header: true,
    header_name: 'column',
    column_names: null as string[] | null
  });
</script>

<div class="transpose-config">
  <div class="field">
    <label>
      <input type="checkbox" bind:checked={config.include_header} />
      Include Original Column Names as First Column
    </label>
  </div>
  
  {#if config.include_header}
    <div class="field">
      <label>Header Column Name</label>
      <input type="text" bind:value={config.header_name} />
    </div>
  {/if}
  
  <div class="info">
    Note: Transpose will convert all columns to same type. Row count and column count will swap.
  </div>
</div>
```

**Integration Tasks**:
- [ ] Add `transpose` operation to backend
- [ ] Create `TransposeConfig.svelte` component
- [ ] Add to operations palette
- [ ] Schema calculation (complex - swaps rows/cols)
- [ ] Write tests
- [ ] Documentation with warnings about type conversion

**Estimated Effort**: Medium (4-5 hours)

---

### 14. Concatenate/Stack Rows (VStack)

**Description**: Appends rows from another DataFrame vertically. Useful for combining multiple datasets with same schema.

**Polars Method**: `df.vstack(other)` or `pl.concat([df1, df2], how='vertical')`

**Use Cases**: 
- Combine monthly datasets
- Append new data to existing dataset
- Union multiple data sources
- Batch processing results

**Backend Implementation** (`backend/modules/compute/engine.py`):
```python
# Add to _apply_step method
elif operation == 'vstack':
    # This would require referencing another datasource or step
    other_step_id = params.get('other_step_id')
    # Would need to get the dataframe from that step
    # This is more complex and might require pipeline refactoring
    # For now, mark as future enhancement
    raise NotImplementedError('VStack requires multi-dataframe pipeline support')
```

**Integration Tasks**:
- [ ] Design multi-dataframe step dependencies
- [ ] Update pipeline execution to support dataframe references
- [ ] Add `vstack` operation
- [ ] Create config component with step selector
- [ ] Schema validation (ensure compatible schemas)
- [ ] Write tests
- [ ] Documentation

**Estimated Effort**: Large (12-15 hours - requires pipeline architecture changes)

---

### 15. Top K / Bottom K

**Description**: Returns top N or bottom N rows based on column values. More efficient than sort + limit for finding extremes.

**Polars Method**: `df.top_k(k, by=...)`, `df.bottom_k(k, by=...)`

**Use Cases**: 
- Top 10 customers by revenue
- Bottom 5 performers
- Highest/lowest values
- Leaderboards

**Backend Implementation** (`backend/modules/compute/engine.py`):
```python
# Add to _apply_step method
elif operation == 'top_k':
    k = params.get('k', 10)
    by = params.get('by', [])  # Column(s) to sort by
    operation_type = params.get('operation_type', 'top')  # 'top' or 'bottom'
    
    if operation_type == 'top':
        return df.top_k(k, by=by)
    elif operation_type == 'bottom':
        return df.bottom_k(k, by=by)
    else:
        raise ValueError(f'Unsupported operation type: {operation_type}')
```

**Frontend Component** (`frontend/src/lib/components/operations/TopKConfig.svelte`):
```svelte
<script lang="ts">
  interface Props {
    step: PipelineStep;
    schema: Record<string, string>;
  }
  
  let { step, schema }: Props = $props();
  
  let config = $state({
    k: 10,
    by: [] as string[],
    operation_type: 'top' as 'top' | 'bottom'
  });
  
  let availableColumns = $derived(Object.keys(schema));
</script>

<div class="topk-config">
  <div class="field">
    <label>Operation</label>
    <select bind:value={config.operation_type}>
      <option value="top">Top K (highest values)</option>
      <option value="bottom">Bottom K (lowest values)</option>
    </select>
  </div>
  
  <div class="field">
    <label>K (number of rows)</label>
    <input type="number" min="1" bind:value={config.k} />
  </div>
  
  <div class="field">
    <label>Sort By Columns</label>
    <select multiple bind:value={config.by}>
      {#each availableColumns as col}
        <option value={col}>{col}</option>
      {/each}
    </select>
  </div>
</div>
```

**Integration Tasks**:
- [ ] Add `top_k` operation to backend
- [ ] Create `TopKConfig.svelte` component
- [ ] Add to operations palette
- [ ] Schema calculation (preserve schema, limit rows)
- [ ] Write tests
- [ ] Documentation

**Estimated Effort**: Small (3-4 hours)

---

### 16. Null Count/Statistics

**Description**: Returns statistics about null values in each column. Useful for data quality assessment.

**Polars Method**: `df.null_count()`, `df.select(pl.all().is_null().sum())`

**Use Cases**: 
- Data quality assessment
- Finding columns with missing data
- Deciding which columns to drop/fill
- Data profiling

**Backend Implementation** (`backend/modules/compute/engine.py`):
```python
# Add to _apply_step method
elif operation == 'null_count':
    # Returns a single row with null counts for each column
    return df.null_count()
```

**Frontend Component**: Simple operation, no configuration needed beyond toggle.

**Integration Tasks**:
- [ ] Add `null_count` operation to backend
- [ ] Create simple config component
- [ ] Add to operations palette
- [ ] Schema calculation (single row, Int64 columns)
- [ ] Write tests
- [ ] Documentation

**Estimated Effort**: Small (2 hours)

---

### 17. Value Counts

**Description**: Returns frequency counts of unique values in a column. Essential for categorical data analysis.

**Polars Method**: `df.select(pl.col().value_counts())`

**Use Cases**: 
- Distribution of categories
- Frequency analysis
- Finding most common values
- Data profiling

**Backend Implementation** (`backend/modules/compute/engine.py`):
```python
# Add to _apply_step method
elif operation == 'value_counts':
    column = params.get('column')
    sort = params.get('sort', True)
    parallel = params.get('parallel', False)
    
    # Value counts returns a struct, need to unnest
    result = df.select(pl.col(column).value_counts(sort=sort, parallel=parallel))
    return result.unnest(column)
```

**Frontend Component** (`frontend/src/lib/components/operations/ValueCountsConfig.svelte`):
```svelte
<script lang="ts">
  interface Props {
    step: PipelineStep;
    schema: Record<string, string>;
  }
  
  let { step, schema }: Props = $props();
  
  let config = $state({
    column: '',
    sort: true
  });
  
  let availableColumns = $derived(Object.keys(schema));
</script>

<div class="value-counts-config">
  <div class="field">
    <label>Column</label>
    <select bind:value={config.column}>
      <option value="">Select column...</option>
      {#each availableColumns as col}
        <option value={col}>{col}</option>
      {/each}
    </select>
  </div>
  
  <div class="field">
    <label>
      <input type="checkbox" bind:checked={config.sort} />
      Sort by Count (descending)
    </label>
  </div>
</div>
```

**Integration Tasks**:
- [ ] Add `value_counts` operation to backend
- [ ] Create `ValueCountsConfig.svelte` component
- [ ] Add to operations palette
- [ ] Schema calculation (returns column + count columns)
- [ ] Write tests
- [ ] Documentation

**Estimated Effort**: Small (3-4 hours)

---

## Low Priority Operations

### 18. SQL Query

**Description**: Allows running SQL queries on the DataFrame. Advanced feature for users familiar with SQL.

**Polars Method**: `df.sql(query)`

**Use Cases**: 
- Users more comfortable with SQL
- Complex queries easier in SQL
- Legacy SQL code migration
- Education/learning

**Backend Implementation**: Already partially supported via expression operation, but could be enhanced.

**Estimated Effort**: Medium (6-8 hours)

---

### 19. Interpolate (Fill Missing with Interpolation)

**Description**: Fills missing values using linear or other interpolation methods. More sophisticated than simple forward/backward fill.

**Polars Method**: `df.interpolate()`

**Use Cases**: 
- Time-series gap filling
- Smooth missing value imputation
- Scientific data processing

**Backend Implementation** (`backend/modules/compute/engine.py`):
```python
# Add to _apply_step method
elif operation == 'interpolate':
    columns = params.get('columns', None)
    method = params.get('method', 'linear')
    
    if columns:
        return df.with_columns([pl.col(c).interpolate(method=method) for c in columns])
    return df.interpolate(method=method)
```

**Estimated Effort**: Medium (4-5 hours)

---

### 20. Correlation Matrix

**Description**: Computes correlation matrix between numeric columns. Useful for feature selection and exploratory analysis.

**Polars Method**: `df.corr()`

**Use Cases**: 
- Feature correlation analysis
- Multicollinearity detection
- Exploratory data analysis
- Feature selection for ML

**Estimated Effort**: Medium (5-6 hours) - requires special visualization

---

### 21. Group By Dynamic (Time-based Grouping)

**Description**: Groups time-series data by dynamic time windows (daily, weekly, monthly). More flexible than standard group by for temporal data.

**Polars Method**: `df.group_by_dynamic()`

**Use Cases**: 
- Daily/weekly/monthly aggregations
- Time-based rollups
- Financial reporting periods
- Seasonal analysis

**Estimated Effort**: Large (8-10 hours)

---

### 22. Cross Join

**Description**: Cartesian product of two DataFrames. Useful for generating all combinations.

**Polars Method**: `df.join(other, how='cross')`

**Use Cases**: 
- Generate all product-store combinations
- Scenario analysis (all parameter combinations)
- Testing data generation

**Estimated Effort**: Medium (4-5 hours) - requires multi-dataframe support

---

### 24. Round/Floor/Ceil

**Description**: Rounding operations on numeric columns.

**Polars Method**: `df.with_columns(pl.col().round()/floor()/ceil())`

**Use Cases**: 
- Rounding prices
- Discretizing continuous values
- Data cleaning

**Estimated Effort**: Small (2-3 hours)

---

### 25. Conditional Column (When/Then/Otherwise)

**Description**: Creates columns with conditional logic (SQL CASE WHEN equivalent).

**Polars Method**: `pl.when().then().otherwise()`

**Use Cases**: 
- Categorization based on conditions
- Flag creation
- Complex business logic
- Status indicators

**Backend Implementation** (`backend/modules/compute/engine.py`):
```python
# Add to _apply_step method
elif operation == 'when_then':
    new_column = params.get('new_column')
    conditions = params.get('conditions', [])  # List of {condition, then_value}
    otherwise_value = params.get('otherwise_value')
    
    # Build when/then/otherwise chain
    expr = None
    for cond in conditions:
        # Parse condition (simplified - would need full parser)
        col = cond['column']
        op = cond['operator']  # '==', '!=', '>', '<', '>=', '<='
        value = cond['value']
        then_val = cond['then_value']
        
        if op == '==':
            condition = pl.col(col) == value
        elif op == '!=':
            condition = pl.col(col) != value
        elif op == '>':
            condition = pl.col(col) > value
        elif op == '<':
            condition = pl.col(col) < value
        elif op == '>=':
            condition = pl.col(col) >= value
        elif op == '<=':
            condition = pl.col(col) <= value
        else:
            raise ValueError(f'Unsupported operator: {op}')
        
        if expr is None:
            expr = pl.when(condition).then(then_val)
        else:
            expr = expr.when(condition).then(then_val)
    
    expr = expr.otherwise(otherwise_value).alias(new_column)
    return df.with_columns(expr)
```

**Estimated Effort**: Large (10-12 hours)

---

## Implementation Strategy

**Recommended Implementation Order**:

1. **Phase 1 - Quick Wins (High Priority, Small Effort)**
   - Sample (2-3h)
   - Head/Tail/Limit (2-3h)
   - Slice (2h)
   - Reverse (1-2h)
   - Top K / Bottom K (3-4h)
   
2. **Phase 2 - Essential Operations (High Priority, Medium Effort)**
   - Unpivot/Melt (4-6h)
   - Cast (5-7h)
   - Rank (4-5h)
   - Shift (3-4h)
   
3. **Phase 3 - Advanced Analytics (High Priority, Large Effort)**
   - Window Functions (8-10h)
   - Add Columns / With Columns (10-12h)
   
4. **Phase 4 - Medium Priority Operations**
   - Binning/Cut (5-6h)
   - Value Counts (3-4h)
   - Transpose (4-5h)
   - Null Count (2h)
   - Interpolate (4-5h)
   
5. **Phase 5 - Advanced/Complex Operations**
   - Conditional When/Then (10-12h)
   - VStack (12-15h) - requires architecture changes
   - Group By Dynamic (8-10h)
   - SQL Query enhancement (6-8h)

**Total Estimated Effort**: ~130-170 hours for all operations

**Notes**:
- Start with Phase 1 to get quick wins and user feedback
- Window Functions and Add Columns are most valuable for analytics
- VStack and Cross Join require multi-dataframe pipeline support (architectural change)
- Conditional When/Then is complex but very powerful
- Consider user feedback to prioritize within phases
- Each operation should include comprehensive tests and documentation
- Some operations may benefit from visual query builders

**Technical Considerations**:
- Schema calculation must be updated for each operation in `transformation-rules.ts`
- Operations that add columns need careful type inference
- Multi-dataframe operations (VStack, Cross Join) require pipeline execution refactoring
- Some operations (like Window Functions) benefit from visual previews
- Error handling is critical for operations like Cast that can fail
- Performance considerations for large datasets (Sample, Limit, Head/Tail are performant)

**Dependencies**:
- No operation has hard dependencies on others
- VStack and Cross Join both require multi-dataframe architecture
- Conditional When/Then could reuse expression parsing if Expression operation has it
- Schema calculation system must be robust before complex operations

**User Experience Priorities**:
1. Visual query builders where possible (especially for Add Columns, When/Then)
2. Clear validation messages for configuration errors
3. Preview of operation results before applying
4. Good default values in configurations
5. Tooltips and examples in UI
6. Error messages that guide users to fixes
