<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import { X, Plus } from 'lucide-svelte';

	interface Props {
		schema: Schema;
		config?: { columns: string[]; descending: boolean[] };
	}

	let { schema, config = $bindable({ columns: [], descending: [] }) }: Props = $props();

	let safeConfig = $derived({
		columns: config?.columns ?? [],
		descending: config?.descending ?? []
	});

	let newColumn = $state('');
	let newDescending = $state(false);

	function addSortRule() {
		if (!newColumn) return;
		if (safeConfig.columns.includes(newColumn)) return;
		config = {
			columns: [...safeConfig.columns, newColumn],
			descending: [...safeConfig.descending, newDescending]
		};
		newColumn = '';
		newDescending = false;
	}

	function removeSortRule(index: number) {
		config = {
			columns: safeConfig.columns.filter((_, i) => i !== index),
			descending: safeConfig.descending.filter((_, i) => i !== index)
		};
	}

	function setDirection(index: number, descending: boolean) {
		config = {
			...safeConfig,
			descending: safeConfig.descending.map((d, i) => (i === index ? descending : d))
		};
	}

	let availableColumns = $derived(
		schema.columns.filter((col) => !safeConfig.columns.includes(col.name))
	);
</script>

<div class="sort-config">
	<h3>Sort Configuration</h3>

	<div class="add-rule">
		<select bind:value={newColumn}>
			<option value="">Select column...</option>
			{#each availableColumns as column (column.name)}
				<option value={column.name}>{column.name} ({column.dtype})</option>
			{/each}
		</select>

		<div class="direction-select">
			<button
				type="button"
				class="dir-btn"
				class:active={!newDescending}
				onclick={() => (newDescending = false)}
				title="Ascending"
			>
				<span class="sort-icon">▲</span>
			</button>
			<button
				type="button"
				class="dir-btn"
				class:active={newDescending}
				onclick={() => (newDescending = true)}
				title="Descending"
			>
				<span class="sort-icon">▼</span>
			</button>
		</div>

		<button type="button" class="add-btn" onclick={addSortRule} disabled={!newColumn}>
			<Plus size={16} />
			Add
		</button>
	</div>

	{#if safeConfig.columns.length > 0}
		<div class="sort-rules">
			<h4>Sort Order</h4>
			{#each safeConfig.columns as column, i (column)}
				<div class="sort-rule-item">
					<span class="rule-column">{column}</span>

					<div class="rule-actions">
						<button
							type="button"
							class="dir-btn"
							class:active={!safeConfig.descending[i]}
							onclick={() => setDirection(i, false)}
							title="Ascending"
						>
							<span class="sort-icon">▲</span>
						</button>
						<button
							type="button"
							class="dir-btn"
							class:active={safeConfig.descending[i]}
							onclick={() => setDirection(i, true)}
							title="Descending"
						>
							<span class="sort-icon">▼</span>
						</button>
						<button
							type="button"
							class="remove-btn"
							onclick={() => removeSortRule(i)}
							title="Remove"
						>
							<X size={14} />
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

	h4 {
		margin-top: 0;
		margin-bottom: var(--space-3);
		font-size: var(--text-sm);
		color: var(--fg-muted);
		text-transform: uppercase;
	}

	.add-rule {
		display: flex;
		gap: var(--space-2);
		align-items: center;
		margin-bottom: var(--space-6);
		flex-wrap: wrap;
	}

	.add-rule select {
		flex: 2;
		min-width: 200px;
		padding: var(--space-2);
		border: 1px solid var(--form-control-border);
		border-radius: var(--radius-sm);
		background-color: var(--form-control-bg);
		color: var(--fg-primary);
	}

	.direction-select {
		display: flex;
		gap: 0;
	}

	.dir-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		padding: 0;
		background-color: var(--bg-tertiary);
		color: var(--fg-secondary);
		border: 1px solid var(--border-primary);
		cursor: pointer;
		transition: all var(--transition);
	}

	.dir-btn:first-child {
		border-radius: var(--radius-sm) 0 0 var(--radius-sm);
		border-right: none;
	}

	.dir-btn:last-child {
		border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
	}

	.dir-btn:hover:not(.active) {
		background-color: var(--bg-secondary);
		color: var(--fg-primary);
	}

	.dir-btn.active {
		background-color: var(--accent-primary);
		color: var(--bg-primary);
		border-color: var(--accent-primary);
	}

	.add-btn {
		display: flex;
		align-items: center;
		gap: var(--space-1);
		padding: var(--space-2) var(--space-4);
		background-color: var(--accent-primary);
		color: var(--bg-primary);
		border: none;
		border-radius: var(--radius-sm);
		cursor: pointer;
		white-space: nowrap;
		font-size: var(--text-sm);
	}

	.add-btn:disabled {
		background-color: var(--border-primary);
		cursor: not-allowed;
		color: var(--fg-muted);
	}

	.sort-rules {
		padding: var(--space-4);
		background-color: var(--panel-muted-bg);
		border-radius: var(--radius-md);
		margin-bottom: var(--space-4);
		border: 1px solid var(--panel-muted-border);
	}

	.sort-rule-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--space-2) var(--space-3);
		background-color: var(--panel-bg);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		margin-bottom: var(--space-2);
	}

	.sort-rule-item:last-child {
		margin-bottom: 0;
	}

	.rule-column {
		font-weight: var(--font-medium);
		font-size: var(--text-sm);
		color: var(--fg-primary);
	}

	.rule-actions {
		display: flex;
		align-items: center;
		gap: var(--space-1);
	}

	.rule-actions button {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		padding: 0;
		background-color: transparent;
		color: var(--fg-secondary);
		border: 1px solid transparent;
		border-radius: var(--radius-sm);
		cursor: pointer;
		transition: all var(--transition);
	}

	.rule-actions button:hover:not(:disabled) {
		background-color: var(--bg-tertiary);
		color: var(--fg-primary);
	}

	.rule-actions button:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.rule-actions .dir-btn {
		width: 28px;
		height: 28px;
		background-color: transparent;
		color: var(--fg-secondary);
	}

	.rule-actions .dir-btn:hover:not(.active) {
		background-color: var(--bg-tertiary);
	}

	.rule-actions .dir-btn.active {
		background-color: var(--accent-primary);
		color: var(--bg-primary);
	}

	.sort-icon {
		font-size: var(--text-sm);
		line-height: 1;
	}

	.remove-btn:hover {
		background-color: var(--error-bg) !important;
		color: var(--error-fg) !important;
		border-color: var(--error-border) !important;
	}

	.empty-state {
		padding: var(--space-8);
		text-align: center;
		color: var(--fg-muted);
		background-color: var(--panel-muted-bg);
		border-radius: var(--radius-md);
		margin-bottom: var(--space-4);
		border: 1px solid var(--panel-muted-border);
	}
</style>
