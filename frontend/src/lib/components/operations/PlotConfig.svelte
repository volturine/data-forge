<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import type {
		OverlayConfig,
		PlotConfigData as PlotConfigBase,
		ReferenceLineConfig
	} from '$lib/types/operation-config';
	import { Plus, X } from 'lucide-svelte';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';

	type PlotConfigData = Omit<PlotConfigBase, 'aggregation' | 'chart_type' | 'stack_mode'> & {
		chart_type:
			| 'bar'
			| 'horizontal_bar'
			| 'area'
			| 'heatgrid'
			| 'histogram'
			| 'scatter'
			| 'line'
			| 'pie'
			| 'boxplot';
		aggregation:
			| 'sum'
			| 'mean'
			| 'count'
			| 'min'
			| 'max'
			| 'median'
			| 'std'
			| 'variance'
			| 'unique_count';
		group_sort_by: 'name' | 'value' | 'custom' | null;
		group_sort_order: 'asc' | 'desc';
		group_sort_column: string | null;
		stack_mode: 'grouped' | 'stacked' | '100%';
		sort_by: 'x' | 'y' | 'custom' | null;
		sort_order: 'asc' | 'desc';
		sort_column: string | null;
		x_axis_label: string | null;
		y_axis_label: string | null;
		y_axis_scale: 'linear' | 'log';
		y_axis_min: number | null;
		y_axis_max: number | null;
		display_units: '' | 'K' | 'M' | 'B' | '%';
		decimal_places: number;
		legend_position: 'top' | 'bottom' | 'left' | 'right' | 'none';
		title: string | null;
		area_opacity: number;
		date_bucket: 'exact' | 'year' | 'quarter' | 'month' | 'week' | 'day' | 'hour' | null;
		date_ordinal: 'day_of_week' | 'month_of_year' | 'quarter_of_year' | null;
		pan_zoom_enabled: boolean;
		selection_enabled: boolean;
		area_selection_enabled: boolean;
		series_colors: string[];
		overlays: OverlayConfig[];
		reference_lines: ReferenceLineConfig[];
	};

	const uid = `plot-${Math.random().toString(36).slice(2, 9)}`;

	interface Props {
		schema: Schema;
		config?: Record<string, unknown>;
	}

	const defaultConfig = {
		chart_type: 'bar',
		x_column: '',
		y_column: '',
		bins: 10,
		aggregation: 'sum',
		group_column: null,
		group_sort_by: null,
		group_sort_order: 'asc',
		group_sort_column: null,
		stack_mode: 'grouped',
		sort_by: null,
		sort_order: 'asc',
		sort_column: null,
		x_axis_label: '',
		y_axis_label: '',
		y_axis_scale: 'linear',
		y_axis_min: null,
		y_axis_max: null,
		display_units: '',
		decimal_places: 2,
		legend_position: 'right',
		title: '',
		area_opacity: 0.35,
		date_bucket: null,
		date_ordinal: null,
		pan_zoom_enabled: false,
		selection_enabled: false,
		area_selection_enabled: false,
		series_colors: [],
		overlays: [],
		reference_lines: []
	} satisfies PlotConfigData;

	const configDefaults = defaultConfig satisfies Record<string, unknown>;

	let { schema, config = $bindable(configDefaults) }: Props = $props();
	const plotConfig = $derived.by(() => config as unknown as PlotConfigData);

	const chartTypes: Array<{ value: PlotConfigData['chart_type']; label: string }> = [
		{ value: 'bar', label: 'Bar Chart' },
		{ value: 'horizontal_bar', label: 'Horizontal Bar' },
		{ value: 'area', label: 'Area Chart' },
		{ value: 'heatgrid', label: 'Heat Grid' },
		{ value: 'histogram', label: 'Histogram' },
		{ value: 'scatter', label: 'Scatter Plot' },
		{ value: 'line', label: 'Line Chart' },
		{ value: 'pie', label: 'Pie Chart' },
		{ value: 'boxplot', label: 'Box Plot' }
	];

	const aggregations = [
		{ value: 'sum', label: 'Sum' },
		{ value: 'mean', label: 'Mean' },
		{ value: 'median', label: 'Median' },
		{ value: 'count', label: 'Count' },
		{ value: 'min', label: 'Min' },
		{ value: 'max', label: 'Max' },
		{ value: 'std', label: 'Std Dev' },
		{ value: 'variance', label: 'Variance' },
		{ value: 'unique_count', label: 'Unique Count' }
	] satisfies Array<{ value: PlotConfigData['aggregation']; label: string }>;

	const needsAggregation = $derived(
		plotConfig.chart_type === 'bar' ||
			plotConfig.chart_type === 'horizontal_bar' ||
			plotConfig.chart_type === 'line' ||
			plotConfig.chart_type === 'area' ||
			plotConfig.chart_type === 'pie' ||
			plotConfig.chart_type === 'heatgrid'
	);
	const needsBins = $derived(plotConfig.chart_type === 'histogram');
	const needsGroup = $derived(
		plotConfig.chart_type === 'scatter' ||
			plotConfig.chart_type === 'bar' ||
			plotConfig.chart_type === 'horizontal_bar' ||
			plotConfig.chart_type === 'line' ||
			plotConfig.chart_type === 'area' ||
			plotConfig.chart_type === 'pie'
	);
	const showStackMode = $derived(
		plotConfig.chart_type === 'bar' ||
			plotConfig.chart_type === 'horizontal_bar' ||
			plotConfig.chart_type === 'area'
	);
	const needsHeatgridY = $derived(plotConfig.chart_type === 'heatgrid');
	const showAreaOpacity = $derived(plotConfig.chart_type === 'area');
	const needsYAxis = $derived(
		plotConfig.chart_type !== 'histogram' &&
			plotConfig.chart_type !== 'pie' &&
			plotConfig.chart_type !== 'heatgrid'
	);
	const showSort = $derived(
		plotConfig.chart_type === 'bar' ||
			plotConfig.chart_type === 'horizontal_bar' ||
			plotConfig.chart_type === 'area' ||
			plotConfig.chart_type === 'line' ||
			plotConfig.chart_type === 'pie' ||
			plotConfig.chart_type === 'histogram'
	);
	const showLegend = $derived(
		plotConfig.chart_type !== 'histogram' && plotConfig.chart_type !== 'heatgrid'
	);
	const showSeriesColors = $derived(
		plotConfig.chart_type === 'bar' ||
			plotConfig.chart_type === 'horizontal_bar' ||
			plotConfig.chart_type === 'area' ||
			plotConfig.chart_type === 'line' ||
			plotConfig.chart_type === 'scatter' ||
			plotConfig.chart_type === 'pie'
	);
	const showGroupSort = $derived(needsGroup && Boolean(plotConfig.group_column));
	const showDateBucket = $derived(
		plotConfig.chart_type === 'bar' ||
			plotConfig.chart_type === 'horizontal_bar' ||
			plotConfig.chart_type === 'line' ||
			plotConfig.chart_type === 'area' ||
			plotConfig.chart_type === 'pie'
	);
	const showInteractivity = $derived(
		plotConfig.chart_type === 'bar' ||
			plotConfig.chart_type === 'horizontal_bar' ||
			plotConfig.chart_type === 'line' ||
			plotConfig.chart_type === 'area' ||
			plotConfig.chart_type === 'scatter'
	);
	const showAreaSelection = $derived(plotConfig.chart_type === 'scatter');

	function parseSeriesColors(value: string): string[] {
		return value
			.split(',')
			.map((item) => item.trim())
			.filter((item) => item.length > 0);
	}
	const showAxisFormatting = $derived(
		plotConfig.chart_type !== 'pie' && plotConfig.chart_type !== 'heatgrid'
	);

	let yMinInput = $state('');
	let yMaxInput = $state('');
	let decimalInput = $state('');
	let yMinDirty = $state(false);
	let yMaxDirty = $state(false);
	let decimalDirty = $state(false);
	let areaOpacityInput = $state('');
	let areaOpacityDirty = $state(false);
	let overlayValue = $state('');
	let overlayAxis = $state<'left' | 'right'>('left');
	let overlayType = $state<OverlayConfig['chart_type']>('line');
	let overlayAgg = $state<OverlayConfig['aggregation']>('sum');
	let refAxis = $state<ReferenceLineConfig['axis']>('y');
	let refValue = $state('');
	let refLabel = $state('');
	let refColor = $state('');

	const yMinDisplay = $derived(
		yMinDirty ? yMinInput : plotConfig.y_axis_min === null ? '' : String(plotConfig.y_axis_min)
	);
	const yMaxDisplay = $derived(
		yMaxDirty ? yMaxInput : plotConfig.y_axis_max === null ? '' : String(plotConfig.y_axis_max)
	);
	const decimalDisplay = $derived(
		decimalDirty ? decimalInput : String(plotConfig.decimal_places ?? 0)
	);
	const areaOpacityDisplay = $derived(
		areaOpacityDirty ? areaOpacityInput : String(plotConfig.area_opacity ?? 0.35)
	);

	function setYAxisMin(value: string) {
		yMinInput = value;
		yMinDirty = true;
	}

	function setYAxisMax(value: string) {
		yMaxInput = value;
		yMaxDirty = true;
	}

	function setDecimalPlaces(value: string) {
		decimalInput = value;
		decimalDirty = true;
	}

	function setAreaOpacity(value: string) {
		areaOpacityInput = value;
		areaOpacityDirty = true;
	}

	function commitYAxisMin() {
		if (yMinInput.trim() === '') {
			plotConfig.y_axis_min = null;
			normalizeAxisRange();
			yMinDirty = false;
			yMinInput = '';
			return;
		}
		const parsed = Number(yMinInput);
		plotConfig.y_axis_min = Number.isNaN(parsed) ? null : parsed;
		if (plotConfig.y_axis_min === null) {
			yMinInput = '';
		}
		normalizeAxisRange();
		yMinDirty = false;
	}

	function commitYAxisMax() {
		if (yMaxInput.trim() === '') {
			plotConfig.y_axis_max = null;
			normalizeAxisRange();
			yMaxDirty = false;
			yMaxInput = '';
			return;
		}
		const parsed = Number(yMaxInput);
		plotConfig.y_axis_max = Number.isNaN(parsed) ? null : parsed;
		if (plotConfig.y_axis_max === null) {
			yMaxInput = '';
		}
		normalizeAxisRange();
		yMaxDirty = false;
	}

	function commitDecimalPlaces() {
		const parsed = Number(decimalInput);
		if (Number.isNaN(parsed)) {
			decimalInput = String(plotConfig.decimal_places ?? 0);
			decimalDirty = false;
			return;
		}
		const clamped = Math.max(0, Math.min(4, Math.round(parsed)));
		plotConfig.decimal_places = clamped;
		decimalInput = String(clamped);
		decimalDirty = false;
	}

	function commitAreaOpacity() {
		const parsed = Number(areaOpacityInput);
		if (Number.isNaN(parsed)) {
			areaOpacityInput = String(plotConfig.area_opacity ?? 0.35);
			areaOpacityDirty = false;
			return;
		}
		const clamped = Math.max(0, Math.min(1, parsed));
		plotConfig.area_opacity = clamped;
		areaOpacityInput = String(clamped);
		areaOpacityDirty = false;
	}

	function normalizeAxisRange() {
		if (plotConfig.y_axis_min === null || plotConfig.y_axis_max === null) return;
		if (plotConfig.y_axis_min <= plotConfig.y_axis_max) return;
		const minValue = plotConfig.y_axis_min;
		plotConfig.y_axis_min = plotConfig.y_axis_max;
		plotConfig.y_axis_max = minValue;
		yMinInput = String(plotConfig.y_axis_min);
		yMaxInput = String(plotConfig.y_axis_max);
	}

	function addOverlay() {
		if (!overlayValue) return;
		plotConfig.overlays = [
			...plotConfig.overlays,
			{
				chart_type: overlayType,
				y_column: overlayValue,
				aggregation: overlayAgg,
				y_axis_position: overlayAxis
			}
		];
		overlayValue = '';
		overlayAxis = 'left';
		overlayType = 'line';
		overlayAgg = 'sum';
	}

	function removeOverlay(index: number) {
		plotConfig.overlays = plotConfig.overlays.filter((_, i) => i !== index);
	}

	function updateOverlay(index: number, next: Partial<OverlayConfig>) {
		plotConfig.overlays = plotConfig.overlays.map((entry, i) =>
			i === index ? { ...entry, ...next } : entry
		);
	}

	function addReferenceLine() {
		if (refValue.trim() === '') return;
		const parsed = Number(refValue);
		if (Number.isNaN(parsed)) return;
		plotConfig.reference_lines = [
			...plotConfig.reference_lines,
			{
				axis: refAxis,
				value: parsed,
				label: refLabel.trim(),
				color: refColor.trim()
			}
		];
		refValue = '';
		refLabel = '';
		refColor = '';
		refAxis = 'y';
	}

	function removeReferenceLine(index: number) {
		plotConfig.reference_lines = plotConfig.reference_lines.filter((_, i) => i !== index);
	}

	function updateReferenceLine(index: number, next: Partial<ReferenceLineConfig>) {
		plotConfig.reference_lines = plotConfig.reference_lines.map((entry, i) =>
			i === index ? { ...entry, ...next } : entry
		);
	}
</script>

<div class="config-panel" role="region" aria-label="Plot configuration">
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

	{#if plotConfig.chart_type !== 'histogram' && plotConfig.chart_type !== 'heatgrid'}
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

	{#if needsHeatgridY}
		<div class="form-section" role="group" aria-labelledby={`${uid}-plot-heat-y`}>
			<h4 id={`${uid}-plot-heat-y`}>Heat Grid Y Column</h4>
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

	{#if showStackMode}
		<div class="form-section" role="group" aria-labelledby={`${uid}-plot-stack`}>
			<h4 id={`${uid}-plot-stack`}>Stack Mode</h4>
			<select bind:value={plotConfig.stack_mode} class="select-mono">
				<option value="grouped">Grouped</option>
				<option value="stacked">Stacked</option>
				<option value="100%">100%</option>
			</select>
		</div>
	{/if}

	{#if needsGroup}
		<div class="form-section" role="group" aria-labelledby={`${uid}-plot-group`}>
			<h4 id={`${uid}-plot-group`}>Segment By</h4>
			<ColumnDropdown
				{schema}
				value={plotConfig.group_column ?? ''}
				onChange={(val) => (plotConfig.group_column = val)}
				placeholder="Optional group column..."
			/>
		</div>
	{/if}

	{#if showGroupSort}
		<div class="form-section" role="group" aria-labelledby={`${uid}-plot-group-sort`}>
			<h4 id={`${uid}-plot-group-sort`}>Group Sorting</h4>
			<div class="grid gap-3">
				<div>
					<label class="form-label" for={`${uid}-group-sort-by`}>Sort By</label>
					<select
						id={`${uid}-group-sort-by`}
						bind:value={plotConfig.group_sort_by}
						class="select-mono"
					>
						<option value={null}>Default</option>
						<option value="name">Name</option>
						<option value="value">Value</option>
						<option value="custom">Custom column</option>
					</select>
				</div>
				<div>
					<label class="form-label" for={`${uid}-group-sort-order`}>Order</label>
					<select
						id={`${uid}-group-sort-order`}
						bind:value={plotConfig.group_sort_order}
						class="select-mono"
					>
						<option value="asc">Ascending</option>
						<option value="desc">Descending</option>
					</select>
				</div>
				{#if plotConfig.group_sort_by === 'custom'}
					<div>
						<label class="form-label" for={`${uid}-group-sort-column`}>Sort Column</label>
						<div id={`${uid}-group-sort-column`}>
							<ColumnDropdown
								{schema}
								value={plotConfig.group_sort_column ?? ''}
								onChange={(val) => (plotConfig.group_sort_column = val)}
								placeholder="Select column..."
							/>
						</div>
					</div>
				{/if}
			</div>
		</div>
	{/if}

	{#if showSeriesColors}
		<div class="form-section" role="group" aria-labelledby={`${uid}-plot-colors`}>
			<h4 id={`${uid}-plot-colors`}>Series Colors</h4>
			<input
				type="text"
				value={plotConfig.series_colors.join(', ')}
				oninput={(e) => (plotConfig.series_colors = parseSeriesColors(e.currentTarget.value))}
				placeholder="#4A8FE7, #50B88E, #E8A838"
			/>
			<p class="form-help">Comma-separated colors (hex or CSS names)</p>
		</div>
	{/if}

	{#if showAreaOpacity}
		<div class="form-section" role="group" aria-labelledby={`${uid}-plot-area-opacity`}>
			<h4 id={`${uid}-plot-area-opacity`}>Area Opacity</h4>
			<input
				type="number"
				min="0"
				max="1"
				step="0.05"
				value={areaOpacityDisplay}
				oninput={(e) => setAreaOpacity(e.currentTarget.value)}
				onblur={commitAreaOpacity}
			/>
			<p class="form-help">Range 0–1</p>
		</div>
	{/if}

	{#if showDateBucket}
		<div class="form-section" role="group" aria-labelledby={`${uid}-plot-date-bucket`}>
			<h4 id={`${uid}-plot-date-bucket`}>Date Bucketing</h4>
			<div class="grid gap-3">
				<div>
					<label class="form-label" for={`${uid}-date-bucket`}>Bucket</label>
					<select id={`${uid}-date-bucket`} bind:value={plotConfig.date_bucket} class="select-mono">
						<option value={null}>None</option>
						<option value="exact">Exact</option>
						<option value="year">Year</option>
						<option value="quarter">Quarter</option>
						<option value="month">Month</option>
						<option value="week">Week</option>
						<option value="day">Day</option>
						<option value="hour">Hour</option>
					</select>
				</div>
				<div>
					<label class="form-label" for={`${uid}-date-ordinal`}>Ordinal</label>
					<select
						id={`${uid}-date-ordinal`}
						bind:value={plotConfig.date_ordinal}
						class="select-mono"
					>
						<option value={null}>None</option>
						<option value="day_of_week">Day of Week</option>
						<option value="month_of_year">Month of Year</option>
						<option value="quarter_of_year">Quarter of Year</option>
					</select>
				</div>
			</div>
			<p class="form-help">Applies when X column is a date/time field.</p>
		</div>
	{/if}

	{#if showInteractivity}
		<div class="form-section" role="group" aria-labelledby={`${uid}-plot-interactivity`}>
			<h4 id={`${uid}-plot-interactivity`}>Interactivity</h4>
			<div class="grid gap-3">
				<label class="form-checkbox" for={`${uid}-plot-zoom`}>
					<input
						id={`${uid}-plot-zoom`}
						type="checkbox"
						bind:checked={plotConfig.pan_zoom_enabled}
					/>
					<span>Pan & Zoom</span>
				</label>
				<label class="form-checkbox" for={`${uid}-plot-select`}>
					<input
						id={`${uid}-plot-select`}
						type="checkbox"
						bind:checked={plotConfig.selection_enabled}
					/>
					<span>Click Selection</span>
				</label>
				{#if showAreaSelection}
					<label class="form-checkbox" for={`${uid}-plot-area-select`}>
						<input
							id={`${uid}-plot-area-select`}
							type="checkbox"
							bind:checked={plotConfig.area_selection_enabled}
						/>
						<span>Area Selection (scatter)</span>
					</label>
				{/if}
			</div>
		</div>
	{/if}

	<div class="form-section" role="group" aria-labelledby={`${uid}-plot-title`}>
		<h4 id={`${uid}-plot-title`}>Chart Title</h4>
		<input
			type="text"
			value={plotConfig.title ?? ''}
			oninput={(e) => (plotConfig.title = e.currentTarget.value)}
			placeholder="Optional title"
		/>
	</div>

	{#if showSort}
		<div class="form-section" role="group" aria-labelledby={`${uid}-plot-sort`}>
			<h4 id={`${uid}-plot-sort`}>Sort Options</h4>
			<div class="grid gap-3">
				<div>
					<label class="form-label" for={`${uid}-sort-by`}>Sort By</label>
					<select id={`${uid}-sort-by`} bind:value={plotConfig.sort_by} class="select-mono">
						<option value={null}>Default</option>
						<option value="x">X value</option>
						<option value="y">Y value</option>
						<option value="custom">Custom column</option>
					</select>
				</div>
				<div>
					<label class="form-label" for={`${uid}-sort-order`}>Order</label>
					<select id={`${uid}-sort-order`} bind:value={plotConfig.sort_order} class="select-mono">
						<option value="asc">Ascending</option>
						<option value="desc">Descending</option>
					</select>
				</div>
				{#if plotConfig.sort_by === 'custom'}
					<div>
						<label class="form-label" for={`${uid}-sort-column`}>Sort Column</label>
						<div id={`${uid}-sort-column`}>
							<ColumnDropdown
								{schema}
								value={plotConfig.sort_column ?? ''}
								onChange={(val) => (plotConfig.sort_column = val)}
								placeholder="Select column..."
							/>
						</div>
					</div>
				{/if}
			</div>
		</div>
	{/if}

	{#if showAxisFormatting}
		<div class="form-section" role="group" aria-labelledby={`${uid}-plot-axis`}>
			<h4 id={`${uid}-plot-axis`}>Axis Formatting</h4>
			<div class="grid gap-3">
				<div>
					<label class="form-label" for={`${uid}-axis-x-label`}>X Axis Label</label>
					<input
						id={`${uid}-axis-x-label`}
						type="text"
						value={plotConfig.x_axis_label ?? ''}
						oninput={(e) => (plotConfig.x_axis_label = e.currentTarget.value)}
						placeholder="Optional label"
					/>
				</div>
				<div>
					<label class="form-label" for={`${uid}-axis-y-label`}>Y Axis Label</label>
					<input
						id={`${uid}-axis-y-label`}
						type="text"
						value={plotConfig.y_axis_label ?? ''}
						oninput={(e) => (plotConfig.y_axis_label = e.currentTarget.value)}
						placeholder="Optional label"
					/>
				</div>
				{#if needsYAxis}
					<div>
						<label class="form-label" for={`${uid}-axis-y-scale`}>Y Axis Scale</label>
						<select
							id={`${uid}-axis-y-scale`}
							bind:value={plotConfig.y_axis_scale}
							class="select-mono"
						>
							<option value="linear">Linear</option>
							<option value="log">Log</option>
						</select>
					</div>
					<div>
						<label class="form-label" for={`${uid}-axis-y-min`}>Y Axis Min</label>
						<input
							id={`${uid}-axis-y-min`}
							type="number"
							value={yMinDisplay}
							oninput={(e) => setYAxisMin(e.currentTarget.value)}
							onblur={commitYAxisMin}
							placeholder="auto"
						/>
					</div>
					<div>
						<label class="form-label" for={`${uid}-axis-y-max`}>Y Axis Max</label>
						<input
							id={`${uid}-axis-y-max`}
							type="number"
							value={yMaxDisplay}
							oninput={(e) => setYAxisMax(e.currentTarget.value)}
							onblur={commitYAxisMax}
							placeholder="auto"
						/>
					</div>
				{/if}
				<div>
					<label class="form-label" for={`${uid}-axis-units`}>Display Units</label>
					<select
						id={`${uid}-axis-units`}
						bind:value={plotConfig.display_units}
						class="select-mono"
					>
						<option value="">None</option>
						<option value="K">Thousands (K)</option>
						<option value="M">Millions (M)</option>
						<option value="B">Billions (B)</option>
						<option value="%">Percent (%)</option>
					</select>
				</div>
				<div>
					<label class="form-label" for={`${uid}-axis-decimals`}>Decimal Places</label>
					<input
						id={`${uid}-axis-decimals`}
						type="number"
						min="0"
						max="4"
						value={decimalDisplay}
						oninput={(e) => setDecimalPlaces(e.currentTarget.value)}
						onblur={commitDecimalPlaces}
					/>
				</div>
			</div>
		</div>
	{/if}

	{#if showLegend}
		<div class="form-section" role="group" aria-labelledby={`${uid}-plot-legend`}>
			<h4 id={`${uid}-plot-legend`}>Legend Position</h4>
			<select
				id={`${uid}-legend-position`}
				bind:value={plotConfig.legend_position}
				class="select-mono"
			>
				<option value="right">Right</option>
				<option value="left">Left</option>
				<option value="top">Top</option>
				<option value="bottom">Bottom</option>
				<option value="none">Hidden</option>
			</select>
		</div>
	{/if}

	<div class="form-section" role="group" aria-labelledby={`${uid}-plot-overlays`}>
		<h4 id={`${uid}-plot-overlays`}>Overlays</h4>
		<div class="grid gap-3">
			<div>
				<label class="form-label" for={`${uid}-overlay-column`}>Y Column</label>
				<ColumnDropdown
					{schema}
					value={overlayValue}
					onChange={(val) => (overlayValue = val)}
					placeholder="Select column..."
				/>
			</div>
			<div>
				<label class="form-label" for={`${uid}-overlay-type`}>Chart Type</label>
				<select id={`${uid}-overlay-type`} bind:value={overlayType} class="select-mono">
					<option value="line">Line</option>
					<option value="area">Area</option>
					<option value="bar">Bar</option>
					<option value="scatter">Scatter</option>
				</select>
			</div>
			<div>
				<label class="form-label" for={`${uid}-overlay-axis`}>Axis</label>
				<select id={`${uid}-overlay-axis`} bind:value={overlayAxis} class="select-mono">
					<option value="left">Left</option>
					<option value="right">Right</option>
				</select>
			</div>
			<div>
				<label class="form-label" for={`${uid}-overlay-agg`}>Aggregation</label>
				<select id={`${uid}-overlay-agg`} bind:value={overlayAgg} class="select-mono">
					{#each aggregations as agg (agg.value)}
						<option value={agg.value}>{agg.label}</option>
					{/each}
				</select>
			</div>
			<button
				type="button"
				class="flex items-center gap-1 py-2 px-4 border-none cursor-pointer whitespace-nowrap bg-accent-bg text-accent-primary disabled:bg-border-tertiary disabled:cursor-not-allowed disabled:text-fg-muted"
				onclick={addOverlay}
				disabled={!overlayValue}
				aria-label="Add overlay"
			>
				<Plus size={16} aria-hidden="true" />
				Add overlay
			</button>
		</div>

		{#if plotConfig.overlays.length > 0}
			<div class="grid gap-2">
				{#each plotConfig.overlays as overlay, index (index)}
					<div class="flex flex-wrap items-center gap-2 border border-tertiary p-2" role="group">
						<div class="min-w-40 flex-1">
							<ColumnDropdown
								{schema}
								value={overlay.y_column}
								onChange={(val) => updateOverlay(index, { y_column: val })}
								placeholder="Select column..."
							/>
						</div>
						<select
							class="select-mono"
							bind:value={overlay.chart_type}
							onchange={(e) =>
								updateOverlay(index, {
									chart_type: e.currentTarget.value as OverlayConfig['chart_type']
								})}
						>
							<option value="line">Line</option>
							<option value="area">Area</option>
							<option value="bar">Bar</option>
							<option value="scatter">Scatter</option>
						</select>
						<select
							class="select-mono"
							bind:value={overlay.aggregation}
							onchange={(e) =>
								updateOverlay(index, {
									aggregation: e.currentTarget.value as OverlayConfig['aggregation']
								})}
						>
							{#each aggregations as agg (agg.value)}
								<option value={agg.value}>{agg.label}</option>
							{/each}
						</select>
						<select
							class="select-mono"
							bind:value={overlay.y_axis_position}
							onchange={(e) =>
								updateOverlay(index, {
									y_axis_position: e.currentTarget.value as OverlayConfig['y_axis_position']
								})}
						>
							<option value="left">Left</option>
							<option value="right">Right</option>
						</select>
						<button
							type="button"
							class="flex items-center justify-center w-7 h-7 p-0 bg-transparent cursor-pointer text-fg-secondary border border-transparent hover:bg-error! hover:text-error-fg! hover:border-error!"
							onclick={() => removeOverlay(index)}
							title="Remove overlay"
							aria-label="Remove overlay"
						>
							<X size={14} aria-hidden="true" />
						</button>
					</div>
				{/each}
			</div>
		{:else}
			<p class="form-help">No overlays configured.</p>
		{/if}
	</div>

	<div class="form-section" role="group" aria-labelledby={`${uid}-plot-reference-lines`}>
		<h4 id={`${uid}-plot-reference-lines`}>Reference Lines</h4>
		<div class="grid gap-3">
			<div>
				<label class="form-label" for={`${uid}-ref-axis`}>Axis</label>
				<select id={`${uid}-ref-axis`} bind:value={refAxis} class="select-mono">
					<option value="y">Y</option>
					<option value="x">X</option>
				</select>
			</div>
			<div>
				<label class="form-label" for={`${uid}-ref-value`}>Value</label>
				<input
					id={`${uid}-ref-value`}
					type="number"
					value={refValue}
					oninput={(e) => (refValue = e.currentTarget.value)}
					placeholder="0"
				/>
			</div>
			<div>
				<label class="form-label" for={`${uid}-ref-label`}>Label</label>
				<input
					id={`${uid}-ref-label`}
					type="text"
					value={refLabel}
					oninput={(e) => (refLabel = e.currentTarget.value)}
					placeholder="Optional"
				/>
			</div>
			<div>
				<label class="form-label" for={`${uid}-ref-color`}>Color</label>
				<input
					id={`${uid}-ref-color`}
					type="text"
					value={refColor}
					oninput={(e) => (refColor = e.currentTarget.value)}
					placeholder="#E0687A"
				/>
			</div>
			<button
				type="button"
				class="flex items-center gap-1 py-2 px-4 border-none cursor-pointer whitespace-nowrap bg-accent-bg text-accent-primary disabled:bg-border-tertiary disabled:cursor-not-allowed disabled:text-fg-muted"
				onclick={addReferenceLine}
				disabled={refValue.trim() === ''}
				aria-label="Add reference line"
			>
				<Plus size={16} aria-hidden="true" />
				Add reference line
			</button>
		</div>

		{#if plotConfig.reference_lines.length > 0}
			<div class="grid gap-2">
				{#each plotConfig.reference_lines as line, index (index)}
					<div class="flex flex-wrap items-center gap-2 border border-tertiary p-2" role="group">
						<select
							class="select-mono"
							bind:value={line.axis}
							onchange={(e) =>
								updateReferenceLine(index, {
									axis: e.currentTarget.value as ReferenceLineConfig['axis']
								})}
						>
							<option value="y">Y</option>
							<option value="x">X</option>
						</select>
						<input
							type="number"
							value={line.value ?? ''}
							oninput={(e) =>
								updateReferenceLine(index, {
									value: Number(e.currentTarget.value)
								})}
							placeholder="0"
						/>
						<input
							type="text"
							value={line.label ?? ''}
							oninput={(e) =>
								updateReferenceLine(index, {
									label: e.currentTarget.value
								})}
							placeholder="Label"
						/>
						<input
							type="text"
							value={line.color ?? ''}
							oninput={(e) =>
								updateReferenceLine(index, {
									color: e.currentTarget.value
								})}
							placeholder="#E0687A"
						/>
						<button
							type="button"
							class="flex items-center justify-center w-7 h-7 p-0 bg-transparent cursor-pointer text-fg-secondary border border-transparent hover:bg-error! hover:text-error-fg! hover:border-error!"
							onclick={() => removeReferenceLine(index)}
							title="Remove reference line"
							aria-label="Remove reference line"
						>
							<X size={14} aria-hidden="true" />
						</button>
					</div>
				{/each}
			</div>
		{:else}
			<p class="form-help">No reference lines configured.</p>
		{/if}
	</div>
</div>
