import type { ChartConfig } from '$lib/types/step-schemas.generated';

export type ChartType = NonNullable<ChartConfig['chart_type']>;

export type CanonicalStepType =
	| 'select'
	| 'drop'
	| 'filter'
	| 'groupby'
	| 'join'
	| 'union_by_name'
	| 'unpivot'
	| 'explode'
	| 'pivot'
	| 'sample'
	| 'limit'
	| 'topk'
	| 'view'
	| 'export'
	| 'download'
	| 'chart'
	| 'notification'
	| 'ai'
	| 'datasource'
	| 'sort'
	| 'rename'
	| 'expression'
	| 'with_columns'
	| 'fill_null'
	| 'deduplicate'
	| 'string_transform'
	| 'timeseries';

export type PlotAliasStepType =
	| 'plot_bar'
	| 'plot_horizontal_bar'
	| 'plot_area'
	| 'plot_heatgrid'
	| 'plot_histogram'
	| 'plot_scatter'
	| 'plot_line'
	| 'plot_pie'
	| 'plot_boxplot';

export type KnownPipelineStepType = CanonicalStepType | PlotAliasStepType;
export type PipelineStepType = KnownPipelineStepType | (string & {});

export const CHART_ALIAS_TO_TYPE = {
	plot_bar: 'bar',
	plot_horizontal_bar: 'horizontal_bar',
	plot_area: 'area',
	plot_heatgrid: 'heatgrid',
	plot_histogram: 'histogram',
	plot_scatter: 'scatter',
	plot_line: 'line',
	plot_pie: 'pie',
	plot_boxplot: 'boxplot'
} as const satisfies Record<PlotAliasStepType, ChartType>;

export function isPlotAliasStepType(stepType: string): stepType is PlotAliasStepType {
	return stepType in CHART_ALIAS_TO_TYPE;
}

export function chartTypeForStep(stepType: string): ChartType | null {
	if (!isPlotAliasStepType(stepType)) return null;
	return CHART_ALIAS_TO_TYPE[stepType];
}

export function isChartStepType(stepType: string): stepType is 'chart' | PlotAliasStepType {
	return stepType === 'chart' || isPlotAliasStepType(stepType);
}

export function normalizePipelineStepType(stepType: string): string {
	return isPlotAliasStepType(stepType) ? 'chart' : stepType;
}
