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

<div class="filter-config">
	<h3>Filter Configuration</h3>

	<div class="logic-selector">
		<label>
			Combine conditions with:
			<select bind:value={config.logic}>
				<option value="AND" selected={safeLogic === 'AND'}>AND</option>
				<option value="OR" selected={safeLogic === 'OR'}>OR</option>
			</select>
		</label>
	</div>

	<div class="conditions">
		{#each safeConditions as condition, i (i)}
			<div class="condition-row">
				<select
					value={condition.column}
					onchange={(event) =>
						updateCondition(i, {
							column: (event.currentTarget as HTMLSelectElement).value
						})}
				>
					<option value="">Select column...</option>
					{#each schema.columns as column (column.name)}
						<option value={column.name}>{column.name} ({column.dtype})</option>
					{/each}
				</select>

				<select
					value={condition.operator}
					onchange={(event) =>
						updateCondition(i, {
							operator: (event.currentTarget as HTMLSelectElement).value
						})}
				>
					{#each operators as op (op)}
						<option value={op}>{op}</option>
					{/each}
				</select>

				<input
					type={getInputType(condition.column)}
					value={condition.value}
					oninput={(event) =>
						updateCondition(i, {
							value: (event.currentTarget as HTMLInputElement).value
						})}
					placeholder="Value"
				/>

				<button
					type="button"
					onclick={() => removeCondition(i)}
					disabled={safeConditions.length === 1}
				>
					Remove
				</button>
			</div>
		{/each}
	</div>

	<button type="button" onclick={addCondition} class="add-btn">Add Condition</button>
</div>

<style>
	.filter-config {
		padding: var(--space-4);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background-color: var(--panel-bg);
	}

	h3 {
		margin-top: 0;
		margin-bottom: var(--space-4);
		color: var(--panel-header-fg);
	}

	.logic-selector {
		margin-bottom: var(--space-4);
		color: var(--fg-secondary);
	}

	.logic-selector select {
		margin-left: var(--space-2);
		padding: var(--space-1) var(--space-2);
		border: 1px solid var(--form-control-border);
		border-radius: var(--radius-sm);
		background-color: var(--form-control-bg);
		color: var(--fg-primary);
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

	.condition-row select,
	.condition-row input {
		padding: var(--space-2);
		border: 1px solid var(--form-control-border);
		border-radius: var(--radius-sm);
		background-color: var(--form-control-bg);
		color: var(--fg-primary);
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
