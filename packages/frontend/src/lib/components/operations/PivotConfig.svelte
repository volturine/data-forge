<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import type { PivotConfigData } from '$lib/types/operation-config';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';
	import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
	import { css, input, label, stepConfig } from '$lib/styles/panda';

	const uid = $props.id();

	interface Props {
		schema: Schema;
		config?: PivotConfigData;
		onRefreshSchema?: () => void;
		isRefreshing?: boolean;
	}

	let {
		schema,
		config = $bindable({ index: [], columns: '', values: null, aggregate_function: 'first' }),
		onRefreshSchema,
		isRefreshing = false
	}: Props = $props();

	const safeIndex = $derived(Array.isArray(config.index) ? config.index : []);
	const aggregateFunctions = ['first', 'last', 'sum', 'mean', 'median', 'min', 'max', 'count'];
	const isConfigValid = $derived(!!config.columns && safeIndex.length > 0);
</script>

<div class={stepConfig()} role="region" aria-label="Pivot configuration">
	<p class={css({ marginTop: '0', marginBottom: '5', color: 'fg.tertiary', fontSize: 'xs' })}>
		Choose how rows are grouped, which values become columns, and what to aggregate.
	</p>

	<div class={css({ display: 'flex', flexDirection: 'column', gap: '5' })}>
		<div
			class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}
			role="group"
			aria-label="Rows"
			data-testid="pivot-rows-group"
		>
			<SectionHeader>Rows</SectionHeader>
			<MultiSelectColumnDropdown
				{schema}
				value={safeIndex}
				onChange={(value) => (config.index = value)}
				showSelectAll={false}
				placeholder="Choose row fields..."
			/>
			<p class={css({ margin: '0', color: 'fg.muted', fontSize: 'xs' })}>
				One output row for each unique combination.
			</p>
		</div>

		<div
			class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}
			role="group"
			aria-label="Columns"
			data-testid="pivot-columns-group"
		>
			<SectionHeader>Columns</SectionHeader>
			<ColumnDropdown
				{schema}
				value={config.columns ?? ''}
				onChange={(value) => (config.columns = value)}
				placeholder="Choose a column field..."
			/>
			<p class={css({ margin: '0', color: 'fg.muted', fontSize: 'xs' })}>
				Each unique value becomes an output column.
			</p>
		</div>

		<div
			class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}
			role="group"
			aria-label="Aggregates"
			data-testid="pivot-aggregates-group"
		>
			<SectionHeader>Aggregates</SectionHeader>
			<p class={css({ margin: '0', color: 'fg.muted', fontSize: 'xs' })}>
				Choose the value column and function for each output cell.
			</p>
			<div class={css({ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2' })}>
				<div role="group" aria-label="Value column">
					<span class={label({ variant: 'field' })}>Value column</span>
					<ColumnDropdown
						{schema}
						value={config.values ?? ''}
						onChange={(value) => (config.values = value || null)}
						placeholder="All remaining columns"
						clearable
					/>
				</div>
				<div>
					<label class={label({ variant: 'field' })} for="{uid}-aggregate-function">Function</label>
					<select
						id="{uid}-aggregate-function"
						data-testid="pivot-agg-select"
						class={input()}
						bind:value={config.aggregate_function}
					>
						{#each aggregateFunctions as func (func)}
							<option value={func}>{func === 'count' ? 'Count rows' : func}</option>
						{/each}
					</select>
				</div>
			</div>
		</div>

		{#if onRefreshSchema}
			<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
				<button
					id="pivot-btn-refresh"
					data-testid="pivot-preview-button"
					class={css({
						backgroundColor: 'accent.primary',
						color: 'fg.inverse',
						borderWidth: '1',
						width: 'full',
						paddingY: '2',
						paddingX: '3',
						fontSize: 'sm',
						fontWeight: 'medium',
						cursor: 'pointer',
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						gap: '2',
						_hover: { opacity: '0.9' },
						_disabled: { opacity: '0.5', cursor: 'not-allowed' }
					})}
					onclick={onRefreshSchema}
					disabled={!isConfigValid || isRefreshing}
					type="button"
					aria-busy={isRefreshing}
				>
					{#if isRefreshing}
						<span
							class={css({
								width: 'iconXs',
								height: 'iconXs',
								borderWidth: '2',
								borderColor: 'currentColor',
								borderTopColor: 'transparent',
								animation: 'spin 0.8s linear infinite'
							})}
							aria-hidden="true"
						></span>
						Previewing...
					{:else}
						Preview columns
					{/if}
				</button>
				<p class={css({ margin: '0', color: 'fg.muted', fontSize: 'xs' })}>
					See the output columns before applying this step.
				</p>
			</div>
		{/if}
	</div>
</div>
