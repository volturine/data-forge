import { describe, test, expect } from 'vitest';
import type { AnalysisTab } from '$lib/types/analysis';
import type { DataSource } from '$lib/types/datasource';
import {
	buildAnalysisPipelinePayload,
	buildDatasourceConfig,
	buildDatasourcePipelinePayload,
	normalizeSnapshotConfig
} from './analysis-pipeline';

function tab(overrides: Partial<AnalysisTab> = {}): AnalysisTab {
	return {
		id: 'tab-1',
		name: 'Tab 1',
		parent_id: null,
		datasource: {
			id: 'ds-1',
			analysis_tab_id: null,
			config: { branch: 'main' }
		},
		output: {
			result_id: 'out-1',
			format: 'parquet',
			filename: 'output',
			build_mode: 'full'
		},
		steps: [],
		...overrides
	};
}

function datasource(overrides: Partial<DataSource> = {}): DataSource {
	return {
		id: 'ds-1',
		name: 'Test DS',
		source_type: 'file',
		config: { file_path: '/data/test.csv', file_type: 'csv' },
		schema_cache: null,
		created_by: 'user-1',
		is_hidden: false,
		created_at: '2024-01-01T00:00:00Z',
		...overrides
	} as DataSource;
}

// ── buildAnalysisPipelinePayload ────────────────────────────────────────────

describe('buildAnalysisPipelinePayload', () => {
	test('returns null for empty analysisId', () => {
		expect(buildAnalysisPipelinePayload('', [tab()], [datasource()])).toBeNull();
	});

	test('returns null for empty tabs', () => {
		expect(buildAnalysisPipelinePayload('a-1', [], [datasource()])).toBeNull();
	});

	test('builds payload for single tab with datasource', () => {
		const result = buildAnalysisPipelinePayload('a-1', [tab()], [datasource()]);
		expect(result).not.toBeNull();
		expect(result!.analysis_id).toBe('a-1');
		expect(result!.tabs).toHaveLength(1);
		expect(result!.tabs[0].id).toBe('tab-1');
		expect(result!.tabs[0].name).toBe('Tab 1');
		expect(result!.tabs[0].steps).toEqual([]);
	});

	test('creates analysis source entry for each tab output', () => {
		const result = buildAnalysisPipelinePayload('a-1', [tab()], [datasource()]);
		expect(result!.sources['out-1']).toEqual({
			source_type: 'analysis',
			analysis_id: 'a-1',
			analysis_tab_id: 'tab-1'
		});
	});

	test('includes datasource source entry', () => {
		const result = buildAnalysisPipelinePayload('a-1', [tab()], [datasource()]);
		expect(result!.sources['ds-1']).toEqual({
			source_type: 'file',
			file_path: '/data/test.csv',
			file_type: 'csv'
		});
	});

	test('returns null when tab has no output result_id', () => {
		const t = tab({ output: { result_id: '', format: 'parquet', filename: 'out' } });
		expect(buildAnalysisPipelinePayload('a-1', [t], [datasource()])).toBeNull();
	});

	test('returns null when datasource is missing from list', () => {
		const t = tab({
			datasource: { id: 'ds-missing', analysis_tab_id: null, config: { branch: 'main' } }
		});
		expect(buildAnalysisPipelinePayload('a-1', [t], [datasource()])).toBeNull();
	});

	test('handles multiple tabs', () => {
		const tabs = [
			tab({ id: 'tab-1', output: { result_id: 'out-1', format: 'csv', filename: 'a' } }),
			tab({
				id: 'tab-2',
				name: 'Tab 2',
				datasource: { id: 'ds-2', analysis_tab_id: null, config: { branch: 'dev' } },
				output: { result_id: 'out-2', format: 'parquet', filename: 'b' }
			})
		];
		const ds = [datasource(), datasource({ id: 'ds-2', name: 'DS 2' })];
		const result = buildAnalysisPipelinePayload('a-1', tabs, ds);
		expect(result).not.toBeNull();
		expect(result!.tabs).toHaveLength(2);
		expect(Object.keys(result!.sources)).toContain('out-1');
		expect(Object.keys(result!.sources)).toContain('out-2');
		expect(Object.keys(result!.sources)).toContain('ds-1');
		expect(Object.keys(result!.sources)).toContain('ds-2');
	});

	test('collects right_source from join step config', () => {
		const t = tab({
			steps: [
				{
					id: 's-1',
					type: 'join',
					config: { right_source: 'ds-join' }
				}
			]
		});
		const ds = [datasource(), datasource({ id: 'ds-join', name: 'Join DS' })];
		const result = buildAnalysisPipelinePayload('a-1', [t], ds);
		expect(result).not.toBeNull();
		expect(Object.keys(result!.sources)).toContain('ds-join');
	});

	test('collects sources array from union step config', () => {
		const t = tab({
			steps: [
				{
					id: 's-1',
					type: 'union',
					config: { sources: ['ds-u1', 'ds-u2'] }
				}
			]
		});
		const ds = [
			datasource(),
			datasource({ id: 'ds-u1', name: 'U1' }),
			datasource({ id: 'ds-u2', name: 'U2' })
		];
		const result = buildAnalysisPipelinePayload('a-1', [t], ds);
		expect(result).not.toBeNull();
		expect(Object.keys(result!.sources)).toContain('ds-u1');
		expect(Object.keys(result!.sources)).toContain('ds-u2');
	});

	test('returns null when a referenced source from step is missing', () => {
		const t = tab({
			steps: [
				{
					id: 's-1',
					type: 'join',
					config: { right_source: 'ds-missing' }
				}
			]
		});
		expect(buildAnalysisPipelinePayload('a-1', [t], [datasource()])).toBeNull();
	});

	test('filters out unapplied steps', () => {
		const t = tab({
			steps: [
				{ id: 's-1', type: 'select', config: { columns: ['a'] }, is_applied: true },
				{ id: 's-2', type: 'filter', config: {}, is_applied: false }
			]
		});
		const result = buildAnalysisPipelinePayload('a-1', [t], [datasource()]);
		expect(result).not.toBeNull();
		expect(result!.tabs[0].steps).toHaveLength(1);
		expect(result!.tabs[0].steps[0].id).toBe('s-1');
	});

	test('skips tabs with empty id', () => {
		const t = tab({ id: '' });
		expect(buildAnalysisPipelinePayload('a-1', [t], [datasource()])).toBeNull();
	});

	test('tab output is spread into pipeline output', () => {
		const t = tab({
			output: {
				result_id: 'out-1',
				format: 'parquet',
				filename: 'export',
				build_mode: 'full',
				iceberg: { namespace: 'ns', table_name: 'tbl' }
			}
		});
		const result = buildAnalysisPipelinePayload('a-1', [t], [datasource()]);
		expect(result!.tabs[0].output.build_mode).toBe('full');
		expect(result!.tabs[0].output.iceberg).toEqual({ namespace: 'ns', table_name: 'tbl' });
	});

	test('does not duplicate source entries for output IDs that match datasource IDs', () => {
		const t = tab({
			datasource: { id: 'out-1', analysis_tab_id: null, config: { branch: 'main' } },
			output: { result_id: 'out-1', format: 'csv', filename: 'out' }
		});
		const result = buildAnalysisPipelinePayload('a-1', [t], [datasource({ id: 'out-1' })]);
		expect(result).not.toBeNull();
		expect(result!.sources['out-1'].source_type).toBe('analysis');
	});

	test('derived tab uses upstream tab output as datasource source', () => {
		const upstream = tab({
			id: 'tab-1',
			output: { result_id: 'out-1', format: 'parquet', filename: 'upstream', build_mode: 'full' }
		});
		const derived = tab({
			id: 'tab-2',
			name: 'Derived',
			datasource: { id: 'out-1', analysis_tab_id: 'tab-1', config: { branch: 'main' } },
			output: { result_id: 'out-2', format: 'parquet', filename: 'derived', build_mode: 'full' }
		});
		const result = buildAnalysisPipelinePayload('a-1', [upstream, derived], [datasource()]);
		expect(result).not.toBeNull();
		expect(result!.tabs).toHaveLength(2);
		expect(result!.tabs[1].datasource.analysis_tab_id).toBe('tab-1');
		expect(result!.tabs[1].datasource.id).toBe('out-1');
		expect(result!.sources['out-1'].source_type).toBe('analysis');
		expect(result!.sources['out-1'].analysis_tab_id).toBe('tab-1');
	});

	test('derived tab does not require matching datasource in datasource list', () => {
		const upstream = tab({
			id: 'tab-1',
			output: { result_id: 'out-1', format: 'parquet', filename: 'upstream', build_mode: 'full' }
		});
		const derived = tab({
			id: 'tab-2',
			name: 'Derived',
			datasource: { id: 'out-1', analysis_tab_id: 'tab-1', config: { branch: 'main' } },
			output: { result_id: 'out-2', format: 'parquet', filename: 'derived', build_mode: 'full' }
		});
		const result = buildAnalysisPipelinePayload('a-1', [upstream, derived], [datasource()]);
		expect(result).not.toBeNull();
		expect(Object.keys(result!.sources)).toContain('out-1');
		expect(Object.keys(result!.sources)).toContain('out-2');
	});

	test('three-tab chain: upstream → derived → second derived', () => {
		const t1 = tab({
			id: 'tab-1',
			output: { result_id: 'out-1', format: 'parquet', filename: 'first', build_mode: 'full' }
		});
		const t2 = tab({
			id: 'tab-2',
			name: 'Middle',
			datasource: { id: 'out-1', analysis_tab_id: 'tab-1', config: { branch: 'main' } },
			output: { result_id: 'out-2', format: 'parquet', filename: 'middle', build_mode: 'full' }
		});
		const t3 = tab({
			id: 'tab-3',
			name: 'Final',
			datasource: { id: 'out-2', analysis_tab_id: 'tab-2', config: { branch: 'main' } },
			output: { result_id: 'out-3', format: 'parquet', filename: 'final', build_mode: 'full' }
		});
		const result = buildAnalysisPipelinePayload('a-1', [t1, t2, t3], [datasource()]);
		expect(result).not.toBeNull();
		expect(result!.tabs).toHaveLength(3);
		expect(result!.sources['out-1'].analysis_tab_id).toBe('tab-1');
		expect(result!.sources['out-2'].analysis_tab_id).toBe('tab-2');
		expect(result!.sources['out-3'].analysis_tab_id).toBe('tab-3');
	});

	test('normalizes time-travel fields in tab datasource config', () => {
		const t = tab({
			datasource: {
				id: 'ds-1',
				analysis_tab_id: null,
				config: {
					branch: 'main',
					time_travel_snapshot_id: 'snap-42',
					time_travel_snapshot_timestamp_ms: 1700000000000,
					time_travel_ui: { open: true }
				}
			}
		});
		const result = buildAnalysisPipelinePayload('a-1', [t], [datasource()]);
		expect(result).not.toBeNull();
		const config = result!.tabs[0].datasource.config;
		expect(config.snapshot_id).toBe('snap-42');
		expect(config.snapshot_timestamp_ms).toBe(1700000000000);
		expect(config.time_travel_snapshot_id).toBeUndefined();
		expect(config.time_travel_ui).toBeUndefined();
	});
});

// ── buildDatasourceConfig ───────────────────────────────────────────────────

describe('buildDatasourceConfig', () => {
	test('returns null when tab is null', () => {
		expect(
			buildDatasourceConfig({
				analysisId: 'a-1',
				tab: null,
				tabs: [],
				datasources: []
			})
		).toBeNull();
	});

	test('returns base config when analysisId is null', () => {
		const t = tab();
		const result = buildDatasourceConfig({
			analysisId: null,
			tab: t,
			tabs: [t],
			datasources: [datasource()]
		});
		expect(result).toEqual({ branch: 'main' });
	});

	test('returns base config when datasource not found', () => {
		const t = tab({
			datasource: { id: 'ds-missing', analysis_tab_id: null, config: { branch: 'dev' } }
		});
		const result = buildDatasourceConfig({
			analysisId: 'a-1',
			tab: t,
			tabs: [t],
			datasources: [datasource()]
		});
		expect(result).toEqual({ branch: 'dev' });
	});

	test('returns base config when datasource was not created by analysis', () => {
		const t = tab();
		const result = buildDatasourceConfig({
			analysisId: 'a-1',
			tab: t,
			tabs: [t],
			datasources: [datasource({ created_by_analysis_id: null })]
		});
		expect(result).toEqual({ branch: 'main' });
	});

	test('returns base config when datasource was created by different analysis', () => {
		const t = tab();
		const result = buildDatasourceConfig({
			analysisId: 'a-1',
			tab: t,
			tabs: [t],
			datasources: [datasource({ created_by_analysis_id: 'a-other' })]
		});
		expect(result).toEqual({ branch: 'main' });
	});

	test('appends analysis_pipeline when datasource matches analysis', () => {
		const t = tab();
		const ds = datasource({ created_by_analysis_id: 'a-1' });
		const result = buildDatasourceConfig({
			analysisId: 'a-1',
			tab: t,
			tabs: [t],
			datasources: [ds]
		});
		expect(result).not.toBeNull();
		expect(result!.analysis_pipeline).toBeDefined();
		const pipeline = result!.analysis_pipeline as { analysis_id: string };
		expect(pipeline.analysis_id).toBe('a-1');
	});

	test('returns base when pipeline build fails', () => {
		const t = tab({ output: { result_id: '', format: 'csv', filename: 'out' } });
		const ds = datasource({ created_by_analysis_id: 'a-1' });
		const result = buildDatasourceConfig({
			analysisId: 'a-1',
			tab: t,
			tabs: [t],
			datasources: [ds]
		});
		expect(result).toEqual({ branch: 'main' });
		expect(result!.analysis_pipeline).toBeUndefined();
	});
});

// ── buildDatasourcePipelinePayload ──────────────────────────────────────────

describe('buildDatasourcePipelinePayload', () => {
	test('builds basic payload from datasource', () => {
		const ds = datasource();
		const result = buildDatasourcePipelinePayload({ datasource: ds });
		expect(result.analysis_id).toBe('ds-1');
		expect(result.tabs).toHaveLength(1);
		expect(result.tabs[0].id).toBe('datasource-ds-1');
		expect(result.tabs[0].name).toBe('Test DS');
		expect(result.tabs[0].steps).toEqual([]);
	});

	test('uses default branch master when no config provided', () => {
		const result = buildDatasourcePipelinePayload({ datasource: datasource() });
		expect(result.tabs[0].datasource.config.branch).toBe('master');
	});

	test('uses branch from datasourceConfig', () => {
		const result = buildDatasourcePipelinePayload({
			datasource: datasource(),
			datasourceConfig: { branch: 'dev' }
		});
		expect(result.tabs[0].datasource.config.branch).toBe('dev');
	});

	test('spreads datasourceConfig into tab config', () => {
		const result = buildDatasourcePipelinePayload({
			datasource: datasource(),
			datasourceConfig: { branch: 'main', extra: 'value' }
		});
		expect(result.tabs[0].datasource.config.extra).toBe('value');
	});

	test('normalizes filename from datasource name', () => {
		const ds = datasource({ name: 'My Test File' });
		const result = buildDatasourcePipelinePayload({ datasource: ds });
		expect(result.tabs[0].output.iceberg?.table_name).toBe('my_test_file');
	});

	test('uses export as fallback name', () => {
		const ds = datasource({ name: undefined as unknown as string });
		const result = buildDatasourcePipelinePayload({ datasource: ds });
		expect(result.tabs[0].name).toBe('Datasource');
		expect(result.tabs[0].output.filename).toBe('export');
	});

	test('sources contains datasource config', () => {
		const ds = datasource();
		const result = buildDatasourcePipelinePayload({ datasource: ds });
		expect(result.sources['ds-1']).toEqual({
			source_type: 'file',
			file_path: '/data/test.csv',
			file_type: 'csv'
		});
	});

	test('output has correct format and build_mode', () => {
		const result = buildDatasourcePipelinePayload({ datasource: datasource() });
		expect(result.tabs[0].output.format).toBe('parquet');
		expect(result.tabs[0].output.build_mode).toBe('full');
	});

	test('trimmed branch used for iceberg table_name', () => {
		const result = buildDatasourcePipelinePayload({
			datasource: datasource(),
			datasourceConfig: { branch: '  dev  ' }
		});
		expect(result.tabs[0].output.iceberg?.branch).toBe('dev');
	});

	test('handles null datasourceConfig', () => {
		const result = buildDatasourcePipelinePayload({
			datasource: datasource(),
			datasourceConfig: null
		});
		expect(result.tabs[0].datasource.config.branch).toBe('master');
	});

	test('normalizes time-travel fields into compute snapshot fields', () => {
		const result = buildDatasourcePipelinePayload({
			datasource: datasource(),
			datasourceConfig: {
				branch: 'main',
				time_travel_snapshot_id: 'snap-42',
				time_travel_snapshot_timestamp_ms: 1700000000000
			}
		});
		const config = result.tabs[0].datasource.config;
		expect(config.snapshot_id).toBe('snap-42');
		expect(config.snapshot_timestamp_ms).toBe(1700000000000);
		expect(config.time_travel_snapshot_id).toBeUndefined();
		expect(config.time_travel_snapshot_timestamp_ms).toBeUndefined();
	});

	test('strips time_travel_ui from pipeline config', () => {
		const result = buildDatasourcePipelinePayload({
			datasource: datasource(),
			datasourceConfig: {
				branch: 'main',
				time_travel_ui: { open: true, month: '2024-06' }
			}
		});
		const config = result.tabs[0].datasource.config;
		expect(config.time_travel_ui).toBeUndefined();
	});
});

// ── normalizeSnapshotConfig ────────────────────────────────────────────────

describe('normalizeSnapshotConfig', () => {
	test('passes through config without time-travel fields', () => {
		const config = { branch: 'main', metadata_path: '/data/table' };
		const result = normalizeSnapshotConfig(config);
		expect(result).toEqual({ branch: 'main', metadata_path: '/data/table' });
	});

	test('maps time_travel_snapshot_id to snapshot_id', () => {
		const result = normalizeSnapshotConfig({
			branch: 'main',
			time_travel_snapshot_id: 'snap-99'
		});
		expect(result.snapshot_id).toBe('snap-99');
		expect(result.time_travel_snapshot_id).toBeUndefined();
	});

	test('maps time_travel_snapshot_timestamp_ms to snapshot_timestamp_ms', () => {
		const result = normalizeSnapshotConfig({
			branch: 'main',
			time_travel_snapshot_id: 'snap-99',
			time_travel_snapshot_timestamp_ms: 1700000000000
		});
		expect(result.snapshot_id).toBe('snap-99');
		expect(result.snapshot_timestamp_ms).toBe(1700000000000);
		expect(result.time_travel_snapshot_timestamp_ms).toBeUndefined();
	});

	test('strips time_travel_ui', () => {
		const result = normalizeSnapshotConfig({
			branch: 'main',
			time_travel_ui: { open: true, month: '2024-06', day: '2024-06-15' }
		});
		expect(result.time_travel_ui).toBeUndefined();
		expect(result.branch).toBe('main');
	});

	test('does not set snapshot_id when time_travel_snapshot_id is absent', () => {
		const result = normalizeSnapshotConfig({ branch: 'dev' });
		expect(result.snapshot_id).toBeUndefined();
		expect(result.snapshot_timestamp_ms).toBeUndefined();
	});

	test('ignores timestamp_ms when snapshot_id is absent', () => {
		const result = normalizeSnapshotConfig({
			branch: 'dev',
			time_travel_snapshot_timestamp_ms: 1700000000000
		});
		expect(result.snapshot_id).toBeUndefined();
		expect(result.snapshot_timestamp_ms).toBeUndefined();
	});

	test('preserves existing snapshot_id from datasource config', () => {
		const result = normalizeSnapshotConfig({
			branch: 'main',
			snapshot_id: 'original-snap'
		});
		expect(result.snapshot_id).toBe('original-snap');
	});

	test('time-travel overrides existing snapshot_id', () => {
		const result = normalizeSnapshotConfig({
			branch: 'main',
			snapshot_id: 'original-snap',
			time_travel_snapshot_id: 'travel-snap'
		});
		expect(result.snapshot_id).toBe('travel-snap');
	});
});
