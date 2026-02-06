<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';

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
	<h3 class="m-0 mb-4 text-sm uppercase tracking-wider" style="color: var(--fg-muted);">
		Rename Configuration
	</h3>

	<div class="mb-5" role="group" aria-labelledby="rename-columns-heading">
		<h4
			id="rename-columns-heading"
			class="m-0 mb-3 text-xs uppercase tracking-wider"
			style="color: var(--fg-muted);"
		>
			Select Column to Rename
		</h4>
		<ColumnDropdown
			{schema}
			value={formOldName}
			onChange={(val) => (formOldName = val)}
			placeholder="Select column to rename..."
			filter={(col) => !safeMapping[col.name]}
		/>
		{#if schema.columns.filter((col) => !safeMapping[col.name]).length === 0}
			<p
				class="p-6 text-center rounded-md mb-4"
				style="color: var(--fg-muted); background-color: var(--panel-muted-bg); border: 1px dashed var(--panel-border);"
			>
				All columns have been renamed.
			</p>
		{/if}
	</div>

	<div class="grid gap-2 mb-5" role="group" aria-label="Add rename mapping form">
		<label for="rename-input-new" class="sr-only">New column name</label>
		<input
			id="rename-input-new"
			data-testid="rename-new-name-input"
			type="text"
			class="w-full disabled:cursor-not-allowed"
			style:background-color={!formOldName ? 'var(--bg-muted)' : undefined}
			style:color={!formOldName ? 'var(--fg-muted)' : undefined}
			bind:value={formNewName}
			placeholder={formOldName ? `New name for ${formOldName}` : 'Select a column first'}
			aria-label="Enter new column name"
			disabled={!formOldName}
		/>

		<button
			id="rename-btn-add"
			data-testid="rename-add-button"
			type="button"
			class="add-btn py-2 px-4 rounded-sm cursor-pointer whitespace-nowrap font-semibold"
			style="background-color: var(--accent-primary); color: var(--bg-primary); border: 1px solid var(--accent-primary);"
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
			class="flex flex-col gap-2 p-3 rounded-md mb-4"
			style="background-color: var(--panel-muted-bg); border: 1px solid var(--panel-border);"
			role="list"
			aria-label="Configured renames"
		>
			<h4 class="mt-0 mb-2 text-xs uppercase tracking-wider" style="color: var(--fg-muted);">
				Renames
			</h4>
			{#each mappings as mapping (mapping.oldName)}
				<div
					class="flex justify-between items-center py-2 px-3 rounded-sm"
					style="background-color: var(--panel-bg); border: 1px solid var(--panel-border);"
					role="listitem"
				>
					<div
						class="flex items-center gap-2 min-w-0 text-sm"
						style="font-family: var(--font-mono);"
					>
						<span
							class="font-semibold max-w-[160px] overflow-hidden text-ellipsis whitespace-nowrap"
							style="color: var(--fg-primary);"
							title={mapping.oldName}>{mapping.oldName}</span
						>
						<span style="color: var(--fg-muted);" aria-hidden="true">→</span>
						<span
							class="font-semibold max-w-[160px] overflow-hidden text-ellipsis whitespace-nowrap"
							style="color: var(--accent-primary);"
							title={mapping.newName}>{mapping.newName}</span
						>
					</div>
					<button
						id={`rename-btn-remove-${mapping.oldName}`}
						data-testid={`rename-remove-button-${mapping.oldName}`}
						type="button"
						class="remove-btn w-7 h-7 inline-flex items-center justify-center rounded-full cursor-pointer text-lg leading-none"
						style="background-color: transparent; color: var(--fg-muted); border: 1px solid transparent;"
						onclick={() => removeMapping(mapping.oldName)}
						aria-label={`Remove rename: ${mapping.oldName} to ${mapping.newName}`}
					>
						×
					</button>
				</div>
			{/each}
		</div>
	{:else}
		<p
			id="rename-empty-state"
			class="p-6 text-center rounded-md mb-4"
			style="color: var(--fg-muted); background-color: var(--panel-muted-bg); border: 1px dashed var(--panel-border);"
			role="status"
		>
			No renames yet.
		</p>
	{/if}
</div>

<style>
	.add-btn:disabled {
		background-color: var(--panel-muted-bg) !important;
		border-color: var(--panel-border) !important;
		cursor: not-allowed;
		color: var(--fg-muted) !important;
	}
	.remove-btn:hover:not(:disabled) {
		color: var(--fg-primary);
		background-color: var(--bg-hover);
		border-color: var(--panel-border);
	}
	button:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
