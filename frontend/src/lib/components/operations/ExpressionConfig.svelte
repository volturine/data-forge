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

<div class="config-panel" role="region" aria-label="Expression configuration">
	<h3>Expression Configuration</h3>

	<div class="form-section" role="group" aria-labelledby="expr-expression-heading">
		<h4 id="expr-expression-heading">Expression</h4>
		<label for="expr-textarea-expression" class="sr-only">Polars expression</label>
		<textarea
			id="expr-textarea-expression"
			data-testid="expr-expression-textarea"
			bind:value={config.expression}
			placeholder="e.g., col(&quot;price&quot;) * 1.2 or col(&quot;first_name&quot;) + &quot; &quot; + col(&quot;last_name&quot;)"
			rows="4"
			aria-describedby="expr-expression-help"
		></textarea>
		<span id="expr-expression-help" class="sr-only"
			>Enter a Polars expression using col() function to reference columns</span
		>

		<div id="expr-syntax-help" class="help-text" aria-label="Syntax help">
			<strong>Polars Expression Syntax:</strong><br />
			Use <code>col("column_name")</code> to reference columns.<br />
			Examples:<br />
			• <code>col("price") * 1.2</code> - Multiply price by 1.2<br />
			• <code>col("first_name") + " " + col("last_name")</code> - Concatenate names<br />
			• <code>col("value").abs()</code> - Absolute value<br />
			• <code>col("date").dt.year()</code> - Extract year from date
		</div>
	</div>

	<div class="form-section" role="group" aria-labelledby="expr-new-column-heading">
		<h4 id="expr-new-column-heading">New Column Name</h4>
		<label for="expr-input-column" class="sr-only">New column name</label>
		<input
			id="expr-input-column"
			data-testid="expr-column-input"
			type="text"
			bind:value={config.column_name}
			placeholder="e.g., price_with_tax, full_name"
		/>
	</div>

	<div class="form-section" role="group" aria-labelledby="expr-columns-heading">
		<h4 id="expr-columns-heading">Available Columns</h4>
		<div id="expr-columns-grid" class="columns-grid" role="listbox" aria-label="Available columns">
			{#each schema.columns as column (column.name)}
				<button
					id={`expr-btn-column-${column.name}`}
					data-testid={`expr-column-button-${column.name}`}
					type="button"
					class="column-chip"
					onclick={() => insertColumn(column.name)}
					title="Click to insert into expression"
					aria-label={`Insert ${column.name} into expression`}
				>
					<span class="column-name">{column.name}</span>
					<span class="column-type">{column.dtype}</span>
				</button>
			{/each}
		</div>
		<p class="help-text">Click a column to insert it into the expression above.</p>
	</div>
</div>

<style>
	textarea {
		width: 100%;
		resize: vertical;
		margin-bottom: var(--space-2);
	}
	.help-text {
		font-size: var(--text-sm);
		color: var(--fg-tertiary);
		line-height: 1.6;
		padding: var(--space-3);
		background-color: var(--form-help-bg);
		border: 1px solid var(--form-help-border);
		border-left: 3px solid var(--form-help-accent);
		border-radius: var(--radius-sm);
	}
	.help-text code {
		background-color: var(--bg-tertiary);
		padding: var(--space-1) var(--space-2);
		border-radius: 3px;
		font-family: var(--font-mono);
		font-size: 0.85em;
		color: var(--accent-primary);
	}
	.columns-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
		gap: var(--space-2);
		margin-bottom: var(--space-2);
		max-height: 200px;
		overflow-y: auto;
		padding: var(--space-2);
		background-color: var(--bg-primary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
	}
	.column-chip {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-1);
		padding: var(--space-2) var(--space-3);
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
	.column-chip .column-name {
		font-weight: var(--font-medium);
		font-size: var(--text-sm);
	}
	.column-chip .column-type {
		font-size: var(--text-xs);
	}
</style>
