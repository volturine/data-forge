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

<div class="config-panel" role="region" aria-label="Rename configuration">
	<h3>Rename Configuration</h3>

	<div class="add-mapping" role="group" aria-label="Add rename mapping form">
		<label for="rename-select-old" class="sr-only">Select column to rename</label>
		<select id="rename-select-old" data-testid="rename-old-column-select" bind:value={formOldName}>
			<option value="">Select column to rename...</option>
			{#each availableColumns as column (column.name)}
				<option value={column.name}>{column.name} ({column.dtype})</option>
			{/each}
		</select>

		<label for="rename-input-new" class="sr-only">New column name</label>
		<input
			id="rename-input-new"
			data-testid="rename-new-name-input"
			type="text"
			bind:value={formNewName}
			placeholder="New column name"
			aria-label="Enter new column name"
		/>

		<button
			id="rename-btn-add"
			data-testid="rename-add-button"
			type="button"
			onclick={addMapping}
			disabled={!canAdd}
			aria-label="Add rename mapping"
		>
			Add Rename
		</button>
	</div>

	{#if mappings.length > 0}
		<div
			id="rename-mappings-list"
			class="mappings-list"
			role="list"
			aria-label="Configured renames"
		>
			<h4>Column Renames</h4>
			{#each mappings as mapping (mapping.oldName)}
				<div class="mapping-item" role="listitem">
					<div class="mapping-info">
						<span class="old-name">{mapping.oldName}</span>
						<span class="arrow" aria-hidden="true">→</span>
						<span class="new-name">{mapping.newName}</span>
					</div>
					<button
						id={`rename-btn-remove-${mapping.oldName}`}
						data-testid={`rename-remove-button-${mapping.oldName}`}
						type="button"
						onclick={() => removeMapping(mapping.oldName)}
						aria-label={`Remove rename: ${mapping.oldName} to ${mapping.newName}`}
					>
						Remove
					</button>
				</div>
			{/each}
		</div>
	{:else}
		<p id="rename-empty-state" class="empty-state" role="status">
			No column renames configured. Add a mapping above.
		</p>
	{/if}
</div>

<style>
	h4 {
		text-transform: uppercase;
	}
	.add-mapping {
		display: flex;
		gap: var(--space-2);
		margin-bottom: var(--space-6);
		flex-wrap: wrap;
	}
	.add-mapping select,
	.add-mapping input {
		flex: 2;
	}
	.add-mapping button {
		padding: var(--space-2) var(--space-4);
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
		padding: var(--space-4);
		background-color: var(--panel-muted-bg);
		border-radius: var(--radius-md);
		margin-bottom: var(--space-4);
		border: 1px solid var(--panel-muted-border);
	}
	.mappings-list h4 {
		margin-top: 0;
		margin-bottom: var(--space-3);
		font-size: var(--text-sm);
		color: var(--fg-muted);
	}
	.mapping-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--space-3);
		background-color: var(--panel-bg);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		margin-bottom: var(--space-2);
	}
	.mapping-item:last-child {
		margin-bottom: 0;
	}
	.mapping-info {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		font-family: var(--font-mono);
	}
	.old-name {
		font-weight: var(--font-medium);
		color: var(--fg-primary);
	}
	.arrow {
		color: var(--fg-muted);
		font-size: var(--text-lg);
	}
	.new-name {
		font-weight: var(--font-medium);
		color: var(--accent-primary);
	}
	.mapping-item button {
		padding: var(--space-1) var(--space-3);
		background-color: var(--error-bg);
		color: var(--error-fg);
		border: 1px solid var(--error-border);
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: var(--text-sm);
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
	button:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
