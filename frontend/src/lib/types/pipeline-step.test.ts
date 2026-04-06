import { describe, expect, test } from 'vitest';
import {
	chartTypeForStep,
	isChartStepType,
	isPlotAliasStepType,
	normalizePipelineStepType
} from './pipeline-step';

describe('pipeline-step helpers', () => {
	test('recognizes plot aliases explicitly', () => {
		expect(isPlotAliasStepType('plot_scatter')).toBe(true);
		expect(isPlotAliasStepType('chart')).toBe(false);
		expect(chartTypeForStep('plot_scatter')).toBe('scatter');
		expect(chartTypeForStep('chart')).toBeNull();
	});

	test('normalizes plot aliases only', () => {
		expect(isChartStepType('chart')).toBe(true);
		expect(isChartStepType('plot_bar')).toBe(true);
		expect(isChartStepType('filter')).toBe(false);
		expect(normalizePipelineStepType('plot_bar')).toBe('chart');
		expect(normalizePipelineStepType('filter')).toBe('filter');
	});
});
