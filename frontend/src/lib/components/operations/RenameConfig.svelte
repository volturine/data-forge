<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	interface RenameConfigData {
		column_mapping: { [oldName: string]: string };
	}

	interface Props {
		schema: Schema;
		config?: RenameConfigData;
	}

	let { schema, config = $bindable({ column_mapping: {} }) }: Props = $props();

	let formOldName = $state('');
	let formNewName = $state('');

	let safeMapping = $derived(config?.column_mapping ?? {});

	let mappings = $derived(
		Object.entries(safeMapping).map(([oldName, newName]) => ({
			oldName,
			newName
		}))
	);

	let availableColumns = $derived(schema.columns.filter((col) => !safeMapping[col.name]));

	let canAdd = $derived(!!formOldName && !!formNewName);

	function addMapping() {
		if (!canAdd) return;
		config = {
			column_mapping: {
				...safeMapping,
				[formOldName]: formNewName
			}
		};
		formOldName = '';
		formNewName = '';
	}

	function removeMapping(oldName: string) {
		const { [oldName]: _, ...rest } = safeMapping;
		config.column_mapping = rest;
	}
</script>

<div class="rename-config">
	<h3>Rename Configuration</h3>

	<div class="add-mapping">
		<select bind:value={formOldName}>
			<option value="">Select column to rename...</option>
			{#each availableColumns as column (column.name)}
				<option value={column.name}>{column.name} ({column.dtype})</option>
			{/each}
		</select>

		<input type="text" bind:value={formNewName} placeholder="New column name" />

		<button type="button" onclick={addMapping} disabled={!canAdd}> Add Rename </button>
	</div>

	{#if mappings.length > 0}
		<div class="mappings-list">
			<h4>Column Renames</h4>
			{#each mappings as mapping (mapping.oldName)}
				<div class="mapping-item">
					<div class="mapping-info">
						<span class="old-name">{mapping.oldName}</span>
						<span class="arrow">→</span>
						<span class="new-name">{mapping.newName}</span>
					</div>
					<button type="button" onclick={() => removeMapping(mapping.oldName)}>Remove</button>
				</div>
			{/each}
		</div>
	{:else}
		<p class="empty-state">No column renames configured. Add a mapping above.</p>
	{/if}
</div>

<style>
	.rename-config {
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

	.add-mapping {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 1.5rem;
		flex-wrap: wrap;
	}

	.add-mapping select,
	.add-mapping input {
		padding: 0.5rem;
		border: 1px solid var(--form-control-border);
		border-radius: var(--radius-sm);
		background-color: var(--form-control-bg);
		color: var(--fg-primary);
	}

	.add-mapping select {
		flex: 2;
	}

	.add-mapping input {
		flex: 2;
	}

	.add-mapping button {
		padding: 0.5rem 1rem;
		background-color: var(--accent-primary);
		color: var(--bg-primary);
		border: none;
		border-radius: var(--radius-sm);
		cursor: pointer;
		white-space: nowrap;
	}

	.add-mapping button:disabled {
		background-color: var(--border-primary);
		cursor: not-allowed;
		color: var(--fg-muted);
	}

	.mappings-list {
		padding: 1rem;
		background-color: var(--panel-muted-bg);
		border-radius: var(--radius-md);
		margin-bottom: 1rem;
		border: 1px solid var(--panel-muted-border);
	}

	.mapping-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 0.75rem;
		background-color: var(--panel-bg);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		margin-bottom: 0.5rem;
	}

	.mapping-item:last-child {
		margin-bottom: 0;
	}

	.mapping-info {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		font-family: var(--font-mono);
	}

	.old-name {
		font-weight: 500;
		color: var(--fg-primary);
	}

	.arrow {
		color: var(--fg-muted);
		font-size: 1.2rem;
	}

	.new-name {
		font-weight: 500;
		color: var(--accent-primary);
	}

	.mapping-item button {
		padding: 0.25rem 0.75rem;
		background-color: var(--error-bg);
		color: var(--error-fg);
		border: 1px solid var(--error-border);
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 0.875rem;
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
