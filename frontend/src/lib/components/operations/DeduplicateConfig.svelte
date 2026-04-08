<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';
	import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { css, cx, label, stepConfig } from '$lib/styles/panda';

	interface DeduplicateConfigData {
		subset: string[] | null;
		keep: string;
	}

	interface Props {
		schema: Schema;
		config?: DeduplicateConfigData;
	}

	let { schema, config = $bindable({ subset: null, keep: 'first' }) }: Props = $props();

	const keepStrategies = [
		{ value: 'first', label: 'Keep First' },
		{ value: 'last', label: 'Keep Last' },
		{ value: 'none', label: 'Keep None' }
	];
</script>

<div class={stepConfig()} role="region" aria-label="Deduplicate configuration">
	<div
		class={css({
			marginBottom: '0',
			paddingBottom: '5',
			backgroundColor: 'transparent',

			border: 'none'
		})}
		role="radiogroup"
		aria-labelledby="keep-strategy-heading"
	>
		<span id="keep-strategy-heading"><SectionHeader>Keep Strategy</SectionHeader></span>
		<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
			{#each keepStrategies as strategy (strategy.value)}
				<label
					class={cx(
						label({ variant: 'checkbox' }),
						css({ paddingY: '2', _hover: { color: 'fg.primary' } })
					)}
				>
					<input
						type="radio"
						name="keep-strategy"
						bind:group={config.keep}
						value={strategy.value}
						class={css({ marginRight: '2', cursor: 'pointer' })}
					/>
					<span>{strategy.label}</span>
				</label>
			{/each}
		</div>
	</div>

	<div
		class={cx(
			css({
				marginBottom: '0',
				paddingBottom: '5',
				backgroundColor: 'transparent',

				border: 'none'
			}),
			css({ borderTopWidth: '1', paddingTop: '5' })
		)}
		role="group"
		aria-labelledby="column-subset-heading"
	>
		<span id="column-subset-heading"><SectionHeader>Column Subset</SectionHeader></span>
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
			Columns to check for duplicates
		</div>
		<MultiSelectColumnDropdown
			{schema}
			value={config.subset ?? []}
			onChange={(val) => (config.subset = val.length > 0 ? val : null)}
			placeholder="Select columns..."
		/>

		{#if config.subset && config.subset.length > 0}
			<Callout>
				Checking {config.subset.length} column{config.subset.length !== 1 ? 's' : ''} for duplicates
			</Callout>
		{:else}
			<Callout>No columns selected - will check all columns for duplicates</Callout>
		{/if}
	</div>
</div>
