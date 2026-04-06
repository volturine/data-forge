import { describe, test, expect, vi, beforeEach } from 'vitest';
import type { Schema } from '$lib/types/schema';

let mockPipeline: Array<{
	id: string;
	type: string;
	config: Record<string, unknown>;
	depends_on: string[];
	is_applied: boolean;
}> = [];
let mockActiveTab: { datasource: { id: string } } | null = null;
let mockActiveSchemaKey: string | null = null;
const mockSourceSchemas = new Map<
	string,
	{ columns: Array<{ name: string; dtype: string; nullable: boolean }>; row_count: number | null }
>();

vi.mock('$lib/stores/analysis.svelte', () => ({
	analysisStore: {
		get activeTab() {
			return mockActiveTab;
		},
		get pipeline() {
			return mockPipeline;
		},
		get activeSchemaKey() {
			return mockActiveSchemaKey;
		},
		get sourceSchemas() {
			return mockSourceSchemas;
		}
	}
}));

vi.mock('$lib/utils/column-types', () => ({
	resolveColumnType: (type?: string | null) => type ?? 'Any'
}));

const { SchemaStore } = await import('./schema.svelte');

function col(name: string, dtype = 'String', nullable = false) {
	return { name, dtype, nullable };
}

function schema(
	columns: Array<{ name: string; dtype: string; nullable: boolean }>,
	count: number | null = null
): Schema {
	return { columns, row_count: count };
}

describe('SchemaStore', () => {
	let store: InstanceType<typeof SchemaStore>;

	beforeEach(() => {
		vi.clearAllMocks();
		mockPipeline = [];
		mockActiveTab = null;
		mockActiveSchemaKey = null;
		mockSourceSchemas.clear();
		store = new SchemaStore();
	});

	describe('initial state', () => {
		test('joinSchemas is empty', () => {
			expect(store.joinSchemas.size).toBe(0);
		});

		test('previewSchemas is empty', () => {
			expect(store.previewSchemas.size).toBe(0);
		});
	});

	describe('join schema management', () => {
		test('setJoinDatasource stores schema', () => {
			const s = schema([col('id', 'Int64')]);
			store.setJoinDatasource('ds-right', s);
			expect(store.joinSchemas.get('ds-right')).toEqual(s);
		});

		test('getJoinSchema returns stored schema', () => {
			const s = schema([col('x')]);
			store.setJoinDatasource('ds-1', s);
			expect(store.getJoinSchema('ds-1')).toEqual(s);
		});

		test('getJoinSchema returns null for missing key', () => {
			expect(store.getJoinSchema('missing')).toBeNull();
		});

		test('removeJoinDatasource deletes schema', () => {
			store.setJoinDatasource('ds-1', schema([col('a')]));
			store.removeJoinDatasource('ds-1');
			expect(store.getJoinSchema('ds-1')).toBeNull();
			expect(store.joinSchemas.size).toBe(0);
		});

		test('removeJoinDatasource is noop for missing key', () => {
			store.setJoinDatasource('ds-1', schema([col('a')]));
			store.removeJoinDatasource('ds-missing');
			expect(store.joinSchemas.size).toBe(1);
		});

		test('overwriting join schema replaces previous', () => {
			store.setJoinDatasource('ds-1', schema([col('a')]));
			store.setJoinDatasource('ds-1', schema([col('b'), col('c')]));
			const s = store.getJoinSchema('ds-1');
			expect(s?.columns).toHaveLength(2);
			expect(s?.columns[0].name).toBe('b');
		});
	});

	describe('preview schema management', () => {
		test('setPreviewSchema stores entry with hash', () => {
			store.setPreviewSchema('step-1', ['a', 'b'], { a: 'Int64', b: 'String' }, 'hash-123');

			const entry = store.previewSchemas.get('step-1');
			expect(entry).toBeDefined();
			expect(entry?.hash).toBe('hash-123');
			expect(entry?.schema.columns).toHaveLength(2);
			expect(entry?.schema.columns[0].name).toBe('a');
			expect(entry?.schema.columns[0].dtype).toBe('Int64');
		});

		test('setPreviewSchema with null hash stores null', () => {
			store.setPreviewSchema('step-1', ['x'], undefined, null);
			expect(store.previewSchemas.get('step-1')?.hash).toBeNull();
		});

		test('setPreviewSchema without hash defaults to null', () => {
			store.setPreviewSchema('step-1', ['x']);
			expect(store.previewSchemas.get('step-1')?.hash).toBeNull();
		});

		test('setPreviewSchema columns are nullable', () => {
			store.setPreviewSchema('step-1', ['x']);
			expect(store.previewSchemas.get('step-1')?.schema.columns[0].nullable).toBe(true);
		});

		test('setPreviewSchema resolves column types', () => {
			store.setPreviewSchema('step-1', ['a'], { a: 'Float64' });
			expect(store.previewSchemas.get('step-1')?.schema.columns[0].dtype).toBe('Float64');
		});

		test('setPreviewSchema uses "Any" for missing column type', () => {
			store.setPreviewSchema('step-1', ['a'], {});
			expect(store.previewSchemas.get('step-1')?.schema.columns[0].dtype).toBe('Any');
		});

		test('clearPreviewSchema removes entry', () => {
			store.setPreviewSchema('step-1', ['a']);
			store.clearPreviewSchema('step-1');
			expect(store.previewSchemas.has('step-1')).toBe(false);
		});

		test('clearPreviewSchema is noop for missing key', () => {
			store.setPreviewSchema('step-1', ['a']);
			store.clearPreviewSchema('step-missing');
			expect(store.previewSchemas.size).toBe(1);
		});
	});

	describe('syncPreviewSchema', () => {
		test('sets preview schema from response', () => {
			store.syncPreviewSchema(
				'step-1',
				{ columns: ['x', 'y'], column_types: { x: 'Int64', y: 'String' } },
				'hash-abc'
			);

			const entry = store.previewSchemas.get('step-1');
			expect(entry?.schema.columns).toHaveLength(2);
			expect(entry?.hash).toBe('hash-abc');
		});

		test('skips when columns is empty', () => {
			store.syncPreviewSchema('step-1', { columns: [], column_types: {} }, 'hash-abc');
			expect(store.previewSchemas.has('step-1')).toBe(false);
		});

		test('skips when columns is undefined', () => {
			store.syncPreviewSchema('step-1', { column_types: { x: 'Int64' } }, 'hash-abc');
			expect(store.previewSchemas.has('step-1')).toBe(false);
		});

		test('skips when column_types is undefined', () => {
			store.syncPreviewSchema('step-1', { columns: ['x'] }, 'hash-abc');
			expect(store.previewSchemas.has('step-1')).toBe(false);
		});
	});

	describe('stepSchemas with empty pipeline', () => {
		test('getInput returns null for unknown step', () => {
			expect(store.getInput('nonexistent')).toBeNull();
		});

		test('getOutput returns null for unknown step', () => {
			expect(store.getOutput('nonexistent')).toBeNull();
		});

		test('getLastOutput returns null with no steps', () => {
			expect(store.getLastOutput()).toBeNull();
		});

		test('getAllOutputs returns empty array with no steps', () => {
			expect(store.getAllOutputs()).toEqual([]);
		});
	});

	describe('stepSchemas with pipeline steps', () => {
		test('single passthrough step uses source schema as input', () => {
			const sourceSchema = schema([col('id', 'Int64'), col('name', 'String')]);
			mockActiveTab = { datasource: { id: 'ds-1' } };
			mockActiveSchemaKey = 'ds-1';
			mockSourceSchemas.set('ds-1', sourceSchema);
			mockPipeline = [
				{
					id: 'step-1',
					type: 'filter',
					config: { conditions: [] },
					depends_on: [],
					is_applied: true
				}
			];

			store = new SchemaStore();

			const input = store.getInput('step-1');
			expect(input?.columns).toHaveLength(2);
			expect(input?.columns[0].name).toBe('id');
		});

		test('unapplied step passes input through as output', () => {
			const sourceSchema = schema([col('id', 'Int64')]);
			mockActiveTab = { datasource: { id: 'ds-1' } };
			mockActiveSchemaKey = 'ds-1';
			mockSourceSchemas.set('ds-1', sourceSchema);
			mockPipeline = [
				{ id: 'step-1', type: 'filter', config: {}, depends_on: [], is_applied: false }
			];

			store = new SchemaStore();

			const input = store.getInput('step-1');
			const output = store.getOutput('step-1');
			expect(output).toEqual(input);
		});

		test('getLastOutput returns output of last step', () => {
			const sourceSchema = schema([col('a')]);
			mockActiveTab = { datasource: { id: 'ds-1' } };
			mockActiveSchemaKey = 'ds-1';
			mockSourceSchemas.set('ds-1', sourceSchema);
			mockPipeline = [
				{
					id: 'step-1',
					type: 'filter',
					config: { conditions: [] },
					depends_on: [],
					is_applied: true
				},
				{
					id: 'step-2',
					type: 'filter',
					config: { conditions: [] },
					depends_on: ['step-1'],
					is_applied: true
				}
			];

			store = new SchemaStore();

			const last = store.getLastOutput();
			expect(last).not.toBeNull();
		});

		test('getAllOutputs returns one output per step', () => {
			mockActiveTab = { datasource: { id: 'ds-1' } };
			mockActiveSchemaKey = 'ds-1';
			mockSourceSchemas.set('ds-1', schema([col('a')]));
			mockPipeline = [
				{ id: 's1', type: 'filter', config: {}, depends_on: [], is_applied: true },
				{ id: 's2', type: 'filter', config: {}, depends_on: ['s1'], is_applied: true }
			];

			store = new SchemaStore();

			expect(store.getAllOutputs()).toHaveLength(2);
		});

		test('no source schema yields empty input', () => {
			mockActiveTab = { datasource: { id: 'ds-1' } };
			mockActiveSchemaKey = null;
			mockPipeline = [
				{ id: 'step-1', type: 'filter', config: {}, depends_on: [], is_applied: true }
			];

			store = new SchemaStore();

			const input = store.getInput('step-1');
			expect(input?.columns).toEqual([]);
		});
	});

	describe('reset', () => {
		test('clears joinSchemas and previewSchemas', () => {
			store.setJoinDatasource('ds-1', schema([col('a')]));
			store.setPreviewSchema('step-1', ['x']);

			store.reset();

			expect(store.joinSchemas.size).toBe(0);
			expect(store.previewSchemas.size).toBe(0);
		});

		test('reset is idempotent', () => {
			store.reset();
			store.reset();
			expect(store.joinSchemas.size).toBe(0);
			expect(store.previewSchemas.size).toBe(0);
		});
	});
});
