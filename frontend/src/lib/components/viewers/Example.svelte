<!-- Example usage of the viewer components -->
<script lang="ts">
	import { SchemaViewer, DataTable, StatsPanel } from '$lib/components/viewers';
	import type { Schema } from '$lib/types/schema';

	// Example schema data
	const exampleSchema: Schema = {
		columns: [
			{ name: 'id', dtype: 'Int64', nullable: false },
			{ name: 'name', dtype: 'Utf8', nullable: false },
			{ name: 'age', dtype: 'Int32', nullable: true },
			{ name: 'price', dtype: 'Float64', nullable: true },
			{ name: 'active', dtype: 'Boolean', nullable: false },
			{ name: 'created_at', dtype: 'Datetime', nullable: false }
		],
		row_count: 1000
	};

	// Example table data
	const exampleColumns = ['id', 'name', 'age', 'price', 'active'];
	const exampleData = [
		{ id: 1, name: 'Alice', age: 30, price: 99.99, active: true },
		{ id: 2, name: 'Bob', age: 25, price: 149.99, active: true },
		{ id: 3, name: 'Charlie', age: null, price: 79.99, active: false },
		{ id: 4, name: 'Diana', age: 35, price: 199.99, active: true },
		{ id: 5, name: 'Eve', age: 28, price: 129.99, active: true }
	];

	// Example stats
	const exampleStats = {
		age: { mean: 29.5, min: 25, max: 35, nullCount: 1 },
		price: { mean: 131.99, min: 79.99, max: 199.99, nullCount: 0 }
	};

	let loading = $state(false);

	function handleSort(column: string, direction: 'asc' | 'desc') {
		console.log(`Sorting by ${column} in ${direction} order`);
	}
</script>

<div class="demo-container">
	<h1>Data Viewer Components Demo</h1>

	<section>
		<h2>Schema Viewer</h2>
		<SchemaViewer schema={exampleSchema} />
	</section>

	<section>
		<h2>Data Table</h2>
		<DataTable columns={exampleColumns} data={exampleData} {loading} onSort={handleSort} />
	</section>

	<section>
		<h2>Stats Panel</h2>
		<StatsPanel rowCount={1000} columnCount={6} stats={exampleStats} />
	</section>
</div>

<style>
	.demo-container {
		max-width: 1200px;
		margin: 0 auto;
		padding: 2rem;
	}

	h1 {
		margin-bottom: 2rem;
		color: #111827;
	}

	section {
		margin-bottom: 3rem;
	}

	h2 {
		margin-bottom: 1rem;
		font-size: 1.25rem;
		color: #374151;
	}
</style>
