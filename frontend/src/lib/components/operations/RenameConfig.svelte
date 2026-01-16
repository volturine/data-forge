<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	interface RenameConfigData {
		column_mapping: { [oldName: string]: string };
	}

	interface Props {
		schema: Schema;
		config: RenameConfigData;
		onSave: (config: RenameConfigData) => void;
	}

	let { schema, config, onSave }: Props = $props();

	let localConfig = $state<RenameConfigData>({
		column_mapping: config?.column_mapping ? { ...config.column_mapping } : {}
	});

	let newMapping = $state({
		oldName: '',
		newName: ''
	});

	let mappings = $derived(
		Object.entries(localConfig.column_mapping).map(([oldName, newName]) => ({
			oldName,
			newName
		}))
	);

	let availableColumns = $derived(
		schema.columns.filter((col) => !localConfig.column_mapping[col.name])
	);

	function addMapping() {
		if (!newMapping.oldName || !newMapping.newName) return;

		localConfig.column_mapping = {
			...localConfig.column_mapping,
			[newMapping.oldName]: newMapping.newName
		};

		newMapping = {
			oldName: '',
			newName: ''
		};
	}

	function removeMapping(oldName: string) {
		const { [oldName]: _, ...rest } = localConfig.column_mapping;
		localConfig.column_mapping = rest;
	}

	function handleSave() {
		onSave(localConfig);
	}

	function handleCancel() {
		localConfig = {
			column_mapping: config?.column_mapping ? { ...config.column_mapping } : {}
		};
	}
</script>

<div class="rename-config">
	<h3>Rename Configuration</h3>

	<div class="add-mapping">
		<select bind:value={newMapping.oldName}>
			<option value="">Select column to rename...</option>
			{#each availableColumns as column (column.name)}
				<option value={column.name}>{column.name} ({column.dtype})</option>
			{/each}
		</select>

		<input type="text" bind:value={newMapping.newName} placeholder="New column name" />

		<button
			type="button"
			onclick={addMapping}
			disabled={!newMapping.oldName || !newMapping.newName}
		>
			Add Rename
		</button>
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

	<div class="actions">
		<button type="button" onclick={handleSave} class="save-btn">Save</button>
		<button type="button" onclick={handleCancel} class="cancel-btn">Cancel</button>
	</div>
</div>

<style>
	.rename-config {
		padding: 1rem;
		border: 1px solid #ddd;
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
		color: #6c757d;
		text-transform: uppercase;
	}

	.add-mapping {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 1.5rem;
	}

	.add-mapping select,
	.add-mapping input {
		padding: 0.5rem;
		border: 1px solid #ccc;
		border-radius: 4px;
	}

	.add-mapping select {
		flex: 2;
	}

	.add-mapping input {
		flex: 2;
	}

	.add-mapping button {
		padding: 0.5rem 1rem;
		background-color: #28a745;
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		white-space: nowrap;
	}

	.add-mapping button:disabled {
		background-color: #ccc;
		cursor: not-allowed;
	}

	.mappings-list {
		padding: 1rem;
		background-color: #f8f9fa;
		border-radius: 4px;
		margin-bottom: 1rem;
	}

	.mapping-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 0.75rem;
		background-color: white;
		border: 1px solid #ddd;
		border-radius: 4px;
		margin-bottom: 0.5rem;
	}

	.mapping-item:last-child {
		margin-bottom: 0;
	}

	.mapping-info {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		font-family: monospace;
	}

	.old-name {
		font-weight: 500;
		color: #495057;
	}

	.arrow {
		color: #6c757d;
		font-size: 1.2rem;
	}

	.new-name {
		font-weight: 500;
		color: #007bff;
	}

	.mapping-item button {
		padding: 0.25rem 0.75rem;
		background-color: #dc3545;
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.875rem;
	}

	.empty-state {
		padding: 2rem;
		text-align: center;
		color: #6c757d;
		background-color: #f8f9fa;
		border-radius: 4px;
		margin-bottom: 1rem;
	}

	.actions {
		display: flex;
		gap: 0.5rem;
	}

	.save-btn {
		padding: 0.5rem 1.5rem;
		background-color: #007bff;
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
	}

	.cancel-btn {
		padding: 0.5rem 1.5rem;
		background-color: #6c757d;
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
	}

	button:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
