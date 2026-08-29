import {
	areaX,
	areaY,
	barX,
	barY,
	boxX,
	cell,
	d3Curve,
	dot,
	group as groupLayout,
	lineX,
	lineY,
	rect,
	ruleX,
	ruleY,
	stack as stackLayout,
	text
} from '@tanstack/charts';
import { pie as pieSlices, polar, radialArc, radialText } from '@tanstack/charts/polar';
import type {
	ChartDefinitionOptions,
	ChartKey,
	ChartMark,
	ChartMarkState,
	ChartMarkStateStyle,
	ChartScaleInput,
	ChartTooltipContent,
	ChartValue,
	DomChartDefinition
} from '@tanstack/charts';
import { scaleBand } from '@tanstack/charts/scales/band';
import { scaleLinear } from '@tanstack/charts/scales/linear';
import { colorGradientLegend } from '@tanstack/charts/legend';
import { brushX, type BrushRange, type BrushXChange } from '@tanstack/charts/interaction/brush';
import { controlledSignal } from '@tanstack/charts/interaction/signal';
import { zoomX, type ZoomXChange, type ZoomXWindow } from '@tanstack/charts/interaction/zoom';
import { keyedSelection, type KeyedSelectionChange } from '@tanstack/charts/selection';
import { tooltip } from '@tanstack/charts/tooltip';
import { scaleLinear as d3ScaleLinear, scaleLog } from 'd3-scale';
import { interpolateBlues } from 'd3-scale-chromatic';
import { curveMonotoneX, curveMonotoneY } from 'd3-shape';
import {
	CHART_THEME,
	FG_SECONDARY,
	areaOpacity,
	formatNumber,
	formatTimeTick,
	groupSort,
	needsRotatedTicks,
	readNumber,
	readString,
	referenceLinesOf,
	seriesColors,
	stackMode,
	truncateLabel,
	xAxisTitle,
	yAxisTitle,
	type ChartConfig,
	type ChartType
} from './format';
import { groupOrder, numberValue, stringValue, type ChartRow } from './preparation';

export type { ChartType };

type AnyMark = ChartMark<
	ChartRow,
	ChartKey | number,
	number,
	ChartKey | number,
	number,
	string,
	string
>;
type MarkStates = readonly ChartMarkState<ChartRow, ChartMarkStateStyle<ChartRow>>[];

function defineChartDom(spec: object, options: object): DomChartDefinition {
	return { ...spec, ...options } as DomChartDefinition;
}

export interface ChartHandlers {
	onZoomWindow(value: [number, number] | null): void;
	onSelectedKey(value: string | null): void;
	onBrushRange(value: [number, number] | null): void;
}

export interface ChartInteraction {
	visibleSeries: ReadonlySet<string>;
	selectedKey: string | null;
	zoomWindow: [number, number] | null;
	brushRange: [number, number] | null;
}

export interface ChartPane {
	key: string;
	label: string;
	definition: DomChartDefinition;
}

export interface BuiltChart {
	panes: ChartPane[];
	seriesLabels: string[];
	colorOf: (label: string) => string;
	zoomExtent: [number, number] | null;
}

export interface ChartInput {
	data: ChartRow[];
	chartType: ChartType;
	config: ChartConfig;
	metadata?: Record<string, unknown> | null;
	interaction: ChartInteraction;
	handlers: ChartHandlers;
}

interface Ctx extends ChartInput {
	metadata: Record<string, unknown> | null;
}

export function buildChart(input: ChartInput): BuiltChart {
	const ctx: Ctx = { ...input, metadata: input.metadata ?? null };
	const colors = seriesColors(ctx.config);
	if (ctx.chartType === 'pie') {
		return { panes: piePanes(ctx), seriesLabels: [], colorOf: () => colors[0], zoomExtent: null };
	}
	const builder = builders[ctx.chartType];
	const built = builder(ctx);
	return {
		panes: [{ key: 'main', label: '', definition: built.definition }],
		seriesLabels: built.seriesLabels,
		colorOf: (label) => colors[Math.max(0, built.seriesLabels.indexOf(label)) % colors.length],
		zoomExtent: built.zoomExtent ?? null
	};
}

const builders: Record<
	Exclude<ChartType, 'pie'>,
	(ctx: Ctx) => {
		definition: DomChartDefinition;
		seriesLabels: string[];
		zoomExtent?: [number, number];
	}
> = {
	bar: barDefinition,
	horizontal_bar: horizontalBarDefinition,
	area: areaDefinition,
	heatgrid: heatgridDefinition,
	line: lineDefinition,
	histogram: histogramDefinition,
	scatter: scatterDefinition,
	boxplot: boxplotDefinition
};

/* ── shared helpers ── */

const str = stringValue;
const num = numberValue;

function hasColumn(data: ChartRow[], column: string): boolean {
	return data.length > 0 && column in data[0];
}

function seriesVisible(interaction: ChartInteraction, series: string): boolean {
	return interaction.visibleSeries.size === 0 || interaction.visibleSeries.has(series);
}

function dimStates(keyOf: (datum: ChartRow) => string, selectedKey: string | null): MarkStates {
	if (selectedKey == null) return [];
	return [
		{
			when: (context: { datum: ChartRow }) => keyOf(context.datum) !== selectedKey,
			style: { opacity: 0.25 }
		}
	] as MarkStates;
}

function selectionOption(
	keyOf: (datum: ChartRow) => string,
	ctx: Ctx
): Pick<ChartDefinitionOptions<ChartRow>, 'selection'> {
	return {
		selection: keyedSelection<ChartRow, string>({
			selected: controlledSignal<string | null, KeyedSelectionChange<ChartRow, string>>(
				ctx.interaction.selectedKey,
				(value) => ctx.handlers.onSelectedKey(value)
			),
			key: (datum: ChartRow): string => keyOf(datum)
		})
	};
}

function zoomOption(extent: [number, number], ctx: Ctx): Pick<ChartDefinitionOptions, 'controls'> {
	const current = ctx.interaction.zoomWindow;
	const windowValue: ZoomXWindow<number> = {
		start: current?.[0] ?? extent[0],
		end: current?.[1] ?? extent[1]
	};
	return {
		controls: [
			zoomX({
				window: controlledSignal<ZoomXWindow<number>, ZoomXChange<number>>(windowValue, (value) =>
					ctx.handlers.onZoomWindow([value.start, value.end])
				),
				extent,
				scaleExtent: [1, 8]
			})
		]
	};
}

function brushOption(values: number[], ctx: Ctx): Pick<ChartDefinitionOptions, 'controls'> {
	const current = ctx.interaction.brushRange;
	const range: BrushRange<ChartValue> = {
		start: current?.[0] ?? values[0] ?? 0,
		end: current?.[1] ?? values[values.length - 1] ?? 1
	};
	return {
		controls: [
			brushX({
				range: controlledSignal<BrushRange<ChartValue>, BrushXChange<ChartValue>>(range, (value) =>
					ctx.handlers.onBrushRange([Number(value.start), Number(value.end)])
				),
				values,
				keyboard: true
			})
		]
	};
}

function overlayYValues(ctx: Ctx): number[] {
	const values: number[] = [];
	for (const overlay of overlayMarksOf(ctx.metadata)) {
		for (const row of overlayData(overlay)) values.push(num(row.y));
	}
	return values;
}

function yScaleInput(values: number[], config: ChartConfig): ChartScaleInput<number> {
	const configMin = readNumber(config, 'y_axis_min');
	const configMax = readNumber(config, 'y_axis_max');
	if (readString(config, 'y_axis_scale') === 'log') {
		const positive = values.filter((v) => v > 0);
		const posMin = positive.length ? Math.min(...positive) : 1;
		const posMax = positive.length ? Math.max(...positive) : posMin;
		const min = configMin != null && configMin > 0 ? configMin : posMin;
		let max = configMax != null && configMax > 0 ? configMax : posMax;
		if (min > 0 && max > 0) {
			if (min === max) max = min * 10;
			return scaleLog().domain([min, max]).nice() as unknown as ChartScaleInput<number>;
		}
	}
	if (configMin != null || configMax != null) {
		const min = configMin ?? Math.min(0, ...values);
		const max = configMax ?? Math.max(...values, min);
		return scaleLinear().domain([min, min === max ? min + 1 : max]);
	}
	return scaleLinear;
}

function stackedScaleInput(maxTotal: number, normalized: boolean): ChartScaleInput<number> {
	return normalized ? scaleLinear().domain([0, 1]) : scaleLinear().domain([0, maxTotal || 1]);
}

function numberAxis(config: ChartConfig, count: number) {
	return {
		ticks: { count, format: (v: number) => formatNumber(v, config) }
	};
}

function categoryAxis(config: ChartConfig, labels: string[], timeFormat: boolean) {
	return {
		ticks: {
			format: timeFormat ? (v: unknown) => formatTimeTick(v, config) : (v: unknown) => String(v)
		},
		tickLabels: { rotate: needsRotatedTicks(labels) ? -35 : undefined }
	};
}

function overlayData(overlay: ChartRow): ChartRow[] {
	const raw = overlay.data;
	if (!Array.isArray(raw)) return [];
	return raw
		.filter((item) => item && typeof item === 'object')
		.map((row) => ({ ...(row as ChartRow), series: overlaySeriesLabel(overlay) }));
}

function overlaySeriesLabel(overlay: ChartRow): string {
	const yCol = readString(overlay, 'y_column');
	const agg = readString(overlay, 'aggregation');
	if (!yCol) return 'Overlay';
	if (!agg) return yCol;
	return `${agg.charAt(0).toUpperCase()}${agg.slice(1)} of ${yCol}`;
}

function overlayChartType(overlay: ChartRow): 'line' | 'area' | 'bar' | 'scatter' {
	const raw = readString(overlay, 'chart_type');
	if (raw === 'area' || raw === 'bar' || raw === 'scatter') return raw;
	return 'line';
}

function overlayOnRight(overlay: ChartRow): boolean {
	return readString(overlay, 'y_axis_position') === 'right';
}

function overlayMarksOf(metadata: Record<string, unknown> | null): ChartRow[] {
	const raw = metadata?.overlays;
	if (!Array.isArray(raw)) return [];
	return raw.filter((item) => item && typeof item === 'object') as ChartRow[];
}

function rightScaleOption(ctx: Ctx, channel: 'x' | 'y'): Record<string, unknown> {
	if (!overlayMarksOf(ctx.metadata).some(overlayOnRight)) return {};
	return {
		right: {
			channel,
			scale: scaleLinear,
			nice: true,
			side: 'right',
			axis: numberAxis(ctx.config, 5)
		}
	};
}

function referenceMarks(
	ctx: Ctx,
	options: { xCategoryLabels?: string[]; yCategoryLabels?: string[]; xMax?: number }
): AnyMark[] {
	const lines = referenceLinesOf(ctx.metadata);
	const marks: AnyMark[] = [];
	for (const line of lines) {
		const value = readNumber(line, 'value');
		if (value == null) continue;
		const color = readString(line, 'color') || 'var(--colors-border-primary)';
		const axis = readString(line, 'axis') || readString(line, 'target_axis') || 'y';
		const position = readString(line, 'y_axis_position') || readString(line, 'target_axis');
		if (axis === 'x') {
			const labels = options.xCategoryLabels;
			const xValue: ChartKey | number = labels
				? (labels[Math.round(value)] ?? String(value))
				: value;
			marks.push(
				ruleX([xValue], {
					x: (v) => v,
					stroke: color,
					strokeDasharray: '4 4'
				}) as unknown as AnyMark
			);
			continue;
		}
		const labels = options.yCategoryLabels;
		const yValue: ChartKey | number = labels ? (labels[Math.round(value)] ?? String(value)) : value;
		const useRight = position === 'right' && overlayMarksOf(ctx.metadata).some(overlayOnRight);
		marks.push(
			ruleY([yValue], {
				y: (v) => v,
				stroke: color,
				strokeDasharray: '4 4',
				...(useRight ? { yScale: 'right' } : {})
			}) as unknown as AnyMark
		);
		const label = readString(line, 'label');
		if (label && !labels) {
			marks.push(
				text([{ x: options.xMax ?? value, y: yValue }], {
					x: (d) => d.x,
					y: (d) => num(d.y),
					text: () => label,
					fill: color,
					fontSize: 10,
					anchor: 'end',
					dy: -6
				}) as unknown as AnyMark
			);
		}
	}
	return marks;
}

function verticalOverlays(
	ctx: Ctx,
	xKind: 'band' | 'index',
	indexOf: (label: string) => number
): AnyMark[] {
	const overlays = overlayMarksOf(ctx.metadata);
	const colors = seriesColors(ctx.config);
	const marks: AnyMark[] = [];
	overlays.forEach((overlay, index) => {
		const rows = overlayData(overlay);
		if (rows.length === 0) return;
		const scaleId = overlayOnRight(overlay) ? 'right' : undefined;
		const color = colors[index % colors.length];
		const type = overlayChartType(overlay);
		const right = scaleId ? { yScale: scaleId } : {};
		if (type === 'scatter') {
			marks.push(
				dot(rows, {
					x: (d) => str(d.x),
					y: (d) => num(d.y),
					fill: color,
					r: 3.5,
					fillOpacity: 0.85,
					...right
				}) as unknown as AnyMark
			);
			return;
		}
		if (type === 'bar') {
			if (xKind === 'band') {
				marks.push(
					barY(rows, {
						x: (d) => str(d.x),
						y: (d) => num(d.y),
						fill: color,
						fillOpacity: 0.25,
						...right
					}) as unknown as AnyMark
				);
			} else {
				marks.push(
					rect(rows, {
						x1: (d) => indexOf(str(d.x)) - 0.2,
						x2: (d) => indexOf(str(d.x)) + 0.2,
						y1: () => 0,
						y2: (d) => num(d.y),
						fill: color,
						fillOpacity: 0.25,
						...right
					}) as unknown as AnyMark
				);
			}
			return;
		}
		marks.push(
			lineY(rows, {
				x: (d) => str(d.x),
				y: (d) => num(d.y),
				stroke: color,
				strokeWidth: 2,
				curve: d3Curve(curveMonotoneX),
				...right
			}) as unknown as AnyMark
		);
		if (type === 'area') {
			marks.push(
				areaY(rows, {
					x: (d) => str(d.x),
					y: (d) => num(d.y),
					fill: color,
					fillOpacity: areaOpacity(ctx.config),
					curve: d3Curve(curveMonotoneX),
					...right
				}) as unknown as AnyMark
			);
		}
	});
	return marks;
}

function horizontalOverlays(ctx: Ctx): AnyMark[] {
	const overlays = overlayMarksOf(ctx.metadata);
	const colors = seriesColors(ctx.config);
	const marks: AnyMark[] = [];
	overlays.forEach((overlay, index) => {
		const rows = overlayData(overlay);
		if (rows.length === 0) return;
		const scaleId = overlayOnRight(overlay) ? 'right' : undefined;
		const color = colors[index % colors.length];
		const type = overlayChartType(overlay);
		const right = scaleId ? { xScale: scaleId } : {};
		if (type === 'scatter') {
			marks.push(
				dot(rows, {
					x: (d) => num(d.y),
					y: (d) => str(d.x),
					fill: color,
					r: 3.5,
					fillOpacity: 0.85,
					...right
				}) as unknown as AnyMark
			);
			return;
		}
		if (type === 'bar') {
			marks.push(
				barX(rows, {
					x: (d) => num(d.y),
					y: (d) => str(d.x),
					fill: color,
					fillOpacity: 0.25,
					...right
				}) as unknown as AnyMark
			);
			return;
		}
		marks.push(
			lineX(rows, {
				x: (d) => num(d.y),
				y: (d) => str(d.x),
				stroke: color,
				strokeWidth: 2,
				curve: d3Curve(curveMonotoneY),
				...right
			}) as unknown as AnyMark
		);
		if (type === 'area') {
			marks.push(
				areaX(rows, {
					x: (d) => num(d.y),
					y: (d) => str(d.x),
					fill: color,
					fillOpacity: areaOpacity(ctx.config),
					...right
				}) as unknown as AnyMark
			);
		}
	});
	return marks;
}

function rowContent(
	config: ChartConfig,
	fallbackLabel: string,
	totals?: Map<string, number>
): (points: readonly { datum: unknown; color: string }[]) => ChartTooltipContent {
	return (points) => {
		const point = points[0];
		if (!point) return { rows: [] };
		const d = point.datum as ChartRow;
		const label = str(d.series) || fallbackLabel;
		const value = num(d.y);
		let text = formatNumber(value, config);
		const total = totals?.get(str(d.x));
		if (total != null && total > 0) text += ` (${((value / total) * 100).toFixed(1)}%)`;
		return {
			title: str(d.x),
			rows: [{ label, value: text, color: point.color }]
		};
	};
}

function totalsByLabel(data: ChartRow[]): Map<string, number> {
	const totals = new Map<string, number>();
	for (const row of data) {
		const key = str(row.x);
		totals.set(key, (totals.get(key) ?? 0) + num(row.y));
	}
	return totals;
}

function colorRamp(min: number, max: number): ChartScaleInput<ChartKey> {
	const blues = [0, 1 / 6, 2 / 6, 0.5, 4 / 6, 5 / 6, 1].map((t) => interpolateBlues(t));
	return d3ScaleLinear<string>()
		.domain([min, max])
		.range(blues) as unknown as ChartScaleInput<ChartKey>;
}

/* ── bar ── */

function barDefinition(ctx: Ctx) {
	const { data, config, interaction } = ctx;
	const groupCol = readString(config, 'group_column');
	const hasGroup = Boolean(groupCol) && hasColumn(data, groupCol);
	const labels = [...new Set(data.map((r) => str(r.x)))];
	const groups = hasGroup ? groupOrder(data, groupCol, groupSort(config)) : [];
	const colors = seriesColors(config);
	const rows = hasGroup ? data.filter((r) => seriesVisible(interaction, str(r[groupCol]))) : data;
	const mode = stackMode(config);
	const normalized = hasGroup && mode === '100%';
	const stacked = hasGroup && mode !== 'grouped';
	const keyOf = (d: ChartRow) => `${hasGroup ? str(d[groupCol]) : ''}::${str(d.x)}`;
	const states = dimStates(keyOf, interaction.selectedKey);
	const color = hasGroup ? (d: ChartRow) => str(d[groupCol]) : undefined;

	const marks: AnyMark[] = [];
	let yScale: ChartScaleInput<number>;
	if (stacked) {
		yScale = stackedScaleInput(Math.max(0, ...totalsByLabel(data).values()), normalized);
		marks.push(
			barY(rows, {
				x: (d) => str(d.x),
				y: (d) => num(d.y),
				color,
				layout: normalized ? stackLayout({ offset: 'normalize' }) : stackLayout(),
				radius: 1,
				states
			}) as unknown as AnyMark
		);
	} else if (hasGroup) {
		yScale = yScaleInput([...data.map((r) => num(r.y)), ...overlayYValues(ctx)], config);
		marks.push(
			barY(rows, {
				x: (d) => str(d.x),
				y: (d) => num(d.y),
				color,
				layout: groupLayout({ padding: 0.05 }),
				radius: 2,
				states
			}) as unknown as AnyMark
		);
		if (groups.length <= 3) {
			for (const group of groups) {
				if (!seriesVisible(interaction, group)) continue;
				marks.push(
					text(
						rows.filter((r) => str(r[groupCol]) === group),
						{
							x: (d) => str(d.x),
							y: (d) => num(d.y),
							text: (d) => formatNumber(num(d.y), config),
							dy: -6,
							fill: FG_SECONDARY,
							fontSize: 9
						}
					) as unknown as AnyMark
				);
			}
		}
	} else {
		yScale = yScaleInput([...data.map((r) => num(r.y)), ...overlayYValues(ctx)], config);
		marks.push(
			barY(rows, {
				x: (d) => str(d.x),
				y: (d) => num(d.y),
				fill: colors[0],
				radius: 2,
				states
			}) as unknown as AnyMark
		);
		marks.push(
			text(rows, {
				x: (d) => str(d.x),
				y: (d) => num(d.y),
				text: (d) => formatNumber(num(d.y), config),
				dy: -6,
				fill: FG_SECONDARY,
				fontSize: 10
			}) as unknown as AnyMark
		);
	}

	marks.push(...verticalOverlays(ctx, 'band', indexOf(labels)));
	marks.push(...referenceMarks(ctx, { xCategoryLabels: labels }));

	const definition = defineChartDom(
		{
			marks,
			scales: {
				x: {
					scale: () => scaleBand<string>().domain(labels).padding(0.2),
					axis: { label: xAxisTitle(config), ...categoryAxis(config, labels, true) }
				},
				y: {
					scale: yScale,
					nice: true,
					grid: true,
					axis: { label: yAxisTitle(config, 'bar'), ...numberAxis(config, 5) }
				},
				...rightScaleOption(ctx, 'y')
			},
			...(hasGroup ? { color: { domain: groups, range: colors } } : {}),
			theme: CHART_THEME,
			clip: true
		},
		{
			tooltip: {
				use: tooltip,
				content: rowContent(
					config,
					yAxisTitle(config, 'bar'),
					normalized ? totalsByLabel(data) : undefined
				)
			},
			...(configSelectionEnabled(config) ? selectionOption(keyOf, ctx) : {})
		}
	);

	return { definition, seriesLabels: groups };
}

/* ── horizontal bar ── */

function horizontalBarDefinition(ctx: Ctx) {
	const { data, config, interaction } = ctx;
	const groupCol = readString(config, 'group_column');
	const hasGroup = Boolean(groupCol) && hasColumn(data, groupCol);
	const labels = [...new Set(data.map((r) => str(r.x)))];
	const groups = hasGroup ? groupOrder(data, groupCol, groupSort(config)) : [];
	const colors = seriesColors(config);
	const rows = hasGroup ? data.filter((r) => seriesVisible(interaction, str(r[groupCol]))) : data;
	const mode = stackMode(config);
	const normalized = hasGroup && mode === '100%';
	const stacked = hasGroup && mode !== 'grouped';
	const keyOf = (d: ChartRow) => `${hasGroup ? str(d[groupCol]) : ''}::${str(d.x)}`;
	const states = dimStates(keyOf, interaction.selectedKey);
	const color = hasGroup ? (d: ChartRow) => str(d[groupCol]) : undefined;

	const marks: AnyMark[] = [];
	let xScale: ChartScaleInput<number>;
	if (stacked) {
		xScale = stackedScaleInput(Math.max(0, ...totalsByLabel(data).values()), normalized);
		marks.push(
			barX(rows, {
				x: (d) => num(d.y),
				y: (d) => str(d.x),
				color,
				layout: normalized ? stackLayout({ offset: 'normalize' }) : stackLayout(),
				radius: 1,
				states
			}) as unknown as AnyMark
		);
	} else if (hasGroup) {
		xScale = yScaleInput([...data.map((r) => num(r.y)), ...overlayYValues(ctx)], config);
		marks.push(
			barX(rows, {
				x: (d) => num(d.y),
				y: (d) => str(d.x),
				color,
				layout: groupLayout({ padding: 0.05 }),
				radius: 2,
				states
			}) as unknown as AnyMark
		);
	} else {
		xScale = yScaleInput([...data.map((r) => num(r.y)), ...overlayYValues(ctx)], config);
		marks.push(
			barX(rows, {
				x: (d) => num(d.y),
				y: (d) => str(d.x),
				fill: colors[0],
				radius: 2,
				states
			}) as unknown as AnyMark
		);
		marks.push(
			text(rows, {
				x: (d) => num(d.y),
				y: (d) => str(d.x),
				text: (d) => formatNumber(num(d.y), config),
				dx: 6,
				anchor: 'start',
				fill: FG_SECONDARY,
				fontSize: 10
			}) as unknown as AnyMark
		);
	}

	marks.push(...horizontalOverlays(ctx));
	marks.push(...referenceMarks(ctx, { yCategoryLabels: labels }));

	const definition = defineChartDom(
		{
			marks,
			scales: {
				x: {
					scale: xScale,
					nice: true,
					grid: true,
					axis: { label: yAxisTitle(config, 'horizontal_bar'), ...numberAxis(config, 5) }
				},
				y: {
					scale: () => scaleBand<string>().domain(labels).padding(0.2),
					axis: { label: xAxisTitle(config), ...categoryAxis(config, labels, false) }
				},
				...rightScaleOption(ctx, 'x')
			},
			...(hasGroup ? { color: { domain: groups, range: colors } } : {}),
			margin: { left: categoryLeftMargin(labels) },
			theme: CHART_THEME,
			clip: true
		},
		{
			tooltip: {
				use: tooltip,
				content: rowContent(
					config,
					yAxisTitle(config, 'horizontal_bar'),
					normalized ? totalsByLabel(data) : undefined
				)
			},
			...(configSelectionEnabled(config) ? selectionOption(keyOf, ctx) : {})
		}
	);

	return { definition, seriesLabels: groups };
}

/* ── area ── */

function areaDefinition(ctx: Ctx) {
	const { data, config, interaction } = ctx;
	const groupCol = readString(config, 'group_column');
	const hasGroup = Boolean(groupCol) && hasColumn(data, groupCol);
	const labels = [...new Set(data.map((r) => str(r.x)))];
	const groups = hasGroup ? groupOrder(data, groupCol, groupSort(config)) : [];
	const colors = seriesColors(config);
	const rows = hasGroup ? data.filter((r) => seriesVisible(interaction, str(r[groupCol]))) : data;
	const mode = stackMode(config);
	const normalized = hasGroup && mode === '100%';
	const stacked = hasGroup && mode !== 'grouped';
	const n = Math.max(1, labels.length);
	const xDomain: [number, number] = [-0.5, n - 0.5];
	const x = (d: ChartRow) => labels.indexOf(str(d.x));
	const color = hasGroup ? (d: ChartRow) => str(d[groupCol]) : undefined;

	const marks: AnyMark[] = [];
	let yScale: ChartScaleInput<number>;
	if (stacked) {
		yScale = stackedScaleInput(Math.max(0, ...totalsByLabel(data).values()), normalized);
		marks.push(
			areaY(rows, {
				x,
				y: (d) => num(d.y),
				color,
				layout: normalized ? stackLayout({ offset: 'normalize' }) : stackLayout(),
				fillOpacity: areaOpacity(config),
				curve: d3Curve(curveMonotoneX)
			}) as unknown as AnyMark
		);
	} else if (hasGroup) {
		yScale = yScaleInput([...data.map((r) => num(r.y)), ...overlayYValues(ctx)], config);
		marks.push(
			areaY(rows, {
				x,
				y1: () => 0,
				y2: (d) => num(d.y),
				color,
				fillOpacity: areaOpacity(config),
				curve: d3Curve(curveMonotoneX)
			}) as unknown as AnyMark
		);
	} else {
		yScale = yScaleInput([...data.map((r) => num(r.y)), ...overlayYValues(ctx)], config);
		marks.push(
			areaY(rows, {
				x,
				y1: () => 0,
				y2: (d) => num(d.y),
				fill: colors[0],
				fillOpacity: areaOpacity(config),
				curve: d3Curve(curveMonotoneX)
			}) as unknown as AnyMark
		);
	}

	marks.push(...verticalOverlays(ctx, 'index', indexOf(labels)));
	marks.push(...referenceMarks(ctx, { xMax: n - 1 }));

	const definition = defineChartDom(
		{
			marks,
			scales: {
				x: {
					scale: scaleLinear().domain(xDomain),
					axis: {
						label: xAxisTitle(config),
						ticks: {
							values: indexTickValues(n, xDomain),
							format: (v: number) => formatTimeTick(labels[Math.round(v)] ?? '', config)
						},
						tickLabels: { rotate: needsRotatedTicks(labels) ? -35 : undefined }
					}
				},
				y: {
					scale: yScale,
					nice: true,
					grid: true,
					axis: { label: yAxisTitle(config, 'area'), ...numberAxis(config, 5) }
				},
				...rightScaleOption(ctx, 'y')
			},
			...(hasGroup ? { color: { domain: groups, range: colors } } : {}),
			theme: CHART_THEME,
			clip: true
		},
		{
			tooltip: {
				use: tooltip,
				content: rowContent(
					config,
					yAxisTitle(config, 'area'),
					normalized ? totalsByLabel(data) : undefined
				)
			}
		}
	);

	return { definition, seriesLabels: groups };
}

/* ── line ── */

function lineDefinition(ctx: Ctx) {
	const { data, config, interaction } = ctx;
	const groupCol = readString(config, 'group_column');
	const hasGroup = Boolean(groupCol) && hasColumn(data, groupCol);
	const labels = [...new Set(data.map((r) => str(r.x)))];
	const groups = hasGroup ? groupOrder(data, groupCol, groupSort(config)) : [];
	const colors = seriesColors(config);
	const rows = hasGroup ? data.filter((r) => seriesVisible(interaction, str(r[groupCol]))) : data;
	const keyOf = (d: ChartRow) => `${hasGroup ? str(d[groupCol]) : ''}::${str(d.x)}`;
	const states = dimStates(keyOf, interaction.selectedKey);
	const n = Math.max(1, labels.length);
	const zoomExtent: [number, number] = [0, n - 1];
	const zoomActive = configZoomEnabled(config) && isZoomActive(interaction, zoomExtent);
	const xDomain: [number, number] = zoomActive ? interaction.zoomWindow! : zoomExtent;
	const x = (d: ChartRow) => labels.indexOf(str(d.x));
	const color = hasGroup ? (d: ChartRow) => str(d[groupCol]) : undefined;

	const marks: AnyMark[] = [];
	if (hasGroup) {
		marks.push(
			areaY(rows, {
				x,
				y1: () => 0,
				y2: (d) => num(d.y),
				color,
				fillOpacity: 0.08,
				curve: d3Curve(curveMonotoneX)
			}) as unknown as AnyMark
		);
		marks.push(
			lineY(rows, {
				x,
				y: (d) => num(d.y),
				color,
				strokeWidth: 2,
				curve: d3Curve(curveMonotoneX)
			}) as unknown as AnyMark
		);
	} else {
		marks.push(
			areaY(rows, {
				x,
				y1: () => 0,
				y2: (d) => num(d.y),
				fill: colors[0],
				fillOpacity: 0.08,
				curve: d3Curve(curveMonotoneX)
			}) as unknown as AnyMark
		);
		marks.push(
			lineY(rows, {
				x,
				y: (d) => num(d.y),
				stroke: colors[0],
				strokeWidth: 2,
				curve: d3Curve(curveMonotoneX)
			}) as unknown as AnyMark
		);
	}
	marks.push(
		dot(rows, {
			x,
			y: (d) => num(d.y),
			...(hasGroup ? { color } : { fill: colors[0] }),
			r: 3.5,
			stroke: 'var(--colors-bg-primary)',
			strokeWidth: 1.5,
			key: keyOf,
			states
		}) as unknown as AnyMark
	);

	marks.push(...verticalOverlays(ctx, 'index', indexOf(labels)));
	marks.push(...referenceMarks(ctx, { xMax: n - 1 }));

	const definition = defineChartDom(
		{
			marks,
			scales: {
				x: {
					scale: scaleLinear().domain(xDomain),
					axis: {
						label: xAxisTitle(config),
						ticks: {
							values: indexTickValues(n, xDomain),
							format: (v: number) => formatTimeTick(labels[Math.round(v)] ?? '', config)
						}
					}
				},
				y: {
					scale: yScaleInput([...data.map((r) => num(r.y)), ...overlayYValues(ctx)], config),
					nice: true,
					grid: true,
					axis: { label: yAxisTitle(config, 'line'), ...numberAxis(config, 5) }
				},
				...rightScaleOption(ctx, 'y')
			},
			...(hasGroup ? { color: { domain: groups, range: colors } } : {}),
			theme: CHART_THEME,
			clip: true
		},
		{
			tooltip: { use: tooltip, content: rowContent(config, yAxisTitle(config, 'line')) },
			...(configSelectionEnabled(config) ? selectionOption(keyOf, ctx) : {}),
			...(configZoomEnabled(config) && n > 1 ? zoomOption(zoomExtent, ctx) : {})
		}
	);

	return { definition, seriesLabels: groups, zoomExtent };
}

/* ── heatgrid ── */

function heatgridDefinition(ctx: Ctx) {
	const { data, config } = ctx;
	const xLabels = [...new Set(data.map((r) => str(r.x)))];
	const yLabels = [...new Set(data.map((r) => str(r.y)))];
	const values = data.map((r) => num(r.value));
	const min = values.length ? Math.min(...values) : 0;
	const max = values.length ? Math.max(...values) : 1;

	const definition = defineChartDom(
		{
			marks: [
				cell(data, {
					x: (d) => str(d.x),
					y: (d) => str(d.y),
					color: (d) => num(d.value),
					key: (d) => `${str(d.x)}|${str(d.y)}`,
					stroke: 'var(--colors-border-primary)'
				}) as unknown as AnyMark
			],
			scales: {
				x: {
					scale: () => scaleBand<string>().domain(xLabels).padding(0.08),
					axis: { label: xAxisTitle(config), ...categoryAxis(config, xLabels, true) }
				},
				y: {
					scale: () => scaleBand<string>().domain(yLabels).padding(0.08),
					axis: { label: yAxisTitle(config, 'heatgrid') }
				}
			},
			color: {
				scale: colorRamp(min, max === min ? min + 1 : max),
				legend: colorGradientLegend({ steps: 6 })
			},
			margin: { left: categoryLeftMargin(yLabels) },
			theme: CHART_THEME,
			clip: true
		},
		{
			tooltip: {
				use: tooltip,
				content: (points: readonly { datum: unknown; color: string }[]) => {
					const point = points[0];
					if (!point) return { rows: [] };
					const d = point.datum as ChartRow;
					return {
						title: str(d.x),
						rows: [
							{ label: str(d.y), value: formatNumber(num(d.value), config), color: point.color }
						]
					};
				}
			}
		}
	);

	return { definition, seriesLabels: [] };
}

/* ── histogram ── */

function histogramDefinition(ctx: Ctx) {
	const { data, config } = ctx;
	const colors = seriesColors(config);
	const starts = data.map((r) => num(r.bin_start));
	const ends = data.map((r) => num(r.bin_end));
	const xMin = starts.length ? Math.min(...starts) : 0;
	const xMax = ends.length ? Math.max(...ends) : 1;

	const definition = defineChartDom(
		{
			marks: [
				rect(data, {
					x1: (d) => num(d.bin_start),
					x2: (d) => num(d.bin_end),
					y1: () => 0,
					y2: (d) => num(d.count),
					fill: colors[0],
					radius: 1
				}) as unknown as AnyMark
			],
			scales: {
				x: {
					scale: scaleLinear().domain([xMin, xMax]),
					axis: { label: xAxisTitle(config), ...numberAxis(config, 6) }
				},
				y: {
					scale: scaleLinear,
					nice: true,
					grid: true,
					axis: { label: yAxisTitle(config, 'histogram'), ...numberAxis(config, 5) }
				}
			},
			theme: CHART_THEME,
			clip: true
		},
		{
			tooltip: {
				use: tooltip,
				content: (points: readonly { datum: unknown; color: string }[]) => {
					const point = points[0];
					if (!point) return { rows: [] };
					const d = point.datum as ChartRow;
					return {
						title: `${formatNumber(num(d.bin_start), config)} – ${formatNumber(num(d.bin_end), config)}`,
						rows: [
							{ label: 'Count', value: formatNumber(num(d.count), config), color: point.color }
						]
					};
				}
			}
		}
	);

	return { definition, seriesLabels: [] };
}

/* ── scatter ── */

function scatterDefinition(ctx: Ctx) {
	const { data, config, interaction } = ctx;
	const hasGroup = hasColumn(data, 'group');
	const groups = hasGroup ? groupOrder(data, 'group', groupSort(config)) : [];
	const colors = seriesColors(config);
	const rows = hasGroup ? data.filter((r) => seriesVisible(interaction, str(r.group))) : data;
	const keyOf = (d: ChartRow) => `${str(d.group ?? '')}::${num(d.x)}::${num(d.y)}`;
	const states = dimStates(keyOf, interaction.selectedKey);
	const color = hasGroup ? (d: ChartRow) => str(d.group) : undefined;
	const xValues = data.map((r) => num(r.x));
	const xExtent: [number, number] = [
		xValues.length ? Math.min(...xValues) : 0,
		xValues.length ? Math.max(...xValues) : 1
	];
	const zoomActive =
		configZoomEnabled(config) &&
		!configAreaSelectEnabled(config) &&
		isZoomActive(interaction, xExtent);
	const xDomain: [number, number] = zoomActive ? interaction.zoomWindow! : xExtent;
	const half = (xDomain[1] - xDomain[0] || 1) * 0.01;

	const marks: AnyMark[] = [
		dot(rows, {
			x: (d) => num(d.x),
			y: (d) => num(d.y),
			...(hasGroup ? { color } : { fill: colors[0] }),
			r: 3,
			fillOpacity: 0.7,
			key: keyOf,
			states
		}) as unknown as AnyMark
	];

	const overlays = overlayMarksOf(ctx.metadata);
	overlays.forEach((overlay, index) => {
		const overlayRows = overlayData(overlay);
		if (overlayRows.length === 0) return;
		const scaleId = overlayOnRight(overlay) ? 'right' : undefined;
		const overlayColor = colors[index % colors.length];
		const type = overlayChartType(overlay);
		const right = scaleId ? { yScale: scaleId } : {};
		if (type === 'scatter') {
			marks.push(
				dot(overlayRows, {
					x: (d) => num(d.x),
					y: (d) => num(d.y),
					fill: overlayColor,
					r: 3.5,
					fillOpacity: 0.85,
					...right
				}) as unknown as AnyMark
			);
			return;
		}
		if (type === 'bar') {
			marks.push(
				rect(overlayRows, {
					x1: (d) => num(d.x) - half,
					x2: (d) => num(d.x) + half,
					y1: () => 0,
					y2: (d) => num(d.y),
					fill: overlayColor,
					fillOpacity: 0.25,
					...right
				}) as unknown as AnyMark
			);
			return;
		}
		const sorted = [...overlayRows].sort((a, b) => num(a.x) - num(b.x));
		marks.push(
			lineY(sorted, {
				x: (d) => num(d.x),
				y: (d) => num(d.y),
				stroke: overlayColor,
				strokeWidth: 2,
				curve: d3Curve(curveMonotoneX),
				...right
			}) as unknown as AnyMark
		);
		if (type === 'area') {
			marks.push(
				areaY(sorted, {
					x: (d) => num(d.x),
					y: (d) => num(d.y),
					fill: overlayColor,
					fillOpacity: areaOpacity(config),
					curve: d3Curve(curveMonotoneX),
					...right
				}) as unknown as AnyMark
			);
		}
	});
	marks.push(...referenceMarks(ctx, { xMax: xExtent[1] }));

	const definition = defineChartDom(
		{
			marks,
			scales: {
				x: {
					scale: scaleLinear().domain(xDomain),
					nice: !zoomActive,
					grid: true,
					axis: { label: xAxisTitle(config), ...numberAxis(config, 6) }
				},
				y: {
					scale: yScaleInput([...data.map((r) => num(r.y)), ...overlayYValues(ctx)], config),
					nice: true,
					grid: true,
					axis: { label: yAxisTitle(config, 'scatter'), ...numberAxis(config, 5) }
				},
				...(overlays.some(overlayOnRight) ? rightScaleOption(ctx, 'y') : {})
			},
			...(hasGroup ? { color: { domain: groups, range: colors } } : {}),
			theme: CHART_THEME,
			clip: true
		},
		{
			tooltip: {
				use: tooltip,
				content: (points: readonly { datum: unknown; color: string }[]) => {
					const point = points[0];
					if (!point) return { rows: [] };
					const d = point.datum as ChartRow;
					const series = str(d.series);
					if (series) {
						return {
							title: series,
							rows: [
								{
									label: yAxisTitle(config, 'scatter'),
									value: formatNumber(num(d.y), config),
									color: point.color
								}
							]
						};
					}
					return {
						title: str(d.group),
						rows: [
							{
								label: xAxisTitle(config),
								value: formatNumber(num(d.x), config),
								color: point.color
							},
							{
								label: yAxisTitle(config, 'scatter'),
								value: formatNumber(num(d.y), config),
								color: point.color
							}
						]
					};
				}
			},
			...(configSelectionEnabled(config) ? selectionOption(keyOf, ctx) : {}),
			...(configAreaSelectEnabled(config)
				? brushOption(
						[...new Set(xValues)].sort((a, b) => a - b),
						ctx
					)
				: configZoomEnabled(config)
					? zoomOption(xExtent, ctx)
					: {})
		}
	);

	return { definition, seriesLabels: groups, zoomExtent: xExtent };
}

/* ── boxplot ── */

function boxplotDefinition(ctx: Ctx) {
	const { data, config } = ctx;
	const colors = seriesColors(config);
	const categories = [...new Set(data.map((r) => str(r.group)))];
	const expanded: ChartRow[] = [];
	for (const row of data) {
		for (const stat of ['min', 'q1', 'median', 'q3', 'max']) {
			expanded.push({ group: str(row.group), value: num(row[stat]) });
		}
	}

	const definition = defineChartDom(
		{
			marks: [
				boxX(expanded, {
					y: (d) => str(d.group),
					x: (d) => num(d.value),
					fill: colors[0],
					fillOpacity: 0.2,
					stroke: colors[0],
					strokeWidth: 1.5
				}) as unknown as AnyMark
			],
			scales: {
				x: {
					scale: scaleLinear,
					nice: true,
					grid: true,
					axis: { label: yAxisTitle(config, 'boxplot'), ...numberAxis(config, 6) }
				},
				y: {
					scale: () => scaleBand<string>().domain(categories).padding(0.3),
					axis: { label: '' }
				}
			},
			margin: { left: categoryLeftMargin(categories) },
			theme: CHART_THEME,
			clip: true
		},
		{
			tooltip: {
				use: tooltip,
				content: (points: readonly { datum: unknown; color: string }[]) => {
					const point = points[0];
					if (!point) return { rows: [] };
					const d = point.datum as {
						kind: string;
						category: string;
						value?: number;
						q1?: number;
						median?: number;
						q3?: number;
						whiskerLow?: number;
						whiskerHigh?: number;
					};
					if (d.kind === 'outlier') {
						return {
							title: d.category,
							rows: [
								{
									label: 'Outlier',
									value: formatNumber(d.value ?? 0, config),
									color: point.color
								}
							]
						};
					}
					return {
						title: d.category,
						rows: [
							{ label: 'Min', value: formatNumber(d.whiskerLow ?? 0, config), color: point.color },
							{ label: 'Q1', value: formatNumber(d.q1 ?? 0, config), color: point.color },
							{ label: 'Median', value: formatNumber(d.median ?? 0, config), color: point.color },
							{ label: 'Q3', value: formatNumber(d.q3 ?? 0, config), color: point.color },
							{ label: 'Max', value: formatNumber(d.whiskerHigh ?? 0, config), color: point.color }
						]
					};
				}
			}
		}
	);

	return { definition, seriesLabels: [] };
}

/* ── pie ── */

function piePanes(ctx: Ctx): ChartPane[] {
	const { data, config } = ctx;
	const colors = seriesColors(config);
	const hasGroup = hasColumn(data, 'group');
	const groups = hasGroup ? groupOrder(data, 'group', groupSort(config)) : [''];
	const labelDomain = [
		...new Set(data.map((r) => str(r.label)).filter((label) => label.length > 0))
	];

	return groups.map((group) => {
		const rows = hasGroup ? data.filter((r) => str(r.group) === group) : data;
		const slices = pieSlices(rows, { value: (d) => num(d.y) });
		const definition = defineChartDom(
			{
				marks: [
					polar({
						scales: {
							angle: { scale: scaleLinear },
							radius: {
								scale: scaleLinear().domain([0, 1]),
								range: [0, (layout) => layout.radius]
							}
						},
						marks: [
							radialArc(slices, {
								startAngle: (d) => d.startAngle,
								endAngle: (d) => d.endAngle,
								color: (d) => str(d.label),
								key: (d) => str(d.label),
								innerRadius: (layout) => layout.radius * 0.4,
								stroke: 'var(--colors-bg-primary)',
								strokeWidth: 2
							}),
							radialText(
								slices.filter((slice) => slice.fraction > 0.08),
								{
									angle: (d) => d.angle,
									radius: () => 0.65,
									text: (d) => `${truncateLabel(str(d.label), 8)} ${Math.round(d.fraction * 100)}%`,
									fill: 'var(--colors-fg-primary)',
									fontSize: 10,
									anchor: 'middle'
								}
							)
						]
					})
				],
				scales: { x: null, y: null },
				color: { domain: labelDomain, range: colors },
				theme: CHART_THEME
			},
			{
				tooltip: {
					use: tooltip,
					content: (points: readonly { datum: unknown; color: string }[]) => {
						const point = points[0];
						if (!point) return { rows: [] };
						const d = point.datum as ChartRow & { value: number; fraction: number };
						return {
							title: str(d.label),
							rows: [
								{
									value: `${formatNumber(d.value, config)} (${(d.fraction * 100).toFixed(1)}%)`,
									color: point.color
								}
							]
						};
					}
				}
			}
		);
		return { key: group || 'all', label: hasGroup ? group || 'Group' : '', definition };
	});
}

/* ── misc ── */

function configSelectionEnabled(config: ChartConfig): boolean {
	return Boolean(config.selection_enabled);
}

function configZoomEnabled(config: ChartConfig): boolean {
	return Boolean(config.pan_zoom_enabled);
}

function configAreaSelectEnabled(config: ChartConfig): boolean {
	return Boolean(config.area_selection_enabled);
}

function isZoomActive(interaction: ChartInteraction, extent: [number, number]): boolean {
	const windowValue = interaction.zoomWindow;
	if (!windowValue) return false;
	return windowValue[0] !== extent[0] || windowValue[1] !== extent[1];
}

function indexTickValues(count: number, domain: [number, number]): number[] {
	const step = Math.max(1, Math.ceil(count / 12));
	const values: number[] = [];
	const start = Math.ceil(domain[0]);
	const end = Math.floor(domain[1]);
	for (let i = start; i <= end; i += step) values.push(i);
	return values;
}

function indexOf(labels: string[]): (label: string) => number {
	return (label) => labels.indexOf(label);
}

function categoryLeftMargin(labels: string[]): number {
	const maxLen = Math.max(0, ...labels.map((label) => label.length));
	return Math.min(32 + Math.round(maxLen * 7.2), 280);
}
