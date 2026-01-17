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

		// Ensure config is an array before adding
		const base = Array.isArray(config) ? config : [];
		config = [...base, { column: newRule.column, descending: newRule.descending }];

		newRule = {
			column: '',
			descending: false
		};
	}

	function removeSortRule(index: number) {
		if (Array.isArray(config)) {
			config = config.filter((_, i) => i !== index);
		}
	}

	function toggleDirection(index: number) {
		if (Array.isArray(config) && config[index]) {
			config = config.map((rule, i) =>
				i === index ? { ...rule, descending: !rule.descending } : rule
			);
		}
	}

	function moveUp(index: number) {
		if (!Array.isArray(config) || index === 0) return;
		const newConfig = [...config];
		[newConfig[index], newConfig[index - 1]] = [newConfig[index - 1], newConfig[index]];
		config = newConfig;
	}

	function moveDown(index: number) {
		if (!Array.isArray(config) || index === config.length - 1) return;
		const newConfig = [...config];
		[newConfig[index], newConfig[index + 1]] = [newConfig[index + 1], newConfig[index]];
		config = newConfig;
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
		font-size: 0.875rem;
		color: var(--fg-muted);
		text-transform: uppercase;
	}

	.add-rule {
		display: flex;
		gap: 0.5rem;
		align-items: center;
		margin-bottom: 1.5rem;
		flex-wrap: wrap;
	}

	.add-rule select {
		flex: 2;
		padding: 0.5rem;
		border: 1px solid var(--form-control-border);
		border-radius: var(--radius-sm);
		background-color: var(--form-control-bg);
		color: var(--fg-primary);
	}

	.direction-toggle {
		display: flex;
		align-items: center;
		gap: 0.25rem;
		cursor: pointer;
		white-space: nowrap;
		color: var(--fg-secondary);
	}

	.direction-toggle input[type='checkbox'] {
		cursor: pointer;
	}

	.add-rule button {
		padding: 0.5rem 1rem;
		background-color: var(--accent-primary);
		color: var(--bg-primary);
		border: none;
		border-radius: var(--radius-sm);
		cursor: pointer;
		white-space: nowrap;
	}

	.add-rule button:disabled {
		background-color: var(--border-primary);
		cursor: not-allowed;
		color: var(--fg-muted);
	}

	.sort-rules {
		padding: 1rem;
		background-color: var(--panel-muted-bg);
		border-radius: var(--radius-md);
		margin-bottom: 1rem;
		border: 1px solid var(--panel-muted-border);
	}

	.sort-rule-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 0.75rem;
		background-color: var(--panel-bg);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
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
		color: var(--fg-primary);
	}

	.direction-btn {
		padding: 0.25rem 0.75rem;
		background-color: var(--accent-primary);
		color: var(--bg-primary);
		border: none;
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 0.875rem;
		font-family: var(--font-mono);
	}

	.rule-actions {
		display: flex;
		gap: 0.25rem;
	}

	.rule-actions button {
		padding: 0.25rem 0.5rem;
		background-color: var(--bg-tertiary);
		color: var(--fg-primary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 0.875rem;
	}

	.rule-actions button:disabled {
		background-color: var(--bg-muted);
		cursor: not-allowed;
		color: var(--fg-muted);
	}

	.rule-actions .remove-btn {
		background-color: var(--error-bg);
		color: var(--error-fg);
		border: 1px solid var(--error-border);
	}

	.empty-state {
		padding: 2rem;
		text-align: center;
		color: var(--fg-muted);
		background-color: var(--panel-muted-bg);
		border-radius: var(--radius-md);
		margin-bottom: 1rem;
		border: 1px solid var(--panel-muted-border);
	}

	button:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
