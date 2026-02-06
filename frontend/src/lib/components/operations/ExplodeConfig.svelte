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
	<h3>Explode Configuration</h3>

	<div
		class="mb-4 rounded-sm border-l-[3px] p-3 text-sm"
		style="background-color: var(--info-bg); border-color: var(--info-border); color: var(--info-fg);"
	>
		Transform list/array columns into multiple rows. Each list element becomes a separate row,
		duplicating all other column values.
	</div>

	<div class="form-section">
		<h4>Columns to Explode</h4>
		<p class="mb-3 text-sm" style="color: var(--fg-tertiary);">
			Select one or more list/array columns to explode
		</p>

		{#if !hasListColumns}
			<div class="warning-box">
				<strong class="mb-2 block">No list/array columns detected</strong>
				<p class="m-0 text-sm">
					This operation requires columns with list or array types. Your current schema doesn't have
					any.
				</p>
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
				<div class="info-box">
					Selected {(config.columns ?? []).length} column{(config.columns ?? []).length !== 1
						? 's'
						: ''}:
					{(config.columns ?? []).join(', ')}
				</div>
			{/if}
		{/if}
	</div>

	<div class="success-box">
		<strong>How it works:</strong>
		<ul class="m-0 pl-6">
			<li class="mb-1">Each list element becomes a new row</li>
			<li class="mb-1">Other column values are duplicated for each new row</li>
			<li class="mb-1">Null values in lists are preserved as null rows</li>
			<li class="mb-1">Empty lists create no additional rows</li>
		</ul>
	</div>

	<div
		class="mb-4 rounded-sm border-l-[3px] p-3 text-sm"
		style="background-color: var(--warning-bg); border-color: var(--warning-border); color: var(--warning-fg);"
	>
		<strong>Example:</strong> A row with tags=['python', 'data', 'ai'] becomes 3 rows, each with one tag
		value.
	</div>
</div>
