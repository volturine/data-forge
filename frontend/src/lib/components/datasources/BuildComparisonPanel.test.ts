import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import BuildComparisonPanel from './BuildComparisonPanel.svelte';
import type { DataSource } from '$lib/types/datasource';
import type { EngineRun } from '$lib/api/engine-runs';
import type { SnapshotCompareResponse } from '$lib/api/datasource';

const mockListEngineRuns = vi.fn();
const mockListIcebergSnapshots = vi.fn();
const mockCompareDatasourceSnapshots = vi.fn();

vi.mock('$lib/api/engine-runs', () => ({
	listEngineRuns: (...args: unknown[]) => mockListEngineRuns(...args)
}));

vi.mock('$lib/api/datasource', () => ({
	listIcebergSnapshots: (...args: unknown[]) => mockListIcebergSnapshots(...args),
	compareDatasourceSnapshots: (...args: unknown[]) => mockCompareDatasourceSnapshots(...args)
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

let runsQueryState = makeQueryResult();
let snapshotsQueryState = makeQueryResult();

vi.mock('@tanstack/svelte-query', () => ({
	createQuery: (optsFn: () => Record<string, unknown>) => {
		const opts = optsFn();
		const key = (opts.queryKey as string[])[0];
		if (key === 'engine-runs') return runsQueryState;
		if (key === 'iceberg-snapshots') return snapshotsQueryState;
		return makeQueryResult();
	},
	createMutation: () => ({
		mutate: vi.fn(),
		isPending: false
	}),
	useQueryClient: () => ({
		invalidateQueries: vi.fn()
	})
}));

function makeDatasource(overrides: Partial<DataSource> = {}): DataSource {
	return {
		id: 'ds-1',
		name: 'Test DS',
		source_type: 'iceberg',
		config: { metadata_path: '/tmp/metadata.json' },
		schema_cache: null,
		created_at: '2024-01-01',
		created_by: 'test',
		is_hidden: false,
		...overrides
	} as DataSource;
}

function makeRun(overrides: Partial<EngineRun> = {}): EngineRun {
	return {
		id: 'run-1',
		analysis_id: null,
		datasource_id: 'ds-1',
		kind: 'datasource_update',
		status: 'success',
		request_json: {},
		result_json: null,
		error_message: null,
		created_at: '2024-06-15T12:00:00Z',
		completed_at: '2024-06-15T12:01:00Z',
		duration_ms: 60000,
		step_timings: {},
		query_plan: null,
		progress: 100,
		current_step: null,
		triggered_by: null,
		...overrides
	};
}

function renderPanel(props: Record<string, unknown> = {}) {
	return render(BuildComparisonPanel, {
		props: {
			datasource: makeDatasource(),
			...props
		}
	});
}

beforeEach(() => {
	runsQueryState = makeQueryResult();
	snapshotsQueryState = makeQueryResult();
});

describe('BuildComparisonPanel', () => {
	describe('header', () => {
		test('renders panel title', () => {
			renderPanel();
			expect(screen.getByText('Build Comparison')).toBeInTheDocument();
		});
	});

	describe('non-iceberg fallback', () => {
		test('shows message for non-iceberg datasources', () => {
			renderPanel({ datasource: makeDatasource({ source_type: 'file' }) });
			expect(
				screen.getByText('Snapshot comparison is only available for Iceberg datasources.')
			).toBeInTheDocument();
		});

		test('does not show select builds section for non-iceberg', () => {
			renderPanel({ datasource: makeDatasource({ source_type: 'database' }) });
			expect(screen.queryByText('Select builds')).not.toBeInTheDocument();
		});
	});

	describe('loading state', () => {
		test('shows loading indicator while runs load', () => {
			runsQueryState = makeQueryResult({ isLoading: true });
			renderPanel();
			expect(screen.getByText('Loading runs...')).toBeInTheDocument();
		});
	});

	describe('error state', () => {
		test('shows error when runs query fails', () => {
			runsQueryState = makeQueryResult({
				isError: true,
				error: new Error('Connection refused')
			});
			renderPanel();
			expect(screen.getByText('Connection refused')).toBeInTheDocument();
		});
	});

	describe('empty state', () => {
		test('shows empty message when no runs found', () => {
			runsQueryState = makeQueryResult({ isSuccess: true, data: [] });
			renderPanel();
			expect(screen.getByText('No successful datasource builds recorded.')).toBeInTheDocument();
		});
	});

	describe('run selection', () => {
		test('renders run list when data available', () => {
			const runs = [
				makeRun({ id: 'run-aaa-1111' }),
				makeRun({ id: 'run-bbb-2222', created_at: '2024-06-16T12:00:00Z' })
			];
			runsQueryState = makeQueryResult({ isSuccess: true, data: runs });
			snapshotsQueryState = makeQueryResult({ data: [] });
			renderPanel();
			expect(screen.getByText('run-aaa-...')).toBeInTheDocument();
			expect(screen.getByText('run-bbb-...')).toBeInTheDocument();
		});

		test('shows selected builds counter at 0/2 initially', () => {
			runsQueryState = makeQueryResult({ isSuccess: true, data: [makeRun()] });
			snapshotsQueryState = makeQueryResult({ data: [] });
			renderPanel();
			expect(screen.getByText('0/2 builds selected')).toBeInTheDocument();
		});

		test('shows prompt to select two builds', () => {
			runsQueryState = makeQueryResult({ isSuccess: true, data: [makeRun()] });
			snapshotsQueryState = makeQueryResult({ data: [] });
			renderPanel();
			expect(screen.getByText('Select two builds to compare.')).toBeInTheDocument();
		});

		test('search input is visible', () => {
			runsQueryState = makeQueryResult({ isSuccess: true, data: [makeRun()] });
			snapshotsQueryState = makeQueryResult({ data: [] });
			renderPanel();
			expect(screen.getByLabelText('Search builds')).toBeInTheDocument();
		});

		test('clicking a run button changes counter to 1/2', async () => {
			const runs = [
				makeRun({ id: 'run-aaa-1111' }),
				makeRun({ id: 'run-bbb-2222', created_at: '2024-06-16T12:00:00Z' })
			];
			runsQueryState = makeQueryResult({ isSuccess: true, data: runs });
			snapshotsQueryState = makeQueryResult({ data: [] });
			renderPanel();

			expect(screen.getByText('0/2 builds selected')).toBeInTheDocument();
			const runButton = screen.getByText('run-aaa-...').closest('button')!;
			await fireEvent.click(runButton);
			expect(screen.getByText('1/2 builds selected')).toBeInTheDocument();
		});

		test('clicking two run buttons changes counter to 2/2', async () => {
			const runs = [
				makeRun({ id: 'run-aaa-1111' }),
				makeRun({ id: 'run-bbb-2222', created_at: '2024-06-16T12:00:00Z' })
			];
			runsQueryState = makeQueryResult({ isSuccess: true, data: runs });
			snapshotsQueryState = makeQueryResult({ data: [] });
			renderPanel();

			await fireEvent.click(screen.getByText('run-aaa-...').closest('button')!);
			await fireEvent.click(screen.getByText('run-bbb-...').closest('button')!);
			expect(screen.getByText('2/2 builds selected')).toBeInTheDocument();
		});

		test('third selection is ignored when already at 2', async () => {
			const runs = [
				makeRun({ id: 'run-aaa-1111' }),
				makeRun({ id: 'run-bbb-2222', created_at: '2024-06-16T12:00:00Z' }),
				makeRun({ id: 'run-ccc-3333', created_at: '2024-06-17T12:00:00Z' })
			];
			runsQueryState = makeQueryResult({ isSuccess: true, data: runs });
			snapshotsQueryState = makeQueryResult({ data: [] });
			renderPanel();

			await fireEvent.click(screen.getByText('run-aaa-...').closest('button')!);
			await fireEvent.click(screen.getByText('run-bbb-...').closest('button')!);
			expect(screen.getByText('2/2 builds selected')).toBeInTheDocument();

			await fireEvent.click(screen.getByText('run-ccc-...').closest('button')!);
			expect(screen.getByText('2/2 builds selected')).toBeInTheDocument();
		});

		test('deselecting a run removes it from selection', async () => {
			const runs = [
				makeRun({ id: 'run-aaa-1111' }),
				makeRun({ id: 'run-bbb-2222', created_at: '2024-06-16T12:00:00Z' })
			];
			runsQueryState = makeQueryResult({ isSuccess: true, data: runs });
			snapshotsQueryState = makeQueryResult({ data: [] });
			renderPanel();

			const runButton = screen.getByText('run-aaa-...').closest('button')!;
			await fireEvent.click(runButton);
			expect(screen.getByText('1/2 builds selected')).toBeInTheDocument();

			const runButtons = screen.getAllByText('run-aaa-...');
			const listButton = runButtons
				.map((el) => el.closest('button')!)
				.find((btn) => !btn.closest('[title="Remove selection"]'))!;
			await fireEvent.click(listButton);
			expect(screen.getByText('0/2 builds selected')).toBeInTheDocument();
		});

		test('remove button in selected builds section deselects run', async () => {
			const runs = [
				makeRun({ id: 'run-aaa-1111' }),
				makeRun({ id: 'run-bbb-2222', created_at: '2024-06-16T12:00:00Z' })
			];
			runsQueryState = makeQueryResult({ isSuccess: true, data: runs });
			snapshotsQueryState = makeQueryResult({ data: [] });
			renderPanel();

			await fireEvent.click(screen.getByText('run-aaa-...').closest('button')!);
			expect(screen.getByText('1/2 builds selected')).toBeInTheDocument();

			const removeButton = screen.getByTitle('Remove selection');
			await fireEvent.click(removeButton);
			expect(screen.getByText('0/2 builds selected')).toBeInTheDocument();
		});
	});

	describe('search filtering', () => {
		test('search input filters visible runs', async () => {
			const runs = [
				makeRun({ id: 'run-aaa-1111' }),
				makeRun({ id: 'run-bbb-2222', created_at: '2024-06-16T12:00:00Z' })
			];
			runsQueryState = makeQueryResult({ isSuccess: true, data: runs });
			snapshotsQueryState = makeQueryResult({ data: [] });
			renderPanel();

			expect(screen.getByText('run-aaa-...')).toBeInTheDocument();
			expect(screen.getByText('run-bbb-...')).toBeInTheDocument();

			const searchInput = screen.getByLabelText('Search builds');
			await fireEvent.input(searchInput, { target: { value: 'aaa' } });

			expect(screen.getByText('run-aaa-...')).toBeInTheDocument();
			expect(screen.queryByText('run-bbb-...')).not.toBeInTheDocument();
		});

		test('search shows "No builds match" when nothing matches', async () => {
			const runs = [makeRun({ id: 'run-aaa-1111' })];
			runsQueryState = makeQueryResult({ isSuccess: true, data: runs });
			snapshotsQueryState = makeQueryResult({ data: [] });
			renderPanel();

			const searchInput = screen.getByLabelText('Search builds');
			await fireEvent.input(searchInput, { target: { value: 'zzz-nonexistent' } });

			expect(screen.getByText('No builds match your search.')).toBeInTheDocument();
		});
	});

	describe('compare button', () => {
		test('shows selected builds section when runs available', () => {
			const runs = [makeRun({ id: 'run-aaa-1111' }), makeRun({ id: 'run-bbb-2222' })];
			runsQueryState = makeQueryResult({ isSuccess: true, data: runs });
			snapshotsQueryState = makeQueryResult({ data: [] });
			renderPanel();
			expect(screen.getByText('Selected builds')).toBeInTheDocument();
		});

		test('shows prompt to select two builds when none selected', () => {
			const runs = [makeRun({ id: 'run-aaa-1111' }), makeRun({ id: 'run-bbb-2222' })];
			runsQueryState = makeQueryResult({ isSuccess: true, data: runs });
			snapshotsQueryState = makeQueryResult({ data: [] });
			renderPanel();
			expect(screen.getByText('Select two builds to compare.')).toBeInTheDocument();
		});

		test('compare button appears after selecting one run', async () => {
			const runs = [
				makeRun({ id: 'run-aaa-1111' }),
				makeRun({ id: 'run-bbb-2222', created_at: '2024-06-16T12:00:00Z' })
			];
			runsQueryState = makeQueryResult({ isSuccess: true, data: runs });
			snapshotsQueryState = makeQueryResult({ data: [] });
			renderPanel();

			await fireEvent.click(screen.getByText('run-aaa-...').closest('button')!);
			expect(screen.getByText('Compare snapshots')).toBeInTheDocument();
		});

		test('compare button is disabled with only one selection', async () => {
			const runs = [
				makeRun({ id: 'run-aaa-1111' }),
				makeRun({ id: 'run-bbb-2222', created_at: '2024-06-16T12:00:00Z' })
			];
			runsQueryState = makeQueryResult({ isSuccess: true, data: runs });
			snapshotsQueryState = makeQueryResult({ data: [] });
			renderPanel();

			await fireEvent.click(screen.getByText('run-aaa-...').closest('button')!);
			const compareBtn = screen.getByText('Compare snapshots').closest('button')!;
			expect(compareBtn).toBeDisabled();
		});

		test('compare button disabled when two selected but snapshot mapping missing', async () => {
			const runs = [
				makeRun({ id: 'run-aaa-1111' }),
				makeRun({ id: 'run-bbb-2222', created_at: '2024-06-16T12:00:00Z' })
			];
			runsQueryState = makeQueryResult({ isSuccess: true, data: runs });
			snapshotsQueryState = makeQueryResult({ data: [] });
			renderPanel();

			await fireEvent.click(screen.getByText('run-aaa-...').closest('button')!);
			await fireEvent.click(screen.getByText('run-bbb-...').closest('button')!);

			const compareBtn = screen.getByText('Compare snapshots').closest('button')!;
			expect(compareBtn).toBeDisabled();
			expect(
				screen.getByText('Snapshot mapping missing for one or both builds.')
			).toBeInTheDocument();
		});

		test('shows "Select one more build" when only 1 selected', async () => {
			const runs = [
				makeRun({ id: 'run-aaa-1111' }),
				makeRun({ id: 'run-bbb-2222', created_at: '2024-06-16T12:00:00Z' })
			];
			runsQueryState = makeQueryResult({ isSuccess: true, data: runs });
			snapshotsQueryState = makeQueryResult({ data: [] });
			renderPanel();

			await fireEvent.click(screen.getByText('run-aaa-...').closest('button')!);
			expect(screen.getByText('Select one more build.')).toBeInTheDocument();
		});

		test('shows info message when some runs selected but no comparison yet', async () => {
			const runs = [
				makeRun({ id: 'run-aaa-1111' }),
				makeRun({ id: 'run-bbb-2222', created_at: '2024-06-16T12:00:00Z' })
			];
			runsQueryState = makeQueryResult({ isSuccess: true, data: runs });
			snapshotsQueryState = makeQueryResult({ data: [] });
			renderPanel();

			await fireEvent.click(screen.getByText('run-aaa-...').closest('button')!);
			expect(
				screen.getByText('Select two builds to enable snapshot comparison.')
			).toBeInTheDocument();
		});
	});

	describe('comparison result', () => {
		function setupWithMappedSnapshots(): SnapshotCompareResponse {
			const runs = [
				makeRun({
					id: 'run-aaa-1111',
					result_json: { snapshot_id: 'snap-100' }
				}),
				makeRun({
					id: 'run-bbb-2222',
					created_at: '2024-06-16T12:00:00Z',
					result_json: { snapshot_id: 'snap-200' }
				})
			];
			const snapshots = [
				{ snapshot_id: 'snap-100', timestamp_ms: 1718450000000 },
				{ snapshot_id: 'snap-200', timestamp_ms: 1718536000000 }
			];
			runsQueryState = makeQueryResult({ isSuccess: true, data: runs });
			snapshotsQueryState = makeQueryResult({ data: snapshots });

			return {
				datasource_id: 'ds-1',
				snapshot_a: 'snap-100',
				snapshot_b: 'snap-200',
				row_count_a: 1000,
				row_count_b: 1200,
				row_count_delta: 200,
				schema_diff: [{ column: 'new_col', status: 'added', type_a: null, type_b: 'String' }],
				stats_a: [{ column: 'id', dtype: 'Int64', null_count: 0, unique_count: 1000 }],
				stats_b: [{ column: 'id', dtype: 'Int64', null_count: 5, unique_count: 1200 }],
				preview_a: { columns: ['id'], column_types: { id: 'Int64' }, data: [], row_count: 1000 },
				preview_b: { columns: ['id'], column_types: { id: 'Int64' }, data: [], row_count: 1200 }
			};
		}

		test('compare button enabled when two runs with snapshots mapped', async () => {
			setupWithMappedSnapshots();
			renderPanel();

			await fireEvent.click(screen.getByText('run-aaa-...').closest('button')!);
			await fireEvent.click(screen.getByText('run-bbb-...').closest('button')!);

			const compareBtn = screen.getByText('Compare snapshots').closest('button')!;
			expect(compareBtn).not.toBeDisabled();
		});

		test('successful comparison renders row counts and schema changes', async () => {
			const comparison = setupWithMappedSnapshots();
			mockCompareDatasourceSnapshots.mockResolvedValue({
				isOk: () => true,
				isErr: () => false,
				value: comparison
			});
			renderPanel();

			await fireEvent.click(screen.getByText('run-aaa-...').closest('button')!);
			await fireEvent.click(screen.getByText('run-bbb-...').closest('button')!);
			await fireEvent.click(screen.getByText('Compare snapshots').closest('button')!);

			await vi.waitFor(() => {
				expect(screen.getByText('Row Count A')).toBeInTheDocument();
			});
			expect(screen.getByText('Row Count B')).toBeInTheDocument();
			expect(screen.getByText('Row Count Delta')).toBeInTheDocument();

			expect(screen.getByText('Schema Changes')).toBeInTheDocument();
			expect(screen.getByText('new_col')).toBeInTheDocument();
			expect(screen.getByText('Added')).toBeInTheDocument();
		});

		test('comparison error shows error message', async () => {
			setupWithMappedSnapshots();
			mockCompareDatasourceSnapshots.mockResolvedValue({
				isOk: () => false,
				isErr: () => true,
				error: { message: 'Snapshot not found' }
			});
			renderPanel();

			await fireEvent.click(screen.getByText('run-aaa-...').closest('button')!);
			await fireEvent.click(screen.getByText('run-bbb-...').closest('button')!);
			await fireEvent.click(screen.getByText('Compare snapshots').closest('button')!);

			await vi.waitFor(() => {
				expect(screen.getByText('Snapshot not found')).toBeInTheDocument();
			});
		});

		test('no schema changes shows "No schema changes detected"', async () => {
			const comparison = setupWithMappedSnapshots();
			comparison.schema_diff = [];
			mockCompareDatasourceSnapshots.mockResolvedValue({
				isOk: () => true,
				isErr: () => false,
				value: comparison
			});
			renderPanel();

			await fireEvent.click(screen.getByText('run-aaa-...').closest('button')!);
			await fireEvent.click(screen.getByText('run-bbb-...').closest('button')!);
			await fireEvent.click(screen.getByText('Compare snapshots').closest('button')!);

			await vi.waitFor(() => {
				expect(screen.getByText('No schema changes detected')).toBeInTheDocument();
			});
		});
	});
});
