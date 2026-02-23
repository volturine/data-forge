<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';

	interface Props {
		schema: Schema;
	}

	let { schema }: Props = $props();
</script>

<div class="schema-viewer overflow-hidden border bg-panel border-tertiary">
	<div class="flex justify-between items-center px-5 py-4 border-b border-tertiary bg-tertiary">
		<h3 class="m-0 text-lg font-semibold text-fg-primary">Schema</h3>
		{#if schema.row_count !== null}
			<span class="text-sm text-fg-muted">{schema.row_count.toLocaleString()} rows</span>
		{/if}
	</div>

	<div class="max-h-125 overflow-y-auto">
		<div
			class="schema-header-grid grid gap-4 px-5 py-3 border-b text-xs font-semibold uppercase tracking-wider border-tertiary text-fg-muted bg-tertiary"
		>
			<div>Column</div>
			<div>Type</div>
			<div>Nullable</div>
		</div>

		{#each schema.columns as column (column.name)}
			<div
				class="schema-header-grid grid gap-4 px-5 py-3.5 border-b last:border-b-0 border-tertiary hover:bg-hover"
			>
				<div class="flex items-center gap-2 font-medium text-fg-primary">
					<span class="font-mono text-sm">{column.name}</span>
				</div>
				<div class="flex items-center">
					<ColumnTypeBadge columnType={column.dtype} size="sm" showIcon={true} />
				</div>
				<div class="flex items-center text-sm">
					{#if column.nullable}
						<span class="text-fg-muted">Yes</span>
					{:else}
						<span class="font-medium text-fg-secondary">No</span>
					{/if}
				</div>
			</div>
		{/each}
	</div>
</div>
