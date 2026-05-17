import { describe, test, expect } from 'vitest';
import { getDefaultConfig, normalizeConfig } from './step-config-defaults';

describe('getDefaultConfig', () => {
	test('returns select defaults with columns and cast_map', () => {
		const config = getDefaultConfig('select');
		expect(config).toEqual({ columns: [], cast_map: {} });
	});

	test('returns filter defaults with one empty condition', () => {
		const config = getDefaultConfig('filter');
		expect(config).toEqual({
			conditions: [{ column: '', operator: '=', value: '', value_type: 'string' }],
			logic: 'AND'
		});
	});

	test('returns limit defaults', () => {
		expect(getDefaultConfig('limit')).toEqual({ n: 100 });
	});

	test('returns sample defaults', () => {
		const config = getDefaultConfig('sample');
		expect(config).toEqual({
			fraction: 0.5,
			seed: null
		});
	});

	test('returns topk defaults', () => {
		expect(getDefaultConfig('topk')).toEqual({ column: '', k: 10, descending: false });
	});

	test('returns empty object for unknown step type', () => {
		expect(getDefaultConfig('nonexistent')).toEqual({});
	});

	test('returns empty object for datasource', () => {
		expect(getDefaultConfig('datasource')).toEqual({});
	});

	test('maps plot_ prefix to chart defaults', () => {
		const config = getDefaultConfig('plot_bar');
		expect(config).toHaveProperty('chart_type', 'bar');
		expect(config).toHaveProperty('x_column', '');
		expect(config).toHaveProperty('y_column', '');
	});

	test('returns a fresh copy each time', () => {
		const a = getDefaultConfig('select');
		const b = getDefaultConfig('select');
		expect(a).toEqual(b);
		expect(a).not.toBe(b);
	});

	test('returns groupby defaults', () => {
		expect(getDefaultConfig('groupby')).toEqual({ group_by: [], aggregations: [] });
	});

	test('returns view defaults', () => {
		expect(getDefaultConfig('view')).toEqual({ rowLimit: 100 });
	});

	test('returns export defaults', () => {
		expect(getDefaultConfig('export')).toEqual({
			format: 'csv',
			filename: 'export',
			destination: 'download'
		});
	});

	test('returns download defaults', () => {
		expect(getDefaultConfig('download')).toEqual({
			format: 'csv',
			filename: 'download'
		});
	});

	test('returns notification defaults', () => {
		const config = getDefaultConfig('notification');
		expect(config).toHaveProperty('method', 'email');
		expect(config).toHaveProperty('recipient', '');
		expect(config).toHaveProperty('batch_size', 10);
	});

	test('returns ai defaults', () => {
		const config = getDefaultConfig('ai');
		expect(config).toHaveProperty('provider', 'ollama');
		expect(config).toHaveProperty('model', 'llama3.2');
		expect(config).toHaveProperty('batch_size', 10);
	});
});

describe('normalizeConfig', () => {
	test('does not inject missing fields', () => {
		const config = normalizeConfig('limit', {});
		expect(config).toEqual({});
	});

	test('preserves existing config values', () => {
		const config = normalizeConfig('limit', { n: 50 });
		expect(config).toEqual({ n: 50 });
	});

	test('handles plot_ prefix by setting chart_type', () => {
		const config = normalizeConfig('plot_scatter', { x_column: 'age' });
		expect(config).toHaveProperty('chart_type', 'scatter');
		expect(config).toHaveProperty('x_column', 'age');
	});

	test('chart step keeps provided chart_type and does not derive from step name', () => {
		const config = normalizeConfig('chart', { chart_type: 'line', x_column: 'age' });
		expect(config).toHaveProperty('chart_type', 'line');
		expect(config).toHaveProperty('x_column', 'age');
	});

	test('export step preserves provided config', () => {
		const config = normalizeConfig('export', {
			format: 'parquet',
			filename: 'out',
			iceberg_options: { table: 'foo' },
			destination: 'iceberg'
		});
		expect(config).toEqual({
			format: 'parquet',
			filename: 'out',
			iceberg_options: { table: 'foo' },
			destination: 'iceberg'
		});
	});

	test('filter preserves provided conditions', () => {
		const config = normalizeConfig('filter', {
			conditions: [{ column: 'age' }],
			logic: 'OR'
		});
		const conditions = (config as Record<string, unknown>).conditions as Array<
			Record<string, unknown>
		>;
		expect(conditions[0]).toEqual({ column: 'age' });
		expect(config).toHaveProperty('logic', 'OR');
	});

	test('filter preserves compare_column without injecting other fields', () => {
		const config = normalizeConfig('filter', {
			conditions: [{ column: 'a', compare_column: 'b' }],
			logic: 'AND'
		});
		const conditions = (config as Record<string, unknown>).conditions as Array<
			Record<string, unknown>
		>;
		expect(conditions[0]).toHaveProperty('compare_column', 'b');
		expect(conditions[0]).toEqual({ column: 'a', compare_column: 'b' });
	});

	test('ai preserves explicit null fields', () => {
		const config = normalizeConfig('ai', {
			provider: 'openai',
			model: 'gpt-4',
			input_columns: null,
			endpoint_url: null,
			api_key: null
		});
		expect(config).toEqual({
			provider: 'openai',
			model: 'gpt-4',
			input_columns: null,
			endpoint_url: null,
			api_key: null
		});
	});

	test('notification preserves explicit null fields', () => {
		const config = normalizeConfig('notification', {
			method: 'telegram',
			input_columns: null,
			bot_token: null,
			recipient: null,
			recipient_source: null,
			recipient_column: null,
			subscriber_ids: null
		});
		expect(config).toEqual({
			method: 'telegram',
			input_columns: null,
			bot_token: null,
			recipient: null,
			recipient_source: null,
			recipient_column: null,
			subscriber_ids: null
		});
	});

	test('chart preserves explicit null fields', () => {
		const config = normalizeConfig('chart', {
			chart_type: 'line',
			x_axis_label: null,
			y_axis_label: null,
			title: null,
			overlays: null,
			reference_lines: null
		});
		expect(config).toEqual({
			chart_type: 'line',
			x_axis_label: null,
			y_axis_label: null,
			title: null,
			overlays: null,
			reference_lines: null
		});
	});

	test('strips ui-only description for known step types', () => {
		const config = normalizeConfig('with_columns', {
			expressions: [],
			description: 'Add quality signal columns'
		});
		expect(config).toEqual({ expressions: [] });
	});

	test('returns empty object for unknown type with empty config', () => {
		expect(normalizeConfig('nonexistent', {})).toEqual({});
	});

	test('preserves extra fields for unknown types', () => {
		const config = normalizeConfig('nonexistent', { custom: 42 });
		expect(config).toEqual({ custom: 42 });
	});

	test('does not migrate legacy groupBy to group_by', () => {
		const input = {
			groupBy: ['region'],
			aggregations: [{ column: 'sales', function: 'sum', alias: 'total' }]
		};
		const config = normalizeConfig('groupby', input);
		expect(config).toEqual(input);
	});

	test('keeps explicit group_by and ignores legacy groupBy', () => {
		const config = normalizeConfig('groupby', {
			groupBy: ['old'],
			group_by: ['new'],
			aggregations: []
		});
		expect(config).toHaveProperty('group_by', ['new']);
	});

	test('does not migrate legacy topk by or reverse', () => {
		const input = { by: 'score', k: 5, reverse: true };
		const config = normalizeConfig('topk', input);
		expect(config).toEqual(input);
	});

	test('keeps explicit topk column when legacy by is also present', () => {
		const config = normalizeConfig('topk', { by: 'old', column: 'new', k: 3, descending: false });
		expect(config).toHaveProperty('column', 'new');
	});

	test('does not overwrite existing topk descending with legacy reverse', () => {
		const config = normalizeConfig('topk', { reverse: true, column: 'x', k: 3, descending: false });
		expect(config).toHaveProperty('descending', false);
	});

	test('does not migrate legacy topk by when reverse is absent', () => {
		const config = normalizeConfig('topk', { by: 'price', k: 10 });
		expect(config).toEqual({ by: 'price', k: 10 });
	});

	test('does not migrate legacy topk reverse when by is absent', () => {
		const config = normalizeConfig('topk', { column: 'price', k: 10, reverse: true });
		expect(config).toEqual({ column: 'price', k: 10, reverse: true });
	});
});
