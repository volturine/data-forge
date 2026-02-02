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
			Add
		</button>
	</div>

	{#if mappings.length > 0}
		<div
			id="rename-mappings-list"
			class="mappings-list"
			role="list"
			aria-label="Configured renames"
		>
			<h4>Renames</h4>
			{#each mappings as mapping (mapping.oldName)}
				<div class="mapping-item" role="listitem">
					<div class="mapping-info">
						<span class="old-name" title={mapping.oldName}>{mapping.oldName}</span>
						<span class="arrow" aria-hidden="true">→</span>
						<span class="new-name" title={mapping.newName}>{mapping.newName}</span>
					</div>
					<button
						id={`rename-btn-remove-${mapping.oldName}`}
						data-testid={`rename-remove-button-${mapping.oldName}`}
						type="button"
						onclick={() => removeMapping(mapping.oldName)}
						aria-label={`Remove rename: ${mapping.oldName} to ${mapping.newName}`}
					>
						×
					</button>
				</div>
			{/each}
		</div>
	{:else}
		<p id="rename-empty-state" class="empty-state" role="status">No renames yet.</p>
	{/if}
</div>

<style>
	h3 {
		margin: 0 0 var(--space-4) 0;
		font-size: var(--text-sm);
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--fg-muted);
	}
	h4 {
		margin: 0 0 var(--space-3) 0;
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--fg-muted);
	}
	.add-mapping {
		display: grid;
		grid-template-columns: 1fr;
		gap: var(--space-2);
		margin-bottom: var(--space-5);
	}
	.add-mapping select,
	.add-mapping input {
		width: 100%;
		min-width: 0;
	}
	.add-mapping button {
		padding: var(--space-2) var(--space-4);
		background-color: var(--accent-primary);
		color: var(--bg-primary);
		border: 1px solid var(--accent-primary);
		border-radius: var(--radius-sm);
		cursor: pointer;
		white-space: nowrap;
		font-weight: 600;
	}
	.add-mapping button:disabled {
		background-color: var(--panel-muted-bg);
		border-color: var(--panel-border);
		cursor: not-allowed;
		color: var(--fg-muted);
	}
	.mappings-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-3);
		background-color: var(--panel-muted-bg);
		border-radius: var(--radius-md);
		margin-bottom: var(--space-4);
		border: 1px solid var(--panel-border);
	}
	.mappings-list h4 {
		margin-top: 0;
		margin-bottom: var(--space-2);
	}
	.mapping-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--space-2) var(--space-3);
		background-color: var(--panel-bg);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
	}
	.mapping-info {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		min-width: 0;
	}
	.old-name {
		font-weight: 600;
		color: var(--fg-primary);
		max-width: 160px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.arrow {
		color: var(--fg-muted);
	}
	.new-name {
		font-weight: 600;
		color: var(--accent-primary);
		max-width: 160px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.mapping-item button {
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
	.mapping-item button:hover:not(:disabled) {
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
	button:hover:not(:disabled) {
		opacity: 0.9;
	}
	@media (max-width: 640px) {
		.add-mapping {
			grid-template-columns: 1fr;
		}
		.add-mapping button {
			width: 100%;
		}
	}
</style>
