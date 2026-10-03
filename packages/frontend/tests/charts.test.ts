import { test, expect } from './fixtures.js';
import { createImportedAnalysis } from './utils/api.js';
import { gotoAnalysisEditor } from './utils/analysis.js';
import { deleteAnalysisViaUI } from './utils/ui-cleanup.js';
import { readyTimeoutMs, waitForChartPreviewReady } from './utils/readiness.js';
import { uid } from './utils/uid.js';
import { screenshot } from './utils/visual.js';

interface ChartStepConfig {
	chart_type: string;
	x_column: string;
	y_column?: string;
	aggregation?: string;
	group_column?: string | null;
	stack_mode?: string;
	bins?: number;
	pan_zoom_enabled?: boolean;
}

function chartSpecs(): Array<{ chart_type: string; config: ChartStepConfig }> {
	return [
		{
			chart_type: 'bar',
			config: {
				chart_type: 'bar',
				x_column: 'city',
				y_column: 'value',
				aggregation: 'sum',
				group_column: 'category',
				stack_mode: '100%'
			}
		},
		{
			chart_type: 'horizontal_bar',
			config: {
				chart_type: 'horizontal_bar',
				x_column: 'city',
				y_column: 'value',
				aggregation: 'sum',
				group_column: 'category'
			}
		},
		{
			chart_type: 'line',
			config: {
				chart_type: 'line',
				x_column: 'month',
				y_column: 'value',
				aggregation: 'sum',
				group_column: 'category',
				pan_zoom_enabled: true
			}
		},
		{
			chart_type: 'area',
			config: {
				chart_type: 'area',
				x_column: 'month',
				y_column: 'value',
				aggregation: 'sum',
				group_column: 'category',
				stack_mode: 'stacked'
			}
		},
		{
			chart_type: 'scatter',
			config: { chart_type: 'scatter', x_column: 'score', y_column: 'value' }
		},
		{
			chart_type: 'pie',
			config: { chart_type: 'pie', x_column: 'city', y_column: 'value', aggregation: 'sum' }
		},
		{
			chart_type: 'histogram',
			config: { chart_type: 'histogram', x_column: 'value', bins: 4 }
		},
		{
			chart_type: 'heatgrid',
			config: {
				chart_type: 'heatgrid',
				x_column: 'city',
				y_column: 'category',
				aggregation: 'count'
			}
		},
		{
			chart_type: 'boxplot',
			config: { chart_type: 'boxplot', x_column: 'city', y_column: 'value' }
		}
	];
}

test.describe('Charts – chart types render', () => {
	for (const spec of chartSpecs()) {
		test(`chart_type "${spec.chart_type}" renders an svg`, async ({
			page,
			request,
			sharedChartDatasource
		}, testInfo) => {
			if (spec.chart_type === 'heatgrid') {
				// This chart's cold engine preview can exceed the suite-wide 120s
				// deadline under 3×4 load; readiness still fails explicitly at 150s.
				testInfo.setTimeout(180_000);
			}
			const analysisName = `E2E Chart ${spec.chart_type} ${uid()}`;
			const stepId = crypto.randomUUID();
			const tabId = crypto.randomUUID();
			const resultId = crypto.randomUUID();
			const datasourceRef = `source-${crypto.randomUUID()}`;
			const aId = await createImportedAnalysis(
				request,
				analysisName,
				{
					tabs: [
						{
							id: tabId,
							name: 'Source 1',
							parent_id: null,
							datasource: {
								id: datasourceRef,
								analysis_tab_id: null,
								config: { branch: 'master' }
							},
							output: {
								result_id: resultId,
								datasource_type: 'iceberg',
								format: 'parquet',
								filename: 'source_1',
								build_mode: 'full',
								iceberg: {
									namespace: 'outputs',
									table_name: 'source_1',
									branch: 'master'
								}
							},
							steps: [
								{
									id: stepId,
									type: 'chart',
									config: spec.config,
									depends_on: [],
									is_applied: true
								}
							]
						}
					]
				},
				{ [datasourceRef]: sharedChartDatasource.id }
			);
			try {
				await gotoAnalysisEditor(page, aId);
				await waitForChartPreviewReady(page, spec.chart_type === 'heatgrid' ? 150_000 : undefined);
				const chart = page.locator('[data-testid="chart-preview"]');
				await expect(chart.locator('svg').first()).toBeVisible({ timeout: readyTimeoutMs() });
				if (spec.chart_type === 'bar') {
					const svg = chart.locator('svg').first();
					const box = await svg.boundingBox();
					await svg.hover({
						position: { x: (box?.width ?? 400) / 2, y: (box?.height ?? 300) / 2 }
					});
					await expect(chart.locator('.ts-chart-tooltip')).toBeVisible({ timeout: 5_000 });
				}
				await screenshot(page, 'charts', spec.chart_type);
			} finally {
				await deleteAnalysisViaUI(page, analysisName);
			}
		});
	}
});
