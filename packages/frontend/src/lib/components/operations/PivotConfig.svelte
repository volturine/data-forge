<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import type { PivotConfigData } from '$lib/types/operation-config';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';
	import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
	import { css, input, label, stepConfig } from '$lib/styles/panda';

	const uid = $props.id();
	const rowsLabelId = `${uid}-rows`;
	const columnsLabelId = `${uid}-columns`;
	const aggregatesLabelId = `${uid}-aggregates`;
	const valueColumnsLabelId = `${uid}-value-columns`;
	const aggregateFunctionId = `${uid}-aggregate-function`;
	const outputColumnsLabelId = `${uid}-output-columns`;

	interface Props {
		schema: Schema;
		config?: PivotConfigData;
		onConfigChange?: () => void;
		outputColumns?: string[];
	}

	let {
		schema,
		config = $bindable({ index: [], columns: '', value_columns: [], aggregate_function: 'first' }),
		onConfigChange,
		outputColumns = []
	}: Props = $props();

	const safeIndex = $derived(Array.isArray(config.index) ? config.index : []);
	const safeValueColumns = $derived(
		Array.isArray(config.value_columns) ? config.value_columns : []
	);
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

	function updateRows(columns: string[]): void {
		config.index = columns.filter(
			(column) => column !== config.columns && !safeValueColumns.includes(column)
		);
		onConfigChange?.();
	}

	function updatePivotColumn(column: string): void {
		config.columns = column;
		config.index = safeIndex.filter((name) => name !== column);
		config.value_columns = safeValueColumns.filter((name) => name !== column);
		onConfigChange?.();
	}

	function updateValueColumns(columns: string[]): void {
		config.value_columns = columns.filter((column) => column !== config.columns);
		config.index = safeIndex.filter((name) => !config.value_columns.includes(name));
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
					(column.name !== config.columns && !safeValueColumns.includes(column.name))}
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
		>
			<SectionHeader id={columnsLabelId}>Columns</SectionHeader>
			<ColumnDropdown
				{schema}
				value={config.columns ?? ''}
				onChange={updatePivotColumn}
				filter={(column) =>
					column.name === config.columns ||
					(!safeIndex.includes(column.name) && !safeValueColumns.includes(column.name))}
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
				Choose one or more value columns. The function applies to each selected column; leave them
				empty to use all remaining columns.
			</p>
			<div class={css({ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2' })}>
				<div role="group" aria-labelledby={valueColumnsLabelId}>
					<span id={valueColumnsLabelId} class={label({ variant: 'field' })}>Value columns</span>
					<MultiSelectColumnDropdown
						{schema}
						value={safeValueColumns}
						onChange={updateValueColumns}
						filter={(column) =>
							safeValueColumns.includes(column.name) ||
							(column.name !== config.columns && !safeIndex.includes(column.name))}
						placeholder="All remaining columns"
						showSelectAll={false}
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
