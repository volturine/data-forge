import { describe, expect, it } from 'vitest';
import type { AnalysisTab } from '$lib/types/analysis';
import type { DataSource } from '$lib/types/datasource';
import { buildAnalysisPipelinePayload, buildDatasourceConfig } from '$lib/utils/analysis-pipeline';

const makeTab = (overrides: Partial<AnalysisTab> = {}): AnalysisTab => ({
	id: 'tab-1',
	name: 'Tab 1',
	type: 'datasource',
	steps: [],
	datasource_id: 'ds-1',
	parent_id: null,
	datasource_config: {},
	...overrides
});

const makeDatasource = (overrides: Partial<DataSource> = {}): DataSource => ({
	id: 'ds-1',
	name: 'Source',
	source_type: 'file',
	config: { file_path: '/tmp/data.csv', file_type: 'csv' },
	schema_cache: null,
	created_by_analysis_id: null,
	created_by: 'import',
	is_hidden: false,
	created_at: '2024-01-01T00:00:00.000Z',
	output_of_tab_id: null,
	...overrides
});

describe('analysis-pipeline', () => {
	it('buildAnalysisPipelinePayload returns sources and steps', () => {
		const tabs = [
			makeTab({
				steps: [{ id: 'step-1', type: 'select', config: { columns: ['name'] }, depends_on: [] }]
			})
		];
		const datasources = [makeDatasource()];
		const payload = buildAnalysisPipelinePayload('analysis-1', tabs, datasources);

		expect(payload?.analysis_id).toBe('analysis-1');
		expect(payload?.tabs[0].steps).toHaveLength(1);
		expect(Object.keys(payload?.sources ?? {})).toEqual(['ds-1']);
	});

	it('buildDatasourceConfig injects analysis pipeline for self-references', () => {
		const tabs = [makeTab()];
		const datasources = [
			makeDatasource({
				config: { analysis_id: 'analysis-1', file_path: '/tmp/data.csv', file_type: 'csv' }
			})
		];
		const config = buildDatasourceConfig({
			analysisId: 'analysis-1',
			tab: tabs[0],
			tabs,
			datasources
		});

		expect(config?.analysis_pipeline).toBeDefined();
	});
});
