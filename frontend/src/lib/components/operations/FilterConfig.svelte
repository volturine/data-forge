<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	interface FilterCondition {
		column: string;
		operator: string;
		value: string;
	}

	interface FilterConfigData {
		conditions: FilterCondition[];
		logic: 'AND' | 'OR';
	}

	interface Props {
		schema: Schema;
		config?: FilterConfigData;
	}

	let {
		schema,
		config = $bindable({ conditions: [{ column: '', operator: '=', value: '' }], logic: 'AND' })
	}: Props = $props();

	// Ensure config has proper structure (handles empty {} from step creation)
	$effect(() => {
		if (!config || typeof config !== 'object') {
			config = { conditions: [{ column: '', operator: '=', value: '' }], logic: 'AND' };
		} else {
			if (!Array.isArray(config.conditions)) {
				config.conditions = [{ column: '', operator: '=', value: '' }];
			}
			if (!config.logic) {
				config.logic = 'AND';
			}
		}
	});

	// Safe accessors
	let safeConditions = $derived(
		Array.isArray(config?.conditions)
			? config.conditions
			: [{ column: '', operator: '=', value: '' }]
	);
	let safeLogic = $derived(config?.logic ?? 'AND');

	const operators = ['=', '!=', '>', '<', '>=', '<=', 'contains', 'starts_with', 'ends_with'];

	function addCondition() {
		config.conditions = [...safeConditions, { column: '', operator: '=', value: '' }];
	}

	function updateCondition(index: number, updates: Partial<FilterCondition>) {
		const next = safeConditions.map((condition, i) =>
			i === index ? { ...condition, ...updates } : condition
		);
		config.conditions = next;
	}

	function removeCondition(index: number) {
		config.conditions = safeConditions.filter((_, i) => i !== index);
	}

	function getInputType(columnName: string): string {
		const column = schema.columns.find((c) => c.name === columnName);
		if (!column) return 'text';

		const dtype = column.dtype.toLowerCase();
		if (dtype.includes('int') || dtype.includes('float') || dtype.includes('decimal')) {
			return 'number';
		}
		return 'text';
	}
</script>

<div class="config-panel" role="region" aria-label="Filter configuration">
	<h3>Filter Configuration</h3>

	<div class="logic-selector">
		<label for="filter-select-logic">
			Combine conditions with:
			<select id="filter-select-logic" data-testid="filter-logic-select" bind:value={config.logic}>
				<option value="AND" selected={safeLogic === 'AND'}>AND</option>
				<option value="OR" selected={safeLogic === 'OR'}>OR</option>
			</select>
		</label>
	</div>

	<div class="conditions" role="group" aria-label="Filter conditions">
		{#each safeConditions as condition, i (i)}
			<div class="condition-row" role="group" aria-label={`Condition ${i + 1}`}>
				<label for={`filter-select-column-${i}`} class="sr-only">Column</label>
				<select
					id={`filter-select-column-${i}`}
					data-testid={`filter-column-select-${i}`}
					value={condition.column}
					onchange={(event) =>
						updateCondition(i, {
							column: (event.currentTarget as HTMLSelectElement).value
						})}
					aria-label="Select column"
				>
					<option value="">Select column...</option>
					{#each schema.columns as column (column.name)}
						<option value={column.name}>{column.name} ({column.dtype})</option>
					{/each}
				</select>

				<label for={`filter-select-operator-${i}`} class="sr-only">Operator</label>
				<select
					id={`filter-select-operator-${i}`}
					data-testid={`filter-operator-select-${i}`}
					value={condition.operator}
					onchange={(event) =>
						updateCondition(i, {
							operator: (event.currentTarget as HTMLSelectElement).value
						})}
					aria-label="Select operator"
				>
					{#each operators as op (op)}
						<option value={op}>{op}</option>
					{/each}
				</select>

				<label for={`filter-input-value-${i}`} class="sr-only">Value</label>
				<input
					id={`filter-input-value-${i}`}
					data-testid={`filter-value-input-${i}`}
					type={getInputType(condition.column)}
					value={condition.value}
					oninput={(event) =>
						updateCondition(i, {
							value: (event.currentTarget as HTMLInputElement).value
						})}
					placeholder="Value"
					aria-label="Filter value"
				/>

				<button
					id={`filter-btn-remove-${i}`}
					data-testid={`filter-remove-button-${i}`}
					type="button"
					onclick={() => removeCondition(i)}
					disabled={safeConditions.length === 1}
					aria-label={`Remove condition ${i + 1}`}
				>
					Remove
				</button>
			</div>
		{/each}
	</div>

	<button
		id="filter-btn-add-condition"
		data-testid="filter-add-condition-button"
		type="button"
		onclick={addCondition}
		class="add-btn"
		aria-label="Add new filter condition"
	>
		Add Condition
	</button>
</div>

<style>
	.logic-selector {
		margin-bottom: var(--space-4);
		color: var(--fg-secondary);
	}
	.logic-selector select {
		margin-left: var(--space-2);
		padding: var(--space-1) var(--space-2);
	}
	.conditions {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin-bottom: var(--space-4);
	}
	.condition-row {
		display: flex;
		gap: var(--space-2);
		align-items: center;
		flex-wrap: wrap;
	}
	.condition-row select:first-child {
		flex: 2;
		min-width: 160px;
	}
	.condition-row select:nth-child(2) {
		flex: 1;
		min-width: 120px;
	}
	.condition-row input {
		flex: 2;
		min-width: 160px;
	}
	.condition-row button {
		padding: var(--space-2) var(--space-4);
		background-color: var(--error-bg);
		color: var(--error-fg);
		border: 1px solid var(--error-border);
		border-radius: var(--radius-sm);
		cursor: pointer;
	}
	.condition-row button:disabled {
		background-color: var(--bg-muted);
		cursor: not-allowed;
		color: var(--fg-muted);
		border-color: var(--border-secondary);
	}
	.add-btn {
		padding: var(--space-2) var(--space-4);
		background-color: var(--accent-primary);
		color: var(--bg-primary);
		border: none;
		border-radius: var(--radius-sm);
		cursor: pointer;
		margin-bottom: var(--space-4);
	}
	button:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
