import { describe, test, expect } from 'vitest';
import {
	isUuid,
	buildOutputConfig,
	ensureTabDefaults,
	validatePipelineTabs,
	formatPipelineErrors
} from './analysis-tab';
import type { AnalysisTab } from '$lib/types/analysis';

describe('isUuid', () => {
	test('accepts valid v4 UUID', () => {
		expect(isUuid('550e8400-e29b-41d4-a716-446655440000')).toBe(true);
	});

	test('accepts uppercase UUID', () => {
		expect(isUuid('550E8400-E29B-41D4-A716-446655440000')).toBe(true);
	});

	test('rejects short string', () => {
		expect(isUuid('not-a-uuid')).toBe(false);
	});

	test('rejects empty string', () => {
		expect(isUuid('')).toBe(false);
	});

	test('rejects null', () => {
		expect(isUuid(null)).toBe(false);
	});

	test('rejects undefined', () => {
		expect(isUuid(undefined)).toBe(false);
	});

	test('rejects string with invalid characters', () => {
		expect(isUuid('550e8400-e29b-41d4-a716-44665544000g')).toBe(false);
	});
});

describe('buildOutputConfig', () => {
	test('builds config with defaults', () => {
		const config = buildOutputConfig({ outputId: 'abc-123' });
		expect(config.result_id).toBe('abc-123');
		expect(config.format).toBe('parquet');
		expect(config.filename).toBe('export');
		expect(config.build_mode).toBe('full');
		expect(config.iceberg).toEqual({
			namespace: 'outputs',
			table_name: 'export',
			branch: 'master'
		});
	});

	test('slugifies name for filename and table_name', () => {
		const config = buildOutputConfig({ outputId: 'x', name: 'My Report' });
		expect(config.filename).toBe('my_report');
		expect((config.iceberg as Record<string, unknown>).table_name).toBe('my_report');
	});

	test('uses custom branch', () => {
		const config = buildOutputConfig({ outputId: 'x', branch: 'dev' });
		expect((config.iceberg as Record<string, unknown>).branch).toBe('dev');
	});

	test('falls back to master for empty branch', () => {
		const config = buildOutputConfig({ outputId: 'x', branch: '' });
		expect((config.iceberg as Record<string, unknown>).branch).toBe('master');
	});

	test('falls back to master for null branch', () => {
		const config = buildOutputConfig({ outputId: 'x', branch: null });
		expect((config.iceberg as Record<string, unknown>).branch).toBe('master');
	});
});

describe('ensureTabDefaults', () => {
	const validUuid = '550e8400-e29b-41d4-a716-446655440000';

	test('preserves existing filename and iceberg.table_name', () => {
		const tab = makeTab({
			output: { result_id: validUuid, format: 'parquet', filename: 'my_export' }
		});
		const result = ensureTabDefaults(tab, 0);
		expect(result.output.filename).toBe('my_export');
		expect((result.output.iceberg as Record<string, unknown>).table_name).toBe('my_export');
	});

	test('does not generate timestamp-based name when filename is missing', () => {
		const tab = makeTab({
			output: { result_id: validUuid, format: 'parquet', filename: '' }
		});
		const result = ensureTabDefaults(tab, 0);
		expect(result.output.filename).not.toMatch(/^output-\d+$/);
		expect(result.output.filename).toBe('export');
	});

	test('does not generate timestamp-based iceberg.table_name when iceberg is missing', () => {
		const tab = makeTab({
			output: { result_id: validUuid, format: 'parquet', filename: '' }
		});
		const result = ensureTabDefaults(tab, 0);
		const iceberg = result.output.iceberg as Record<string, unknown>;
		expect(iceberg.table_name).not.toMatch(/^output-\d+$/);
		expect(iceberg.table_name).toBe('export');
	});

	test('throws for missing result_id', () => {
		const tab = makeTab({
			output: { result_id: 'not-a-uuid', format: 'parquet', filename: 'x' }
		});
		expect(() => ensureTabDefaults(tab, 0)).toThrow(/missing or invalid output.result_id/);
	});
});

function makeTab(overrides: Partial<AnalysisTab> = {}): AnalysisTab {
	return {
		id: 'tab-1',
		name: 'Source 1',
		parent_id: null,
		datasource: {
			id: 'ds-1',
			analysis_tab_id: null,
			config: { branch: 'master' }
		},
		output: {
			result_id: '550e8400-e29b-41d4-a716-446655440000',
			format: 'parquet',
			filename: 'source_1'
		},
		steps: [],
		...overrides
	};
}

describe('validatePipelineTabs', () => {
	test('returns no errors for valid tab', () => {
		expect(validatePipelineTabs([makeTab()])).toEqual([]);
	});

	test('detects missing datasource', () => {
		const tab = makeTab();
		const broken = { ...tab, datasource: undefined } as unknown as AnalysisTab;
		const errors = validatePipelineTabs([broken]);
		expect(errors).toHaveLength(1);
		expect(errors[0].field).toBe('datasource');
	});

	test('detects missing datasource.id', () => {
		const tab = makeTab();
		tab.datasource.id = '';
		const errors = validatePipelineTabs([tab]);
		expect(errors).toHaveLength(1);
		expect(errors[0].field).toBe('datasource.id');
	});

	test('detects missing output', () => {
		const tab = makeTab();
		const broken = { ...tab, output: undefined } as unknown as AnalysisTab;
		const errors = validatePipelineTabs([broken]);
		expect(errors).toHaveLength(1);
		expect(errors[0].field).toBe('output');
	});

	test('detects missing output.result_id', () => {
		const tab = makeTab();
		tab.output.result_id = '';
		const errors = validatePipelineTabs([tab]);
		expect(errors).toHaveLength(1);
		expect(errors[0].field).toBe('output.result_id');
	});

	test('detects mismatched upstream tab reference', () => {
		const upstream = makeTab({ id: 'tab-1' });
		const downstream = makeTab({
			id: 'tab-2',
			datasource: {
				id: 'wrong-id',
				analysis_tab_id: 'tab-1',
				config: { branch: 'master' }
			}
		});
		const errors = validatePipelineTabs([upstream, downstream]);
		expect(errors).toHaveLength(1);
		expect(errors[0].field).toBe('datasource.id');
	});

	test('detects reference to missing upstream tab', () => {
		const tab = makeTab({
			datasource: {
				id: 'some-id',
				analysis_tab_id: 'nonexistent',
				config: { branch: 'master' }
			}
		});
		const errors = validatePipelineTabs([tab]);
		expect(errors).toHaveLength(1);
		expect(errors[0].field).toBe('datasource.analysis_tab_id');
	});

	test('returns empty for empty tabs array', () => {
		expect(validatePipelineTabs([])).toEqual([]);
	});

	test('valid derived tab with correct upstream reference passes', () => {
		const upstream = makeTab({ id: 'tab-1' });
		const derived = makeTab({
			id: 'tab-2',
			datasource: {
				id: upstream.output.result_id,
				analysis_tab_id: 'tab-1',
				config: { branch: 'master' }
			}
		});
		expect(validatePipelineTabs([upstream, derived])).toEqual([]);
	});

	test('derived tab referencing non-existent upstream produces error', () => {
		const derived = makeTab({
			id: 'tab-2',
			datasource: {
				id: 'some-output-id',
				analysis_tab_id: 'ghost-tab',
				config: { branch: 'master' }
			}
		});
		const errors = validatePipelineTabs([derived]);
		expect(errors).toHaveLength(1);
		expect(errors[0].field).toBe('datasource.analysis_tab_id');
	});

	test('derived tab with mismatched datasource.id produces error', () => {
		const upstream = makeTab({ id: 'tab-1' });
		const derived = makeTab({
			id: 'tab-2',
			datasource: {
				id: 'wrong-output-id',
				analysis_tab_id: 'tab-1',
				config: { branch: 'master' }
			}
		});
		const errors = validatePipelineTabs([upstream, derived]);
		expect(errors).toHaveLength(1);
		expect(errors[0].field).toBe('datasource.id');
	});

	test('chained derived tabs all pass validation', () => {
		const t1 = makeTab({ id: 'tab-1' });
		const t2 = makeTab({
			id: 'tab-2',
			datasource: {
				id: t1.output.result_id,
				analysis_tab_id: 'tab-1',
				config: { branch: 'master' }
			},
			output: {
				result_id: '660e8400-e29b-41d4-a716-446655440000',
				format: 'parquet',
				filename: 'derived_1'
			}
		});
		const t3 = makeTab({
			id: 'tab-3',
			datasource: {
				id: '660e8400-e29b-41d4-a716-446655440000',
				analysis_tab_id: 'tab-2',
				config: { branch: 'master' }
			}
		});
		expect(validatePipelineTabs([t1, t2, t3])).toEqual([]);
	});
});

describe('formatPipelineErrors', () => {
	test('returns empty string for no errors', () => {
		expect(formatPipelineErrors([])).toBe('');
	});

	test('returns single error message', () => {
		const result = formatPipelineErrors([{ tabId: '1', field: 'x', message: 'missing x' }]);
		expect(result).toBe('missing x');
	});

	test('appends count for multiple errors', () => {
		const result = formatPipelineErrors([
			{ tabId: '1', field: 'x', message: 'missing x' },
			{ tabId: '2', field: 'y', message: 'missing y' },
			{ tabId: '3', field: 'z', message: 'missing z' }
		]);
		expect(result).toBe('missing x (+2 more)');
	});
});
