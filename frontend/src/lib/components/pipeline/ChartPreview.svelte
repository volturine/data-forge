<script lang="ts">
	import * as d3 from 'd3';
	import { downloadBlob } from '$lib/api/compute';
	import { SvelteMap, SvelteSet } from 'svelte/reactivity';

	type ChartType =
		| 'bar'
		| 'horizontal_bar'
		| 'area'
		| 'heatgrid'
		| 'line'
		| 'pie'
		| 'histogram'
		| 'scatter'
		| 'boxplot';
	type Row = Record<string, unknown>;

	interface Props {
		data: Row[];
		chartType: ChartType;
		config: Record<string, unknown>;
		metadata?: Record<string, unknown> | null;
	}

	const { data, chartType, config, metadata }: Props = $props();

	/* ── Enterprise color palette (Contour-inspired) ── */
	const PALETTE = [
		'#4A8FE7',
		'#50B88E',
		'#E8A838',
		'#E0687A',
		'#7F72B5',
		'#3AB4A0',
		'#EC8B56',
		'#9B8EC4'
	];

	const HOVER_DIM = 0.25;

	/* ── Refs ── */
	let chartEl: HTMLDivElement | undefined = $state();
	let wrapperEl: HTMLDivElement | undefined = $state();

	/* ── Tooltip state (reactive, avoids direct DOM manipulation) ── */
	let tipTitle = $state('');
	let tipLines: Array<{ label: string; value: string }> = $state([]);
	let tipX = $state(0);
	let tipY = $state(0);
	let tipVisible = $state(false);
	const selectedKeys = new SvelteSet<string>();
	const hiddenSeries = new SvelteSet<string>();
	let zoomTransform = $state<d3.ZoomTransform | null>(null);
	let zoomBehavior = $state<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
	let zoomTarget = $state<SVGSVGElement | null>(null);
	const zoomEnabled = $derived(Boolean(config.pan_zoom_enabled));
	const selectEnabled = $derived(Boolean(config.selection_enabled));
	const areaSelectEnabled = $derived(Boolean(config.area_selection_enabled));
	const zoomActive = $derived(Boolean(zoomTransform));

	// Subscription: $derived can't reset zoom state.
	$effect(() => {
		if (zoomEnabled) return;
		zoomTransform = null;
		zoomBehavior = null;
		zoomTarget = null;
	});

	// Subscription: $derived can't clear selection sets.
	$effect(() => {
		if (selectEnabled) return;
		selectedKeys.clear();
	});

	function resetZoom() {
		if (!zoomTransform) return;
		zoomTransform = null;
		if (!zoomBehavior || !zoomTarget) return;
		d3.select(zoomTarget).call(zoomBehavior.transform, d3.zoomIdentity);
	}

	/* ── Primitive helpers ── */
	function num(v: unknown): number {
		if (typeof v === 'number') return v;
		if (typeof v === 'string') return Number(v) || 0;
		return 0;
	}

	function str(v: unknown): string {
		if (v == null) return '';
		return String(v);
	}

	function getChartAriaLabel(): string {
		const title = str(config.title).trim();
		if (title) return title;
		const typeLabel = chartType.replace('_', ' ');
		return `${typeLabel} chart`;
	}

	function getDecimalPlaces(): number {
		const raw = Number(config.decimal_places ?? 2);
		if (Number.isNaN(raw)) return 2;
		if (raw < 0) return 0;
		if (raw > 6) return 6;
		return Math.round(raw);
	}

	function formatUnits(v: number): { value: number; suffix: string } {
		const unit = str(config.display_units);
		if (unit === 'K') return { value: v / 1e3, suffix: 'K' };
		if (unit === 'M') return { value: v / 1e6, suffix: 'M' };
		if (unit === 'B') return { value: v / 1e9, suffix: 'B' };
		if (unit === '%') return { value: v * 100, suffix: '%' };
		return { value: v, suffix: '' };
	}

	/* Abbreviated format for axis ticks */
	function fmtAxis(v: number): string {
		const decimals = getDecimalPlaces();
		const formatted = formatUnits(v);
		const fmt = d3.format(`,.${decimals}f`)(formatted.value);
		return `${fmt}${formatted.suffix}`;
	}

	function fmtAxisTime(value: unknown): string {
		const raw = str(value);
		if (!raw) return '';
		const parsed = new Date(raw);
		if (Number.isNaN(parsed.getTime())) return raw;
		const bucket = str(config.date_bucket);
		const ordinal = str(config.date_ordinal);
		if (ordinal === 'day_of_week') return d3.timeFormat('%a')(parsed);
		if (ordinal === 'month_of_year') return d3.timeFormat('%b')(parsed);
		if (ordinal === 'quarter_of_year') {
			const quarter = Math.floor(parsed.getMonth() / 3) + 1;
			return `Q${quarter}`;
		}
		if (bucket === 'year') return d3.timeFormat('%Y')(parsed);
		if (bucket === 'quarter') {
			const quarter = Math.floor(parsed.getMonth() / 3) + 1;
			return `Q${quarter} ${parsed.getFullYear()}`;
		}
		if (bucket === 'month') return d3.timeFormat('%b %Y')(parsed);
		if (bucket === 'week') return d3.timeFormat('%b %d')(parsed);
		if (bucket === 'day') return d3.timeFormat('%b %d')(parsed);
		if (bucket === 'hour') return d3.timeFormat('%b %d %H:00')(parsed);
		return d3.timeFormat('%Y-%m-%d')(parsed);
	}

	/* Full format for tooltips and value labels */
	function fmtFull(v: number): string {
		const decimals = getDecimalPlaces();
		const formatted = formatUnits(v);
		const fmt = d3.format(`,.${decimals}f`)(formatted.value);
		return `${fmt}${formatted.suffix}`;
	}

	/* Derive axis titles from config */
	function getXTitle(): string {
		const label = str(config.x_axis_label).trim();
		if (label) return label;
		return str(config.x_column) || 'Category';
	}

	function getYTitle(): string {
		const label = str(config.y_axis_label).trim();
		if (label) return label;
		const agg = str(config.aggregation);
		const col = str(config.y_column);
		if (chartType === 'histogram') return 'Count';
		if (chartType === 'heatgrid') return col || 'Value';
		if (chartType === 'scatter' || chartType === 'boxplot') return col || 'Value';
		if (!col) return 'Count';
		const title = `${agg.charAt(0).toUpperCase()}${agg.slice(1)} of ${col}`;
		return title;
	}

	function getStackMode(): 'grouped' | 'stacked' | '100%' {
		const raw = str(config.stack_mode);
		if (raw === 'stacked' || raw === '100%') return raw;
		return 'grouped';
	}

	function getSeriesColors(): string[] {
		const raw = config.series_colors;
		if (!Array.isArray(raw)) return PALETTE;
		const cleaned = raw.map((value) => str(value).trim()).filter((value) => value.length > 0);
		if (cleaned.length === 0) return PALETTE;
		return cleaned;
	}

	function getOverlayConfigs(): Array<Record<string, unknown>> {
		const raw = metadata?.overlays;
		if (!Array.isArray(raw)) return [];
		return raw.filter((item) => item && typeof item === 'object') as Array<Record<string, unknown>>;
	}

	function getReferenceLines(): Array<Record<string, unknown>> {
		const raw = metadata?.reference_lines;
		if (!Array.isArray(raw)) return [];
		return raw.filter((item) => item && typeof item === 'object') as Array<Record<string, unknown>>;
	}

	function overlayAxisPosition(item: Record<string, unknown>): 'left' | 'right' {
		const raw = str(item.y_axis_position);
		if (raw === 'right') return 'right';
		return 'left';
	}

	function referenceLineAxisValue(item: Record<string, unknown>): 'x' | 'y' {
		const raw = str(item.axis);
		if (raw === 'x' || raw === 'y') return raw;
		const target = str(item.target_axis);
		if (target === 'x' || target === 'y') return target;
		return 'y';
	}

	function referenceLineAxisPosition(item: Record<string, unknown>): 'left' | 'right' {
		const raw = str(item.y_axis_position);
		if (raw === 'right') return 'right';
		const target = str(item.target_axis);
		if (target === 'right') return 'right';
		return 'left';
	}

	function overlayChartType(item: Record<string, unknown>): 'line' | 'area' | 'bar' | 'scatter' {
		const raw = str(item.chart_type);
		if (raw === 'area' || raw === 'bar' || raw === 'scatter') return raw;
		return 'line';
	}

	function overlaySeriesLabel(item: Record<string, unknown>): string {
		const yCol = str(item.y_column);
		const agg = str(item.aggregation);
		if (!yCol) return 'Overlay';
		if (!agg) return yCol;
		const label = `${agg.charAt(0).toUpperCase()}${agg.slice(1)} of ${yCol}`;
		return label;
	}

	function overlayData(item: Record<string, unknown>): Row[] {
		const raw = item.data;
		if (!Array.isArray(raw)) return [];
		return raw as Row[];
	}

	function getPrimaryColor(): string {
		const colors = getSeriesColors();
		return colors[0] ?? PALETTE[0];
	}

	function getAreaOpacity(): number {
		const raw = Number(config.area_opacity ?? 0.35);
		if (Number.isNaN(raw)) return 0.35;
		return Math.max(0, Math.min(1, raw));
	}

	function getGroupSortBy(): 'name' | 'value' | 'custom' | null {
		const raw = str(config.group_sort_by);
		if (raw === 'name' || raw === 'value' || raw === 'custom') return raw;
		return null;
	}

	function getGroupSortOrder(): 'asc' | 'desc' {
		const raw = str(config.group_sort_order);
		if (raw === 'desc') return 'desc';
		return 'asc';
	}

	function getGroupOrder(rows: Row[], groupKey: string): string[] {
		const groups = [...new Set(rows.map((r) => str(r[groupKey])))];
		const mode = getGroupSortBy();
		if (!mode) return groups;
		const order = getGroupSortOrder();
		if (mode === 'name') {
			return [...groups].sort((a, b) =>
				order === 'asc' ? a.localeCompare(b) : b.localeCompare(a)
			);
		}
		if (mode === 'value') {
			const sums = new SvelteMap<string, number>();
			for (const row of rows) {
				const key = str(row[groupKey]);
				const next = (sums.get(key) ?? 0) + num(row.y);
				sums.set(key, next);
			}
			return [...groups].sort((a, b) => {
				const aVal = sums.get(a) ?? 0;
				const bVal = sums.get(b) ?? 0;
				if (order === 'asc') return aVal - bVal;
				return bVal - aVal;
			});
		}
		const col = str(config.group_sort_column);
		if (!col) return groups;
		const values = new SvelteMap<string, string>();
		for (const row of rows) {
			const key = str(row[groupKey]);
			if (values.has(key)) continue;
			values.set(key, str(row[col]));
		}
		return [...groups].sort((a, b) => {
			const aVal = values.get(a) ?? '';
			const bVal = values.get(b) ?? '';
			const cmp = aVal.localeCompare(bVal);
			if (order === 'asc') return cmp;
			return -cmp;
		});
	}

	function makeKey(group: string, label: string): string {
		return `${group}::${label}`;
	}

	function makePointKey(group: string, label: string, value: number): string {
		return `${group}::${label}::${value}`;
	}

	function selectionOpacity(key: string): number {
		if (selectedKeys.size === 0) return 1;
		if (selectedKeys.has(key)) return 1;
		return HOVER_DIM;
	}

	function isSeriesVisible(series: string): boolean {
		if (hiddenSeries.size === 0) return true;
		return !hiddenSeries.has(series);
	}

	function updateLegend(svg: Svg) {
		svg.selectAll<SVGGElement, unknown>('.legend-item').each(function () {
			const item = d3.select(this);
			const label = str(item.attr('data-legend'));
			item.attr('opacity', isSeriesVisible(label) ? 1 : 0.35);
		});
	}

	function updateSeriesVisibility(svg: Svg) {
		svg.selectAll<SVGElement, unknown>('[data-series]').each(function () {
			const item = d3.select(this);
			const label = str(item.attr('data-series'));
			const visible = isSeriesVisible(label);
			item.attr('opacity', visible ? 1 : 0.15);
			item.attr('pointer-events', visible ? 'auto' : 'none');
		});
	}

	function updateSelection(svg: Svg) {
		svg.selectAll<SVGElement, unknown>('[data-key]').each(function () {
			const item = d3.select(this);
			const key = str(item.attr('data-key'));
			const series = str(item.attr('data-series'));
			if (series && !isSeriesVisible(series)) {
				item.attr('opacity', 0.15);
				return;
			}
			item.attr('opacity', selectionOpacity(key));
		});
	}

	function toggleSelection(key: string, multi: boolean) {
		if (!multi) selectedKeys.clear();
		if (selectedKeys.has(key)) {
			selectedKeys.delete(key);
			return;
		}
		selectedKeys.add(key);
	}

	function toggleSeries(series: string) {
		if (hiddenSeries.has(series)) {
			hiddenSeries.delete(series);
			return;
		}
		hiddenSeries.add(series);
	}

	function isolateSeries(series: string, all: string[]) {
		const next = new SvelteSet<string>();
		for (const item of all) {
			if (item !== series) next.add(item);
		}
		hiddenSeries.clear();
		for (const item of next) {
			hiddenSeries.add(item);
		}
	}

	function applyZoom(
		zoom: d3.ZoomTransform,
		x: d3.ScaleLinear<number, number> | d3.ScalePoint<string> | d3.ScaleBand<string>,
		y: AxisScale
	) {
		if ('invert' in x) {
			const zx = zoom.rescaleX(x);
			const zy = zoom.rescaleY(y as d3.ScaleLinear<number, number>);
			return { zx, zy };
		}
		const zy = zoom.rescaleY(y as d3.ScaleLinear<number, number>);
		return { zx: x, zy };
	}

	function buildStackRows(labels: string[], groups: string[], groupCol: string) {
		const rows = new SvelteMap<string, StackRow>();
		for (const label of labels) {
			const row = { x: label } as StackRow;
			for (const group of groups) {
				row[group] = 0;
			}
			rows.set(label, row);
		}

		for (const item of data) {
			const label = str(item.x);
			const group = str(item[groupCol]);
			const row = rows.get(label);
			if (!row) continue;
			row[group] = (row[group] ?? 0) + num(item.y);
		}

		const ordered = labels.map((label) => rows.get(label) ?? ({ x: label } as StackRow));
		const totals = ordered.map((row) => groups.reduce((sum, group) => sum + (row[group] ?? 0), 0));

		return { rows: ordered, totals };
	}

	/* ── Tooltip ── */
	function showTip(
		title: string,
		lines: Array<{ label: string; value: string }>,
		event: MouseEvent
	) {
		if (!wrapperEl) return;
		const rect = wrapperEl.getBoundingClientRect();
		let left = event.clientX - rect.left + 14;
		let top = event.clientY - rect.top - 14;
		if (left + 180 > rect.width) left = event.clientX - rect.left - 190;
		if (top < 4) top = event.clientY - rect.top + 14;
		tipTitle = title;
		tipLines = lines;
		tipX = left;
		tipY = top;
		tipVisible = true;
	}
	function hideTip() {
		tipVisible = false;
	}

	/* ── Shared D3 helpers ── */

	type Svg = d3.Selection<SVGGElement, unknown, null, undefined>;
	type RootSvg = d3.Selection<SVGSVGElement, unknown, null, undefined>;
	type AxisScale = d3.ScaleLinear<number, number> | d3.ScaleLogarithmic<number, number>;
	type StackRow = { x: string } & Record<string, number>;

	function getOptionalNumber(value: unknown): number | null {
		if (value == null) return null;
		const parsed = Number(value);
		if (Number.isNaN(parsed)) return null;
		return parsed;
	}

	function normalizeDomain(domain: [number, number], scale: 'linear' | 'log'): [number, number] {
		const min = domain[0];
		const max = domain[1];
		if (min !== max) return domain;
		if (scale === 'log') {
			const base = min <= 0 ? 1 : min;
			return [base, base * 10];
		}
		const delta = min === 0 ? 1 : Math.abs(min) * 0.1;
		return [min - delta, max + delta];
	}

	function buildValueScale(values: number[], baseMin: number, range: [number, number]): AxisScale {
		const configMin = getOptionalNumber(config.y_axis_min);
		const configMax = getOptionalNumber(config.y_axis_max);
		const scaleType = str(config.y_axis_scale) === 'log' ? 'log' : 'linear';
		const maxValue = d3.max(values) ?? 0;
		const minValue = d3.min(values) ?? baseMin;
		if (scaleType === 'log') {
			const positive = values.filter((v) => v > 0);
			const posMin = d3.min(positive) ?? 1;
			const posMax = d3.max(positive) ?? posMin;
			let min = posMin;
			if (configMin != null && configMin > 0) min = configMin;
			let max = posMax;
			if (configMax != null && configMax > 0) max = configMax;
			if (min > 0 && max > 0) {
				const domain = normalizeDomain([min, max], 'log');
				return d3.scaleLog().domain(domain).nice().range(range);
			}
		}
		const min = configMin ?? minValue;
		const max = configMax ?? maxValue;
		const domain = normalizeDomain([min, max], 'linear');
		return d3.scaleLinear().domain(domain).nice().range(range);
	}

	function buildYScale(values: number[], baseMin: number, h: number): AxisScale {
		return buildValueScale(values, baseMin, [h, 0]);
	}

	function addGrid(svg: Svg, y: AxisScale, w: number) {
		const grid = svg
			.append('g')
			.attr('class', 'grid')
			.call(
				d3
					.axisLeft(y)
					.ticks(5)
					.tickSize(-w)
					.tickFormat(() => '')
			);
		grid
			.selectAll('line')
			.attr('stroke', 'var(--border-primary)')
			.attr('stroke-opacity', 0.15)
			.attr('stroke-dasharray', '3,3');
		grid.select('.domain').remove();
		return grid;
	}

	function addVerticalGrid(svg: Svg, x: AxisScale, h: number) {
		const grid = svg
			.append('g')
			.attr('class', 'grid-v')
			.call(
				d3
					.axisBottom(x)
					.ticks(5)
					.tickSize(-h)
					.tickFormat(() => '')
			);
		grid.attr('transform', `translate(0,${h})`);
		grid
			.selectAll('line')
			.attr('stroke', 'var(--border-primary)')
			.attr('stroke-opacity', 0.15)
			.attr('stroke-dasharray', '3,3');
		grid.select('.domain').remove();
		return grid;
	}

	function addTitles(svg: Svg, xLabel: string, yLabel: string, w: number, h: number) {
		svg
			.append('text')
			.attr('x', w / 2)
			.attr('y', h + 44)
			.attr('text-anchor', 'middle')
			.attr('fill', 'var(--fg-muted)')
			.style('font-size', '11px')
			.style('font-family', 'var(--font-mono)')
			.text(xLabel);
		svg
			.append('text')
			.attr('transform', 'rotate(-90)')
			.attr('x', -h / 2)
			.attr('y', -48)
			.attr('text-anchor', 'middle')
			.attr('fill', 'var(--fg-muted)')
			.style('font-size', '11px')
			.style('font-family', 'var(--font-mono)')
			.text(yLabel);
	}

	function addChartTitle(svg: RootSvg, title: string, width: number) {
		const label = title.trim();
		if (!label) return;
		svg
			.append('text')
			.attr('x', width / 2)
			.attr('y', 18)
			.attr('text-anchor', 'middle')
			.attr('fill', 'var(--fg-primary)')
			.style('font-size', '12px')
			.style('font-family', 'var(--font-mono)')
			.text(label);
	}

	function addLegend(
		svg: Svg,
		labels: string[],
		color: (l: string) => string,
		w: number,
		h: number,
		options?: { onClick?: (label: string, event: MouseEvent | KeyboardEvent) => void }
	) {
		const position = str(config.legend_position) || 'right';
		if (position === 'none') return;
		const g = svg.append('g').attr('class', 'legend');
		const isVertical = position === 'left' || position === 'right';
		let xOff = 0;
		let yOff = 0;
		let maxWidth = 0;
		for (const label of labels) {
			const truncated = label.length > 14 ? label.slice(0, 14) + '…' : label;
			const item = g
				.append('g')
				.attr('class', 'legend-item')
				.attr('data-legend', label)
				.attr('transform', isVertical ? `translate(0, ${yOff})` : `translate(${xOff}, 0)`);
			if (options?.onClick) {
				item
					.attr('role', 'button')
					.attr('tabindex', 0)
					.attr('aria-label', `Toggle ${label}`)
					.style('cursor', 'pointer')
					.on('click', function (event: MouseEvent) {
						options.onClick?.(label, event);
					})
					.on('keydown', function (event: KeyboardEvent) {
						if (event.key !== 'Enter' && event.key !== ' ') return;
						event.preventDefault();
						options.onClick?.(label, event);
					});
			}
			item
				.append('rect')
				.attr('width', 8)
				.attr('height', 8)
				.attr('y', -8)
				.attr('fill', color(label))
				.attr('rx', 1);
			item
				.append('text')
				.attr('x', 12)
				.attr('fill', 'var(--fg-muted)')
				.style('font-size', '10px')
				.style('font-family', 'var(--font-mono)')
				.text(truncated);
			const itemWidth = truncated.length * 6.2 + 24;
			if (itemWidth > maxWidth) maxWidth = itemWidth;
			if (isVertical) yOff += 16;
			if (!isVertical) xOff += itemWidth;
		}
		const baseY = position === 'top' ? -24 : -8;
		const y = position === 'bottom' ? h + 12 : baseY;
		let x = 0;
		if (position === 'right') x = w - maxWidth;
		if (position === 'top' || position === 'bottom') x = (w - xOff) / 2;
		g.attr('transform', `translate(${x}, ${y})`);
		updateLegend(svg);
	}

	function addRightYAxis(svg: Svg, y: AxisScale, w: number) {
		const axis = svg
			.append('g')
			.attr('class', 'axis-right')
			.attr('transform', `translate(${w},0)`)
			.call(
				d3
					.axisRight(y)
					.ticks(5)
					.tickFormat((d) => fmtAxis(d as number))
			);
		axis
			.selectAll('.tick text')
			.attr('fill', 'var(--fg-tertiary)')
			.style('font-size', '10px')
			.style('font-family', 'var(--font-mono)');
		axis.selectAll('.domain').attr('stroke', 'var(--border-primary)');
		axis.selectAll('.tick line').attr('stroke', 'var(--border-primary)');
		return axis;
	}

	function drawReferenceLines(
		svg: Svg,
		lines: Array<Record<string, unknown>>,
		xScale: d3.ScaleBand<string> | d3.ScalePoint<string> | d3.ScaleLinear<number, number>,
		yScale:
			| AxisScale
			| d3.ScaleBand<string>
			| d3.ScalePoint<string>
			| d3.ScaleLinear<number, number>,
		w: number,
		h: number,
		yRight?: AxisScale | null
	) {
		if (!lines.length) return;
		for (const line of lines) {
			const axis = referenceLineAxisValue(line);
			const value = getOptionalNumber(line.value);
			if (value == null) continue;
			const color = str(line.color) || 'var(--border-primary)';
			const label = str(line.label);
			if (axis === 'x') {
				let xPos: number | null = null;
				if ('bandwidth' in xScale) {
					const band = xScale as d3.ScaleBand<string>;
					const domain = band.domain();
					const idx = Math.round(value);
					const key = domain[idx];
					if (key != null) {
						const pos = band(key);
						xPos = pos != null ? pos + band.bandwidth() / 2 : null;
					}
				} else if ('domain' in xScale) {
					xPos = (xScale as d3.ScaleLinear<number, number>)(value);
				}
				if (xPos == null) continue;
				svg
					.append('line')
					.attr('class', 'reference-line')
					.attr('x1', xPos)
					.attr('x2', xPos)
					.attr('y1', 0)
					.attr('y2', h)
					.attr('stroke', color)
					.attr('stroke-width', 1)
					.attr('stroke-dasharray', '4,4');
				if (label) {
					svg
						.append('text')
						.attr('class', 'reference-label')
						.attr('x', xPos + 4)
						.attr('y', 12)
						.attr('fill', color)
						.style('font-size', '10px')
						.style('font-family', 'var(--font-mono)')
						.text(label);
				}
				continue;
			}
			let yPos: number | null = null;
			const axisPosition = referenceLineAxisPosition(line);
			const canUseRight = Boolean(yRight) && !('bandwidth' in yScale);
			const scale = axisPosition === 'right' && canUseRight ? (yRight ?? yScale) : yScale;
			if ('bandwidth' in scale) {
				const band = scale as d3.ScaleBand<string>;
				const domain = band.domain();
				const idx = Math.round(value);
				const key = domain[idx];
				if (key != null) {
					const pos = band(key);
					yPos = pos != null ? pos + band.bandwidth() / 2 : null;
				}
			} else {
				yPos = (scale as AxisScale)(value);
			}
			if (yPos == null) continue;
			svg
				.append('line')
				.attr('class', 'reference-line')
				.attr('x1', 0)
				.attr('x2', w)
				.attr('y1', yPos)
				.attr('y2', yPos)
				.attr('stroke', color)
				.attr('stroke-width', 1)
				.attr('stroke-dasharray', '4,4');
			if (label) {
				svg
					.append('text')
					.attr('class', 'reference-label')
					.attr('x', w - 4)
					.attr('y', yPos - 6)
					.attr('text-anchor', 'end')
					.attr('fill', color)
					.style('font-size', '10px')
					.style('font-family', 'var(--font-mono)')
					.text(label);
			}
		}
	}

	function redrawReferenceLines(
		svg: Svg,
		lines: Array<Record<string, unknown>>,
		xScale: d3.ScaleBand<string> | d3.ScalePoint<string> | d3.ScaleLinear<number, number>,
		yScale:
			| AxisScale
			| d3.ScaleBand<string>
			| d3.ScalePoint<string>
			| d3.ScaleLinear<number, number>,
		w: number,
		h: number,
		yRight?: AxisScale | null
	) {
		svg.selectAll('.reference-line').remove();
		svg.selectAll('.reference-label').remove();
		drawReferenceLines(svg, lines, xScale, yScale, w, h, yRight);
	}

	function styleChart(svg: Svg) {
		svg.selectAll('.domain').attr('stroke', 'var(--border-primary)');
		svg.selectAll('.tick line:not(.grid line)').attr('stroke', 'var(--border-primary)');
		svg
			.selectAll('.tick text')
			.attr('fill', 'var(--fg-tertiary)')
			.style('font-size', '10px')
			.style('font-family', 'var(--font-mono)');
	}

	function makeXAxis(
		svg: Svg,
		x: d3.ScaleBand<string> | d3.ScalePoint<string>,
		h: number,
		labels: string[]
	) {
		const maxLen = Math.max(...labels.map((l) => l.length));
		const shouldRotate = maxLen > 8 && labels.length > 4;
		const axis = svg
			.append('g')
			.attr('transform', `translate(0,${h})`)
			.call(
				d3
					.axisBottom(x)
					.tickSizeOuter(0)
					.tickFormat((d) => fmtAxisTime(d))
			);
		if (shouldRotate) {
			axis
				.selectAll('text')
				.attr('transform', 'rotate(-35)')
				.attr('text-anchor', 'end')
				.attr('dx', '-0.5em')
				.attr('dy', '0.3em');
		}
	}

	function makeYAxis(svg: Svg, y: AxisScale) {
		svg.append('g').call(
			d3
				.axisLeft(y)
				.ticks(5)
				.tickFormat((d) => fmtAxis(d as number))
		);
	}

	const EXPORT_STYLE_PROPS = [
		'fill',
		'stroke',
		'stroke-width',
		'stroke-dasharray',
		'stroke-linecap',
		'stroke-linejoin',
		'stroke-opacity',
		'opacity',
		'font-size',
		'font-family',
		'font-weight',
		'text-anchor',
		'dominant-baseline',
		'letter-spacing',
		'paint-order'
	];

	function inlineSvgStyles(svg: SVGSVGElement, clone: SVGSVGElement) {
		const originals = [svg, ...Array.from(svg.querySelectorAll('*'))];
		const clones = [clone, ...Array.from(clone.querySelectorAll('*'))];
		for (let i = 0; i < originals.length; i += 1) {
			const original = originals[i];
			const cloned = clones[i];
			if (!original || !cloned) continue;
			const computed = getComputedStyle(original);
			const style = EXPORT_STYLE_PROPS.map(
				(prop) => `${prop}:${computed.getPropertyValue(prop)}`
			).join(';');
			cloned.setAttribute('style', style);
		}
	}

	function exportChartPng() {
		if (!chartEl) return;
		const svg = chartEl.querySelector('svg');
		if (!svg) return;
		const chartNode = chartEl;
		const rect = svg.getBoundingClientRect();
		const width = Math.max(1, rect.width);
		const height = Math.max(1, rect.height);
		const clone = svg.cloneNode(true) as SVGSVGElement;
		clone.setAttribute('width', `${width}`);
		clone.setAttribute('height', `${height}`);
		if (!clone.getAttribute('viewBox')) {
			clone.setAttribute('viewBox', `0 0 ${width} ${height}`);
		}
		inlineSvgStyles(svg, clone);
		const serializer = new XMLSerializer();
		const svgString = serializer.serializeToString(clone);
		const blob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' });
		const url = URL.createObjectURL(blob);
		const img = new Image();
		const scale = window.devicePixelRatio || 1;
		img.onload = () => {
			const canvas = document.createElement('canvas');
			canvas.width = Math.round(width * scale);
			canvas.height = Math.round(height * scale);
			const ctx = canvas.getContext('2d');
			if (!ctx) {
				URL.revokeObjectURL(url);
				return;
			}
			const bg = getComputedStyle(chartNode).backgroundColor;
			ctx.scale(scale, scale);
			ctx.fillStyle = bg;
			ctx.fillRect(0, 0, width, height);
			ctx.drawImage(img, 0, 0, width, height);
			canvas.toBlob((png) => {
				if (!png) {
					URL.revokeObjectURL(url);
					return;
				}
				downloadBlob(png, 'chart.png');
				URL.revokeObjectURL(url);
			}, 'image/png');
		};
		img.onerror = () => {
			URL.revokeObjectURL(url);
		};
		img.src = url;
	}

	type CsvRow = { dataset: string; x: string; y: string };

	function csvEscape(value: string): string {
		const escaped = value.replaceAll('"', '""');
		const needsQuotes = escaped.includes(',') || escaped.includes('\n') || escaped.includes('"');
		if (!needsQuotes) return escaped;
		return `"${escaped}"`;
	}

	function getRowDataset(row: Row, fallback: string): string {
		const groupCol = str(config.group_column);
		if (groupCol && row[groupCol] != null) return str(row[groupCol]);
		if (row['group'] != null) return str(row['group']);
		return fallback;
	}

	function baseCsvRows(): CsvRow[] {
		const title = str(config.title).trim();
		const fallback = title || 'Primary';
		if (chartType === 'histogram') {
			return data.map((row) => ({
				dataset: fallback,
				x: str(row.bin_start),
				y: str(row.count)
			}));
		}
		if (chartType === 'heatgrid') {
			return data.map((row) => ({
				dataset: str(row.y) || fallback,
				x: str(row.x),
				y: str(row.value)
			}));
		}
		if (chartType === 'boxplot') {
			const rows: CsvRow[] = [];
			for (const row of data) {
				const dataset = str(row.group) || fallback;
				const stats: Array<[string, unknown]> = [
					['min', row.min],
					['q1', row.q1],
					['median', row.median],
					['q3', row.q3],
					['max', row.max]
				];
				for (const stat of stats) {
					rows.push({
						dataset,
						x: stat[0],
						y: str(stat[1])
					});
				}
			}
			return rows;
		}
		if (chartType === 'pie') {
			return data.map((row) => ({
				dataset: str(row.group) || fallback,
				x: str(row.label ?? row.x),
				y: str(row.y ?? row.value ?? row.count)
			}));
		}
		return data.map((row) => ({
			dataset: getRowDataset(row, fallback),
			x: str(row.x ?? row.label),
			y: str(row.y ?? row.value ?? row.count)
		}));
	}

	function overlayCsvRows(): CsvRow[] {
		const rows: CsvRow[] = [];
		for (const overlay of getOverlayConfigs()) {
			const label = overlaySeriesLabel(overlay);
			const points = overlayData(overlay);
			for (const point of points) {
				rows.push({
					dataset: label,
					x: str(point.x ?? point.label),
					y: str(point.y ?? point.value ?? point.count)
				});
			}
		}
		return rows;
	}

	function referenceLineCsvRows(): CsvRow[] {
		const rows: CsvRow[] = [];
		for (const line of getReferenceLines()) {
			const axis = referenceLineAxisValue(line);
			const position = referenceLineAxisPosition(line);
			const value = getOptionalNumber(line.value);
			if (value == null) continue;
			const baseLabel = str(line.label).trim();
			const suffix = position === 'right' && axis === 'y' ? ' right' : '';
			const dataset = baseLabel || `Reference ${axis.toUpperCase()}${suffix}`;
			if (axis === 'x') {
				rows.push({ dataset, x: String(value), y: '' });
				continue;
			}
			rows.push({ dataset, x: '', y: String(value) });
		}
		return rows;
	}

	function exportChartCsv() {
		const rows = [...baseCsvRows(), ...overlayCsvRows(), ...referenceLineCsvRows()];
		const header = 'dataset,x,y';
		const body = rows.map((row) => [row.dataset, row.x, row.y].map(csvEscape).join(',')).join('\n');
		const csv = [header, body].filter((line) => line.length > 0).join('\n');
		const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
		downloadBlob(blob, 'chart.csv');
	}

	/* ── Main render effect ── */

	// DOM: $derived can't render SVG imperatively.
	$effect(() => {
		if (!chartEl || data.length === 0) return;

		let rafId = 0;

		function draw() {
			if (!chartEl) return;
			d3.select(chartEl).selectAll('svg').remove();
			const rect = chartEl.getBoundingClientRect();
			const w = rect.width || 400;
			const h = rect.height || 300;
			switch (chartType) {
				case 'bar':
					renderBar(chartEl, w, h);
					break;
				case 'horizontal_bar':
					renderHorizontalBar(chartEl, w, h);
					break;
				case 'area':
					renderArea(chartEl, w, h);
					break;
				case 'heatgrid':
					renderHeatgrid(chartEl, w, h);
					break;
				case 'line':
					renderLine(chartEl, w, h);
					break;
				case 'pie':
					renderPie(chartEl, w, h);
					break;
				case 'histogram':
					renderHistogram(chartEl, w, h);
					break;
				case 'scatter':
					renderScatter(chartEl, w, h);
					break;
				case 'boxplot':
					renderBoxplot(chartEl, w, h);
					break;
				default:
					renderBar(chartEl, w, h);
			}
		}

		// DOM: $derived can't drive ResizeObserver.
		const observer = new ResizeObserver(() => {
			cancelAnimationFrame(rafId);
			rafId = requestAnimationFrame(draw);
		});

		observer.observe(chartEl);
		draw();

		return () => {
			observer.disconnect();
			cancelAnimationFrame(rafId);
			if (chartEl) d3.select(chartEl).selectAll('svg').remove();
		};
	});

	/* ═══════════════════════════════════════════════════
	   CHART RENDERERS
	   ═══════════════════════════════════════════════════ */

	function renderBar(el: HTMLDivElement, width: number, height: number) {
		const overlays = getOverlayConfigs();
		const overlayRight = overlays.some((overlay) => overlayAxisPosition(overlay) === 'right');
		const margin = { top: 28, right: overlayRight ? 64 : 24, bottom: 56, left: 64 };
		const w = width - margin.left - margin.right;
		const h = height - margin.top - margin.bottom;

		const root = d3
			.select(el)
			.append('svg')
			.attr('width', width)
			.attr('height', height)
			.attr('role', 'img')
			.attr('aria-label', getChartAriaLabel()) as RootSvg;
		addChartTitle(root, str(config.title), width);
		const svg = root
			.append('g')
			.attr('transform', `translate(${margin.left},${margin.top})`) as Svg;

		const groupCol = config.group_column as string | null;
		const hasGroup = groupCol && data.length > 0 && groupCol in data[0];

		const stackMode = getStackMode();

		const overlayPoints: Row[] = [];
		const overlayGroupNames: string[] = [];
		const overlayValues: number[] = [];
		for (const overlay of overlays) {
			const rows = overlayData(overlay);
			const label = overlaySeriesLabel(overlay);
			const withLabel = rows.map((row) => ({ ...row, overlay_label: label }));
			overlayPoints.push(...withLabel);
			overlayGroupNames.push(label);
			overlayValues.push(...withLabel.map((row) => num((row as Row).y)));
		}
		const overlayColor = d3
			.scaleOrdinal<string>()
			.domain(overlayGroupNames)
			.range(getSeriesColors());
		let refX:
			| d3.ScaleBand<string>
			| d3.ScalePoint<string>
			| d3.ScaleLinear<number, number>
			| undefined;
		let refY:
			| AxisScale
			| d3.ScaleBand<string>
			| d3.ScalePoint<string>
			| d3.ScaleLinear<number, number>
			| undefined;
		const rightValues = overlayPoints
			.filter((row) => {
				const label = str(row.overlay_label);
				const overlay = overlays.find((item) => overlaySeriesLabel(item) === label);
				return overlay ? overlayAxisPosition(overlay) === 'right' : false;
			})
			.map((row) => num((row as Row).y));
		const yRight = rightValues.length > 0 ? buildYScale(rightValues, 0, h) : null;

		if (hasGroup && stackMode !== 'grouped') {
			const labels = [...new Set(data.map((r) => str(r.x)))];
			const groups = getGroupOrder(data, groupCol);
			const color = d3.scaleOrdinal<string>().domain(groups).range(getSeriesColors());

			const x = d3.scaleBand().domain(labels).range([0, w]).padding(0.2);
			const normalized = stackMode === '100%';
			const stackData = buildStackRows(labels, groups, groupCol);
			const series = d3.stack<StackRow>().keys(groups)(stackData.rows);

			const maxValue = normalized ? 1 : (d3.max(stackData.totals) ?? 0);
			const y = buildYScale([maxValue], 0, h);

			refX = x;
			refY = y;
			addGrid(svg, y, w);
			makeXAxis(svg, x, h, labels);
			makeYAxis(svg, y);
			if (yRight) addRightYAxis(svg, yRight, w);
			addTitles(svg, getXTitle(), getYTitle(), w, h);
			addLegend(svg, groups, (l) => color(l), w, h, {
				onClick: (series: string, event: MouseEvent | KeyboardEvent) => {
					if (event.metaKey || event.ctrlKey) {
						isolateSeries(series, groups);
						updateLegend(svg);
						updateSeriesVisibility(svg);
						updateSelection(svg);
						return;
					}
					toggleSeries(series);
					updateLegend(svg);
					updateSeriesVisibility(svg);
					updateSelection(svg);
				}
			});

			const adjustedSeries = series.map((layer) => {
				const groupKey = layer.key;
				const entries = layer.map((d, i) => {
					const xVal = stackData.rows[i]?.x ?? labels[i] ?? '';
					const total = stackData.totals[i] ?? 0;
					const value = stackData.rows[i]?.[groupKey] ?? 0;
					if (!normalized || total === 0) {
						return { ...d, x: xVal, value, total };
					}
					const start = (d[0] as number) / total;
					const end = (d[1] as number) / total;
					return { 0: start, 1: end, x: xVal, value, total };
				});
				return { key: groupKey, values: entries };
			});

			for (const layer of adjustedSeries) {
				const group = layer.key;
				if (!isSeriesVisible(group)) continue;
				svg
					.selectAll(`.stack-${CSS.escape(group)}`)
					.data(layer.values)
					.join('rect')
					.attr('class', 'chart-bar')
					.attr('data-series', group)
					.attr('data-key', (d) => makeKey(group, str(d.x)))
					.attr('x', (d) => x(d.x) ?? 0)
					.attr('y', (d) => y(d[1] as number))
					.attr('width', x.bandwidth())
					.attr('height', (d) => y(d[0] as number) - y(d[1] as number))
					.attr('fill', color(group))
					.attr('rx', 1)
					.style('cursor', 'pointer')
					.on('mouseover', function (event: MouseEvent, d) {
						svg.selectAll('.chart-bar').attr('opacity', HOVER_DIM);
						d3.select(this).attr('opacity', 1);
						const pct = d.total ? `${((d.value / d.total) * 100).toFixed(1)}%` : '0%';
						const label = normalized ? `${fmtFull(d.value)} (${pct})` : fmtFull(d.value);
						showTip(d.x, [{ label: group, value: label }], event);
					})
					.on('click', function (event: MouseEvent, d) {
						if (!selectEnabled) return;
						toggleSelection(makeKey(group, str(d.x)), event.metaKey || event.ctrlKey);
						updateSelection(svg);
					})
					.on('mouseout', function () {
						updateSelection(svg);
						hideTip();
					});
			}

			for (const overlay of overlays) {
				const rows = overlayPoints.filter(
					(row) => str(row.overlay_label) === overlaySeriesLabel(overlay)
				);
				const type = overlayChartType(overlay);
				const label = overlaySeriesLabel(overlay);
				const axis = overlayAxisPosition(overlay);
				const yScale: AxisScale = axis === 'right' && yRight ? yRight : y;
				const color = overlayColor(label);
				if (type === 'scatter') {
					svg
						.selectAll(`.overlay-dot-${CSS.escape(label)}`)
						.data(rows)
						.join('circle')
						.attr('class', 'chart-dot overlay-dot')
						.attr('data-series', label)
						.attr('data-axis', axis)
						.attr('cx', (r) => (x(str(r.x)) ?? 0) + x.bandwidth() / 2)
						.attr('cy', (r) => yScale(num(r.y)))
						.attr('r', 3.5)
						.attr('fill', color)
						.attr('opacity', 0.85);
					continue;
				}
				if (type === 'bar') {
					svg
						.selectAll(`.overlay-bar-${CSS.escape(label)}`)
						.data(rows)
						.join('rect')
						.attr('class', 'chart-bar overlay-bar')
						.attr('data-series', label)
						.attr('data-axis', axis)
						.attr('x', (r) => x(str(r.x)) ?? 0)
						.attr('width', x.bandwidth())
						.attr('y', (r) => yScale(num(r.y)))
						.attr('height', (r) => h - yScale(num(r.y)))
						.attr('fill', color)
						.attr('opacity', 0.25);
					continue;
				}
				const sorted = rows.sort((a, b) => labels.indexOf(str(a.x)) - labels.indexOf(str(b.x)));
				const line = d3
					.line<Row>()
					.x((r) => (x(str(r.x)) ?? 0) + x.bandwidth() / 2)
					.y((r) => yScale(num(r.y)))
					.curve(d3.curveMonotoneX);
				svg
					.append('path')
					.datum(sorted)
					.attr('class', 'overlay-path')
					.attr('data-series', label)
					.attr('data-axis', axis)
					.attr('d', line)
					.attr('fill', 'none')
					.attr('stroke', color)
					.attr('stroke-width', 2);
				if (type === 'area') {
					const area = d3
						.area<Row>()
						.x((r) => (x(str(r.x)) ?? 0) + x.bandwidth() / 2)
						.y0(h)
						.y1((r) => yScale(num(r.y)))
						.curve(d3.curveMonotoneX);
					svg
						.append('path')
						.datum(sorted)
						.attr('class', 'overlay-area')
						.attr('data-series', label)
						.attr('data-axis', axis)
						.attr('d', area)
						.attr('fill', color)
						.attr('opacity', getAreaOpacity());
				}
			}
		} else if (hasGroup) {
			const labels = [...new Set(data.map((r) => str(r.x)))];
			const groups = getGroupOrder(data, groupCol);
			const color = d3.scaleOrdinal<string>().domain(groups).range(getSeriesColors());

			const x0 = d3.scaleBand().domain(labels).range([0, w]).padding(0.2);
			const x1 = d3.scaleBand().domain(groups).range([0, x0.bandwidth()]).padding(0.05);
			const y = buildYScale(
				data.map((r) => num(r.y)),
				0,
				h
			);

			refX = x0;
			refY = y;
			addGrid(svg, y, w);
			makeXAxis(svg, x0, h, labels);
			makeYAxis(svg, y);
			if (yRight) addRightYAxis(svg, yRight, w);
			addTitles(svg, getXTitle(), getYTitle(), w, h);
			addLegend(svg, groups, (l) => color(l), w, h, {
				onClick: (series: string, event: MouseEvent | KeyboardEvent) => {
					if (event.metaKey || event.ctrlKey) {
						isolateSeries(series, groups);
						updateLegend(svg);
						updateSeriesVisibility(svg);
						updateSelection(svg);
						return;
					}
					toggleSeries(series);
					updateLegend(svg);
					updateSeriesVisibility(svg);
					updateSelection(svg);
				}
			});

			for (const group of groups) {
				if (!isSeriesVisible(group)) continue;
				const rows = data.filter((r) => str(r[groupCol]) === group);
				svg
					.selectAll(`.bar-${CSS.escape(group)}`)
					.data(rows)
					.join('rect')
					.attr('class', 'chart-bar')
					.attr('data-series', group)
					.attr('data-key', (r) => makeKey(group, str(r.x)))
					.attr('x', (r) => (x0(str(r.x)) ?? 0) + (x1(group) ?? 0))
					.attr('y', (r) => y(num(r.y)))
					.attr('width', x1.bandwidth())
					.attr('height', (r) => h - y(num(r.y)))
					.attr('fill', color(group))
					.attr('rx', 2)
					.style('cursor', 'pointer')
					.on('mouseover', function (event: MouseEvent, r: Row) {
						svg.selectAll('.chart-bar').attr('opacity', HOVER_DIM);
						d3.select(this).attr('opacity', 1);
						showTip(str(r.x), [{ label: group, value: fmtFull(num(r.y)) }], event);
					})
					.on('click', function (event: MouseEvent, r: Row) {
						if (!selectEnabled) return;
						const key = makeKey(group, str(r.x));
						toggleSelection(key, event.metaKey || event.ctrlKey);
						updateSelection(svg);
					})
					.on('mouseout', function () {
						updateSelection(svg);
						hideTip();
					});
			}

			/* Value labels for grouped (only when few groups) */
			if (groups.length <= 3) {
				for (const group of groups) {
					const rows = data.filter((r) => str(r[groupCol]) === group);
					svg
						.selectAll(`.vlabel-${CSS.escape(group)}`)
						.data(rows)
						.join('text')
						.attr('class', 'value-label')
						.attr('x', (r) => (x0(str(r.x)) ?? 0) + (x1(group) ?? 0) + x1.bandwidth() / 2)
						.attr('y', (r) => y(num(r.y)) - 5)
						.attr('text-anchor', 'middle')
						.attr('fill', 'var(--fg-tertiary)')
						.style('font-size', '9px')
						.style('font-family', 'var(--font-mono)')
						.style('pointer-events', 'none')
						.text((r) => fmtFull(num(r.y)));
				}
			}

			for (const overlay of overlays) {
				const rows = overlayPoints.filter(
					(row) => str(row.overlay_label) === overlaySeriesLabel(overlay)
				);
				const type = overlayChartType(overlay);
				const label = overlaySeriesLabel(overlay);
				const axis = overlayAxisPosition(overlay);
				const yScale: AxisScale = axis === 'right' && yRight ? yRight : y;
				const color = overlayColor(label);
				if (type === 'scatter') {
					svg
						.selectAll(`.overlay-dot-${CSS.escape(label)}`)
						.data(rows)
						.join('circle')
						.attr('class', 'chart-dot overlay-dot')
						.attr('data-series', label)
						.attr('data-axis', axis)
						.attr('cx', (r) => (x0(str(r.x)) ?? 0) + x0.bandwidth() / 2)
						.attr('cy', (r) => yScale(num(r.y)))
						.attr('r', 3.5)
						.attr('fill', color)
						.attr('opacity', 0.85);
					continue;
				}
				const sorted = rows.sort((a, b) => labels.indexOf(str(a.x)) - labels.indexOf(str(b.x)));
				if (type === 'bar') {
					svg
						.selectAll(`.overlay-bar-${CSS.escape(label)}`)
						.data(sorted)
						.join('rect')
						.attr('class', 'chart-bar overlay-bar')
						.attr('data-series', label)
						.attr('data-axis', axis)
						.attr('x', (r) => x0(str(r.x)) ?? 0)
						.attr('width', x0.bandwidth())
						.attr('y', (r) => yScale(num(r.y)))
						.attr('height', (r) => h - yScale(num(r.y)))
						.attr('fill', color)
						.attr('opacity', 0.25);
					continue;
				}
				const line = d3
					.line<Row>()
					.x((r) => (x0(str(r.x)) ?? 0) + x0.bandwidth() / 2)
					.y((r) => yScale(num(r.y)))
					.curve(d3.curveMonotoneX);
				svg
					.append('path')
					.datum(sorted)
					.attr('class', 'overlay-path')
					.attr('data-series', label)
					.attr('data-axis', axis)
					.attr('d', line)
					.attr('fill', 'none')
					.attr('stroke', color)
					.attr('stroke-width', 2);
				if (type === 'area') {
					const area = d3
						.area<Row>()
						.x((r) => (x0(str(r.x)) ?? 0) + x0.bandwidth() / 2)
						.y0(h)
						.y1((r) => yScale(num(r.y)))
						.curve(d3.curveMonotoneX);
					svg
						.append('path')
						.datum(sorted)
						.attr('class', 'overlay-area')
						.attr('data-series', label)
						.attr('data-axis', axis)
						.attr('d', area)
						.attr('fill', color)
						.attr('opacity', getAreaOpacity());
				}
			}
		} else {
			const labels = data.map((r) => str(r.x));
			const x = d3.scaleBand().domain(labels).range([0, w]).padding(0.25);
			const y = buildYScale(
				data.map((r) => num(r.y)),
				0,
				h
			);

			refX = x;
			refY = y;
			addGrid(svg, y, w);
			makeXAxis(svg, x, h, labels);
			makeYAxis(svg, y);
			if (yRight) addRightYAxis(svg, yRight, w);
			addTitles(svg, getXTitle(), getYTitle(), w, h);

			svg
				.selectAll('.bar')
				.data(data)
				.join('rect')
				.attr('class', 'chart-bar')
				.attr('data-series', '')
				.attr('data-key', (r) => makeKey('', str(r.x)))
				.attr('x', (r) => x(str(r.x)) ?? 0)
				.attr('y', (r) => y(num(r.y)))
				.attr('width', x.bandwidth())
				.attr('height', (r) => h - y(num(r.y)))
				.attr('fill', getPrimaryColor())
				.attr('rx', 2)
				.style('cursor', 'pointer')
				.on('mouseover', function (event: MouseEvent, r: Row) {
					svg.selectAll('.chart-bar').attr('opacity', HOVER_DIM);
					d3.select(this).attr('opacity', 1);
					showTip(str(r.x), [{ label: getYTitle(), value: fmtFull(num(r.y)) }], event);
				})
				.on('click', function (event: MouseEvent, r: Row) {
					if (!selectEnabled) return;
					const key = makeKey('', str(r.x));
					toggleSelection(key, event.metaKey || event.ctrlKey);
					updateSelection(svg);
				})
				.on('mouseout', function () {
					updateSelection(svg);
					hideTip();
				});

			/* Value labels */
			svg
				.selectAll('.value-label')
				.data(data)
				.join('text')
				.attr('class', 'value-label')
				.attr('x', (r) => (x(str(r.x)) ?? 0) + x.bandwidth() / 2)
				.attr('y', (r) => y(num(r.y)) - 6)
				.attr('text-anchor', 'middle')
				.attr('fill', 'var(--fg-secondary)')
				.style('font-size', '10px')
				.style('font-family', 'var(--font-mono)')
				.style('pointer-events', 'none')
				.text((r) => fmtFull(num(r.y)));

			for (const overlay of overlays) {
				const rows = overlayPoints.filter(
					(row) => str(row.overlay_label) === overlaySeriesLabel(overlay)
				);
				const type = overlayChartType(overlay);
				const label = overlaySeriesLabel(overlay);
				const axis = overlayAxisPosition(overlay);
				const yScale: AxisScale = axis === 'right' && yRight ? yRight : y;
				const color = overlayColor(label);
				if (type === 'scatter') {
					svg
						.selectAll(`.overlay-dot-${CSS.escape(label)}`)
						.data(rows)
						.join('circle')
						.attr('class', 'chart-dot overlay-dot')
						.attr('data-series', label)
						.attr('data-axis', axis)
						.attr('cx', (r) => (x(str(r.x)) ?? 0) + x.bandwidth() / 2)
						.attr('cy', (r) => yScale(num(r.y)))
						.attr('r', 3.5)
						.attr('fill', color)
						.attr('opacity', 0.85);
					continue;
				}
				if (type === 'bar') {
					svg
						.selectAll(`.overlay-bar-${CSS.escape(label)}`)
						.data(rows)
						.join('rect')
						.attr('class', 'chart-bar overlay-bar')
						.attr('data-series', label)
						.attr('data-axis', axis)
						.attr('x', (r) => x(str(r.x)) ?? 0)
						.attr('width', x.bandwidth())
						.attr('y', (r) => yScale(num(r.y)))
						.attr('height', (r) => h - yScale(num(r.y)))
						.attr('fill', color)
						.attr('opacity', 0.25);
					continue;
				}
				const sorted = rows.sort((a, b) => labels.indexOf(str(a.x)) - labels.indexOf(str(b.x)));
				const line = d3
					.line<Row>()
					.x((r) => (x(str(r.x)) ?? 0) + x.bandwidth() / 2)
					.y((r) => yScale(num(r.y)))
					.curve(d3.curveMonotoneX);
				svg
					.append('path')
					.datum(sorted)
					.attr('class', 'overlay-path')
					.attr('data-series', label)
					.attr('data-axis', axis)
					.attr('d', line)
					.attr('fill', 'none')
					.attr('stroke', color)
					.attr('stroke-width', 2);
				if (type === 'area') {
					const area = d3
						.area<Row>()
						.x((r) => (x(str(r.x)) ?? 0) + x.bandwidth() / 2)
						.y0(h)
						.y1((r) => yScale(num(r.y)))
						.curve(d3.curveMonotoneX);
					svg
						.append('path')
						.datum(sorted)
						.attr('class', 'overlay-area')
						.attr('data-series', label)
						.attr('data-axis', axis)
						.attr('d', area)
						.attr('fill', color)
						.attr('opacity', getAreaOpacity());
				}
			}
		}

		updateSeriesVisibility(svg);
		updateSelection(svg);
		if (refX && refY) {
			drawReferenceLines(svg, getReferenceLines(), refX, refY, w, h, yRight);
		}
		styleChart(svg);
	}

	function renderHorizontalBar(el: HTMLDivElement, width: number, height: number) {
		const overlays = getOverlayConfigs();
		const overlayRight = overlays.some((overlay) => overlayAxisPosition(overlay) === 'right');
		const margin = { top: 28, right: overlayRight ? 64 : 24, bottom: 48, left: 84 };
		const w = width - margin.left - margin.right;
		const h = height - margin.top - margin.bottom;

		const root = d3
			.select(el)
			.append('svg')
			.attr('width', width)
			.attr('height', height)
			.attr('role', 'img')
			.attr('aria-label', getChartAriaLabel()) as RootSvg;
		addChartTitle(root, str(config.title), width);
		const svg = root
			.append('g')
			.attr('transform', `translate(${margin.left},${margin.top})`) as Svg;

		const groupCol = config.group_column as string | null;
		const hasGroup = groupCol && data.length > 0 && groupCol in data[0];
		const stackMode = getStackMode();

		const overlayPoints: Row[] = [];
		const overlayGroupNames: string[] = [];
		const overlayValues: number[] = [];
		for (const overlay of overlays) {
			const rows = overlayData(overlay);
			const label = overlaySeriesLabel(overlay);
			const withLabel = rows.map((row) => ({ ...row, overlay_label: label }));
			overlayPoints.push(...withLabel);
			overlayGroupNames.push(label);
			overlayValues.push(...withLabel.map((row) => num((row as Row).y)));
		}
		const overlayColor = d3
			.scaleOrdinal<string>()
			.domain(overlayGroupNames)
			.range(getSeriesColors());
		const rightValues = overlayPoints
			.filter((row) => {
				const label = str(row.overlay_label);
				const overlay = overlays.find((item) => overlaySeriesLabel(item) === label);
				return overlay ? overlayAxisPosition(overlay) === 'right' : false;
			})
			.map((row) => num((row as Row).y));
		const yRight = rightValues.length > 0 ? buildValueScale(rightValues, 0, [0, w]) : null;

		const labels = [...new Set(data.map((r) => str(r.x)))];
		const yBand = d3.scaleBand().domain(labels).range([0, h]).padding(0.2);
		const yAxis = d3.axisLeft(yBand).tickSizeOuter(0);
		const yAxisGroup = svg.append('g').call(yAxis);
		const maxLen = Math.max(...labels.map((l) => l.length));
		if (maxLen > 12) {
			yAxisGroup.selectAll('text').style('font-size', '9px');
		}

		if (hasGroup && stackMode !== 'grouped') {
			const groups = getGroupOrder(data, groupCol);
			const color = d3.scaleOrdinal<string>().domain(groups).range(getSeriesColors());
			const normalized = stackMode === '100%';
			const stackData = buildStackRows(labels, groups, groupCol);
			const maxValue = normalized ? 1 : (d3.max(stackData.totals) ?? 0);
			const x = buildValueScale([maxValue], 0, [0, w]);

			const stack = d3.stack<StackRow>().keys(groups)(stackData.rows);

			addVerticalGrid(svg, x, h);
			svg
				.append('g')
				.attr('transform', `translate(0,${h})`)
				.call(
					d3
						.axisBottom(x as d3.ScaleLinear<number, number>)
						.ticks(5)
						.tickFormat((d) => fmtAxis(d as number))
				);
			if (yRight) addRightYAxis(svg, yRight as AxisScale, w);
			addTitles(svg, getYTitle(), getXTitle(), w, h);
			addLegend(svg, groups, (l) => color(l), w, h, {
				onClick: (series: string, event: MouseEvent | KeyboardEvent) => {
					if (event.metaKey || event.ctrlKey) {
						isolateSeries(series, groups);
						updateLegend(svg);
						updateSeriesVisibility(svg);
						updateSelection(svg);
						return;
					}
					toggleSeries(series);
					updateLegend(svg);
					updateSeriesVisibility(svg);
					updateSelection(svg);
				}
			});

			const totalByRow = stackData.rows.map((row) =>
				groups.reduce((total, group) => total + (row[group] ?? 0), 0)
			);

			for (const layer of stack) {
				const group = layer.key;
				svg
					.selectAll(`.hstack-${CSS.escape(group)}`)
					.data(layer.map((d, i) => ({ segment: d, index: i })))
					.join('rect')
					.attr('class', 'chart-bar')
					.attr('data-series', group)
					.attr('data-key', (d) => makeKey(group, str(stackData.rows[d.index]?.x ?? '')))
					.attr('y', (d) => yBand(stackData.rows[d.index]?.x ?? '') ?? 0)
					.attr('x', (d) => {
						const segment = d.segment;
						if (!normalized) return x(segment[0] as number);
						const total = totalByRow[d.index] ?? 0;
						if (total === 0) return x(0);
						return x((segment[0] as number) / total);
					})
					.attr('height', yBand.bandwidth())
					.attr('width', (d) => {
						const segment = d.segment;
						if (!normalized) return x(segment[1] as number) - x(segment[0] as number);
						const total = totalByRow[d.index] ?? 0;
						if (total === 0) return 0;
						return x((segment[1] as number) / total) - x((segment[0] as number) / total);
					})
					.attr('fill', color(group))
					.attr('rx', 1)
					.style('cursor', 'pointer')
					.on('mouseover', function (event: MouseEvent, d) {
						svg.selectAll('.chart-bar').attr('opacity', HOVER_DIM);
						d3.select(this).attr('opacity', 1);
						const total = totalByRow[d.index] ?? 0;
						const value = stackData.rows[d.index]?.[group] ?? 0;
						const pct = total ? `${((value / total) * 100).toFixed(1)}%` : '0%';
						const label = normalized ? `${fmtFull(value)} (${pct})` : fmtFull(value);
						showTip(stackData.rows[d.index]?.x ?? '', [{ label: group, value: label }], event);
					})
					.on('click', function (event: MouseEvent, d) {
						if (!selectEnabled) return;
						const key = makeKey(group, str(stackData.rows[d.index]?.x ?? ''));
						toggleSelection(key, event.metaKey || event.ctrlKey);
						updateSelection(svg);
					})
					.on('mouseout', function () {
						updateSelection(svg);
						hideTip();
					});
			}
			for (const overlay of overlays) {
				const rows = overlayPoints.filter(
					(row) => str(row.overlay_label) === overlaySeriesLabel(overlay)
				);
				const type = overlayChartType(overlay);
				const label = overlaySeriesLabel(overlay);
				const axis = overlayAxisPosition(overlay);
				const xScale = axis === 'right' && yRight ? yRight : x;
				const color = overlayColor(label);
				if (type === 'scatter') {
					svg
						.selectAll(`.overlay-dot-${CSS.escape(label)}`)
						.data(rows)
						.join('circle')
						.attr('class', 'chart-dot overlay-dot')
						.attr('data-series', label)
						.attr('data-axis', axis)
						.attr('cx', (r) => xScale(num(r.y)))
						.attr('cy', (r) => (yBand(str(r.x)) ?? 0) + yBand.bandwidth() / 2)
						.attr('r', 3.5)
						.attr('fill', color)
						.attr('opacity', 0.85);
					continue;
				}
				if (type === 'bar') {
					svg
						.selectAll(`.overlay-bar-${CSS.escape(label)}`)
						.data(rows)
						.join('rect')
						.attr('class', 'chart-bar overlay-bar')
						.attr('data-series', label)
						.attr('data-axis', axis)
						.attr('y', (r) => yBand(str(r.x)) ?? 0)
						.attr('x', 0)
						.attr('height', yBand.bandwidth())
						.attr('width', (r) => xScale(num(r.y)))
						.attr('fill', color)
						.attr('opacity', 0.25);
					continue;
				}
				const sorted = rows.sort((a, b) => labels.indexOf(str(a.x)) - labels.indexOf(str(b.x)));
				const line = d3
					.line<Row>()
					.x((r) => xScale(num(r.y)))
					.y((r) => (yBand(str(r.x)) ?? 0) + yBand.bandwidth() / 2)
					.curve(d3.curveMonotoneY);
				svg
					.append('path')
					.datum(sorted)
					.attr('class', 'overlay-path')
					.attr('data-series', label)
					.attr('data-axis', axis)
					.attr('d', line)
					.attr('fill', 'none')
					.attr('stroke', color)
					.attr('stroke-width', 2);
				if (type === 'area') {
					const area = d3
						.area<Row>()
						.x((row) => xScale(num(row.y)))
						.y0((row) => (yBand(str(row.x)) ?? 0) + yBand.bandwidth())
						.y1((row) => yBand(str(row.x)) ?? 0)
						.curve(d3.curveMonotoneY);
					svg
						.append('path')
						.datum(sorted)
						.attr('class', 'overlay-area')
						.attr('data-series', label)
						.attr('data-axis', axis)
						.attr('d', area)
						.attr('fill', color)
						.attr('opacity', getAreaOpacity());
				}
			}

			drawReferenceLines(svg, getReferenceLines(), x, yBand, w, h, yRight);
			styleChart(svg);
			return;
		}

		const values = data.map((r) => num(r.y));
		const x = buildValueScale(values, 0, [0, w]);

		addVerticalGrid(svg, x, h);
		svg
			.append('g')
			.attr('transform', `translate(0,${h})`)
			.call(
				d3
					.axisBottom(x as d3.ScaleLinear<number, number>)
					.ticks(5)
					.tickFormat((d) => fmtAxis(d as number))
			);
		if (yRight) addRightYAxis(svg, yRight as AxisScale, w);
		addTitles(svg, getYTitle(), getXTitle(), w, h);

		if (hasGroup) {
			const groups = getGroupOrder(data, groupCol);
			const color = d3.scaleOrdinal<string>().domain(groups).range(getSeriesColors());
			addLegend(svg, groups, (l) => color(l), w, h, {
				onClick: (series: string, event: MouseEvent | KeyboardEvent) => {
					if (event.metaKey || event.ctrlKey) {
						isolateSeries(series, groups);
						updateLegend(svg);
						updateSeriesVisibility(svg);
						updateSelection(svg);
						return;
					}
					toggleSeries(series);
					updateLegend(svg);
					updateSeriesVisibility(svg);
					updateSelection(svg);
				}
			});
			const sub = d3.scaleBand().domain(groups).range([0, yBand.bandwidth()]).padding(0.05);

			for (const group of groups) {
				if (!isSeriesVisible(group)) continue;
				const rows = data.filter((r) => str(r[groupCol]) === group);
				svg
					.selectAll(`.hbar-${CSS.escape(group)}`)
					.data(rows)
					.join('rect')
					.attr('class', 'chart-bar')
					.attr('data-series', group)
					.attr('data-key', (r) => makeKey(group, str(r.x)))
					.attr('y', (r) => (yBand(str(r.x)) ?? 0) + (sub(group) ?? 0))
					.attr('x', 0)
					.attr('height', sub.bandwidth())
					.attr('width', (r) => x(num(r.y)))
					.attr('fill', color(group))
					.attr('rx', 2)
					.style('cursor', 'pointer')
					.on('mouseover', function (event: MouseEvent, r: Row) {
						svg.selectAll('.chart-bar').attr('opacity', HOVER_DIM);
						d3.select(this).attr('opacity', 1);
						showTip(str(r.x), [{ label: group, value: fmtFull(num(r.y)) }], event);
					})
					.on('click', function (event: MouseEvent, r: Row) {
						if (!selectEnabled) return;
						const key = makeKey(group, str(r.x));
						toggleSelection(key, event.metaKey || event.ctrlKey);
						updateSelection(svg);
					})
					.on('mouseout', function () {
						updateSelection(svg);
						hideTip();
					});
			}
		} else {
			svg
				.selectAll('.bar')
				.data(data)
				.join('rect')
				.attr('class', 'chart-bar')
				.attr('data-series', '')
				.attr('data-key', (r) => makeKey('', str(r.x)))
				.attr('y', (r) => yBand(str(r.x)) ?? 0)
				.attr('x', 0)
				.attr('height', yBand.bandwidth())
				.attr('width', (r) => x(num(r.y)))
				.attr('fill', getPrimaryColor())
				.attr('rx', 2)
				.style('cursor', 'pointer')
				.on('mouseover', function (event: MouseEvent, r: Row) {
					svg.selectAll('.chart-bar').attr('opacity', HOVER_DIM);
					d3.select(this).attr('opacity', 1);
					showTip(str(r.x), [{ label: getYTitle(), value: fmtFull(num(r.y)) }], event);
				})
				.on('click', function (event: MouseEvent, r: Row) {
					if (!selectEnabled) return;
					const key = makeKey('', str(r.x));
					toggleSelection(key, event.metaKey || event.ctrlKey);
					updateSelection(svg);
				})
				.on('mouseout', function () {
					updateSelection(svg);
					hideTip();
				});
		}

		for (const overlay of overlays) {
			const rows = overlayPoints.filter(
				(row) => str(row.overlay_label) === overlaySeriesLabel(overlay)
			);
			const type = overlayChartType(overlay);
			const label = overlaySeriesLabel(overlay);
			const axis = overlayAxisPosition(overlay);
			const xScale = axis === 'right' && yRight ? yRight : x;
			const color = overlayColor(label);
			if (type === 'scatter') {
				svg
					.selectAll(`.overlay-dot-${CSS.escape(label)}`)
					.data(rows)
					.join('circle')
					.attr('class', 'chart-dot overlay-dot')
					.attr('data-series', label)
					.attr('data-axis', axis)
					.attr('cx', (r) => xScale(num(r.y)))
					.attr('cy', (r) => (yBand(str(r.x)) ?? 0) + yBand.bandwidth() / 2)
					.attr('r', 3.5)
					.attr('fill', color)
					.attr('opacity', 0.85);
				continue;
			}
			if (type === 'bar') {
				svg
					.selectAll(`.overlay-bar-${CSS.escape(label)}`)
					.data(rows)
					.join('rect')
					.attr('class', 'chart-bar overlay-bar')
					.attr('data-series', label)
					.attr('data-axis', axis)
					.attr('y', (r) => yBand(str(r.x)) ?? 0)
					.attr('x', 0)
					.attr('height', yBand.bandwidth())
					.attr('width', (r) => xScale(num(r.y)))
					.attr('fill', color)
					.attr('opacity', 0.25);
				continue;
			}
			const sorted = rows.sort((a, b) => labels.indexOf(str(a.x)) - labels.indexOf(str(b.x)));
			const line = d3
				.line<Row>()
				.x((r) => xScale(num(r.y)))
				.y((r) => (yBand(str(r.x)) ?? 0) + yBand.bandwidth() / 2)
				.curve(d3.curveMonotoneY);
			svg
				.append('path')
				.datum(sorted)
				.attr('class', 'overlay-path')
				.attr('data-series', label)
				.attr('data-axis', axis)
				.attr('d', line)
				.attr('fill', 'none')
				.attr('stroke', color)
				.attr('stroke-width', 2);
			if (type === 'area') {
				const area = d3
					.area<Row>()
					.x((row) => xScale(num(row.y)))
					.y0((row) => (yBand(str(row.x)) ?? 0) + yBand.bandwidth())
					.y1((row) => yBand(str(row.x)) ?? 0)
					.curve(d3.curveMonotoneY);
				svg
					.append('path')
					.datum(sorted)
					.attr('class', 'overlay-area')
					.attr('data-series', label)
					.attr('data-axis', axis)
					.attr('d', area)
					.attr('fill', color)
					.attr('opacity', getAreaOpacity());
			}
		}

		updateSeriesVisibility(svg);
		updateSelection(svg);
		drawReferenceLines(svg, getReferenceLines(), x, yBand, w, h, yRight);
		styleChart(svg);
	}

	function renderArea(el: HTMLDivElement, width: number, height: number) {
		const overlays = getOverlayConfigs();
		const overlayRight = overlays.some((overlay) => overlayAxisPosition(overlay) === 'right');
		const margin = { top: 28, right: overlayRight ? 64 : 24, bottom: 56, left: 64 };
		const w = width - margin.left - margin.right;
		const h = height - margin.top - margin.bottom;

		const root = d3
			.select(el)
			.append('svg')
			.attr('width', width)
			.attr('height', height)
			.attr('role', 'img')
			.attr('aria-label', getChartAriaLabel()) as RootSvg;
		addChartTitle(root, str(config.title), width);
		const svg = root
			.append('g')
			.attr('transform', `translate(${margin.left},${margin.top})`) as Svg;

		const groupCol = config.group_column as string | null;
		const hasGroup = groupCol && data.length > 0 && groupCol in data[0];
		const labels = [...new Set(data.map((r) => str(r.x)))];
		const x = d3.scalePoint().domain(labels).range([0, w]).padding(0.5);
		const stackMode = getStackMode();

		const overlayPoints: Row[] = [];
		const overlayGroupNames: string[] = [];
		const overlayValues: number[] = [];
		for (const overlay of overlays) {
			const rows = overlayData(overlay);
			const label = overlaySeriesLabel(overlay);
			const withLabel = rows.map((row) => ({ ...row, overlay_label: label }));
			overlayPoints.push(...withLabel);
			overlayGroupNames.push(label);
			overlayValues.push(...withLabel.map((row) => num((row as Row).y)));
		}
		const overlayColor = d3
			.scaleOrdinal<string>()
			.domain(overlayGroupNames)
			.range(getSeriesColors());
		const rightValues = overlayPoints
			.filter((row) => {
				const label = str(row.overlay_label);
				const overlay = overlays.find((item) => overlaySeriesLabel(item) === label);
				return overlay ? overlayAxisPosition(overlay) === 'right' : false;
			})
			.map((row) => num((row as Row).y));
		const yRight = rightValues.length > 0 ? buildYScale(rightValues, 0, h) : null;

		if (hasGroup && stackMode !== 'grouped') {
			const groups = getGroupOrder(data, groupCol);
			const color = d3.scaleOrdinal<string>().domain(groups).range(getSeriesColors());
			const normalized = stackMode === '100%';
			const stackData = buildStackRows(labels, groups, groupCol);
			const maxValue = normalized ? 1 : (d3.max(stackData.totals) ?? 0);
			const y = buildYScale([maxValue], 0, h);

			addGrid(svg, y, w);
			makeXAxis(svg, x, h, labels);
			makeYAxis(svg, y);
			if (yRight) addRightYAxis(svg, yRight, w);
			addTitles(svg, getXTitle(), getYTitle(), w, h);
			addLegend(svg, groups, (l) => color(l), w, h, {
				onClick: (series: string, event: MouseEvent | KeyboardEvent) => {
					if (event.metaKey || event.ctrlKey) {
						isolateSeries(series, groups);
						updateLegend(svg);
						updateSeriesVisibility(svg);
						updateSelection(svg);
						return;
					}
					toggleSeries(series);
					updateLegend(svg);
					updateSeriesVisibility(svg);
					updateSelection(svg);
				}
			});

			const stacked = d3.stack<StackRow>().keys(groups)(stackData.rows);

			const area = d3
				.area<d3.SeriesPoint<StackRow>>()
				.x((_, i) => x(stackData.rows[i]?.x ?? '') ?? 0)
				.y0((d, i) => {
					if (!normalized) return y(d[0] as number);
					const total = stackData.totals[i] ?? 0;
					if (total === 0) return y(0);
					return y((d[0] as number) / total);
				})
				.y1((d, i) => {
					if (!normalized) return y(d[1] as number);
					const total = stackData.totals[i] ?? 0;
					if (total === 0) return y(0);
					return y((d[1] as number) / total);
				})
				.curve(d3.curveMonotoneX);

			for (const layer of stacked) {
				svg
					.append('path')
					.datum(layer)
					.attr('class', 'area-layer')
					.attr('data-series', layer.key)
					.attr('d', area)
					.attr('fill', color(layer.key))
					.attr('opacity', getAreaOpacity());
			}

			for (const overlay of overlays) {
				const rows = overlayPoints.filter(
					(row) => str(row.overlay_label) === overlaySeriesLabel(overlay)
				);
				const type = overlayChartType(overlay);
				const label = overlaySeriesLabel(overlay);
				const axis = overlayAxisPosition(overlay);
				const yScale = axis === 'right' && yRight ? yRight : y;
				const color = overlayColor(label);
				if (type === 'scatter') {
					svg
						.selectAll(`.overlay-dot-${CSS.escape(label)}`)
						.data(rows)
						.join('circle')
						.attr('class', 'chart-dot overlay-dot')
						.attr('data-series', label)
						.attr('data-axis', axis)
						.attr('cx', (r) => x(str(r.x)) ?? 0)
						.attr('cy', (r) => yScale(num(r.y)))
						.attr('r', 3.5)
						.attr('fill', color)
						.attr('opacity', 0.85);
					continue;
				}
				if (type === 'bar') {
					svg
						.selectAll(`.overlay-bar-${CSS.escape(label)}`)
						.data(rows)
						.join('rect')
						.attr('class', 'chart-bar overlay-bar')
						.attr('data-series', label)
						.attr('data-axis', axis)
						.attr('x', (r) => (x(str(r.x)) ?? 0) - x.step() * 0.15)
						.attr('width', x.step() * 0.3)
						.attr('y', (r) => yScale(num(r.y)))
						.attr('height', (r) => h - yScale(num(r.y)))
						.attr('fill', color)
						.attr('opacity', 0.25);
					continue;
				}
				const sorted = rows.sort((a, b) => labels.indexOf(str(a.x)) - labels.indexOf(str(b.x)));
				const line = d3
					.line<Row>()
					.x((r) => x(str(r.x)) ?? 0)
					.y((r) => yScale(num(r.y)))
					.curve(d3.curveMonotoneX);
				svg
					.append('path')
					.datum(sorted)
					.attr('class', 'overlay-path')
					.attr('data-series', label)
					.attr('data-axis', axis)
					.attr('d', line)
					.attr('fill', 'none')
					.attr('stroke', color)
					.attr('stroke-width', 2);
				if (type === 'area') {
					const area = d3
						.area<Row>()
						.x((r) => x(str(r.x)) ?? 0)
						.y0(h)
						.y1((r) => yScale(num(r.y)))
						.curve(d3.curveMonotoneX);
					svg
						.append('path')
						.datum(sorted)
						.attr('class', 'overlay-area')
						.attr('data-series', label)
						.attr('data-axis', axis)
						.attr('d', area)
						.attr('fill', color)
						.attr('opacity', getAreaOpacity());
				}
			}

			drawReferenceLines(svg, getReferenceLines(), x, y, w, h, yRight);
			styleChart(svg);
			return;
		}

		const y = buildYScale(
			data.map((r) => num(r.y)),
			0,
			h
		);

		addGrid(svg, y, w);
		makeXAxis(svg, x, h, labels);
		makeYAxis(svg, y);
		if (yRight) addRightYAxis(svg, yRight, w);
		addTitles(svg, getXTitle(), getYTitle(), w, h);

		if (hasGroup) {
			const groups = getGroupOrder(data, groupCol);
			const color = d3.scaleOrdinal<string>().domain(groups).range(getSeriesColors());
			addLegend(svg, groups, (l) => color(l), w, h, {
				onClick: (series: string, event: MouseEvent | KeyboardEvent) => {
					if (event.metaKey || event.ctrlKey) {
						isolateSeries(series, groups);
						updateLegend(svg);
						updateSeriesVisibility(svg);
						updateSelection(svg);
						return;
					}
					toggleSeries(series);
					updateLegend(svg);
					updateSeriesVisibility(svg);
					updateSelection(svg);
				}
			});

			for (const group of groups) {
				const rows = data
					.filter((r) => str(r[groupCol]) === group)
					.sort((a, b) => labels.indexOf(str(a.x)) - labels.indexOf(str(b.x)));
				const area = d3
					.area<Row>()
					.x((r) => x(str(r.x)) ?? 0)
					.y0(h)
					.y1((r) => y(num(r.y)))
					.curve(d3.curveMonotoneX);
				svg
					.append('path')
					.datum(rows)
					.attr('class', 'area-layer')
					.attr('data-series', group)
					.attr('d', area)
					.attr('fill', color(group))
					.attr('opacity', getAreaOpacity());
			}
		} else {
			const sorted = [...data].sort((a, b) => labels.indexOf(str(a.x)) - labels.indexOf(str(b.x)));
			const area = d3
				.area<Row>()
				.x((r) => x(str(r.x)) ?? 0)
				.y0(h)
				.y1((r) => y(num(r.y)))
				.curve(d3.curveMonotoneX);
			svg
				.append('path')
				.datum(sorted)
				.attr('d', area)
				.attr('fill', getPrimaryColor())
				.attr('opacity', getAreaOpacity());
		}

		for (const overlay of overlays) {
			const rows = overlayPoints.filter(
				(row) => str(row.overlay_label) === overlaySeriesLabel(overlay)
			);
			const type = overlayChartType(overlay);
			const label = overlaySeriesLabel(overlay);
			const axis = overlayAxisPosition(overlay);
			const yScale = axis === 'right' && yRight ? yRight : y;
			const color = overlayColor(label);
			if (type === 'scatter') {
				svg
					.selectAll(`.overlay-dot-${CSS.escape(label)}`)
					.data(rows)
					.join('circle')
					.attr('class', 'chart-dot overlay-dot')
					.attr('data-series', label)
					.attr('data-axis', axis)
					.attr('cx', (r) => x(str(r.x)) ?? 0)
					.attr('cy', (r) => yScale(num(r.y)) ?? 0)
					.attr('r', 3.5)
					.attr('fill', color)
					.attr('opacity', 0.85);
				continue;
			}
			if (type === 'bar') {
				svg
					.selectAll(`.overlay-bar-${CSS.escape(label)}`)
					.data(rows)
					.join('rect')
					.attr('class', 'chart-bar overlay-bar')
					.attr('data-series', label)
					.attr('data-axis', axis)
					.attr('x', (r) => (x(str(r.x)) ?? 0) - x.step() * 0.15)
					.attr('width', x.step() * 0.3)
					.attr('y', (r) => yScale(num(r.y)) ?? 0)
					.attr('height', (r) => h - (yScale(num(r.y)) ?? 0))
					.attr('fill', color)
					.attr('opacity', 0.25);
				continue;
			}
			const sorted = rows.sort((a, b) => labels.indexOf(str(a.x)) - labels.indexOf(str(b.x)));
			const line = d3
				.line<Row>()
				.x((r) => x(str(r.x)) ?? 0)
				.y((r) => yScale(num(r.y)) ?? 0)
				.curve(d3.curveMonotoneX);
			svg
				.append('path')
				.datum(sorted)
				.attr('class', 'overlay-path')
				.attr('data-series', label)
				.attr('data-axis', axis)
				.attr('d', line)
				.attr('fill', 'none')
				.attr('stroke', color)
				.attr('stroke-width', 2);
			if (type === 'area') {
				const area = d3
					.area<Row>()
					.x((r) => x(str(r.x)) ?? 0)
					.y0(h)
					.y1((r) => yScale(num(r.y)) ?? 0)
					.curve(d3.curveMonotoneX);
				svg
					.append('path')
					.datum(sorted)
					.attr('class', 'overlay-area')
					.attr('data-series', label)
					.attr('data-axis', axis)
					.attr('d', area)
					.attr('fill', color)
					.attr('opacity', getAreaOpacity());
			}
		}

		updateSeriesVisibility(svg);
		updateSelection(svg);
		drawReferenceLines(svg, getReferenceLines(), x, y, w, h, yRight);
		styleChart(svg);
	}

	function renderHeatgrid(el: HTMLDivElement, width: number, height: number) {
		const margin = { top: 28, right: 64, bottom: 56, left: 80 };
		const w = width - margin.left - margin.right;
		const h = height - margin.top - margin.bottom;

		const root = d3
			.select(el)
			.append('svg')
			.attr('width', width)
			.attr('height', height)
			.attr('role', 'img')
			.attr('aria-label', getChartAriaLabel()) as RootSvg;
		addChartTitle(root, str(config.title), width);
		const svg = root
			.append('g')
			.attr('transform', `translate(${margin.left},${margin.top})`) as Svg;

		const xLabels = [...new Set(data.map((r) => str(r.x)))];
		const yLabels = [...new Set(data.map((r) => str(r.y)))];
		const x = d3.scaleBand().domain(xLabels).range([0, w]).padding(0.08);
		const y = d3.scaleBand().domain(yLabels).range([0, h]).padding(0.08);

		const values = data.map((r) => num(r.value));
		const minValue = d3.min(values) ?? 0;
		const maxValue = d3.max(values) ?? 0;
		const color = d3.scaleSequential(d3.interpolateBlues).domain([minValue, maxValue || 1]);

		svg.append('g').call(d3.axisLeft(y).tickSizeOuter(0));
		makeXAxis(svg, x, h, xLabels);
		addTitles(svg, getXTitle(), getYTitle(), w, h);

		svg
			.selectAll('.heat-cell')
			.data(data)
			.join('rect')
			.attr('class', 'heat-cell')
			.attr('x', (r) => x(str(r.x)) ?? 0)
			.attr('y', (r) => y(str(r.y)) ?? 0)
			.attr('width', x.bandwidth())
			.attr('height', y.bandwidth())
			.attr('rx', 2)
			.attr('fill', (r) => color(num(r.value)))
			.attr('stroke', 'var(--border-primary)')
			.attr('stroke-opacity', 0.3)
			.style('cursor', 'pointer')
			.on('mouseover', function (event: MouseEvent, r: Row) {
				d3.select(this).attr('stroke-opacity', 0.8);
				showTip(str(r.x), [{ label: str(r.y), value: fmtFull(num(r.value)) }], event);
			})
			.on('mouseout', function () {
				d3.select(this).attr('stroke-opacity', 0.3);
				hideTip();
			});

		const legendHeight = h;
		const legendWidth = 10;
		const legendScale = d3
			.scaleLinear()
			.domain([minValue, maxValue || minValue + 1])
			.range([legendHeight, 0]);
		const legendAxis = d3
			.axisRight(legendScale)
			.ticks(5)
			.tickFormat((d) => fmtAxis(d as number));

		const legend = svg.append('g').attr('transform', `translate(${w + 20},0)`);
		const legendId = `heat-${Math.random().toString(36).slice(2, 7)}`;
		const defs = root.append('defs');
		const gradient = defs
			.append('linearGradient')
			.attr('id', legendId)
			.attr('x1', '0%')
			.attr('y1', '100%')
			.attr('x2', '0%')
			.attr('y2', '0%');
		const steps = 6;
		for (let i = 0; i <= steps; i += 1) {
			const t = i / steps;
			const val = minValue + (maxValue - minValue) * t;
			gradient
				.append('stop')
				.attr('offset', `${t * 100}%`)
				.attr('stop-color', color(val));
		}
		legend
			.append('rect')
			.attr('width', legendWidth)
			.attr('height', legendHeight)
			.attr('fill', `url(#${legendId})`)
			.attr('rx', 2);
		legend.append('g').attr('transform', `translate(${legendWidth},0)`).call(legendAxis);

		styleChart(svg);
	}

	function renderLine(el: HTMLDivElement, width: number, height: number) {
		const overlays = getOverlayConfigs();
		const overlayRight = overlays.some((overlay) => overlayAxisPosition(overlay) === 'right');
		const margin = { top: 28, right: overlayRight ? 64 : 24, bottom: 56, left: 64 };
		const w = width - margin.left - margin.right;
		const h = height - margin.top - margin.bottom;

		const root = d3
			.select(el)
			.append('svg')
			.attr('width', width)
			.attr('height', height)
			.attr('role', 'img')
			.attr('aria-label', getChartAriaLabel()) as RootSvg;
		addChartTitle(root, str(config.title), width);
		const svg = root
			.append('g')
			.attr('transform', `translate(${margin.left},${margin.top})`) as Svg;

		const groupCol = config.group_column as string | null;
		const hasGroup = groupCol && data.length > 0 && groupCol in data[0];
		const labels = [...new Set(data.map((r) => str(r.x)))];
		const indexDomain = labels.map((_, i) => i);

		const overlayPoints: Row[] = [];
		const overlayGroupNames: string[] = [];
		const overlayValues: number[] = [];
		for (const overlay of overlays) {
			const rows = overlayData(overlay);
			const label = overlaySeriesLabel(overlay);
			const withLabel = rows.map((row) => ({ ...row, overlay_label: label }));
			overlayPoints.push(...withLabel);
			overlayGroupNames.push(label);
			overlayValues.push(...withLabel.map((row) => num((row as Row).y)));
		}
		const overlayColor = d3
			.scaleOrdinal<string>()
			.domain(overlayGroupNames)
			.range(getSeriesColors());
		const rightValues = overlayPoints
			.filter((row) => {
				const label = str(row.overlay_label);
				const overlay = overlays.find((item) => overlaySeriesLabel(item) === label);
				return overlay ? overlayAxisPosition(overlay) === 'right' : false;
			})
			.map((row) => num((row as Row).y));
		const yRightBase = rightValues.length > 0 ? buildYScale(rightValues, 0, h) : null;

		const xBase = d3
			.scaleLinear()
			.domain(d3.extent(indexDomain) as [number, number])
			.range([0, w]);
		const yBase = buildYScale(
			data.map((r) => num(r.y)),
			0,
			h
		);
		const zoomed = zoomTransform ? applyZoom(zoomTransform, xBase, yBase) : null;
		const x = zoomed ? (zoomed.zx as d3.ScaleLinear<number, number>) : xBase;
		const y = zoomed ? zoomed.zy : yBase;
		const yRight = yRightBase
			? zoomTransform
				? zoomTransform.rescaleY(yRightBase)
				: yRightBase
			: null;

		const grid = addGrid(svg, y, w);
		const axisX = svg
			.append('g')
			.attr('transform', `translate(0,${h})`)
			.call(
				d3
					.axisBottom(x)
					.tickSizeOuter(0)
					.tickFormat((d) => fmtAxisTime(labels[Math.round(d as number)] ?? d))
			);
		const axisY = svg.append('g').call(
			d3
				.axisLeft(y)
				.ticks(5)
				.tickFormat((d) => fmtAxis(d as number))
		);
		if (yRight) addRightYAxis(svg, yRight, w);
		addTitles(svg, getXTitle(), getYTitle(), w, h);

		if (hasGroup) {
			const groups = getGroupOrder(data, groupCol);
			const color = d3.scaleOrdinal<string>().domain(groups).range(getSeriesColors());
			addLegend(svg, groups, (l) => color(l), w, h, {
				onClick: (series: string, event: MouseEvent | KeyboardEvent) => {
					if (event.metaKey || event.ctrlKey) {
						isolateSeries(series, groups);
						updateLegend(svg);
						updateSeriesVisibility(svg);
						updateSelection(svg);
						return;
					}
					toggleSeries(series);
					updateLegend(svg);
					updateSeriesVisibility(svg);
					updateSelection(svg);
				}
			});

			for (const group of groups) {
				if (!isSeriesVisible(group)) continue;
				const rows = data
					.filter((r) => str(r[groupCol]) === group)
					.sort((a, b) => labels.indexOf(str(a.x)) - labels.indexOf(str(b.x)));

				const line = d3
					.line<Row>()
					.x((r) => x(labels.indexOf(str(r.x))))
					.y((r) => y(num(r.y)))
					.curve(d3.curveMonotoneX);

				const area = d3
					.area<Row>()
					.x((r) => x(labels.indexOf(str(r.x))))
					.y0(h)
					.y1((r) => y(num(r.y)))
					.curve(d3.curveMonotoneX);

				svg
					.append('path')
					.datum(rows)
					.attr('class', 'line-area')
					.attr('data-series', group)
					.attr('d', area)
					.attr('fill', color(group))
					.attr('opacity', 0.08);
				svg
					.append('path')
					.datum(rows)
					.attr('class', 'line-path')
					.attr('data-series', group)
					.attr('d', line)
					.attr('fill', 'none')
					.attr('stroke', color(group))
					.attr('stroke-width', 2);

				/* Dots with hover */
				svg
					.selectAll(`.dot-${CSS.escape(group)}`)
					.data(rows)
					.join('circle')
					.attr('class', 'chart-dot')
					.attr('data-series', group)
					.attr('data-key', (r) => makeKey(group, str(r.x)))
					.attr('cx', (r) => x(labels.indexOf(str(r.x))))
					.attr('cy', (r) => y(num(r.y)))
					.attr('r', 3.5)
					.attr('fill', color(group))
					.attr('stroke', 'var(--bg-primary)')
					.attr('stroke-width', 1.5)
					.style('cursor', 'pointer')
					.on('mouseover', function (event: MouseEvent, r: Row) {
						d3.select(this).attr('r', 6);
						showTip(str(r.x), [{ label: group, value: fmtFull(num(r.y)) }], event);
					})
					.on('click', function (event: MouseEvent, r: Row) {
						if (!selectEnabled) return;
						const key = makeKey(group, str(r.x));
						toggleSelection(key, event.metaKey || event.ctrlKey);
						updateSelection(svg);
					})
					.on('mouseout', function () {
						d3.select(this).attr('r', 3.5);
						updateSelection(svg);
						hideTip();
					});
			}
		} else {
			const sorted = [...data].sort((a, b) => labels.indexOf(str(a.x)) - labels.indexOf(str(b.x)));

			const line = d3
				.line<Row>()
				.x((r) => x(labels.indexOf(str(r.x))))
				.y((r) => y(num(r.y)))
				.curve(d3.curveMonotoneX);

			const area = d3
				.area<Row>()
				.x((r) => x(labels.indexOf(str(r.x))))
				.y0(h)
				.y1((r) => y(num(r.y)))
				.curve(d3.curveMonotoneX);

			svg
				.append('path')
				.datum(sorted)
				.attr('class', 'line-area')
				.attr('data-series', '')
				.attr('d', area)
				.attr('fill', getPrimaryColor())
				.attr('opacity', 0.08);
			svg
				.append('path')
				.datum(sorted)
				.attr('class', 'line-path')
				.attr('data-series', '')
				.attr('d', line)
				.attr('fill', 'none')
				.attr('stroke', getPrimaryColor())
				.attr('stroke-width', 2);

			svg
				.selectAll('.chart-dot')
				.data(sorted)
				.join('circle')
				.attr('class', 'chart-dot')
				.attr('data-series', '')
				.attr('data-key', (r) => makeKey('', str(r.x)))
				.attr('cx', (r) => x(labels.indexOf(str(r.x))))
				.attr('cy', (r) => y(num(r.y)))
				.attr('r', 3.5)
				.attr('fill', getPrimaryColor())
				.attr('stroke', 'var(--bg-primary)')
				.attr('stroke-width', 1.5)
				.style('cursor', 'pointer')
				.on('mouseover', function (event: MouseEvent, r: Row) {
					d3.select(this).attr('r', 6);
					showTip(str(r.x), [{ label: getYTitle(), value: fmtFull(num(r.y)) }], event);
				})
				.on('click', function (event: MouseEvent, r: Row) {
					if (!selectEnabled) return;
					const key = makeKey('', str(r.x));
					toggleSelection(key, event.metaKey || event.ctrlKey);
					updateSelection(svg);
				})
				.on('mouseout', function () {
					d3.select(this).attr('r', 3.5);
					updateSelection(svg);
					hideTip();
				});
		}

		for (const overlay of overlays) {
			const rows = overlayPoints.filter(
				(row) => str(row.overlay_label) === overlaySeriesLabel(overlay)
			);
			const type = overlayChartType(overlay);
			const label = overlaySeriesLabel(overlay);
			const axis = overlayAxisPosition(overlay);
			const yScale: AxisScale = axis === 'right' && yRight ? yRight : y;
			const color = overlayColor(label);
			if (type === 'scatter') {
				svg
					.selectAll(`.overlay-dot-${CSS.escape(label)}`)
					.data(rows)
					.join('circle')
					.attr('class', 'chart-dot overlay-dot')
					.attr('data-series', label)
					.attr('data-axis', axis)
					.attr('cx', (r) => x(labels.indexOf(str(r.x))))
					.attr('cy', (r) => yScale(num(r.y)))
					.attr('r', 3.5)
					.attr('fill', color)
					.attr('opacity', 0.85);
				continue;
			}
			if (type === 'bar') {
				svg
					.selectAll(`.overlay-bar-${CSS.escape(label)}`)
					.data(rows)
					.join('rect')
					.attr('class', 'chart-bar overlay-bar')
					.attr('data-series', label)
					.attr('data-axis', axis)
					.attr('x', (r) => x(labels.indexOf(str(r.x))) - 4)
					.attr('width', 8)
					.attr('y', (r) => yScale(num(r.y)))
					.attr('height', (r) => h - yScale(num(r.y)))
					.attr('fill', color)
					.attr('opacity', 0.25);
				continue;
			}
			const sorted = rows.sort((a, b) => labels.indexOf(str(a.x)) - labels.indexOf(str(b.x)));
			const line = d3
				.line<Row>()
				.x((r) => x(labels.indexOf(str(r.x))))
				.y((r) => yScale(num(r.y)))
				.curve(d3.curveMonotoneX);
			svg
				.append('path')
				.datum(sorted)
				.attr('class', 'overlay-path')
				.attr('data-series', label)
				.attr('data-axis', axis)
				.attr('d', line)
				.attr('fill', 'none')
				.attr('stroke', color)
				.attr('stroke-width', 2);
			if (type === 'area') {
				const area = d3
					.area<Row>()
					.x((r) => x(labels.indexOf(str(r.x))))
					.y0(h)
					.y1((r) => yScale(num(r.y)))
					.curve(d3.curveMonotoneX);
				svg
					.append('path')
					.datum(sorted)
					.attr('class', 'overlay-area')
					.attr('data-series', label)
					.attr('data-axis', axis)
					.attr('d', area)
					.attr('fill', color)
					.attr('opacity', getAreaOpacity());
			}
		}

		if (zoomEnabled) {
			const zoom = d3
				.zoom<SVGSVGElement, unknown>()
				.scaleExtent([1, 8])
				.on('zoom', (event) => {
					zoomTransform = event.transform;
					const z = applyZoom(event.transform, xBase, yBase);
					const zx = z.zx as d3.ScaleLinear<number, number>;
					axisX.call(
						d3
							.axisBottom(zx)
							.tickSizeOuter(0)
							.tickFormat((d) => fmtAxisTime(labels[Math.round(d as number)] ?? d))
					);
					axisY.call(
						d3
							.axisLeft(z.zy)
							.ticks(5)
							.tickFormat((d) => fmtAxis(d as number))
					);
					const zRight = yRightBase ? event.transform.rescaleY(yRightBase) : null;
					if (zRight) {
						svg.selectAll<SVGGElement, unknown>('.axis-right').call(
							d3
								.axisRight(zRight)
								.ticks(5)
								.tickFormat((d) => fmtAxis(d as number))
						);
					}
					grid.call(
						d3
							.axisLeft(z.zy)
							.ticks(5)
							.tickSize(-w)
							.tickFormat(() => '')
					);
					grid
						.selectAll('line')
						.attr('stroke', 'var(--border-primary)')
						.attr('stroke-opacity', 0.15)
						.attr('stroke-dasharray', '3,3');
					grid.select('.domain').remove();
					svg.selectAll<SVGPathElement, Row[]>('.line-path').attr('d', (rows) => {
						const line = d3
							.line<Row>()
							.x((r) => zx(labels.indexOf(str(r.x))))
							.y((r) => z.zy(num(r.y)))
							.curve(d3.curveMonotoneX);
						return line(rows) ?? '';
					});
					svg.selectAll<SVGPathElement, Row[]>('.line-area').attr('d', (rows) => {
						const area = d3
							.area<Row>()
							.x((r) => zx(labels.indexOf(str(r.x))))
							.y0(h)
							.y1((r) => z.zy(num(r.y)))
							.curve(d3.curveMonotoneX);
						return area(rows) ?? '';
					});
					svg
						.selectAll<SVGCircleElement, Row>('.chart-dot')
						.attr('cx', (r) => zx(labels.indexOf(str(r.x))));
					svg.selectAll<SVGCircleElement, Row>('.chart-dot').attr('cy', (r) => z.zy(num(r.y)));
					svg.selectAll<SVGPathElement, Row[]>('.overlay-path').attr('d', function (rows) {
						const axis = str(d3.select(this).attr('data-axis'));
						const yScale = axis === 'right' && zRight ? zRight : z.zy;
						const line = d3
							.line<Row>()
							.x((r) => zx(labels.indexOf(str(r.x))))
							.y((r) => yScale(num(r.y)))
							.curve(d3.curveMonotoneX);
						return line(rows) ?? '';
					});
					svg.selectAll<SVGPathElement, Row[]>('.overlay-area').attr('d', function (rows) {
						const axis = str(d3.select(this).attr('data-axis'));
						const yScale = axis === 'right' && zRight ? zRight : z.zy;
						const area = d3
							.area<Row>()
							.x((r) => zx(labels.indexOf(str(r.x))))
							.y0(h)
							.y1((r) => yScale(num(r.y)))
							.curve(d3.curveMonotoneX);
						return area(rows) ?? '';
					});
					svg
						.selectAll<SVGCircleElement, Row>('.overlay-dot')
						.attr('cx', (r) => zx(labels.indexOf(str(r.x))))
						.attr('cy', function (r) {
							const axis = str(d3.select(this).attr('data-axis'));
							const yScale = axis === 'right' && zRight ? zRight : z.zy;
							return yScale(num(r.y));
						});
					svg
						.selectAll<SVGRectElement, Row>('.overlay-bar')
						.attr('x', (r) => zx(labels.indexOf(str(r.x))) - 4)
						.attr('width', 8)
						.attr('y', function (r) {
							const axis = str(d3.select(this).attr('data-axis'));
							const yScale = axis === 'right' && zRight ? zRight : z.zy;
							return yScale(num(r.y));
						})
						.attr('height', function (r) {
							const axis = str(d3.select(this).attr('data-axis'));
							const yScale = axis === 'right' && zRight ? zRight : z.zy;
							return h - yScale(num(r.y));
						});
					redrawReferenceLines(svg, getReferenceLines(), zx, z.zy, w, h, zRight);
				});
			zoomBehavior = zoom;
			zoomTarget = root.node();
			root.call(zoom);
		}

		updateSeriesVisibility(svg);
		updateSelection(svg);
		drawReferenceLines(svg, getReferenceLines(), x, y, w, h, yRight);
		styleChart(svg);
	}

	function renderPie(el: HTMLDivElement, width: number, height: number) {
		const margin = 16;
		const radius = Math.min(width, height) / 2 - margin;

		const root = d3
			.select(el)
			.append('svg')
			.attr('width', width)
			.attr('height', height)
			.attr('role', 'img')
			.attr('aria-label', getChartAriaLabel()) as RootSvg;
		addChartTitle(root, str(config.title), width);
		const hasGroup = data.length > 0 && 'group' in data[0];
		const grouped = hasGroup ? d3.group(data, (r) => str(r.group)) : new Map([['', data]]);
		const groupOrder = hasGroup ? getGroupOrder(data, 'group') : [''];
		const groupEntries = hasGroup
			? groupOrder.map((key) => [key, grouped.get(key) ?? []] as [string, Row[]])
			: (Array.from(grouped.entries()) as Array<[string, Row[]]>);
		const labelDomain = Array.from(
			new Set(data.map((r) => str(r.label)).filter((label) => label.length > 0))
		);
		const color = d3.scaleOrdinal<string, string>().domain(labelDomain).range(getSeriesColors());
		const pie = d3.pie<number>().sort(null);
		const arc = d3
			.arc<d3.PieArcDatum<number>>()
			.innerRadius(radius * 0.4)
			.outerRadius(radius);
		const hoverArc = d3
			.arc<d3.PieArcDatum<number>>()
			.innerRadius(radius * 0.4)
			.outerRadius(radius + 6);
		const labelArc = d3
			.arc<d3.PieArcDatum<number>>()
			.innerRadius(radius * 0.65)
			.outerRadius(radius * 0.65);
		const groupWidth = width / Math.max(groupEntries.length, 1);
		const baseRadius = Math.min(groupWidth, height) / 2 - margin;

		for (let i = 0; i < groupEntries.length; i += 1) {
			const entry = groupEntries[i];
			const groupName = entry?.[0] ?? '';
			const groupRows = entry?.[1] ?? [];
			const values = groupRows.map((r) => num(r.y));
			const labels = groupRows.map((r) => str(r.label));
			const total = d3.sum(values);
			const cx = groupWidth * i + groupWidth / 2;
			const cy = height / 2;
			const groupRadius = Math.max(60, Math.min(baseRadius, radius));
			const g = root.append('g').attr('transform', `translate(${cx},${cy})`) as Svg;

			const groupArc = arc.outerRadius(groupRadius);
			const groupHoverArc = hoverArc.outerRadius(groupRadius + 6);
			const groupLabelArc = labelArc.outerRadius(groupRadius * 0.65);
			if (hasGroup) {
				root
					.append('text')
					.attr('x', cx)
					.attr('y', margin + 8)
					.attr('text-anchor', 'middle')
					.attr('fill', 'var(--fg-muted)')
					.style('font-size', '10px')
					.style('font-family', 'var(--font-mono)')
					.text(groupName || 'Group');
			}

			const arcs = g.selectAll('.arc').data(pie(values)).join('g').attr('class', 'arc');

			arcs
				.append('path')
				.attr('d', groupArc)
				.attr('fill', (_, i) => color(labels[i] ?? ''))
				.attr('stroke', 'var(--bg-primary)')
				.attr('stroke-width', 2)
				.style('cursor', 'pointer')
				.on('mouseover', function (event: MouseEvent, d) {
					d3.select(this).transition().duration(120).attr('d', groupHoverArc(d));
					g.selectAll('.arc path').attr('opacity', HOVER_DIM);
					d3.select(this).attr('opacity', 1);
					const i = d.index;
					const pct = total ? ((values[i] / total) * 100).toFixed(1) : '0.0';
					showTip(labels[i], [{ label: '', value: `${fmtFull(values[i])} (${pct}%)` }], event);
				})
				.on('mouseout', function (_, d) {
					d3.select(this).transition().duration(120).attr('d', groupArc(d));
					g.selectAll('.arc path').attr('opacity', 1);
					hideTip();
				});

			arcs
				.filter((d) => (d.endAngle - d.startAngle) / (2 * Math.PI) > 0.08)
				.append('text')
				.attr('transform', (d) => `translate(${groupLabelArc.centroid(d)})`)
				.attr('text-anchor', 'middle')
				.attr('dominant-baseline', 'central')
				.attr('fill', 'var(--fg-primary)')
				.style('font-size', '10px')
				.style('font-family', 'var(--font-mono)')
				.style('pointer-events', 'none')
				.text((_, i) => {
					const pct = total ? ((values[i] / total) * 100).toFixed(0) : '0';
					const lbl = labels[i]?.length > 8 ? labels[i].slice(0, 8) + '…' : labels[i];
					return `${lbl} ${pct}%`;
				});
		}
	}

	function renderHistogram(el: HTMLDivElement, width: number, height: number) {
		const margin = { top: 28, right: 24, bottom: 56, left: 64 };
		const w = width - margin.left - margin.right;
		const h = height - margin.top - margin.bottom;

		const root = d3
			.select(el)
			.append('svg')
			.attr('width', width)
			.attr('height', height)
			.attr('role', 'img')
			.attr('aria-label', getChartAriaLabel()) as RootSvg;
		addChartTitle(root, str(config.title), width);
		const svg = root
			.append('g')
			.attr('transform', `translate(${margin.left},${margin.top})`) as Svg;

		const xMin = d3.min(data, (r) => num(r.bin_start)) ?? 0;
		const xMax = d3.max(data, (r) => num(r.bin_end)) ?? 1;
		const x = d3.scaleLinear().domain([xMin, xMax]).range([0, w]);
		const y = buildYScale(
			data.map((r) => num(r.count)),
			0,
			h
		);

		addGrid(svg, y, w);

		svg
			.append('g')
			.attr('transform', `translate(0,${h})`)
			.call(
				d3
					.axisBottom(x)
					.ticks(6)
					.tickFormat((d) => fmtAxis(d as number))
			);

		makeYAxis(svg, y);
		addTitles(svg, getXTitle(), 'Count', w, h);

		svg
			.selectAll('.bin')
			.data(data)
			.join('rect')
			.attr('class', 'chart-bar')
			.attr('x', (r) => x(num(r.bin_start)))
			.attr('y', (r) => y(num(r.count)))
			.attr('width', (r) => Math.max(0, x(num(r.bin_end)) - x(num(r.bin_start)) - 1))
			.attr('height', (r) => h - y(num(r.count)))
			.attr('fill', getPrimaryColor())
			.attr('rx', 1)
			.style('cursor', 'pointer')
			.on('mouseover', function (event: MouseEvent, r: Row) {
				svg.selectAll('.chart-bar').attr('opacity', HOVER_DIM);
				d3.select(this).attr('opacity', 1);
				showTip(
					`${fmtFull(num(r.bin_start))} – ${fmtFull(num(r.bin_end))}`,
					[{ label: 'Count', value: fmtFull(num(r.count)) }],
					event
				);
			})
			.on('mouseout', function () {
				svg.selectAll('.chart-bar').attr('opacity', 1);
				hideTip();
			});

		styleChart(svg);
	}

	function renderScatter(el: HTMLDivElement, width: number, height: number) {
		const overlays = getOverlayConfigs();
		const overlayRight = overlays.some((overlay) => overlayAxisPosition(overlay) === 'right');
		const margin = { top: 28, right: overlayRight ? 64 : 24, bottom: 56, left: 64 };
		const w = width - margin.left - margin.right;
		const h = height - margin.top - margin.bottom;

		const root = d3
			.select(el)
			.append('svg')
			.attr('width', width)
			.attr('height', height)
			.attr('role', 'img')
			.attr('aria-label', getChartAriaLabel()) as RootSvg;
		addChartTitle(root, str(config.title), width);
		const svg = root
			.append('g')
			.attr('transform', `translate(${margin.left},${margin.top})`) as Svg;

		const xExtent = d3.extent(data, (r) => num(r.x)) as [number, number];
		const yExtent = d3.extent(data, (r) => num(r.y)) as [number, number];

		const overlayPoints: Row[] = [];
		const overlayGroupNames: string[] = [];
		const overlayValues: number[] = [];
		for (const overlay of overlays) {
			const rows = overlayData(overlay);
			const label = overlaySeriesLabel(overlay);
			const withLabel = rows.map((row) => ({ ...row, overlay_label: label }));
			overlayPoints.push(...withLabel);
			overlayGroupNames.push(label);
			overlayValues.push(...withLabel.map((row) => num((row as Row).y)));
		}
		const overlayColor = d3
			.scaleOrdinal<string>()
			.domain(overlayGroupNames)
			.range(getSeriesColors());
		const rightValues = overlayPoints
			.filter((row) => {
				const label = str(row.overlay_label);
				const overlay = overlays.find((item) => overlaySeriesLabel(item) === label);
				return overlay ? overlayAxisPosition(overlay) === 'right' : false;
			})
			.map((row) => num((row as Row).y));
		const rightMin = d3.min(rightValues) ?? 0;
		const yRightBase = rightValues.length > 0 ? buildYScale(rightValues, rightMin, h) : null;
		const xBase = d3.scaleLinear().domain(xExtent).nice().range([0, w]);
		const yBase = buildYScale(
			data.map((r) => num(r.y)),
			yExtent[0],
			h
		);
		const zoomed = zoomTransform ? applyZoom(zoomTransform, xBase, yBase) : null;
		const x = zoomed ? (zoomed.zx as d3.ScaleLinear<number, number>) : xBase;
		const y = zoomed ? zoomed.zy : yBase;
		const yRight = yRightBase
			? zoomTransform
				? zoomTransform.rescaleY(yRightBase)
				: yRightBase
			: null;

		const grid = addGrid(svg, y, w);

		/* Vertical grid lines for scatter */
		const vGrid = svg
			.append('g')
			.attr('class', 'grid-v')
			.call(
				d3
					.axisBottom(x)
					.ticks(6)
					.tickSize(-h)
					.tickFormat(() => '')
			);
		vGrid.attr('transform', `translate(0,${h})`);
		vGrid
			.selectAll('line')
			.attr('stroke', 'var(--border-primary)')
			.attr('stroke-opacity', 0.15)
			.attr('stroke-dasharray', '3,3');
		vGrid.select('.domain').remove();

		const axisX = svg
			.append('g')
			.attr('transform', `translate(0,${h})`)
			.call(
				d3
					.axisBottom(x)
					.ticks(6)
					.tickFormat((d) => fmtAxis(d as number))
			);

		const axisY = svg.append('g').call(
			d3
				.axisLeft(y)
				.ticks(5)
				.tickFormat((d) => fmtAxis(d as number))
		);
		if (yRight) addRightYAxis(svg, yRight, w);
		addTitles(svg, getXTitle(), getYTitle(), w, h);

		const hasGroup = data.length > 0 && 'group' in data[0];

		if (hasGroup) {
			const groups = getGroupOrder(data, 'group');
			const color = d3.scaleOrdinal<string>().domain(groups).range(getSeriesColors());
			addLegend(svg, groups, (l) => color(l), w, h, {
				onClick: (series: string, event: MouseEvent | KeyboardEvent) => {
					if (event.metaKey || event.ctrlKey) {
						isolateSeries(series, groups);
						updateLegend(svg);
						updateSeriesVisibility(svg);
						updateSelection(svg);
						return;
					}
					toggleSeries(series);
					updateLegend(svg);
					updateSeriesVisibility(svg);
					updateSelection(svg);
				}
			});

			svg
				.selectAll('.dot')
				.data(data)
				.join('circle')
				.attr('class', 'chart-dot')
				.attr('data-series', (r) => str(r.group))
				.attr('data-key', (r) => makePointKey(str(r.group), str(r.x), num(r.y)))
				.attr('cx', (r) => x(num(r.x)))
				.attr('cy', (r) => y(num(r.y)))
				.attr('r', 3)
				.attr('fill', (r) => color(str(r.group)))
				.attr('opacity', 0.7)
				.style('cursor', 'pointer')
				.on('mouseover', function (event: MouseEvent, r: Row) {
					d3.select(this).attr('r', 6).attr('opacity', 1);
					showTip(
						str(r.group),
						[
							{ label: getXTitle(), value: fmtFull(num(r.x)) },
							{ label: getYTitle(), value: fmtFull(num(r.y)) }
						],
						event
					);
				})
				.on('click', function (event: MouseEvent, r: Row) {
					if (!selectEnabled) return;
					const key = makePointKey(str(r.group), str(r.x), num(r.y));
					toggleSelection(key, event.metaKey || event.ctrlKey);
					updateSelection(svg);
				})
				.on('mouseout', function () {
					d3.select(this).attr('r', 3).attr('opacity', 0.7);
					updateSelection(svg);
					hideTip();
				});
		} else {
			svg
				.selectAll('.dot')
				.data(data)
				.join('circle')
				.attr('class', 'chart-dot')
				.attr('data-series', '')
				.attr('data-key', (r) => makePointKey('', str(r.x), num(r.y)))
				.attr('cx', (r) => x(num(r.x)))
				.attr('cy', (r) => y(num(r.y)))
				.attr('r', 3)
				.attr('fill', getPrimaryColor())
				.attr('opacity', 0.7)
				.style('cursor', 'pointer')
				.on('mouseover', function (event: MouseEvent, r: Row) {
					d3.select(this).attr('r', 6).attr('opacity', 1);
					showTip(
						'',
						[
							{ label: getXTitle(), value: fmtFull(num(r.x)) },
							{ label: getYTitle(), value: fmtFull(num(r.y)) }
						],
						event
					);
				})
				.on('click', function (event: MouseEvent, r: Row) {
					if (!selectEnabled) return;
					const key = makePointKey('', str(r.x), num(r.y));
					toggleSelection(key, event.metaKey || event.ctrlKey);
					updateSelection(svg);
				})
				.on('mouseout', function () {
					d3.select(this).attr('r', 3).attr('opacity', 0.7);
					updateSelection(svg);
					hideTip();
				});
		}

		for (const overlay of overlays) {
			const rows = overlayPoints.filter(
				(row) => str(row.overlay_label) === overlaySeriesLabel(overlay)
			);
			const type = overlayChartType(overlay);
			const label = overlaySeriesLabel(overlay);
			const axis = overlayAxisPosition(overlay);
			const yScale: AxisScale = axis === 'right' && yRight ? yRight : y;
			const color = overlayColor(label);
			if (type === 'scatter') {
				svg
					.selectAll(`.overlay-dot-${CSS.escape(label)}`)
					.data(rows)
					.join('circle')
					.attr('class', 'chart-dot overlay-dot')
					.attr('data-series', label)
					.attr('data-axis', axis)
					.attr('cx', (r) => x(num(r.x)))
					.attr('cy', (r) => yScale(num(r.y)))
					.attr('r', 3.5)
					.attr('fill', color)
					.attr('opacity', 0.85);
				continue;
			}
			if (type === 'bar') {
				svg
					.selectAll(`.overlay-bar-${CSS.escape(label)}`)
					.data(rows)
					.join('rect')
					.attr('class', 'chart-bar overlay-bar')
					.attr('data-series', label)
					.attr('data-axis', axis)
					.attr('x', (r) => x(num(r.x)) - 4)
					.attr('width', 8)
					.attr('y', (r) => yScale(num(r.y)))
					.attr('height', (r) => h - yScale(num(r.y)))
					.attr('fill', color)
					.attr('opacity', 0.25);
				continue;
			}
			const sorted = rows.sort((a, b) => num(a.x) - num(b.x));
			const line = d3
				.line<Row>()
				.x((r) => x(num(r.x)))
				.y((r) => yScale(num(r.y)))
				.curve(d3.curveMonotoneX);
			svg
				.append('path')
				.datum(sorted)
				.attr('class', 'overlay-path')
				.attr('data-series', label)
				.attr('data-axis', axis)
				.attr('d', line)
				.attr('fill', 'none')
				.attr('stroke', color)
				.attr('stroke-width', 2);
			if (type === 'area') {
				const area = d3
					.area<Row>()
					.x((r) => x(num(r.x)))
					.y0(h)
					.y1((r) => yScale(num(r.y)))
					.curve(d3.curveMonotoneX);
				svg
					.append('path')
					.datum(sorted)
					.attr('class', 'overlay-area')
					.attr('data-series', label)
					.attr('data-axis', axis)
					.attr('d', area)
					.attr('fill', color)
					.attr('opacity', getAreaOpacity());
			}
		}

		if (zoomEnabled && !areaSelectEnabled) {
			const zoom = d3
				.zoom<SVGSVGElement, unknown>()
				.scaleExtent([1, 8])
				.on('zoom', (event) => {
					zoomTransform = event.transform;
					const z = applyZoom(event.transform, xBase, yBase);
					const zx = z.zx as d3.ScaleLinear<number, number>;
					axisX.call(
						d3
							.axisBottom(zx)
							.ticks(6)
							.tickFormat((d) => fmtAxis(d as number))
					);
					axisY.call(
						d3
							.axisLeft(z.zy)
							.ticks(5)
							.tickFormat((d) => fmtAxis(d as number))
					);
					const zRight = yRightBase ? event.transform.rescaleY(yRightBase) : null;
					if (zRight) {
						svg.selectAll<SVGGElement, unknown>('.axis-right').call(
							d3
								.axisRight(zRight)
								.ticks(5)
								.tickFormat((d) => fmtAxis(d as number))
						);
					}
					grid.call(
						d3
							.axisLeft(z.zy)
							.ticks(5)
							.tickSize(-w)
							.tickFormat(() => '')
					);
					grid
						.selectAll('line')
						.attr('stroke', 'var(--border-primary)')
						.attr('stroke-opacity', 0.15)
						.attr('stroke-dasharray', '3,3');
					grid.select('.domain').remove();
					vGrid.call(
						d3
							.axisBottom(zx)
							.ticks(6)
							.tickSize(-h)
							.tickFormat(() => '')
					);
					svg.selectAll('.chart-dot').attr('cx', (r) => zx(num((r as Row).x) as number));
					svg.selectAll('.chart-dot').attr('cy', (r) => z.zy(num((r as Row).y) as number));
					svg.selectAll<SVGPathElement, Row[]>('.overlay-path').attr('d', function (rows) {
						const axis = str(d3.select(this).attr('data-axis'));
						const yScale = axis === 'right' && zRight ? zRight : z.zy;
						const line = d3
							.line<Row>()
							.x((r) => zx(num(r.x)))
							.y((r) => yScale(num(r.y)))
							.curve(d3.curveMonotoneX);
						return line(rows) ?? '';
					});
					svg.selectAll<SVGPathElement, Row[]>('.overlay-area').attr('d', function (rows) {
						const axis = str(d3.select(this).attr('data-axis'));
						const yScale = axis === 'right' && zRight ? zRight : z.zy;
						const area = d3
							.area<Row>()
							.x((r) => zx(num(r.x)))
							.y0(h)
							.y1((r) => yScale(num(r.y)))
							.curve(d3.curveMonotoneX);
						return area(rows) ?? '';
					});
					svg
						.selectAll<SVGCircleElement, Row>('.overlay-dot')
						.attr('cx', (r) => zx(num(r.x)))
						.attr('cy', function (r) {
							const axis = str(d3.select(this).attr('data-axis'));
							const yScale = axis === 'right' && zRight ? zRight : z.zy;
							return yScale(num(r.y));
						});
					svg
						.selectAll<SVGRectElement, Row>('.overlay-bar')
						.attr('x', (r) => zx(num(r.x)) - 4)
						.attr('width', 8)
						.attr('y', function (r) {
							const axis = str(d3.select(this).attr('data-axis'));
							const yScale = axis === 'right' && zRight ? zRight : z.zy;
							return yScale(num(r.y));
						})
						.attr('height', function (r) {
							const axis = str(d3.select(this).attr('data-axis'));
							const yScale = axis === 'right' && zRight ? zRight : z.zy;
							return h - yScale(num(r.y));
						});
					redrawReferenceLines(svg, getReferenceLines(), zx, z.zy, w, h, zRight);
				});
			zoomBehavior = zoom;
			zoomTarget = root.node();
			root.call(zoom);
		}

		if (areaSelectEnabled) {
			const brush = d3
				.brush()
				.extent([
					[0, 0],
					[w, h]
				])
				.on('end', (event) => {
					if (!selectEnabled) return;
					const selection = event.selection as [[number, number], [number, number]] | null;
					selectedKeys.clear();
					if (!selection) {
						updateSelection(svg);
						return;
					}
					const [[x0, y0], [x1, y1]] = selection;
					svg.selectAll<SVGCircleElement, Row>('.chart-dot').each(function (r) {
						const cx = x(num(r.x));
						const cy = y(num(r.y));
						if (cx < x0 || cx > x1 || cy < y0 || cy > y1) return;
						const key = makePointKey(str(r.group ?? ''), str(r.x), num(r.y));
						selectedKeys.add(key);
					});
					updateSelection(svg);
				});
			svg.append('g').attr('class', 'brush').call(brush);
		}

		updateSeriesVisibility(svg);
		updateSelection(svg);
		drawReferenceLines(svg, getReferenceLines(), x, y, w, h, yRight);

		styleChart(svg);
	}

	function renderBoxplot(el: HTMLDivElement, width: number, height: number) {
		const margin = { top: 20, right: 24, bottom: 48, left: 80 };
		const w = width - margin.left - margin.right;
		const h = height - margin.top - margin.bottom;

		const root = d3
			.select(el)
			.append('svg')
			.attr('width', width)
			.attr('height', height)
			.attr('role', 'img')
			.attr('aria-label', getChartAriaLabel()) as RootSvg;
		addChartTitle(root, str(config.title), width);
		const svg = root
			.append('g')
			.attr('transform', `translate(${margin.left},${margin.top})`) as Svg;

		const groups = data.map((r) => str(r.group));
		const y = d3.scaleBand().domain(groups).range([0, h]).padding(0.3);

		const xMin = d3.min(data, (r) => num(r.min)) ?? 0;
		const xMax = d3.max(data, (r) => num(r.max)) ?? 1;
		const x = d3.scaleLinear().domain([xMin, xMax]).nice().range([0, w]);

		/* Vertical grid for boxplot */
		const vGrid = svg
			.append('g')
			.attr('class', 'grid-v')
			.call(
				d3
					.axisBottom(x)
					.ticks(6)
					.tickSize(-h)
					.tickFormat(() => '')
			);
		vGrid.attr('transform', `translate(0,${h})`);
		vGrid
			.selectAll('line')
			.attr('stroke', 'var(--border-primary)')
			.attr('stroke-opacity', 0.15)
			.attr('stroke-dasharray', '3,3');
		vGrid.select('.domain').remove();

		svg.append('g').call(d3.axisLeft(y).tickSizeOuter(0));

		svg
			.append('g')
			.attr('transform', `translate(0,${h})`)
			.call(
				d3
					.axisBottom(x)
					.ticks(6)
					.tickFormat((d) => fmtAxis(d as number))
			);

		addTitles(svg, getYTitle(), '', w, h);

		const bandH = y.bandwidth();

		for (const row of data) {
			const g = str(row.group);
			const cy = (y(g) ?? 0) + bandH / 2;
			const boxGroup = svg.append('g').attr('class', 'boxplot-group');

			/* Whisker line */
			boxGroup
				.append('line')
				.attr('x1', x(num(row.min)))
				.attr('x2', x(num(row.max)))
				.attr('y1', cy)
				.attr('y2', cy)
				.attr('stroke', getPrimaryColor())
				.attr('stroke-width', 1);

			/* Box (Q1 to Q3) */
			const q1x = x(num(row.q1));
			const q3x = x(num(row.q3));
			boxGroup
				.append('rect')
				.attr('x', q1x)
				.attr('y', cy - bandH * 0.35)
				.attr('width', Math.max(0, q3x - q1x))
				.attr('height', bandH * 0.7)
				.attr('fill', getPrimaryColor())
				.attr('opacity', 0.2)
				.attr('stroke', getPrimaryColor())
				.attr('stroke-width', 1.5)
				.attr('rx', 2);

			/* Median line */
			boxGroup
				.append('line')
				.attr('x1', x(num(row.median)))
				.attr('x2', x(num(row.median)))
				.attr('y1', cy - bandH * 0.35)
				.attr('y2', cy + bandH * 0.35)
				.attr('stroke', getPrimaryColor())
				.attr('stroke-width', 2.5);

			/* Whisker caps */
			for (const val of [num(row.min), num(row.max)]) {
				boxGroup
					.append('line')
					.attr('x1', x(val))
					.attr('x2', x(val))
					.attr('y1', cy - bandH * 0.2)
					.attr('y2', cy + bandH * 0.2)
					.attr('stroke', getPrimaryColor())
					.attr('stroke-width', 1.5);
			}

			/* Hover area for tooltip */
			boxGroup
				.append('rect')
				.attr('x', x(num(row.min)))
				.attr('y', cy - bandH * 0.4)
				.attr('width', Math.max(0, x(num(row.max)) - x(num(row.min))))
				.attr('height', bandH * 0.8)
				.attr('fill', 'transparent')
				.style('cursor', 'pointer')
				.on('mouseover', function (event: MouseEvent) {
					boxGroup.select('rect:first-of-type').attr('opacity', 0.35);
					showTip(
						g,
						[
							{ label: 'Min', value: fmtFull(num(row.min)) },
							{ label: 'Q1', value: fmtFull(num(row.q1)) },
							{ label: 'Median', value: fmtFull(num(row.median)) },
							{ label: 'Q3', value: fmtFull(num(row.q3)) },
							{ label: 'Max', value: fmtFull(num(row.max)) }
						],
						event
					);
				})
				.on('mouseout', function () {
					boxGroup.select('rect:first-of-type').attr('opacity', 0.2);
					hideTip();
				});
		}

		styleChart(svg);
	}
</script>

<div class="chart-wrapper" bind:this={wrapperEl}>
	<div class="chart-controls">
		<button
			type="button"
			class="btn-ghost btn-sm border border-tertiary text-xs"
			aria-label="Export chart as PNG"
			onclick={exportChartPng}
		>
			Export PNG
		</button>
		<button
			type="button"
			class="btn-ghost btn-sm border border-tertiary text-xs"
			aria-label="Export chart data as CSV"
			onclick={exportChartCsv}
		>
			Export CSV
		</button>
	</div>
	<div class="chart-area" bind:this={chartEl}>
		{#if data.length === 0}
			<div class="chart-empty">
				<span>No data to display</span>
			</div>
		{/if}
	</div>
	{#if zoomEnabled && zoomActive}
		<div class="chart-reset">
			<button
				type="button"
				class="btn-ghost btn-sm border border-tertiary text-xs"
				aria-label="Reset chart zoom"
				onclick={resetZoom}
			>
				Reset zoom
			</button>
		</div>
	{/if}
	<div
		class="chart-tooltip"
		class:tip-visible={tipVisible}
		style:left="{tipX}px"
		style:top="{tipY}px"
	>
		{#if tipTitle}<strong>{tipTitle}</strong>{/if}
		{#each tipLines as line, i (i)}
			{#if tipTitle || tipLines.length > 1}<br />{/if}
			{#if line.label}{line.label}:
			{/if}{line.value}
		{/each}
	</div>
</div>

<style>
	.chart-wrapper {
		position: relative;
		width: 100%;
		height: 300px;
		background-color: var(--bg-primary);
		overflow: hidden;
		contain: content;
	}

	.chart-area {
		width: 100%;
		height: 100%;
	}

	.chart-controls {
		position: absolute;
		top: 10px;
		left: 12px;
		display: flex;
		gap: 8px;
		z-index: var(--z-overlay);
	}

	.chart-reset {
		position: absolute;
		top: 10px;
		right: 12px;
		z-index: var(--z-overlay);
	}

	.chart-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		color: var(--fg-muted);
		font-size: 0.75rem;
	}

	.chart-tooltip {
		position: absolute;
		pointer-events: none;
		opacity: 0;
		padding: 8px 12px;
		background-color: var(--bg-tertiary);
		border: 1px solid var(--border-primary);
		color: var(--fg-primary);
		font-family: var(--font-mono);
		font-size: 0.6875rem;
		line-height: 1.6;
		white-space: nowrap;
		z-index: var(--z-tooltip);
		transition: opacity 80ms ease;
	}

	.chart-tooltip.tip-visible {
		opacity: 1;
	}
</style>
