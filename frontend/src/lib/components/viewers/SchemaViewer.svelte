<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';

	interface Props {
		schema: Schema;
	}

	let { schema }: Props = $props();
</script>

<div
	class="overflow-hidden rounded-md border"
	style="background: var(--panel-bg); border-color: var(--panel-border);"
>
	<div
		class="flex justify-between items-center px-5 py-4 border-b"
		style="border-color: var(--border-primary); background: var(--panel-header-bg);"
	>
		<h3 class="m-0 text-lg font-semibold" style="color: var(--fg-primary);">Schema</h3>
		{#if schema.row_count !== null}
			<span class="text-sm" style="color: var(--fg-muted);">{schema.row_count.toLocaleString()} rows</span>
		{/if}
	</div>

	<div class="max-h-[500px] overflow-y-auto">
		<div
			class="grid gap-4 px-5 py-3 border-b text-xs font-semibold uppercase tracking-wider"
			style="grid-template-columns: 2fr 1.5fr 1fr; background: var(--table-header-bg); border-color: var(--border-primary); color: var(--fg-muted);"
		>
			<div>Column</div>
			<div>Type</div>
			<div>Nullable</div>
		</div>

		{#each schema.columns as column (column.name)}
			<div
				class="column-row grid gap-4 px-5 py-3.5 border-b transition-colors last:border-b-0"
				style="grid-template-columns: 2fr 1.5fr 1fr; border-color: var(--border-primary);"
			>
				<div class="flex items-center gap-2 font-medium" style="color: var(--fg-primary);">
					<span class="font-mono text-sm">{column.name}</span>
				</div>
				<div class="flex items-center">
					<ColumnTypeBadge columnType={column.dtype} size="sm" showIcon={true} />
				</div>
				<div class="flex items-center text-sm">
					{#if column.nullable}
						<span style="color: var(--fg-muted);">Yes</span>
					{:else}
						<span class="font-medium" style="color: var(--fg-secondary);">No</span>
					{/if}
				</div>
			</div>
		{/each}
	</div>
</div>

<style>
	.column-row:hover {
		background: var(--table-row-hover);
	}
</style>
