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
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background-color: var(--panel-bg);
	}

	h3 {
		margin-top: 0;
		margin-bottom: 1rem;
		color: var(--panel-header-fg);
	}

	h4 {
		margin-top: 0;
		margin-bottom: 0.75rem;
		font-size: 1rem;
		color: var(--fg-secondary);
	}

	.section {
		margin-bottom: 1.5rem;
		padding: 1rem;
		background-color: var(--form-section-bg);
		border-radius: var(--radius-md);
		border: 1px solid var(--form-section-border);
	}

	textarea {
		width: 100%;
		padding: 0.75rem;
		border: 1px solid var(--form-control-border);
		border-radius: var(--radius-sm);
		font-family: var(--font-mono);
		font-size: 0.875rem;
		resize: vertical;
		margin-bottom: 0.5rem;
		background-color: var(--form-control-bg);
		color: var(--fg-primary);
	}

	input[type='text'] {
		width: 100%;
		padding: 0.5rem;
		border: 1px solid var(--form-control-border);
		border-radius: var(--radius-sm);
		background-color: var(--form-control-bg);
		color: var(--fg-primary);
	}

	.help-text {
		font-size: 0.875rem;
		color: var(--fg-tertiary);
		line-height: 1.6;
		padding: 0.75rem;
		background-color: var(--form-help-bg);
		border-left: 3px solid var(--form-help-accent);
		border-radius: var(--radius-sm);
		border: 1px solid var(--form-help-border);
	}

	.help-text code {
		background-color: var(--bg-tertiary);
		padding: 0.125rem 0.375rem;
		border-radius: 3px;
		font-family: var(--font-mono);
		font-size: 0.85em;
		color: var(--accent-primary);
	}

	.columns-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
		gap: 0.5rem;
		margin-bottom: 0.5rem;
		max-height: 200px;
		overflow-y: auto;
		padding: 0.5rem;
		background-color: var(--bg-primary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
	}

	.column-chip {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 0.25rem;
		padding: 0.5rem 0.75rem;
		background-color: var(--info-bg);
		border: 1px solid var(--info-border);
		border-radius: var(--radius-sm);
		cursor: pointer;
		transition: all 0.2s;
		color: var(--info-fg);
	}

	.column-chip:hover {
		background-color: var(--bg-hover);
		border-color: var(--border-focus);
		transform: translateY(-1px);
	}

	.column-name {
		font-weight: 500;
		font-size: 0.875rem;
		color: var(--fg-primary);
	}

	.column-type {
		font-size: 0.75rem;
		color: var(--fg-tertiary);
		font-family: var(--font-mono);
	}

	button:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
