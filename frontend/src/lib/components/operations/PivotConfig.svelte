<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import type { PivotConfigData } from '$lib/types/operation-config';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';
	import { css, cx, input, label, stepConfig } from '$lib/styles/panda';

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

	// Check if config is valid for schema refresh
	const isConfigValid = $derived(
		!!(config?.columns && Array.isArray(config?.index) && config.index.length > 0)
	);

	// Safe accessor
	const safeIndex = $derived(Array.isArray(config?.index) ? config.index : []);

	const aggregateFunctions = ['first', 'last', 'sum', 'mean', 'median', 'min', 'max', 'count'];

	function toggleIndexColumn(columnName: string) {
		const base = Array.isArray(config.index) ? config.index : [];
		const idx = base.indexOf(columnName);
		config.index = idx > -1 ? base.filter((_, i) => i !== idx) : [...base, columnName];
	}
</script>

<div class={stepConfig()} role="region" aria-label="Pivot configuration">
	<div class={css({ marginBottom: '5' })}>
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
			Pivot Column <span class={css({ fontSize: 'xs', color: 'fg.muted' })}
				>(values become new columns)</span
			>
		</div>
		<ColumnDropdown
			{schema}
			value={config.columns ?? ''}
			onChange={(val) => (config.columns = val)}
			placeholder="Select column..."
		/>
		<span id="pivot-column-help" class={css({ fontSize: 'xs', color: 'fg.muted' })}
			>Select the column whose unique values will become new columns</span
		>
	</div>

	<div class={css({ marginBottom: '5' })} role="group" aria-labelledby="index-columns-label">
		<span
			id="index-columns-label"
			class={css({
				display: 'block',
				fontSize: 'xs',
				fontWeight: 'semibold',
				color: 'fg.muted',
				marginBottom: '1.5',
				textTransform: 'uppercase',
				letterSpacing: 'wider'
			})}>Index Columns <span class={css({ fontSize: 'xs', color: 'fg.muted' })}>(rows)</span></span
		>
		<div
			class={css({
				gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
				border: 'none',
				backgroundColor: 'transparent',
				display: 'grid',
				gap: '3',
				padding: '2',
				maxHeight: 'inputSm',
				overflowY: 'auto'
			})}
		>
			{#each schema.columns as column (column.name)}
				<label
					class={cx(
						label({ variant: 'checkbox' }),
						css({ paddingX: '2', paddingY: '1', _hover: { backgroundColor: 'bg.hover' } })
					)}
				>
					<input
						id={`pivot-checkbox-index-${column.name}`}
						data-testid={`pivot-index-checkbox-${column.name}`}
						type="checkbox"
						name="pivot-index"
						class={css({ accentColor: 'token(colors.accent.primary)' })}
						checked={safeIndex.includes(column.name)}
						onchange={() => toggleIndexColumn(column.name)}
						aria-label={`Include ${column.name} as index column`}
					/>
					<span>{column.name}</span>
				</label>
			{/each}
		</div>
		{#if safeIndex.length > 0}
			<div
				id="pivot-index-summary"
				class={css({ marginTop: '2', fontSize: 'xs', color: 'fg.muted' })}
				aria-live="polite"
			>
				{safeIndex.length} selected
			</div>
		{/if}
	</div>

	<div class={css({ marginBottom: '5' })}>
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
			Values Column
		</div>
		<ColumnDropdown
			{schema}
			value={config.values ?? ''}
			onChange={(val) => (config.values = val)}
			placeholder="All remaining columns"
		/>
	</div>

	<div class={css({ marginBottom: '5' })}>
		<label class={label()} for="pivot-select-agg">Aggregation</label>
		<select
			id="pivot-select-agg"
			data-testid="pivot-agg-select"
			class={input()}
			bind:value={config.aggregate_function}
		>
			{#each aggregateFunctions as func (func)}
				<option value={func}>{func}</option>
			{/each}
		</select>
	</div>

	{#if onRefreshSchema}
		<div class={css({ marginBottom: '5' })}>
			<button
				id="pivot-btn-refresh"
				data-testid="pivot-refresh-button"
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
					Refreshing...
				{:else}
					Refresh Output Columns
				{/if}
			</button>
			<p class={css({ fontSize: 'xs', marginTop: '1', color: 'fg.muted' })}>
				Click to compute the resulting columns after pivot
			</p>
		</div>
	{/if}
</div>
