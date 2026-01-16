<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	interface ExpressionConfigData {
		expression: string;
		column_name: string;
	}

	interface Props {
		schema: Schema;
		config?: ExpressionConfigData;
	}

	let { schema, config = $bindable({ expression: '', column_name: '' }) }: Props = $props();

	function insertColumn(columnName: string) {
		const _cursorPos = 0;
		const colRef = `col("${columnName}")`;
		config.expression = config.expression ? `${config.expression} ${colRef}` : colRef;
	}
</script>

<div class="expression-config">
	<h3>Expression Configuration</h3>

	<div class="section">
		<h4>Expression</h4>
		<textarea
			bind:value={config.expression}
			placeholder="e.g., col(&quot;price&quot;) * 1.2 or col(&quot;first_name&quot;) + &quot; &quot; + col(&quot;last_name&quot;)"
			rows="4"
		></textarea>

		<div class="help-text">
			<strong>Polars Expression Syntax:</strong><br />
			Use <code>col("column_name")</code> to reference columns.<br />
			Examples:<br />
			• <code>col("price") * 1.2</code> - Multiply price by 1.2<br />
			• <code>col("first_name") + " " + col("last_name")</code> - Concatenate names<br />
			• <code>col("value").abs()</code> - Absolute value<br />
			• <code>col("date").dt.year()</code> - Extract year from date<br />
		</div>
	</div>

	<div class="section">
		<h4>New Column Name</h4>
		<input
			type="text"
			bind:value={config.column_name}
			placeholder="e.g., price_with_tax, full_name"
		/>
	</div>

	<div class="section">
		<h4>Available Columns</h4>
		<div class="columns-grid">
			{#each schema.columns as column (column.name)}
				<button
					type="button"
					class="column-chip"
					onclick={() => insertColumn(column.name)}
					title="Click to insert into expression"
				>
					<span class="column-name">{column.name}</span>
					<span class="column-type">{column.dtype}</span>
				</button>
			{/each}
		</div>
		<div class="help-text">Click a column to insert it into the expression above.</div>
	</div>
</div>

<style>
	.expression-config {
		padding: 1rem;
		border: 1px solid #ddd;
		border-radius: 4px;
	}

	h3 {
		margin-top: 0;
		margin-bottom: 1rem;
	}

	h4 {
		margin-top: 0;
		margin-bottom: 0.75rem;
		font-size: 1rem;
	}

	.section {
		margin-bottom: 1.5rem;
		padding: 1rem;
		background-color: #f8f9fa;
		border-radius: 4px;
	}

	textarea {
		width: 100%;
		padding: 0.75rem;
		border: 1px solid #ccc;
		border-radius: 4px;
		font-family: monospace;
		font-size: 0.875rem;
		resize: vertical;
		margin-bottom: 0.5rem;
	}

	input[type='text'] {
		width: 100%;
		padding: 0.5rem;
		border: 1px solid #ccc;
		border-radius: 4px;
	}

	.help-text {
		font-size: 0.875rem;
		color: #6c757d;
		line-height: 1.6;
		padding: 0.75rem;
		background-color: #fff;
		border-left: 3px solid #007bff;
		border-radius: 4px;
	}

	.help-text code {
		background-color: #f8f9fa;
		padding: 0.125rem 0.375rem;
		border-radius: 3px;
		font-family: monospace;
		font-size: 0.85em;
		color: #e83e8c;
	}

	.columns-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
		gap: 0.5rem;
		margin-bottom: 0.5rem;
		max-height: 200px;
		overflow-y: auto;
		padding: 0.5rem;
		background-color: white;
		border: 1px solid #ddd;
		border-radius: 4px;
	}

	.column-chip {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 0.25rem;
		padding: 0.5rem 0.75rem;
		background-color: #e7f3ff;
		border: 1px solid #bee5eb;
		border-radius: 4px;
		cursor: pointer;
		transition: all 0.2s;
	}

	.column-chip:hover {
		background-color: #d1ecf1;
		border-color: #007bff;
		transform: translateY(-1px);
	}

	.column-name {
		font-weight: 500;
		font-size: 0.875rem;
		color: #212529;
	}

	.column-type {
		font-size: 0.75rem;
		color: #6c757d;
		font-family: monospace;
	}

	button:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
