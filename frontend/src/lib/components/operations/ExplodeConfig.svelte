<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';

	interface ExplodeConfigData {
		columns: string[];
	}

	interface Props {
		schema: Schema;
		config?: ExplodeConfigData;
	}

	let { schema, config = $bindable({ columns: [] }) }: Props = $props();

	const hasListColumns = $derived(
		schema.columns.some(
			(col) =>
				col.dtype.toLowerCase().includes('list') ||
				col.dtype.toLowerCase().includes('array') ||
				col.dtype.toLowerCase().startsWith('list[')
		)
	);

	function isListColumn(col: { name: string; dtype: string }): boolean {
		const d = col.dtype.toLowerCase();
		return d.includes('list') || d.includes('array');
	}
</script>

<div class="config-panel">
	<p class="description">
		Transform list/array columns into multiple rows. Each list element becomes a separate row.
	</p>

	<div class="mb-5">
		<h4>Columns to Explode</h4>

		{#if !hasListColumns}
			<div class="warning-box">
				No list/array columns detected. This operation requires columns with list or array types.
			</div>
		{:else}
			<MultiSelectColumnDropdown
				{schema}
				value={config.columns ?? []}
				onChange={(val) => (config.columns = val)}
				filter={isListColumn}
				showSelectAll={false}
				placeholder="Select list columns..."
			/>

			{#if (config.columns ?? []).length > 0}
				<span class="mt-2 block text-xs text-fg-muted">
					{(config.columns ?? []).length} column{(config.columns ?? []).length !== 1
						? 's'
						: ''} selected: {(config.columns ?? []).join(', ')}
				</span>
			{/if}
		{/if}
	</div>

	<div class="text-xs text-fg-muted leading-relaxed">
		Each list element becomes a new row. Other column values are duplicated.
		Null values are preserved; empty lists create no rows.
	</div>
</div>
