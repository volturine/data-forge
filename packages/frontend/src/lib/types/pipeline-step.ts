import type { ChartType, ProtocolPipelineStepType } from '$lib/types/protocol-enum-tokens';
import { STEP_TYPE_TOKENS } from '$lib/types/protocol-enum-tokens';

export type { ChartType };

export type PlotAliasStepType = Extract<ProtocolPipelineStepType, `plot_${string}`>;
export type CanonicalStepType = Exclude<ProtocolPipelineStepType, PlotAliasStepType>;

export type KnownPipelineStepType = CanonicalStepType | PlotAliasStepType;
export type PipelineStepType = KnownPipelineStepType | (string & {});

export const KNOWN_PIPELINE_STEP_TYPES = Object.values(STEP_TYPE_TOKENS) as KnownPipelineStepType[];
export const CANONICAL_STEP_TYPES = KNOWN_PIPELINE_STEP_TYPES.filter(
	(stepType): stepType is CanonicalStepType => !stepType.startsWith('plot_')
);

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
