import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import DatasourceConfigPanel from './DatasourceConfigPanel.svelte';
import type { DataSource, SchemaInfo } from '$lib/types/datasource';

vi.mock('$lib/stores/namespace.svelte', () => ({
	requireNamespace: () => 'default',
	isNamespaceReady: () => true,
	useNamespace: () => ({ value: 'default', switching: false })
}));

vi.mock('$lib/components/datasources/ColumnStatsPanel.svelte', async () => ({
	default: (await import('$lib/test-utils/stubs/IconStub.svelte')).default
}));

const mockGetDatasource = vi.fn();
const mockGetDatasourceSchema = vi.fn();
const mockIngestDatasource = vi.fn();
const mockUpdateDatasource = vi.fn();
const mockUpdateDatasourceColumnDescriptions = vi.fn();

vi.mock('$lib/api/datasource', () => ({
	getDatasource: (...args: unknown[]) => mockGetDatasource(...args),
	getDatasourceSchema: (...args: unknown[]) => mockGetDatasourceSchema(...args),
	ingestDatasource: (...args: unknown[]) => mockIngestDatasource(...args),
	updateDatasource: (...args: unknown[]) => mockUpdateDatasource(...args),
	updateDatasourceColumnDescriptions: (...args: unknown[]) =>
		mockUpdateDatasourceColumnDescriptions(...args)
}));

const mockBuildLoad = vi.fn();
const mockBuildClose = vi.fn();
const mockBuildReset = vi.fn();

let mockBuilds: unknown[] = [];
let mockBuildStatus = 'disconnected';
let mockBuildError: string | null = null;

vi.mock('$lib/stores/builds.svelte', () => ({
	BuildsStore: class {
		get builds() {
			return mockBuilds;
		}
		get status() {
			return mockBuildStatus;
		}
		get error() {
			return mockBuildError;
		}
		load(params?: unknown) {
			mockBuildLoad(params);
			mockBuildStatus = 'connected';
		}
		refresh() {
			mockBuildLoad('refresh');
			mockBuildStatus = 'connected';
		}
		silentRefresh() {
			mockBuildLoad('silent-refresh');
			mockBuildStatus = 'connected';
		}
		close() {
			mockBuildClose();
		}
		reset() {
			mockBuildReset();
			mockBuildStatus = 'disconnected';
		}
	}
}));

function makeQueryResult(overrides: Record<string, unknown> = {}) {
	return {
		data: undefined,
		error: null,
		isLoading: false,
		isError: false,
		isSuccess: false,
		isFetching: false,
		...overrides
	};
}

let datasourceQueryState = makeQueryResult();
let schemaQueryState = makeQueryResult();

vi.mock('@tanstack/svelte-query', () => ({
	createQuery: (optsFn: () => Record<string, unknown>) => {
		const opts = optsFn();
		const key = (opts.queryKey as string[])[0];
		if (key === 'datasource') return datasourceQueryState;
		if (key === 'datasource-schema') return schemaQueryState;
		return makeQueryResult();
	},
	createMutation: () => ({
		mutateAsync: vi.fn(),
		mutate: vi.fn(),
		isPending: false,
		isError: false,
		isSuccess: false,
		error: null
	}),
	useQueryClient: () => ({
		invalidateQueries: vi.fn(),
		setQueryData: vi.fn()
	})
}));

function makeDatasource(overrides: Partial<DataSource> = {}): DataSource {
	return {
		id: 'ds-1',
		name: 'Test datasource',
		description: null,
		source_type: 'iceberg',
		config: { metadata_path: '/tmp/metadata', branch: 'master' },
		schema_cache: null,
		created_at: '2024-01-01T00:00:00Z',
		created_by: 'import',
		created_by_analysis_id: null,
		is_hidden: false,
		output_of_tab_id: null,
		...overrides
	} as DataSource;
}

function makeSchema(overrides: Partial<SchemaInfo> = {}): SchemaInfo {
	return {
		columns: [],
		row_count: 10,
		...overrides
	};
}

function renderPanel(props: Record<string, unknown> = {}) {
	return render(DatasourceConfigPanel, {
		props: {
			datasource: makeDatasource(),
			...props
		}
	});
}

beforeEach(() => {
	mockGetDatasource.mockReset();
	mockGetDatasourceSchema.mockReset();
	mockIngestDatasource.mockReset();
	mockUpdateDatasource.mockReset();
	mockUpdateDatasourceColumnDescriptions.mockReset();
	mockBuildLoad.mockReset();
	mockBuildClose.mockReset();
	mockBuildReset.mockReset();
	mockBuilds = [];
	mockBuildStatus = 'disconnected';
	mockBuildError = null;
	const datasource = makeDatasource();
	datasourceQueryState = makeQueryResult({ data: datasource });
	schemaQueryState = makeQueryResult({ data: makeSchema() });
});

describe('DatasourceConfigPanel', () => {
	test('does not eagerly load run history on initial render', () => {
		renderPanel();

		expect(mockBuildLoad).not.toHaveBeenCalled();
	});

	test('loads run history only when the Runs tab is opened and keeps requests alive across tab switches', async () => {
		const view = renderPanel();

		await fireEvent.click(screen.getByRole('tab', { name: 'Runs' }));

		expect(mockBuildLoad).toHaveBeenCalledTimes(1);
		expect(mockBuildLoad).toHaveBeenCalledWith({ datasource_id: 'ds-1', limit: 50 });

		await fireEvent.click(screen.getByRole('tab', { name: 'General' }));

		expect(mockBuildClose).not.toHaveBeenCalled();

		view.unmount();

		expect(mockBuildClose).toHaveBeenCalledTimes(1);
	});

	test('clears a custom freshness threshold back to the default', async () => {
		renderPanel({ datasource: makeDatasource({ freshness_threshold_minutes: 90 }) });

		const threshold = screen.getByLabelText('Freshness threshold');
		expect(threshold).toHaveValue('custom');

		await fireEvent.change(threshold, { target: { value: '' } });

		expect(threshold).toHaveValue('');
	});

	test('shows an input for a custom freshness threshold', async () => {
		renderPanel();

		await fireEvent.change(screen.getByLabelText('Freshness threshold'), {
			target: { value: 'custom' }
		});

		expect(screen.getByLabelText('Custom freshness threshold in minutes')).toBeVisible();
	});
});
