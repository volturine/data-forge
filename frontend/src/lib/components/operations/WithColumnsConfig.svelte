<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	interface WithColumnsExpr {
		name: string;
		type: 'literal' | 'column';
		value?: string | number | null;
		column?: string | null;
	}

	interface WithColumnsConfigData {
		expressions: WithColumnsExpr[];
	}

	interface Props {
		schema: Schema;
		config?: WithColumnsConfigData;
	}

	let { schema, config = $bindable({ expressions: [] }) }: Props = $props();

	let exprType = $state<'column' | 'literal'>('column');
	let exprName = $state('');
	let exprColumn = $state('');
	let exprValue = $state('');

	let canAdd = $derived(!!exprName && (exprType === 'column' ? !!exprColumn : exprValue !== ''));

	function addExpression() {
		if (!canAdd) return;
		const base: WithColumnsExpr =
			exprType === 'column'
				? { name: exprName, type: 'column', column: exprColumn }
				: { name: exprName, type: 'literal', value: exprValue };
		const expressions = Array.isArray(config.expressions) ? config.expressions : [];
		config.expressions = [...expressions, base];
		exprName = '';
		exprColumn = '';
		exprValue = '';
		exprType = 'column';
	}

	function removeExpression(index: number) {
		const expressions = Array.isArray(config.expressions) ? config.expressions : [];
		config.expressions = expressions.filter((expr: WithColumnsExpr, idx: number) => idx !== index);
	}
</script>

<div class="config-panel" role="region" aria-label="With columns configuration">
	<h3>With Columns Configuration</h3>

	<div class="form-section" role="group" aria-labelledby="withcols-add-heading">
		<h4 id="withcols-add-heading">Add Column</h4>
		<div class="add-row">
			<label for="withcols-input-name" class="sr-only">New column name</label>
			<input
				id="withcols-input-name"
				data-testid="withcols-name-input"
				type="text"
				bind:value={exprName}
				placeholder="New column name"
			/>

			<label for="withcols-select-type" class="sr-only">Expression type</label>
			<select id="withcols-select-type" bind:value={exprType}>
				<option value="column">From column</option>
				<option value="literal">Literal value</option>
			</select>
		</div>

		{#if exprType === 'column'}
			<div class="add-row">
				<label for="withcols-select-column" class="sr-only">Source column</label>
				<select id="withcols-select-column" bind:value={exprColumn}>
					<option value="">Select column...</option>
					{#each schema.columns as column (column.name)}
						<option value={column.name}>{column.name}</option>
					{/each}
				</select>
				<button
					id="withcols-btn-add"
					data-testid="withcols-add-button"
					type="button"
					onclick={addExpression}
					disabled={!canAdd}
				>
					Add
				</button>
			</div>
		{:else}
			<div class="add-row">
				<label for="withcols-input-value" class="sr-only">Literal value</label>
				<input
					id="withcols-input-value"
					data-testid="withcols-value-input"
					type="text"
					bind:value={exprValue}
					placeholder="Literal value"
				/>
				<button
					id="withcols-btn-add"
					data-testid="withcols-add-button"
					type="button"
					onclick={addExpression}
					disabled={!canAdd}
				>
					Add
				</button>
			</div>
		{/if}
	</div>

	{#if (config.expressions ?? []).length > 0}
		<div class="expressions-list" role="list" aria-label="Configured columns">
			<h4>Columns</h4>
			{#each config.expressions ?? [] as expr, index (index)}
				<div class="expression-item" role="listitem">
					<div class="expression-info">
						<span class="expr-name" title={expr.name}>{expr.name}</span>
						<span class="expr-meta">
							{expr.type === 'column' ? `from ${expr.column ?? ''}` : 'literal'}
						</span>
					</div>
					<button
						id={`withcols-btn-remove-${index}`}
						data-testid={`withcols-remove-button-${index}`}
						type="button"
						onclick={() => removeExpression(index)}
						aria-label={`Remove column ${expr.name}`}
					>
						×
					</button>
				</div>
			{/each}
		</div>
	{:else}
		<p class="empty-state" role="status">No columns configured yet.</p>
	{/if}
</div>

<style>
	.add-row {
		display: grid;
		grid-template-columns: 1fr auto auto;
		gap: var(--space-2);
		margin-bottom: var(--space-2);
	}
	.add-row input,
	.add-row select {
		min-width: 0;
	}
	.add-row button {
		padding: var(--space-2) var(--space-4);
		background-color: var(--accent-primary);
		color: var(--bg-primary);
		border: 1px solid var(--accent-primary);
		border-radius: var(--radius-sm);
		cursor: pointer;
		white-space: nowrap;
		font-weight: 600;
	}
	.add-row button:disabled {
		background-color: var(--panel-muted-bg);
		border-color: var(--panel-border);
		cursor: not-allowed;
		color: var(--fg-muted);
	}
	.expressions-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-3);
		background-color: var(--panel-muted-bg);
		border-radius: var(--radius-md);
		margin-bottom: var(--space-4);
		border: 1px solid var(--panel-border);
	}
	.expressions-list h4 {
		margin: 0 0 var(--space-2) 0;
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--fg-muted);
	}
	.expression-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--space-2) var(--space-3);
		background-color: var(--panel-bg);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
	}
	.expression-info {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
	}
	.expr-name {
		font-weight: 600;
		color: var(--fg-primary);
		max-width: 220px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.expr-meta {
		font-size: var(--text-xs);
		color: var(--fg-muted);
	}
	.expression-item button {
		width: 28px;
		height: 28px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		background-color: transparent;
		color: var(--fg-muted);
		border: 1px solid transparent;
		border-radius: 999px;
		cursor: pointer;
		font-size: 1.1rem;
		line-height: 1;
	}
	.expression-item button:hover:not(:disabled) {
		color: var(--fg-primary);
		background-color: var(--bg-hover);
		border-color: var(--panel-border);
	}
	.empty-state {
		padding: var(--space-6);
		text-align: center;
		color: var(--fg-muted);
		background-color: var(--panel-muted-bg);
		border-radius: var(--radius-md);
		margin-bottom: var(--space-4);
		border: 1px dashed var(--panel-border);
	}
	@media (max-width: 640px) {
		.add-row {
			grid-template-columns: 1fr;
		}
		.add-row button {
			width: 100%;
		}
	}
</style>
