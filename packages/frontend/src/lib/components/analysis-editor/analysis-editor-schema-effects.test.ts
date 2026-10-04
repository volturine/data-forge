import { beforeEach, describe, expect, test, vi } from 'vitest';

type TestTab = {
	id: string;
	datasource: { id: string; analysis_tab_id: string | null; config: Record<string, unknown> };
};

const mocks = vi.hoisted(() => {
	const sourceSchemas = new Map<string, unknown>();
	return {
		analysisStore: {
			activeTab: null as TestTab | null,
			tabs: [] as TestTab[],
			sourceSchemas,
			setSourceSchema: vi.fn((key: string, value: unknown) => sourceSchemas.set(key, value))
		},
		datasourceStore: { datasources: [] as unknown[] },
		getDatasourceSchema: vi.fn(),
		getStepSchema: vi.fn(),
		track: vi.fn()
	};
});

vi.mock('$lib/stores/analysis.svelte', () => ({ analysisStore: mocks.analysisStore }));
vi.mock('$lib/stores/datasource.svelte', () => ({ datasourceStore: mocks.datasourceStore }));
vi.mock('$lib/stores/schema.svelte', () => ({ schemaStore: {} }));
vi.mock('$lib/api/datasource', () => ({ getDatasourceSchema: mocks.getDatasourceSchema }));
vi.mock('$lib/api/compute', () => ({
	getStepSchema: mocks.getStepSchema
}));
vi.mock('$lib/utils/audit-log', () => ({ track: mocks.track }));

const { setupSourceSchemaLoadingEffect } = await import('./analysis-editor-schema-effects.svelte');

describe('analysis editor source schema loading', () => {
	beforeEach(() => {
		mocks.analysisStore.activeTab = null;
		mocks.analysisStore.tabs = [];
		mocks.analysisStore.sourceSchemas.clear();
		mocks.analysisStore.setSourceSchema.mockClear();
		mocks.getDatasourceSchema.mockReset();
	});

	test('keeps a datasource schema result when the active tab changes but its schema key does not', async () => {
		const datasourceId = '11111111-1111-1111-1111-111111111111';
		mocks.analysisStore.activeTab = {
			id: 'tab-a',
			datasource: { id: datasourceId, analysis_tab_id: null, config: { branch: 'master' } }
		};

		let resolveSchema!: (schema: unknown) => void;
		const pendingSchema = new Promise<unknown>((resolve) => {
			resolveSchema = resolve;
		});
		mocks.getDatasourceSchema.mockReturnValue({
			match: (onSuccess: (schema: unknown) => void, onError: (error: unknown) => void) =>
				pendingSchema.then(onSuccess, onError)
		});

		const loader = setupSourceSchemaLoadingEffect({
			validAnalysisId: () => null,
			analysisId: () => 'analysis-1',
			datasourceId: () => datasourceId,
			schemaKey: () => datasourceId,
			datasources: () => []
		});

		loader.load();
		expect(loader.isLoading()).toBe(true);
		mocks.analysisStore.activeTab = {
			id: 'tab-b',
			datasource: { id: datasourceId, analysis_tab_id: null, config: { branch: 'master' } }
		};

		const schema = {
			columns: [{ name: 'name', dtype: 'String', nullable: true }],
			row_count: 1
		};
		resolveSchema(schema);
		await vi.waitFor(() => {
			expect(mocks.analysisStore.sourceSchemas.get(datasourceId)).toEqual(schema);
		});

		expect(loader.isLoading()).toBe(false);
		expect(mocks.analysisStore.setSourceSchema).toHaveBeenCalledOnce();
		loader.cancel();
	});
});
