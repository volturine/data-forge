import { describe, expect, test } from 'vitest';
import type { DataSource } from '$lib/types/datasource';
import { rankDatasources } from './datasource-picker';

function ds(name: string, createdAt: string, lastDataUpdate: string | null = null): DataSource {
	return {
		id: name,
		name,
		description: null,
		source_type: 'iceberg',
		config: {},
		created_by: 'import',
		is_hidden: false,
		created_at: createdAt,
		last_data_update: lastDataUpdate
	} as DataSource;
}

const names = (list: DataSource[]) => list.map((item) => item.name);

describe('rankDatasources', () => {
	test('orders by most recent data update, falling back to creation time', () => {
		const list = [
			ds('old', '2026-01-01T00:00:00Z'),
			ds('refreshed', '2025-01-01T00:00:00Z', '2026-09-01T00:00:00Z'),
			ds('new', '2026-06-01T00:00:00Z')
		];

		expect(names(rankDatasources(list, ''))).toEqual(['refreshed', 'new', 'old']);
	});

	test('puts prefix matches before substring matches and drops non-matches', () => {
		const list = [
			ds('daily_sales', '2026-09-01T00:00:00Z'),
			ds('Sales_eu', '2026-01-01T00:00:00Z'),
			ds('inventory', '2026-09-02T00:00:00Z'),
			ds('sales_us', '2026-05-01T00:00:00Z')
		];

		expect(names(rankDatasources(list, ' SALES '))).toEqual([
			'sales_us',
			'Sales_eu',
			'daily_sales'
		]);
	});

	test('does not mutate the input list', () => {
		const list = [ds('a', '2026-01-01T00:00:00Z'), ds('b', '2026-02-01T00:00:00Z')];

		rankDatasources(list, '');

		expect(names(list)).toEqual(['a', 'b']);
	});

	test('ranks thousands of datasources quickly', () => {
		const list = Array.from({ length: 10_000 }, (_, index) =>
			ds(`dataset_${index}`, new Date(Date.UTC(2026, 0, 1) + index * 60_000).toISOString())
		);

		const started = performance.now();
		const ranked = rankDatasources(list, 'dataset_99');
		const elapsed = performance.now() - started;

		expect(ranked[0].name).toBe('dataset_9999');
		expect(ranked).toHaveLength(111);
		expect(elapsed).toBeLessThan(200);
	});
});
