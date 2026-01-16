# Data Viewer Components

This directory contains viewer components for displaying data in the analysis platform.

## Components

### SchemaViewer.svelte

Displays schema information with columns, data types, and nullable status.

**Props:**

- `schema: Schema` - Schema object containing columns and row count

**Features:**

- Column name, dtype, and nullable status display
- Type-specific icons and badges for different data types
- Color-coded badges (numeric, float, string, boolean, datetime, etc.)
- Hover effects for better UX

**Example:**

```svelte
<script lang="ts">
	import { SchemaViewer } from '$lib/components/viewers';
	import type { Schema } from '$lib/types/schema';

	const schema: Schema = {
		columns: [
			{ name: 'id', dtype: 'Int64', nullable: false },
			{ name: 'name', dtype: 'Utf8', nullable: false }
		],
		row_count: 1000
	};
</script>

<SchemaViewer {schema} />
```

### DataTable.svelte

Displays tabular data with sorting capabilities.

**Props:**

- `columns: string[]` - Array of column names
- `data: Record<string, any>[]` - Array of data rows
- `loading?: boolean` - Loading state (optional)
- `onSort?: (column: string, direction: 'asc' | 'desc') => void` - Sort callback (optional)

**Features:**

- Column sorting (click headers to sort)
- Loading state with spinner
- Empty state handling
- Value formatting (numbers, booleans, nulls)
- Responsive table with scrolling
- Row count display in footer

**Example:**

```svelte
<script lang="ts">
	import { DataTable } from '$lib/components/viewers';

	const columns = ['id', 'name', 'age'];
	const data = [
		{ id: 1, name: 'Alice', age: 30 },
		{ id: 2, name: 'Bob', age: 25 }
	];

	function handleSort(column: string, direction: 'asc' | 'desc') {
		console.log(`Sorting by ${column} in ${direction} order`);
	}
</script>

<DataTable {columns} {data} loading={false} onSort={handleSort} />
```

### StatsPanel.svelte

Displays summary statistics for the dataset.

**Props:**

- `rowCount: number` - Total number of rows
- `columnCount: number` - Total number of columns
- `stats?: Record<string, { mean?: number; min?: number; max?: number; nullCount?: number }>` - Column statistics (optional)

**Features:**

- Primary stats cards (rows, columns, data points)
- Optional column-level statistics
- Hover effects on stat cards
- Responsive grid layout

**Example:**

```svelte
<script lang="ts">
	import { StatsPanel } from '$lib/components/viewers';

	const stats = {
		age: { mean: 29.5, min: 25, max: 35, nullCount: 1 },
		price: { mean: 131.99, min: 79.99, max: 199.99 }
	};
</script>

<StatsPanel rowCount={1000} columnCount={6} {stats} />
```

## Usage

Import components individually or from the index:

```svelte
import {(SchemaViewer, DataTable, StatsPanel)} from '$lib/components/viewers';
```

See `Example.svelte` for a complete demo of all components.

## Styling

All components use scoped CSS with consistent color palette:

- Primary: `#3b82f6` (blue)
- Background: `#f9fafb` (light gray)
- Border: `#e5e7eb` (gray)
- Text: `#111827` (dark gray)

Components are designed to work together and share a consistent design language.
