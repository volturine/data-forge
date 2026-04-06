import { describe, test, expect, vi, beforeEach } from 'vitest';
import type { DataSource, SchemaInfo } from '$lib/types/datasource';

const mockListDatasources = vi.fn();
const mockUploadFile = vi.fn();
const mockGetDatasourceSchema = vi.fn();
const mockDeleteDatasource = vi.fn();

vi.mock('$lib/api/datasource', () => ({
	listDatasources: (...args: unknown[]) => mockListDatasources(...args),
	uploadFile: (...args: unknown[]) => mockUploadFile(...args),
	getDatasourceSchema: (...args: unknown[]) => mockGetDatasourceSchema(...args),
	deleteDatasource: (...args: unknown[]) => mockDeleteDatasource(...args)
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
		created_at: new Date().toISOString(),
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

function mockListSuccess(datasources: DataSource[]) {
	mockListDatasources.mockReturnValue({
		match: (onOk: (ds: DataSource[]) => void) => {
			onOk(datasources);
			return Promise.resolve();
		}
	});
}

function mockListError(message: string) {
	mockListDatasources.mockReturnValue({
		match: (_onOk: unknown, onErr: (e: { message: string }) => void) => {
			onErr({ message });
			return Promise.resolve();
		}
	});
}

function mockUploadSuccess(datasource: DataSource) {
	mockUploadFile.mockReturnValue({
		match: (onOk: (ds: DataSource) => DataSource) => {
			return Promise.resolve(onOk(datasource));
		}
	});
}

function mockUploadError(message: string) {
	mockUploadFile.mockReturnValue({
		match: (_onOk: unknown, onErr: (e: { message: string }) => never) => {
			return Promise.resolve().then(() => onErr({ message }));
		}
	});
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

function mockDeleteSuccess() {
	mockDeleteDatasource.mockReturnValue({
		match: (onOk: () => void) => {
			onOk();
			return Promise.resolve();
		}
	});
}

function mockDeleteError(message: string) {
	mockDeleteDatasource.mockReturnValue({
		match: (_onOk: unknown, onErr: (e: { message: string }) => void) => {
			onErr({ message });
			return Promise.resolve();
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
		test('datasources is empty array', () => {
			expect(store.datasources).toEqual([]);
		});

		test('loading is false', () => {
			expect(store.loading).toBe(false);
		});

		test('error is null', () => {
			expect(store.error).toBeNull();
		});

		test('schemas map is empty', () => {
			expect(store.schemas.size).toBe(0);
		});
	});

	describe('loadDatasources', () => {
		test('success populates datasources and clears loading', async () => {
			const ds = [makeDatasource({ id: 'ds-1' }), makeDatasource({ id: 'ds-2' })];
			mockListSuccess(ds);

			await store.loadDatasources();

			expect(store.datasources).toHaveLength(2);
			expect(store.datasources[0].id).toBe('ds-1');
			expect(store.loading).toBe(false);
			expect(store.error).toBeNull();
		});

		test('error sets error message and clears loading', async () => {
			mockListError('Network error');

			await store.loadDatasources();

			expect(store.error).toBe('Network error');
			expect(store.loading).toBe(false);
			expect(store.datasources).toEqual([]);
		});

		test('passes includeHidden=false by default', async () => {
			mockListSuccess([]);
			await store.loadDatasources();
			expect(mockListDatasources).toHaveBeenCalledWith(false);
		});

		test('passes includeHidden=true when specified', async () => {
			mockListSuccess([]);
			await store.loadDatasources(true);
			expect(mockListDatasources).toHaveBeenCalledWith(true);
		});

		test('replaces previous datasources on reload', async () => {
			mockListSuccess([makeDatasource({ id: 'ds-old' })]);
			await store.loadDatasources();
			expect(store.datasources).toHaveLength(1);

			mockListSuccess([makeDatasource({ id: 'ds-new-a' }), makeDatasource({ id: 'ds-new-b' })]);
			await store.loadDatasources();
			expect(store.datasources).toHaveLength(2);
			expect(store.datasources[0].id).toBe('ds-new-a');
		});
	});

	describe('uploadFile', () => {
		test('success appends datasource and returns it', async () => {
			const ds = makeDatasource({ id: 'ds-uploaded', name: 'upload.csv' });
			mockUploadSuccess(ds);

			const file = new File(['data'], 'upload.csv');
			const result = await store.uploadFile(file, 'upload.csv');

			expect(result.id).toBe('ds-uploaded');
			expect(store.datasources).toHaveLength(1);
			expect(store.datasources[0].id).toBe('ds-uploaded');
			expect(store.loading).toBe(false);
		});

		test('appends to existing datasources', async () => {
			mockListSuccess([makeDatasource({ id: 'ds-existing' })]);
			await store.loadDatasources();

			const ds = makeDatasource({ id: 'ds-new' });
			mockUploadSuccess(ds);
			await store.uploadFile(new File(['x'], 'f.csv'), 'f.csv');

			expect(store.datasources).toHaveLength(2);
		});

		test('error sets error and throws', async () => {
			mockUploadError('File too large');

			const file = new File(['data'], 'big.csv');
			await expect(store.uploadFile(file, 'big.csv')).rejects.toThrow('File too large');
			expect(store.error).toBe('File too large');
			expect(store.loading).toBe(false);
		});
	});

	describe('getSchema', () => {
		test('fetches and caches schema', async () => {
			const s = makeSchema();
			mockSchemaSuccess(s);
			store.datasources = [makeDatasource({ id: 'ds-1' })];

			const result = await store.getSchema('ds-1');

			expect(result).toEqual(s);
			expect(store.schemas.get('ds-1')).toEqual(s);
			expect(mockGetDatasourceSchema).toHaveBeenCalledTimes(1);
		});

		test('returns cached schema without API call', async () => {
			const s = makeSchema();
			store.schemas.set('ds-1', s);
			store.datasources = [makeDatasource({ id: 'ds-1' })];

			const result = await store.getSchema('ds-1');

			expect(result).toEqual(s);
			expect(mockGetDatasourceSchema).not.toHaveBeenCalled();
		});

		test('bypasses cache when sheetName is provided', async () => {
			const cached = makeSchema({ row_count: 5 });
			const fresh = makeSchema({ row_count: 100 });
			store.schemas.set('ds-1', cached);
			store.datasources = [makeDatasource({ id: 'ds-1' })];
			mockSchemaSuccess(fresh);

			const result = await store.getSchema('ds-1', 'Sheet2');

			expect(result).toEqual(fresh);
			expect(mockGetDatasourceSchema).toHaveBeenCalledTimes(1);
		});

		test('does not cache when sheetName is provided', async () => {
			const s = makeSchema();
			store.datasources = [makeDatasource({ id: 'ds-1' })];
			mockSchemaSuccess(s);

			await store.getSchema('ds-1', 'Sheet2');

			expect(store.schemas.has('ds-1')).toBe(false);
		});

		test('throws for analysis source_type', async () => {
			store.datasources = [makeDatasource({ id: 'ds-analysis', source_type: 'analysis' })];

			await expect(store.getSchema('ds-analysis')).rejects.toThrow(
				'Schema must be fetched via analysis output'
			);
			expect(mockGetDatasourceSchema).not.toHaveBeenCalled();
		});

		test('throws on API error', async () => {
			store.datasources = [makeDatasource({ id: 'ds-1' })];
			mockSchemaError('Not found');

			await expect(store.getSchema('ds-1')).rejects.toThrow('Failed to get schema');
		});
	});

	describe('deleteDatasource', () => {
		test('removes datasource from list and schema cache', async () => {
			const ds1 = makeDatasource({ id: 'ds-1' });
			const ds2 = makeDatasource({ id: 'ds-2' });
			store.datasources = [ds1, ds2];
			store.schemas.set('ds-1', makeSchema());
			mockDeleteSuccess();

			await store.deleteDatasource('ds-1');

			expect(store.datasources).toHaveLength(1);
			expect(store.datasources[0].id).toBe('ds-2');
			expect(store.schemas.has('ds-1')).toBe(false);
			expect(store.loading).toBe(false);
		});

		test('error sets error and preserves datasources', async () => {
			store.datasources = [makeDatasource({ id: 'ds-1' })];
			mockDeleteError('Permission denied');

			await store.deleteDatasource('ds-1');

			expect(store.error).toBe('Permission denied');
			expect(store.datasources).toHaveLength(1);
			expect(store.loading).toBe(false);
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
		test('clears all state', async () => {
			mockListSuccess([makeDatasource({ id: 'ds-1' })]);
			await store.loadDatasources();
			store.schemas.set('ds-1', makeSchema());
			store.error = 'stale error';

			store.reset();

			expect(store.datasources).toEqual([]);
			expect(store.schemas.size).toBe(0);
			expect(store.error).toBeNull();
			expect(store.loading).toBe(false);
		});
	});
});
