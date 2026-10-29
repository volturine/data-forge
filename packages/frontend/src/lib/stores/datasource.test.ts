import { describe, test, expect, vi, beforeEach } from 'vitest';
import type { DataSource, SchemaInfo } from '#lib/types/datasource.js';

const mockGetDatasourceSchema = vi.fn();

vi.mock('#lib/api/datasource.js', () => ({
	getDatasourceSchema: (...args: unknown[]) => mockGetDatasourceSchema(...args)
}));

const { DatasourceStore } = await import('./datasource.svelte');

function makeDatasource(overrides: Partial<DataSource> = {}): DataSource {
	return {
		id: `ds-${crypto.randomUUID().slice(0, 8)}`,
		name: 'test-ds',
		source_type: 'file',
		config: { file_path: '/tmp/test.csv', file_type: 'csv' },
		schema_cache: null,
		created_by: 'test',
		is_hidden: false,
		created_at: Temporal.Now.instant().toString(),
		...overrides
	} as DataSource;
}

function makeSchema(overrides: Partial<SchemaInfo> = {}): SchemaInfo {
	return {
		columns: [{ name: 'id', dtype: 'Int64', nullable: false }],
		row_count: 10,
		...overrides
	};
}

function mockSchemaSuccess(schema: SchemaInfo) {
	mockGetDatasourceSchema.mockReturnValue({
		match: (onOk: (s: SchemaInfo) => SchemaInfo) => {
			return Promise.resolve(onOk(schema));
		}
	});
}

function mockSchemaError(message: string) {
	mockGetDatasourceSchema.mockReturnValue({
		match: (_onOk: unknown, onErr: (e: { message: string }) => never) => {
			return Promise.resolve().then(() => onErr({ message }));
		}
	});
}

describe('DatasourceStore', () => {
	let store: InstanceType<typeof DatasourceStore>;

	beforeEach(() => {
		vi.clearAllMocks();
		store = new DatasourceStore();
	});

	describe('initial state', () => {
		test('has no datasources, is not loaded and has an empty schema map', () => {
			expect(store.datasources).toEqual([]);
			expect(store.loaded).toBe(false);
			expect(store.schemas.size).toBe(0);
		});
	});

	describe('getSchema', () => {
		test('fetches and caches schema with refresh false by default', async () => {
			const s = makeSchema();
			mockSchemaSuccess(s);
			store.datasources = [makeDatasource({ id: 'ds-1' })];

			const result = await store.getSchema('ds-1');

			expect(result).toEqual(s);
			expect(store.schemas.get('ds-1')).toEqual(s);
			expect(mockGetDatasourceSchema).toHaveBeenCalledTimes(1);
			expect(mockGetDatasourceSchema).toHaveBeenCalledWith('ds-1', {
				sheetName: undefined,
				refresh: false
			});
		});

		test('returns cached schema without API call', async () => {
			const s = makeSchema();
			store.schemas.set('ds-1', s);
			store.datasources = [makeDatasource({ id: 'ds-1' })];

			const result = await store.getSchema('ds-1');

			expect(result).toEqual(s);
			expect(mockGetDatasourceSchema).not.toHaveBeenCalled();
		});

		test('bypasses memory cache when refresh is true', async () => {
			const cached = makeSchema({ row_count: 5 });
			const fresh = makeSchema({ row_count: 100 });
			store.schemas.set('ds-1', cached);
			store.datasources = [makeDatasource({ id: 'ds-1' })];
			mockSchemaSuccess(fresh);

			const result = await store.getSchema('ds-1', { refresh: true });

			expect(result).toEqual(fresh);
			expect(store.schemas.get('ds-1')).toEqual(fresh);
			expect(mockGetDatasourceSchema).toHaveBeenCalledWith('ds-1', {
				sheetName: undefined,
				refresh: true
			});
		});

		test('bypasses cache when sheetName is provided', async () => {
			const cached = makeSchema({ row_count: 5 });
			const fresh = makeSchema({ row_count: 100 });
			store.schemas.set('ds-1', cached);
			store.datasources = [makeDatasource({ id: 'ds-1' })];
			mockSchemaSuccess(fresh);

			const result = await store.getSchema('ds-1', { sheetName: 'Sheet2' });

			expect(result).toEqual(fresh);
			expect(mockGetDatasourceSchema).toHaveBeenCalledTimes(1);
			expect(mockGetDatasourceSchema).toHaveBeenCalledWith('ds-1', {
				sheetName: 'Sheet2',
				refresh: false
			});
		});

		test('does not cache when sheetName is provided', async () => {
			const s = makeSchema();
			store.datasources = [makeDatasource({ id: 'ds-1' })];
			mockSchemaSuccess(s);

			await store.getSchema('ds-1', { sheetName: 'Sheet2' });

			expect(store.schemas.has('ds-1')).toBe(false);
		});

		test('throws for analysis source_type', async () => {
			store.datasources = [makeDatasource({ id: 'ds-analysis', source_type: 'analysis' })];

			await expect(store.getSchema('ds-analysis')).rejects.toThrow(
				'Schema must be fetched via analysis output'
			);
			expect(mockGetDatasourceSchema).not.toHaveBeenCalled();
		});

		test('throws on API error with server message', async () => {
			store.datasources = [makeDatasource({ id: 'ds-1' })];
			mockSchemaError('Not found');

			await expect(store.getSchema('ds-1')).rejects.toThrow('Not found');
		});
	});

	describe('getDatasource', () => {
		test('returns datasource by id', () => {
			store.datasources = [makeDatasource({ id: 'ds-a' }), makeDatasource({ id: 'ds-b' })];
			const result = store.getDatasource('ds-b');
			expect(result?.id).toBe('ds-b');
		});

		test('returns undefined for unknown id', () => {
			store.datasources = [makeDatasource({ id: 'ds-a' })];
			expect(store.getDatasource('ds-missing')).toBeUndefined();
		});

		test('returns undefined for empty store', () => {
			expect(store.getDatasource('any')).toBeUndefined();
		});
	});

	describe('clearSchemaCache', () => {
		test('clears specific id', () => {
			store.schemas.set('ds-1', makeSchema());
			store.schemas.set('ds-2', makeSchema());

			store.clearSchemaCache('ds-1');

			expect(store.schemas.has('ds-1')).toBe(false);
			expect(store.schemas.has('ds-2')).toBe(true);
		});

		test('clears all when no id given', () => {
			store.schemas.set('ds-1', makeSchema());
			store.schemas.set('ds-2', makeSchema());

			store.clearSchemaCache();

			expect(store.schemas.size).toBe(0);
		});

		test('noop for nonexistent id', () => {
			store.schemas.set('ds-1', makeSchema());
			store.clearSchemaCache('ds-missing');
			expect(store.schemas.size).toBe(1);
		});
	});

	describe('reset', () => {
		test('clears all state', () => {
			store.datasources = [makeDatasource({ id: 'ds-1' })];
			store.loaded = true;
			store.schemas.set('ds-1', makeSchema());

			store.reset();

			expect(store.datasources).toEqual([]);
			expect(store.schemas.size).toBe(0);
			expect(store.loaded).toBe(false);
		});
	});
});
