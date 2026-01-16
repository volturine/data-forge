<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	interface SortRule {
		column: string;
		descending: boolean;
	}

	interface Props {
		schema: Schema;
		config?: SortRule[];
	}

	let { schema, config = $bindable([]) }: Props = $props();

	// Ensure config is an array (handles empty {} from step creation)
	let safeConfig = $derived(Array.isArray(config) ? config : []);

	let newRule = $state<SortRule>({
		column: '',
		descending: false
	});

	function addSortRule() {
		if (!newRule.column) return;

		// Check if column is already in sort rules
		const exists = safeConfig.some((rule) => rule.column === newRule.column);
		if (exists) return;

		// Ensure config is an array before pushing
		if (!Array.isArray(config)) {
			config = [] as unknown as SortRule[];
		}
		config.push({
			column: newRule.column,
			descending: newRule.descending
		});

		newRule = {
			column: '',
			descending: false
		};
	}

	function removeSortRule(index: number) {
		if (Array.isArray(config)) {
			config.splice(index, 1);
		}
	}

	function toggleDirection(index: number) {
		if (Array.isArray(config) && config[index]) {
			config[index].descending = !config[index].descending;
		}
	}

	function moveUp(index: number) {
		if (!Array.isArray(config) || index === 0) return;
		const temp = config[index];
		config[index] = config[index - 1];
		config[index - 1] = temp;
	}

	function moveDown(index: number) {
		if (!Array.isArray(config) || index === config.length - 1) return;
		const temp = config[index];
		config[index] = config[index + 1];
		config[index + 1] = temp;
	}

	let availableColumns = $derived(
		schema.columns.filter((col) => !safeConfig.some((rule) => rule.column === col.name))
	);
</script>

<div class="sort-config">
	<h3>Sort Configuration</h3>

	<div class="add-rule">
		<select bind:value={newRule.column}>
			<option value="">Select column...</option>
			{#each availableColumns as column (column.name)}
				<option value={column.name}>{column.name} ({column.dtype})</option>
			{/each}
		</select>

		<label class="direction-toggle">
			<input type="checkbox" bind:checked={newRule.descending} />
			<span>Descending</span>
		</label>

		<button type="button" onclick={addSortRule} disabled={!newRule.column}> Add Sort Rule </button>
	</div>

	{#if safeConfig.length > 0}
		<div class="sort-rules">
			<h4>Sort Order (top to bottom)</h4>
			{#each safeConfig as rule, i (i)}
				<div class="sort-rule-item">
					<div class="rule-info">
						<span class="rule-column">{rule.column}</span>
						<button type="button" class="direction-btn" onclick={() => toggleDirection(i)}>
							{rule.descending ? '↓ DESC' : '↑ ASC'}
						</button>
					</div>

					<div class="rule-actions">
						<button type="button" onclick={() => moveUp(i)} disabled={i === 0} title="Move up">
							↑
						</button>
						<button
							type="button"
							onclick={() => moveDown(i)}
							disabled={i === safeConfig.length - 1}
							title="Move down"
						>
							↓
						</button>
						<button type="button" class="remove-btn" onclick={() => removeSortRule(i)}>
							Remove
						</button>
					</div>
				</div>
			{/each}
		</div>
	{:else}
		<p class="empty-state">No sort rules configured. Add a column to sort by.</p>
	{/if}
</div>

<style>
	.sort-config {
		padding: 1rem;
		border: 1px solid var(--border-primary);
		border-radius: 4px;
	}

	h3 {
		margin-top: 0;
		margin-bottom: 1rem;
	}

	h4 {
		margin-top: 0;
		margin-bottom: 0.75rem;
		font-size: 0.875rem;
		color: var(--fg-muted);
		text-transform: uppercase;
	}

	.add-rule {
		display: flex;
		gap: 0.5rem;
		align-items: center;
		margin-bottom: 1.5rem;
	}

	.add-rule select {
		flex: 2;
		padding: 0.5rem;
		border: 1px solid var(--border-primary);
		border-radius: 4px;
	}

	.direction-toggle {
		display: flex;
		align-items: center;
		gap: 0.25rem;
		cursor: pointer;
		white-space: nowrap;
	}

	.direction-toggle input[type='checkbox'] {
		cursor: pointer;
	}

	.add-rule button {
		padding: 0.5rem 1rem;
		background-color: var(--success-fg);
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		white-space: nowrap;
	}

	.add-rule button:disabled {
		background-color: var(--border-primary);
		cursor: not-allowed;
	}

	.sort-rules {
		padding: 1rem;
		background-color: var(--bg-tertiary);
		border-radius: 4px;
		margin-bottom: 1rem;
	}

	.sort-rule-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 0.75rem;
		background-color: var(--bg-primary);
		border: 1px solid var(--border-primary);
		border-radius: 4px;
		margin-bottom: 0.5rem;
	}

	.sort-rule-item:last-child {
		margin-bottom: 0;
	}

	.rule-info {
		display: flex;
		align-items: center;
		gap: 1rem;
	}

	.rule-column {
		font-weight: 500;
		font-size: 0.95rem;
	}

	.direction-btn {
		padding: 0.25rem 0.75rem;
		background-color: var(--accent-primary);
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.875rem;
		font-family: monospace;
	}

	.rule-actions {
		display: flex;
		gap: 0.25rem;
	}

	.rule-actions button {
		padding: 0.25rem 0.5rem;
		background-color: var(--fg-muted);
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.875rem;
	}

	.rule-actions button:disabled {
		background-color: var(--border-primary);
		cursor: not-allowed;
	}

	.remove-btn {
		background-color: var(--error-fg) !important;
	}

	.empty-state {
		padding: 2rem;
		text-align: center;
		color: var(--fg-muted);
		background-color: var(--bg-tertiary);
		border-radius: 4px;
		margin-bottom: 1rem;
	}

	button:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
