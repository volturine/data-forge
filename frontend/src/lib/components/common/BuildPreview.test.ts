import { describe, test, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/svelte';
import BuildPreview from './BuildPreview.svelte';
import { BuildStreamStore } from '$lib/stores/build-stream.svelte';
import type { ActiveBuildDetail } from '$lib/types/build-stream';

vi.mock('$lib/api/build-stream', () => ({
	connectBuildStream: () => ({ close: vi.fn() })
}));

vi.mock('$lib/stores/clientIdentity.svelte', () => ({
	getClientIdentity: () => ({ clientId: 'client-1', clientSignature: 'sig-1' })
}));

vi.mock('$lib/stores/namespace.svelte', () => ({
	getNamespace: () => 'default'
}));

const STARTER = { user_id: null, display_name: null, email: null, triggered_by: null };

function makeDetail(overrides: Partial<ActiveBuildDetail> = {}): ActiveBuildDetail {
	return {
		build_id: 'build-1',
		analysis_id: 'analysis-1',
		analysis_name: 'Test Analysis',
		namespace: 'default',
		status: 'running',
		progress: 0.5,
		started_at: '2025-01-01T00:00:00Z',
		starter: STARTER,
		resource_config: null,
		elapsed_ms: 2000,
		estimated_remaining_ms: 2000,
		current_step: 'Loading',
		current_step_index: 0,
		total_steps: 4,
		current_tab_id: null,
		current_tab_name: null,
		total_tabs: 1,
		steps: [],
		query_plans: [],
		latest_resources: null,
		resources: [],
		logs: [],
		results: [],
		duration_ms: null,
		error: null,
		...overrides
	};
}

function renderPreview(detail?: ActiveBuildDetail) {
	const store = new BuildStreamStore();
	if (detail) store.applySnapshot(detail);
	render(BuildPreview, { props: { store } });
	return store;
}

describe('BuildPreview', () => {
	beforeEach(() => {
		vi.restoreAllMocks();
	});

	describe('header', () => {
		test('renders build preview container', () => {
			renderPreview(makeDetail());
			expect(screen.getByTestId('build-preview')).toBeInTheDocument();
		});

		test('shows build id prefix', () => {
			renderPreview(makeDetail({ build_id: 'abcdef1234567890' }));
			expect(screen.getByText('abcdef12')).toBeInTheDocument();
		});

		test('shows status chip for running build', () => {
			renderPreview(makeDetail({ status: 'running', current_step: 'Filtering' }));
			expect(screen.getByText('Filtering')).toBeInTheDocument();
		});

		test('shows Complete chip for completed build', () => {
			renderPreview(
				makeDetail({ status: 'completed', progress: 1, duration_ms: 5000, error: null })
			);
			expect(screen.getByText('Complete')).toBeInTheDocument();
		});

		test('shows Failed chip for failed build', () => {
			renderPreview(makeDetail({ status: 'failed', error: 'Engine crashed' }));
			expect(screen.getByText('Failed')).toBeInTheDocument();
		});
	});

	describe('progress bar', () => {
		test('renders progress bar with correct aria values', () => {
			renderPreview(makeDetail({ progress: 0.42 }));
			const bar = screen.getByTestId('build-progress-bar');
			expect(bar).toHaveAttribute('aria-valuenow', '42');
			expect(bar).toHaveAttribute('aria-valuemin', '0');
			expect(bar).toHaveAttribute('aria-valuemax', '100');
		});

		test('shows step count during running build', () => {
			renderPreview(makeDetail({ current_step_index: 2, total_steps: 8 }));
			expect(screen.getByText('Step 3/8')).toBeInTheDocument();
		});

		test('shows duration after completion', () => {
			renderPreview(
				makeDetail({ status: 'completed', progress: 1, duration_ms: 4500, error: null })
			);
			expect(screen.getByText('Finished in 4.50s')).toBeInTheDocument();
		});
	});

	describe('tabs', () => {
		test('shows Steps tab by default', () => {
			renderPreview(makeDetail());
			const stepsTab = screen.getByRole('tab', { name: /Steps/i });
			expect(stepsTab).toHaveAttribute('aria-selected', 'true');
		});

		test('shows Plan tab when query plans exist', () => {
			renderPreview(
				makeDetail({
					query_plans: [
						{
							tab_id: 't1',
							tab_name: 'Sheet 1',
							optimized_plan: 'SCAN',
							unoptimized_plan: 'SCAN -> PROJECT'
						}
					]
				})
			);
			expect(screen.getByRole('tab', { name: /Plan/i })).toBeInTheDocument();
		});

		test('hides Plan tab when no query plans', () => {
			renderPreview(makeDetail({ query_plans: [] }));
			expect(screen.queryByRole('tab', { name: /Plan/i })).not.toBeInTheDocument();
		});

		test('shows Resources tab when resources exist', () => {
			renderPreview(
				makeDetail({
					latest_resources: {
						sampled_at: '2025-01-01T00:00:01Z',
						cpu_percent: 50,
						memory_mb: 256,
						memory_limit_mb: 1024,
						active_threads: 2,
						max_threads: 8
					}
				})
			);
			expect(screen.getByRole('tab', { name: /Resources/i })).toBeInTheDocument();
		});

		test('shows Logs tab when logs exist', () => {
			renderPreview(
				makeDetail({
					logs: [
						{
							timestamp: '2025-01-01T00:00:00Z',
							level: 'info',
							message: 'Started',
							step_name: null,
							step_id: null,
							tab_id: null,
							tab_name: null
						}
					]
				})
			);
			expect(screen.getByRole('tab', { name: /Logs/i })).toBeInTheDocument();
		});
	});

	describe('steps panel', () => {
		test('shows connecting state when no steps and connecting', () => {
			const store = new BuildStreamStore();
			render(BuildPreview, { props: { store } });
			expect(screen.getByText('Waiting for build to start...')).toBeInTheDocument();
		});

		test('shows step names and states', () => {
			renderPreview(
				makeDetail({
					steps: [
						{
							build_step_index: 0,
							step_index: 0,
							step_id: 's1',
							step_name: 'Load CSV',
							step_type: 'source',
							tab_id: null,
							tab_name: null,
							state: 'completed',
							duration_ms: 100,
							row_count: 500,
							error: null
						},
						{
							build_step_index: 1,
							step_index: 1,
							step_id: 's2',
							step_name: 'Filter',
							step_type: 'filter',
							tab_id: null,
							tab_name: null,
							state: 'running',
							duration_ms: null,
							row_count: null,
							error: null
						}
					]
				})
			);
			expect(screen.getByText('Load CSV')).toBeInTheDocument();
			expect(screen.getByText('Filter')).toBeInTheDocument();
			expect(screen.getByText('500 rows')).toBeInTheDocument();
			expect(screen.getByText('100ms')).toBeInTheDocument();
		});

		test('shows step error text', () => {
			renderPreview(
				makeDetail({
					steps: [
						{
							build_step_index: 0,
							step_index: 0,
							step_id: 's1',
							step_name: 'Transform',
							step_type: 'filter',
							tab_id: null,
							tab_name: null,
							state: 'failed',
							duration_ms: null,
							row_count: null,
							error: 'column not found'
						}
					]
				})
			);
			expect(screen.getByText('error')).toBeInTheDocument();
		});
	});

	describe('plan panel', () => {
		test('switches between optimized and unoptimized plans', async () => {
			renderPreview(
				makeDetail({
					query_plans: [
						{
							tab_id: 't1',
							tab_name: 'Sheet 1',
							optimized_plan: 'OPT PLAN TEXT',
							unoptimized_plan: 'UNOPT PLAN TEXT'
						}
					]
				})
			);

			await fireEvent.click(screen.getByRole('tab', { name: /Plan/i }));
			expect(screen.getByText('OPT PLAN TEXT')).toBeInTheDocument();

			await fireEvent.click(screen.getByText('Unoptimized'));
			expect(screen.getByText('UNOPT PLAN TEXT')).toBeInTheDocument();
		});
	});

	describe('resources panel', () => {
		test('shows CPU and memory values', async () => {
			renderPreview(
				makeDetail({
					latest_resources: {
						sampled_at: '2025-01-01T00:00:01Z',
						cpu_percent: 78.5,
						memory_mb: 512,
						memory_limit_mb: 1024,
						active_threads: 4,
						max_threads: 8
					}
				})
			);

			await fireEvent.click(screen.getByRole('tab', { name: /Resources/i }));
			const panel = screen.getByTestId('build-resources-panel');
			expect(within(panel).getByText('78.5%')).toBeInTheDocument();
			expect(within(panel).getByText('512 MB')).toBeInTheDocument();
			expect(within(panel).getByText('4/8 threads')).toBeInTheDocument();
		});

		test('shows memory warning when above 80%', async () => {
			renderPreview(
				makeDetail({
					latest_resources: {
						sampled_at: '2025-01-01T00:00:01Z',
						cpu_percent: 50,
						memory_mb: 900,
						memory_limit_mb: 1024,
						active_threads: 2,
						max_threads: 4
					}
				})
			);

			await fireEvent.click(screen.getByRole('tab', { name: /Resources/i }));
			expect(screen.getByTestId('memory-warning')).toBeInTheDocument();
		});

		test('does not show memory warning when below 80%', async () => {
			renderPreview(
				makeDetail({
					latest_resources: {
						sampled_at: '2025-01-01T00:00:01Z',
						cpu_percent: 50,
						memory_mb: 400,
						memory_limit_mb: 1024,
						active_threads: 2,
						max_threads: 4
					}
				})
			);

			await fireEvent.click(screen.getByRole('tab', { name: /Resources/i }));
			expect(screen.queryByTestId('memory-warning')).not.toBeInTheDocument();
		});

		test('shows resource config summary when available', async () => {
			renderPreview(
				makeDetail({
					resource_config: { max_threads: 8, max_memory_mb: 2048, streaming_chunk_size: 10000 },
					latest_resources: {
						sampled_at: '2025-01-01T00:00:01Z',
						cpu_percent: 50,
						memory_mb: 256,
						memory_limit_mb: 2048,
						active_threads: 2,
						max_threads: 8
					}
				})
			);

			await fireEvent.click(screen.getByRole('tab', { name: /Resources/i }));
			const config = screen.getByTestId('resource-config-summary');
			expect(within(config).getByText('8')).toBeInTheDocument();
			expect(within(config).getByText('2048 MB')).toBeInTheDocument();
			expect(within(config).getByText('10,000')).toBeInTheDocument();
		});

		test('shows memory warning icon on Resources tab', () => {
			renderPreview(
				makeDetail({
					latest_resources: {
						sampled_at: '2025-01-01T00:00:01Z',
						cpu_percent: 50,
						memory_mb: 900,
						memory_limit_mb: 1024,
						active_threads: 2,
						max_threads: 4
					}
				})
			);

			const resourcesTab = screen.getByRole('tab', { name: /Resources/i });
			expect(resourcesTab).toBeInTheDocument();
		});
	});

	describe('logs panel', () => {
		function makeLogsDetail() {
			return makeDetail({
				logs: [
					{
						timestamp: '2025-01-01T00:00:00Z',
						level: 'info',
						message: 'Build started',
						step_name: null,
						step_id: null,
						tab_id: null,
						tab_name: null
					},
					{
						timestamp: '2025-01-01T00:00:01Z',
						level: 'warning',
						message: 'Low disk space',
						step_name: 'Load',
						step_id: 's1',
						tab_id: null,
						tab_name: null
					},
					{
						timestamp: '2025-01-01T00:00:02Z',
						level: 'error',
						message: 'Column missing',
						step_name: 'Filter',
						step_id: 's2',
						tab_id: null,
						tab_name: null
					}
				]
			});
		}

		test('shows all logs by default', async () => {
			renderPreview(makeLogsDetail());

			await fireEvent.click(screen.getByRole('tab', { name: /Logs/i }));
			const panel = screen.getByTestId('build-logs-panel');
			expect(within(panel).getByText(/Build started/)).toBeInTheDocument();
			expect(within(panel).getByText(/Low disk space/)).toBeInTheDocument();
			expect(within(panel).getByText(/Column missing/)).toBeInTheDocument();
		});

		test('filters to errors only', async () => {
			renderPreview(makeLogsDetail());

			await fireEvent.click(screen.getByRole('tab', { name: /Logs/i }));
			const filter = screen.getByTestId('log-level-filter');
			await fireEvent.click(within(filter).getByText(/Errors/));

			const panel = screen.getByTestId('build-logs-panel');
			expect(within(panel).queryByText(/Build started/)).not.toBeInTheDocument();
			expect(within(panel).queryByText(/Low disk space/)).not.toBeInTheDocument();
			expect(within(panel).getByText(/Column missing/)).toBeInTheDocument();
		});

		test('filters to warnings and errors', async () => {
			renderPreview(makeLogsDetail());

			await fireEvent.click(screen.getByRole('tab', { name: /Logs/i }));
			const filter = screen.getByTestId('log-level-filter');
			await fireEvent.click(within(filter).getByText(/Warn\+/));

			const panel = screen.getByTestId('build-logs-panel');
			expect(within(panel).queryByText(/Build started/)).not.toBeInTheDocument();
			expect(within(panel).getByText(/Low disk space/)).toBeInTheDocument();
			expect(within(panel).getByText(/Column missing/)).toBeInTheDocument();
		});

		test('shows log counts in filter buttons', async () => {
			renderPreview(makeLogsDetail());

			await fireEvent.click(screen.getByRole('tab', { name: /Logs/i }));
			const filter = screen.getByTestId('log-level-filter');
			expect(within(filter).getByText(/All \(3\)/)).toBeInTheDocument();
			expect(within(filter).getByText(/Warn\+ \(2\)/)).toBeInTheDocument();
			expect(within(filter).getByText(/Errors \(1\)/)).toBeInTheDocument();
		});

		test('shows step name in log entry', async () => {
			renderPreview(makeLogsDetail());

			await fireEvent.click(screen.getByRole('tab', { name: /Logs/i }));
			const panel = screen.getByTestId('build-logs-panel');
			expect(within(panel).getByText('[Load]')).toBeInTheDocument();
		});

		test('copy button is present', async () => {
			renderPreview(makeLogsDetail());

			await fireEvent.click(screen.getByRole('tab', { name: /Logs/i }));
			expect(screen.getByTestId('log-copy')).toBeInTheDocument();
		});

		test('copy button calls clipboard API', async () => {
			const writeText = vi.fn().mockResolvedValue(undefined);
			Object.assign(navigator, { clipboard: { writeText } });

			renderPreview(makeLogsDetail());
			await fireEvent.click(screen.getByRole('tab', { name: /Logs/i }));
			await fireEvent.click(screen.getByTestId('log-copy'));

			expect(writeText).toHaveBeenCalledOnce();
			const copied = writeText.mock.calls[0][0];
			expect(copied).toContain('[info] Build started');
			expect(copied).toContain('[warning][Load] Low disk space');
			expect(copied).toContain('[error][Filter] Column missing');
		});
	});

	describe('error display', () => {
		test('shows error callout when build has error', () => {
			renderPreview(makeDetail({ status: 'failed', error: 'Engine crashed unexpectedly' }));
			const errorEl = screen.getByTestId('build-error');
			expect(errorEl).toHaveTextContent('Engine crashed unexpectedly');
		});

		test('does not show error callout when no error', () => {
			renderPreview(makeDetail());
			expect(screen.queryByTestId('build-error')).not.toBeInTheDocument();
		});
	});

	describe('results', () => {
		test('shows results section after completion', () => {
			renderPreview(
				makeDetail({
					status: 'completed',
					progress: 1,
					duration_ms: 5000,
					error: null,
					results: [
						{ tab_id: 't1', tab_name: 'Sheet 1', status: 'success' },
						{ tab_id: 't2', tab_name: 'Sheet 2', status: 'failed', error: 'fail' }
					]
				})
			);
			const results = screen.getByTestId('build-results');
			expect(within(results).getByText('Sheet 1')).toBeInTheDocument();
			expect(within(results).getByText('Sheet 2')).toBeInTheDocument();
		});

		test('does not show results section when no results', () => {
			renderPreview(makeDetail());
			expect(screen.queryByTestId('build-results')).not.toBeInTheDocument();
		});
	});
});
