<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';

	interface ExpressionConfigData {
		expression: string;
		column_name: string;
	}

	interface Props {
		schema: Schema;
		config?: ExpressionConfigData;
	}

	let { schema, config = $bindable({ expression: '', column_name: '' }) }: Props = $props();

	let selectedColumnToInsert = $state('');

	function insertColumn(columnName: string) {
		const colRef = `pl.col("${columnName}")`;
		config.expression = config.expression ? `${config.expression} ${colRef}` : colRef;
		selectedColumnToInsert = ''; // Reset selection after insert
	}

	// Watch for changes to selectedColumnToInsert and insert when changed
	$effect(() => {
		if (selectedColumnToInsert) {
			insertColumn(selectedColumnToInsert);
		}
	});
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
			placeholder="e.g., pl.col(&quot;price&quot;) * 1.2"
			rows="4"
			aria-describedby="expr-expression-help"
		></textarea>
		<span id="expr-expression-help" class="sr-only"
			>Enter a Polars expression using pl.col() to reference columns</span
		>

		<div id="expr-syntax-help" class="help-text" aria-label="Syntax help">
			<strong>Polars Expression Syntax:</strong><br />
			Use <code>pl.col("column")</code> to reference columns.<br />
			Examples:<br />
			• <code>pl.col("price") * 1.2</code> - Multiply<br />
			• <code>pl.col("value").cast(pl.Float64)</code> - Cast type<br />
			• <code>pl.col("name").str.to_uppercase()</code> - String method<br />
			• <code>pl.col("date").dt.year()</code> - Date component
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
		<h4 id="expr-columns-heading">Insert Column</h4>
		<ColumnDropdown
			{schema}
			value={selectedColumnToInsert}
			onChange={(val) => (selectedColumnToInsert = val)}
			placeholder="Select column to insert..."
		/>
		<p class="help-text">Select a column to insert it into the expression above.</p>
	</div>
</div>

<style>
	/* Component-specific styles - dropdown pattern defined in app.css */
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
</style>
