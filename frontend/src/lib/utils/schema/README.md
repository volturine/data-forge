# Schema Calculator

Client-side schema calculation utilities for the Polars-FastAPI-Svelte analysis platform.

## Overview

The Schema Calculator enables client-side prediction of output schemas for data transformation pipelines, eliminating the need for backend round-trips during pipeline construction.

## Files

- **`polars-types.ts`** (173 lines) - Polars data type constants and utilities
- **`transformation-rules.ts`** (214 lines) - Transformation rules for each operation type
- **`schema-calculator.svelte.ts`** (239 lines) - Main calculator class with Svelte 5 runes
- **`index.ts`** (25 lines) - Convenience exports
- **`example.ts`** (90 lines) - Usage examples

## Usage

### Basic Import

```typescript
import { schemaCalculator } from '$lib/utils/schema';
```

### Calculate Pipeline Schema

```typescript
import type { Schema } from '$lib/types/schema';
import type { PipelineStep } from '$lib/types/analysis';

const baseSchema: Schema = {
	columns: [
		{ name: 'id', dtype: 'Int64', nullable: false },
		{ name: 'name', dtype: 'String', nullable: false },
		{ name: 'salary', dtype: 'Float64', nullable: true }
	],
	row_count: 1000
};

const steps: PipelineStep[] = [
	{
		id: 'step_1',
		type: 'filter',
		config: { conditions: [{ column: 'salary', operator: '>', value: '50000' }] },
		depends_on: []
	},
	{
		id: 'step_2',
		type: 'select',
		config: { columns: ['name', 'salary'] },
		depends_on: ['step_1']
	}
];

// Get final schema
const result = schemaCalculator.calculatePipelineSchema(baseSchema, steps);
```

### Get Intermediate Schema

```typescript
// Get schema at a specific step
const intermediateSchema = schemaCalculator.getStepSchema(baseSchema, steps, 'step_1');
```

## Supported Operations

### Filter

- **Schema change**: None (affects rows only)
- **Config**: `{ conditions: Array, logic: 'AND' | 'OR' }`

### Select

- **Schema change**: Returns only selected columns
- **Config**: `{ columns: string[] }`

### Rename

- **Schema change**: Updates column names
- **Config**: `{ mapping: Record<string, string> }`

### GroupBy

- **Schema change**: Returns group keys + aggregation columns
- **Config**: `{ group_by: string[], aggregations: Record<string, string> }`
- **Aggregations**: count, sum, mean, median, min, max, std, var, first, last, n_unique

### Join

- **Schema change**: Merges left and right schemas
- **Config**: `{ how: 'inner' | 'left' | 'right' | 'outer', left_on: string[], right_on: string[], suffix: string }`

### Sort

- **Schema change**: None (affects order only)
- **Config**: `{ by: string[], descending: boolean[] }`

### Expression / WithColumn

- **Schema change**: Adds or replaces a column
- **Config**: `{ column_name: string, expression: string }`

### Drop

- **Schema change**: Removes specified columns
- **Config**: `{ columns: string[] }`

### Unique

- **Schema change**: None (affects rows only)
- **Config**: `{ subset?: string[] }`

### Cast

- **Schema change**: Changes column dtype
- **Config**: `{ column: string, dtype: string }`

## Data Types

```typescript
import { PolarsDType, isNumericDType, isTemporalDType } from '$lib/utils/schema';

// Check dtype categories
if (isNumericDType(column.dtype)) {
	// Handle numeric column
}

if (isTemporalDType(column.dtype)) {
	// Handle date/time column
}
```

Available dtypes: Int8, Int16, Int32, Int64, UInt8, UInt16, UInt32, UInt64, Float32, Float64, String, Utf8, Boolean, Date, Datetime, Time, Duration, Categorical, List, Struct, Null, Object

## Caching

The calculator includes built-in caching for performance:

```typescript
// Clear all cached schemas
schemaCalculator.clearCache();

// Clear cache for specific step
schemaCalculator.clearCacheFor('step_1');
```

## Design Decisions

1. **Svelte 5 Runes**: Uses `$state()` for reactive cache management
2. **Singleton Pattern**: Single shared instance via `schemaCalculator` export
3. **Type Safety**: Full TypeScript typing with Schema and PipelineStep interfaces
4. **Modular Design**: Separate transformation rules for maintainability
5. **Null Handling**: Propagates nullability based on operation semantics
6. **Dependency Tracking**: Supports multi-step pipelines with dependencies
7. **Expression Parsing**: Basic heuristics for expression result types

## Limitations

- Expression dtype inference uses heuristics (not full expression parsing)
- List and Struct dtypes have limited support
- Join key dtype compatibility not validated
- No validation of column existence before operations

## Future Enhancements

- Full expression parser for accurate dtype inference
- Schema validation before transformations
- Support for custom aggregation functions
- Polars expression builder integration
- Performance metrics and optimization
