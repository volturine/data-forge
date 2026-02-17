<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	type PlotConfigData = {
		chart_type: 'bar' | 'histogram' | 'scatter' | 'line' | 'pie' | 'boxplot';
		x_column: string;
		y_column: string;
		bins: number;
		aggregation: 'sum' | 'mean' | 'count' | 'min' | 'max';
		group_column: string | null;
	};
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';

	const uid = `plot-${Math.random().toString(36).slice(2, 9)}`;

	interface Props {
		schema: Schema;
		config?: Record<string, unknown>;
	}

	const defaultConfig: PlotConfigData = {
		chart_type: 'bar',
		x_column: '',
		y_column: '',
		bins: 10,
		aggregation: 'sum',
		group_column: null
	};

	let { schema, config = $bindable(defaultConfig) }: Props = $props();
	let plotConfig = $derived.by(() => config as PlotConfigData);

	const chartTypes: Array<{ value: PlotConfigData['chart_type']; label: string }> = [
		{ value: 'bar', label: 'Bar Chart' },
		{ value: 'histogram', label: 'Histogram' },
		{ value: 'scatter', label: 'Scatter Plot' },
		{ value: 'line', label: 'Line Chart' },
		{ value: 'pie', label: 'Pie Chart' },
		{ value: 'boxplot', label: 'Box Plot' }
	];

	const aggregations: Array<{ value: PlotConfigData['aggregation']; label: string }> = [
		{ value: 'sum', label: 'Sum' },
		{ value: 'mean', label: 'Mean' },
		{ value: 'count', label: 'Count' },
		{ value: 'min', label: 'Min' },
		{ value: 'max', label: 'Max' }
	];

	const needsAggregation = $derived(
		plotConfig.chart_type === 'bar' ||
			plotConfig.chart_type === 'line' ||
			plotConfig.chart_type === 'pie'
	);
	const needsBins = $derived(plotConfig.chart_type === 'histogram');
	const needsGroup = $derived(plotConfig.chart_type === 'scatter');
</script>

<div class="config-panel" role="region" aria-label="Plot configuration">
	<h3>Plot Configuration</h3>

	<div class="form-section" role="group" aria-labelledby={`${uid}-plot-type`}>
		<h4 id={`${uid}-plot-type`}>Chart Type</h4>
		<select bind:value={plotConfig.chart_type} class="select-mono">
			{#each chartTypes as type (type.value)}
				<option value={type.value}>{type.label}</option>
			{/each}
		</select>
	</div>

	<div class="form-section" role="group" aria-labelledby={`${uid}-plot-x`}>
		<h4 id={`${uid}-plot-x`}>X Column</h4>
		<ColumnDropdown
			{schema}
			value={plotConfig.x_column}
			onChange={(val) => (plotConfig.x_column = val)}
			placeholder="Select column..."
		/>
	</div>

	{#if plotConfig.chart_type !== 'histogram'}
		<div class="form-section" role="group" aria-labelledby={`${uid}-plot-y`}>
			<h4 id={`${uid}-plot-y`}>Y Column</h4>
			<ColumnDropdown
				{schema}
				value={plotConfig.y_column}
				onChange={(val) => (plotConfig.y_column = val)}
				placeholder="Select column..."
			/>
		</div>
	{/if}

	{#if needsBins}
		<div class="form-section" role="group" aria-labelledby={`${uid}-plot-bins`}>
			<h4 id={`${uid}-plot-bins`}>Bins</h4>
			<input type="number" min="2" max="100" bind:value={plotConfig.bins} />
		</div>
	{/if}

	{#if needsAggregation}
		<div class="form-section" role="group" aria-labelledby={`${uid}-plot-agg`}>
			<h4 id={`${uid}-plot-agg`}>Aggregation</h4>
			<select bind:value={plotConfig.aggregation} class="select-mono">
				{#each aggregations as agg (agg.value)}
					<option value={agg.value}>{agg.label}</option>
				{/each}
			</select>
		</div>
	{/if}

	{#if needsGroup}
		<div class="form-section" role="group" aria-labelledby={`${uid}-plot-group`}>
			<h4 id={`${uid}-plot-group`}>Group Column</h4>
			<ColumnDropdown
				{schema}
				value={plotConfig.group_column ?? ''}
				onChange={(val) => (plotConfig.group_column = val)}
				placeholder="Optional group column..."
			/>
		</div>
	{/if}
</div>
