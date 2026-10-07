<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import type { PivotConfigData } from '$lib/types/operation-config';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';
	import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
	import { button, css, input, label, spinner, stepConfig } from '$lib/styles/panda';

	const uid = $props.id();
	const rowsLabelId = `${uid}-rows`;
	const columnsLabelId = `${uid}-columns`;
	const aggregatesLabelId = `${uid}-aggregates`;
	const valueColumnLabelId = `${uid}-value-column`;
	const aggregateFunctionId = `${uid}-aggregate-function`;
	const outputColumnsLabelId = `${uid}-output-columns`;

	interface Props {
		schema: Schema;
		config?: PivotConfigData;
		onRefreshSchema?: () => void;
		onConfigChange?: () => void;
		isRefreshing?: boolean;
		outputColumns?: string[];
	}

	let {
		schema,
		config = $bindable({ index: [], columns: '', values: null, aggregate_function: 'first' }),
		onRefreshSchema,
		onConfigChange,
		isRefreshing = false,
		outputColumns = []
	}: Props = $props();

	const safeIndex = $derived(Array.isArray(config.index) ? config.index : []);
	const aggregateFunctions: PivotConfigData['aggregate_function'][] = [
		'first',
		'last',
		'sum',
		'mean',
		'median',
		'min',
		'max',
		'count'
	];
	const isConfigValid = $derived(
		!!config.columns &&
			safeIndex.length > 0 &&
			!safeIndex.includes(config.columns) &&
			(!config.values || (config.values !== config.columns && !safeIndex.includes(config.values)))
	);

	function updateRows(columns: string[]): void {
		config.index = columns.filter(
			(column) => column !== config.columns && column !== config.values
		);
		onConfigChange?.();
	}

	function updatePivotColumn(column: string): void {
		config.columns = column;
		config.index = safeIndex.filter((name) => name !== column);
		if (config.values === column) config.values = null;
		onConfigChange?.();
	}

	function updateValueColumn(column: string): void {
		const value = column || null;
		config.values = value;
		if (value) config.index = safeIndex.filter((name) => name !== value);
		onConfigChange?.();
	}

	function updateAggregateFunction(value: PivotConfigData['aggregate_function']): void {
		config.aggregate_function = value;
		onConfigChange?.();
	}
</script>

<div class={stepConfig()} role="region" aria-label="Pivot configuration">
	<p class={css({ marginTop: '0', marginBottom: '5', color: 'fg.tertiary', fontSize: 'xs' })}>
		Choose how rows are grouped, which values become columns, and what to aggregate.
	</p>

	<div class={css({ display: 'flex', flexDirection: 'column', gap: '5' })}>
		<div
			class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}
			role="group"
			aria-labelledby={rowsLabelId}
			data-testid="pivot-rows-group"
		>
			<SectionHeader id={rowsLabelId}>Rows</SectionHeader>
			<MultiSelectColumnDropdown
				{schema}
				value={safeIndex}
				onChange={updateRows}
				filter={(column) =>
					safeIndex.includes(column.name) ||
					(column.name !== config.columns && column.name !== config.values)}
				showSelectAll={false}
				placeholder="Choose row fields..."
			/>
			<p
				class={css({ margin: '0', color: 'fg.muted', fontSize: 'xs' })}
				role="status"
				aria-live="polite"
			>
				{safeIndex.length} row field{safeIndex.length === 1 ? '' : 's'} selected. One output row for each
				unique combination.
			</p>
		</div>

		<div
			class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}
			role="group"
			aria-labelledby={columnsLabelId}
			data-testid="pivot-columns-group"
		>
			<SectionHeader id={columnsLabelId}>Columns</SectionHeader>
			<ColumnDropdown
				{schema}
				value={config.columns ?? ''}
				onChange={updatePivotColumn}
				filter={(column) =>
					column.name === config.columns ||
					(!safeIndex.includes(column.name) && column.name !== config.values)}
				placeholder="Choose a column field..."
			/>
			<p class={css({ margin: '0', color: 'fg.muted', fontSize: 'xs' })}>
				Each unique value becomes an output column.
			</p>
		</div>

		<div
			class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}
			role="group"
			aria-labelledby={aggregatesLabelId}
			data-testid="pivot-aggregates-group"
		>
			<SectionHeader id={aggregatesLabelId}>Aggregates</SectionHeader>
			<p class={css({ margin: '0', color: 'fg.muted', fontSize: 'xs' })}>
				Choose the value column and function for each output cell.
			</p>
			<div class={css({ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2' })}>
				<div role="group" aria-labelledby={valueColumnLabelId}>
					<span id={valueColumnLabelId} class={label({ variant: 'field' })}>Value column</span>
					<ColumnDropdown
						{schema}
						value={config.values ?? ''}
						onChange={updateValueColumn}
						filter={(column) =>
							column.name === config.values ||
							(column.name !== config.columns && !safeIndex.includes(column.name))}
						triggerLabelledby={valueColumnLabelId}
						placeholder="All remaining columns"
						clearable
					/>
				</div>
				<div>
					<label class={label({ variant: 'field' })} for={aggregateFunctionId}>Function</label>
					<select
						id={aggregateFunctionId}
						data-testid="pivot-agg-select"
						class={input()}
						value={config.aggregate_function}
						onchange={(event) =>
							updateAggregateFunction(
								event.currentTarget.value as PivotConfigData['aggregate_function']
							)}
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
					data-testid="pivot-preview-button"
					class={button({ variant: 'primary', width: 'full' })}
					onclick={onRefreshSchema}
					disabled={!isConfigValid || isRefreshing}
					type="button"
					aria-busy={isRefreshing}
				>
					{#if isRefreshing}
						<span class={spinner({ size: 'sm' })} aria-hidden="true"></span>
						Loading output columns…
					{:else}
						Show output columns
					{/if}
				</button>
				<p class={css({ margin: '0', color: 'fg.muted', fontSize: 'xs' })}>
					Load the pivoted column names for the following steps.
				</p>
			</div>
		{/if}
		{#if outputColumns.length > 0}
			<div
				class={css({ borderWidth: '1', padding: '3', maxHeight: 'labelLg', overflowY: 'auto' })}
				role="region"
				aria-labelledby={outputColumnsLabelId}
				aria-live="polite"
				data-testid="pivot-output-schema"
			>
				<SectionHeader id={outputColumnsLabelId}>Output columns</SectionHeader>
				<ul
					class={css({ margin: '2 0 0', paddingLeft: '5', fontSize: 'xs', color: 'fg.secondary' })}
				>
					{#each outputColumns as column (column)}
						<li data-testid="pivot-output-column">{column}</li>
					{/each}
				</ul>
			</div>
		{/if}
	</div>
</div>
