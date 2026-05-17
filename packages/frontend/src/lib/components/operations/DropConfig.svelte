<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import { TriangleAlert } from 'lucide-svelte';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { css, stepConfig } from '$lib/styles/panda';

	interface DropConfigData {
		columns: string[];
	}

	interface Props {
		schema: Schema;
		config?: DropConfigData;
	}

	let { schema, config = $bindable({ columns: [] }) }: Props = $props();

	const safeColumns = $derived(Array.isArray(config.columns) ? config.columns : []);
</script>

<div class={stepConfig()} role="region" aria-label="Drop columns configuration">
	<h3 class={css({ marginBottom: '2' })}>Drop Columns</h3>

	<p
		class={css({
			marginTop: '0',
			marginBottom: '3',
			color: 'fg.tertiary',
			fontSize: 'xs',
			lineHeight: '1.6'
		})}
	>
		Select the columns you want to drop (remove) from the dataset.
	</p>

	<div
		class={css({
			marginBottom: '0',
			paddingBottom: '5',
			backgroundColor: 'transparent',

			border: 'none'
		})}
	>
		<div
			class={css({
				display: 'block',
				fontSize: 'xs',
				fontWeight: 'semibold',
				color: 'fg.muted',
				marginBottom: '1.5',
				textTransform: 'uppercase',
				letterSpacing: 'wider'
			})}
		>
			Columns to drop
		</div>
		<MultiSelectColumnDropdown
			{schema}
			value={safeColumns}
			onChange={(val) => (config.columns = val)}
			placeholder="Select columns to drop..."
		/>
	</div>

	{#if safeColumns.length > 0}
		<Callout tone="warn">
			<strong class={css({ display: 'inline-flex', alignItems: 'center', gap: '2' })}>
				<TriangleAlert size={14} />
				Columns to Drop ({safeColumns.length}):
			</strong>
			<p>These columns will be removed from the dataset.</p>
		</Callout>
	{:else}
		<Callout tone="warn">
			<strong>Warning:</strong> No columns selected. This operation will have no effect.
		</Callout>
	{/if}
</div>
