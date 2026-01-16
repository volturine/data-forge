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

	const operators = ['=', '!=', '>', '<', '>=', '<=', 'contains'];

	function addCondition() {
		config.conditions.push({ column: '', operator: '=', value: '' });
	}

	function removeCondition(index: number) {
		config.conditions.splice(index, 1);
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
				<option value="AND">AND</option>
				<option value="OR">OR</option>
			</select>
		</label>
	</div>

	<div class="conditions">
		{#each config.conditions as condition, i (i)}
			<div class="condition-row">
				<select bind:value={condition.column}>
					<option value="">Select column...</option>
					{#each schema.columns as column (column.name)}
						<option value={column.name}>{column.name} ({column.dtype})</option>
					{/each}
				</select>

				<select bind:value={condition.operator}>
					{#each operators as op (op)}
						<option value={op}>{op}</option>
					{/each}
				</select>

				<input
					type={getInputType(condition.column)}
					bind:value={condition.value}
					placeholder="Value"
				/>

				<button
					type="button"
					onclick={() => removeCondition(i)}
					disabled={config.conditions.length === 1}
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
		padding: 1rem;
		border: 1px solid var(--border-primary);
		border-radius: 4px;
	}

	h3 {
		margin-top: 0;
		margin-bottom: 1rem;
	}

	.logic-selector {
		margin-bottom: 1rem;
	}

	.logic-selector select {
		margin-left: 0.5rem;
		padding: 0.25rem 0.5rem;
	}

	.conditions {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		margin-bottom: 1rem;
	}

	.condition-row {
		display: flex;
		gap: 0.5rem;
		align-items: center;
	}

	.condition-row select,
	.condition-row input {
		padding: 0.5rem;
		border: 1px solid var(--border-primary);
		border-radius: 4px;
	}

	.condition-row select:first-child {
		flex: 2;
	}

	.condition-row select:nth-child(2) {
		flex: 1;
	}

	.condition-row input {
		flex: 2;
	}

	.condition-row button {
		padding: 0.5rem 1rem;
		background-color: var(--error-fg);
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
	}

	.condition-row button:disabled {
		background-color: var(--border-primary);
		cursor: not-allowed;
	}

	.add-btn {
		padding: 0.5rem 1rem;
		background-color: var(--success-fg);
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		margin-bottom: 1rem;
	}

	button:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
