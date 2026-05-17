<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';
	import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { css, stepConfig } from '$lib/styles/panda';

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

<div class={stepConfig()}>
	<p
		class={css({
			marginTop: '0',
			marginBottom: '3',
			color: 'fg.tertiary',
			fontSize: 'xs',
			lineHeight: '1.6'
		})}
	>
		Transform list/array columns into multiple rows. Each list element becomes a separate row.
	</p>

	<div class={css({ marginBottom: '5' })}>
		<SectionHeader>Columns to Explode</SectionHeader>

		{#if !hasListColumns}
			<Callout tone="warn">
				No list/array columns detected. This operation requires columns with list or array types.
			</Callout>
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
				<span class={css({ marginTop: '2', display: 'block', fontSize: 'xs', color: 'fg.muted' })}>
					{(config.columns ?? []).length} column{(config.columns ?? []).length !== 1 ? 's' : ''} selected:
					{(config.columns ?? []).join(', ')}
				</span>
			{/if}
		{/if}
	</div>

	<div class={css({ fontSize: 'xs', color: 'fg.muted', lineHeight: 'relaxed' })}>
		Each list element becomes a new row. Other column values are duplicated. Null values are
		preserved; empty lists create no rows.
	</div>
</div>
