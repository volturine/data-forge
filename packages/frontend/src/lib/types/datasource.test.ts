import { describe, expect, it } from 'vitest';

import type { DataSource } from './datasource';
import {
	datasourceFileConfig,
	datasourceIsAnalysisOutput,
	datasourceIsCsv,
	datasourceRowCount,
	datasourceIsSchedulableRaw,
	datasourceNeedsExternalIngest,
	datasourceSupportsSchemaRefresh
} from './datasource';

function makeDatasource(overrides: Partial<DataSource>): DataSource {
	return {
		id: 'ds-1',
		name: 'Sample datasource',
		description: null,
		schema_cache: null,
		created_by_analysis_id: null,
		created_by: 'import',
		is_hidden: false,
		created_at: '2026-05-01T00:00:00Z',
		output_of_tab_id: null,
		source_type: 'file',
		config: {
			file_path: '/tmp/data.csv',
			file_type: 'csv'
		},
		...overrides
	} as DataSource;
}

describe('datasourceRowCount', () => {
	it('prefers the list scalar over schema_cache', () => {
		const datasource = makeDatasource({
			row_count: 42,
			schema_cache: { row_count: 99, columns: [] }
		});
		expect(datasourceRowCount(datasource)).toBe(42);
	});

	it('falls back to schema_cache when list scalar is absent', () => {
		const datasource = makeDatasource({
			schema_cache: { row_count: 17, columns: [] }
		});
		expect(datasourceRowCount(datasource)).toBe(17);
	});

	it('returns null when neither source has a finite count', () => {
		expect(datasourceRowCount(makeDatasource({ schema_cache: null }))).toBeNull();
		expect(
			datasourceRowCount(makeDatasource({ row_count: null, schema_cache: { row_count: 'x' } }))
		).toBeNull();
	});
});

describe('datasource ownership helpers', () => {
	it('owns direct file classification', () => {
		const datasource = makeDatasource({ source_type: 'file' });

		expect(datasourceFileConfig(datasource)?.file_type).toBe('csv');
		expect(datasourceIsCsv(datasource)).toBe(true);
		expect(datasourceSupportsSchemaRefresh(datasource)).toBe(true);
	});

	it('owns external iceberg ingestion classification', () => {
		const datasource = makeDatasource({
			source_type: 'iceberg',
			config: {
				metadata_path: '/tmp/table/metadata/v1.metadata.json',
				branch: 'master',
				source: {
					source_type: 'file',
					file_path: '/tmp/data.csv',
					file_type: 'csv'
				}
			}
		});

		expect(datasourceFileConfig(datasource)?.file_path).toBe('/tmp/data.csv');
		expect(datasourceNeedsExternalIngest(datasource)).toBe(true);
		expect(datasourceIsSchedulableRaw(datasource)).toBe(true);
	});

	it('owns external database-backed iceberg ingestion classification', () => {
		const datasource = makeDatasource({
			source_type: 'iceberg',
			config: {
				metadata_path: '/tmp/table/metadata/v1.metadata.json',
				branch: 'master',
				source: {
					source_type: 'database',
					connection_string: 'postgresql://example/db',
					query: 'select * from public.users'
				}
			}
		});

		expect(datasourceNeedsExternalIngest(datasource)).toBe(true);
		expect(datasourceIsSchedulableRaw(datasource)).toBe(true);
	});

	it('owns analysis-output classification', () => {
		const datasource = makeDatasource({
			source_type: 'iceberg',
			created_by: 'analysis',
			created_by_analysis_id: 'analysis-1',
			config: {
				metadata_path: '/tmp/table/metadata/v1.metadata.json'
			}
		});

		expect(datasourceIsAnalysisOutput(datasource)).toBe(true);
		expect(datasourceIsSchedulableRaw(datasource)).toBe(false);
	});

	it('disables schema refresh for analysis datasources', () => {
		const datasource = makeDatasource({
			source_type: 'analysis',
			config: { analysis_id: 'analysis-1' }
		});

		expect(datasourceSupportsSchemaRefresh(datasource)).toBe(false);
	});
});
