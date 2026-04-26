import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import ColumnStatsPanel from './ColumnStatsPanel.svelte';
import type { ColumnStatsResponse } from '$lib/api/datasource';

const mockGetColumnStats = vi.fn();
vi.mock('$lib/api/datasource', () => ({
	getColumnStats: (...args: unknown[]) => mockGetColumnStats(...args)
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

let queryState = makeQueryResult();

vi.mock('@tanstack/svelte-query', () => ({
	createQuery: () => queryState
}));

function makeStats(overrides: Partial<ColumnStatsResponse> = {}): ColumnStatsResponse {
	return {
		column: 'price',
		dtype: 'Float64',
		count: 1000,
		null_count: 50,
		null_percentage: 5.0,
		unique: 950,
		mean: 42.5,
		std: 12.3,
		min: 0.5,
		max: 99.9,
		median: 40.0,
		q25: 25.0,
		q75: 60.0,
		...overrides
	};
}

function renderPanel(props: Record<string, unknown> = {}) {
	return render(ColumnStatsPanel, {
		props: {
			datasourceId: 'ds-1',
			columnName: 'price',
			open: true,
			onClose: vi.fn(),
			...props
		}
	});
}

beforeEach(() => {
	queryState = makeQueryResult();
});

describe('ColumnStatsPanel', () => {
	describe('visibility', () => {
		test('renders panel when open is true', () => {
			renderPanel();
			expect(screen.getByTestId('column-stats-panel')).toBeInTheDocument();
		});

		test('does not render when open is false', () => {
			renderPanel({ open: false });
			expect(screen.queryByTestId('column-stats-panel')).not.toBeInTheDocument();
		});
	});

	describe('header', () => {
		test('shows Column Stats title', () => {
			renderPanel();
			expect(screen.getByText('Column Stats')).toBeInTheDocument();
		});

		test('shows column name in header', () => {
			renderPanel({ columnName: 'revenue' });
			expect(screen.getByText('revenue')).toBeInTheDocument();
		});

		test('shows dtype when stats loaded', () => {
			queryState = makeQueryResult({ data: makeStats({ dtype: 'Int64' }) });
			renderPanel();
			expect(screen.getByText('(Int64)')).toBeInTheDocument();
		});

		test('does not show column name when columnName is null', () => {
			queryState = makeQueryResult();
			renderPanel({ columnName: null });
			const header = screen.getByText('Column Stats');
			const parent = header.parentElement!;
			const spans = parent.querySelectorAll('span');
			const monoSpans = Array.from(spans).filter(
				(s) => s.className.includes('mono') || s.classList.length > 0
			);
			const nonEmptyMonoSpans = monoSpans.filter((s) => s.textContent?.trim());
			expect(nonEmptyMonoSpans.length).toBeLessThanOrEqual(0);
		});
	});

	describe('close button', () => {
		test('renders close button', () => {
			renderPanel();
			expect(screen.getByTestId('column-stats-close')).toBeInTheDocument();
		});

		test('calls onClose when close button clicked', async () => {
			const onClose = vi.fn();
			renderPanel({ onClose });
			await fireEvent.click(screen.getByTestId('column-stats-close'));
			expect(onClose).toHaveBeenCalledOnce();
		});
	});

	describe('loading state', () => {
		test('shows loading text', () => {
			queryState = makeQueryResult({ isLoading: true });
			renderPanel();
			expect(screen.getByText('Computing stats...')).toBeInTheDocument();
		});
	});

	describe('error state', () => {
		test('shows error message', () => {
			queryState = makeQueryResult({
				isLoading: false,
				error: new Error('Column not found')
			});
			renderPanel();
			expect(screen.getByText('Column not found')).toBeInTheDocument();
		});

		test('shows generic message for non-Error', () => {
			queryState = makeQueryResult({
				isLoading: false,
				error: 'unknown'
			});
			renderPanel();
			expect(screen.getByText('Failed to load stats')).toBeInTheDocument();
		});
	});

	describe('overview section', () => {
		test('shows row count', () => {
			queryState = makeQueryResult({ data: makeStats({ count: 5000 }) });
			renderPanel();
			expect(screen.getByText('5,000')).toBeInTheDocument();
		});

		test('shows null count', () => {
			queryState = makeQueryResult({ data: makeStats({ null_count: 123 }) });
			renderPanel();
			expect(screen.getByText('123')).toBeInTheDocument();
		});

		test('shows null percentage', () => {
			queryState = makeQueryResult({ data: makeStats({ null_percentage: 12.5 }) });
			renderPanel();
			expect(screen.getByText('12.50% null')).toBeInTheDocument();
		});

		test('shows unique count', () => {
			queryState = makeQueryResult({ data: makeStats({ unique: 456 }) });
			renderPanel();
			expect(screen.getByText('456')).toBeInTheDocument();
		});

		test('hides unique row when unique is null', () => {
			queryState = makeQueryResult({ data: makeStats({ unique: null }) });
			renderPanel();
			expect(screen.queryByText('Unique')).not.toBeInTheDocument();
		});

		test('hides unique row when unique is undefined', () => {
			queryState = makeQueryResult({ data: makeStats({ unique: undefined }) });
			renderPanel();
			expect(screen.queryByText('Unique')).not.toBeInTheDocument();
		});

		test('shows Overview section label', () => {
			queryState = makeQueryResult({ data: makeStats() });
			renderPanel();
			expect(screen.getByText('Overview')).toBeInTheDocument();
		});

		test('shows column description when provided', () => {
			queryState = makeQueryResult({ data: makeStats() });
			renderPanel({ columnDescription: 'Revenue in USD before tax' });
			expect(screen.getByText('Description')).toBeInTheDocument();
			expect(screen.getByText('Revenue in USD before tax')).toBeInTheDocument();
		});

		test('shows empty description state when missing', () => {
			queryState = makeQueryResult({ data: makeStats() });
			renderPanel({ columnDescription: null });
			expect(screen.getByText('No description')).toBeInTheDocument();
		});
	});

	describe('numeric distribution', () => {
		test('shows distribution section for numeric columns', () => {
			queryState = makeQueryResult({ data: makeStats({ mean: 42.5 }) });
			renderPanel();
			expect(screen.getByText('Distribution')).toBeInTheDocument();
		});

		test('shows mean value', () => {
			queryState = makeQueryResult({ data: makeStats({ mean: 42.5 }) });
			renderPanel();
			expect(screen.getByText('42.50')).toBeInTheDocument();
		});

		test('shows min and max', () => {
			queryState = makeQueryResult({ data: makeStats({ min: 1, max: 100 }) });
			renderPanel();
			expect(screen.getByText('Min')).toBeInTheDocument();
			expect(screen.getByText('Max')).toBeInTheDocument();
		});

		test('shows quartiles when present', () => {
			queryState = makeQueryResult({
				data: makeStats({ q25: 25.0, q75: 75.0 })
			});
			renderPanel();
			expect(screen.getByText('Q25')).toBeInTheDocument();
			expect(screen.getByText('Q75')).toBeInTheDocument();
		});

		test('shows median when present', () => {
			queryState = makeQueryResult({ data: makeStats({ median: 40.0 }) });
			renderPanel();
			expect(screen.getByText('Median')).toBeInTheDocument();
			expect(screen.getByText('40')).toBeInTheDocument();
		});

		test('hides median when null', () => {
			queryState = makeQueryResult({ data: makeStats({ median: null }) });
			renderPanel();
			expect(screen.queryByText('Median')).not.toBeInTheDocument();
		});

		test('shows std when present', () => {
			queryState = makeQueryResult({ data: makeStats({ std: 12.3 }) });
			renderPanel();
			expect(screen.getByText('Std Dev')).toBeInTheDocument();
			expect(screen.getByText('12.30')).toBeInTheDocument();
		});

		test('hides std when null', () => {
			queryState = makeQueryResult({ data: makeStats({ std: null }) });
			renderPanel();
			expect(screen.queryByText('Std Dev')).not.toBeInTheDocument();
		});

		test('does not show distribution section when mean is null', () => {
			queryState = makeQueryResult({
				data: makeStats({ mean: null, std: null, min: null, max: null })
			});
			renderPanel();
			expect(screen.queryByText('Distribution')).not.toBeInTheDocument();
		});
	});

	describe('datetime/range branch', () => {
		test('shows Range section for datetime-like columns', () => {
			queryState = makeQueryResult({
				data: makeStats({
					mean: null,
					std: null,
					min: '2024-01-01T00:00:00Z',
					max: '2024-12-31T23:59:59Z',
					median: null,
					q25: null,
					q75: null
				})
			});
			renderPanel();
			expect(screen.getByText('Range')).toBeInTheDocument();
			expect(screen.getByText('2024-01-01T00:00:00Z')).toBeInTheDocument();
			expect(screen.getByText('2024-12-31T23:59:59Z')).toBeInTheDocument();
		});

		test('does not show Range section when min is numeric', () => {
			queryState = makeQueryResult({
				data: makeStats({ mean: null, min: 10, max: 100, std: null })
			});
			renderPanel();
			expect(screen.queryByText('Range')).not.toBeInTheDocument();
		});

		test('does not show Range section when min is null', () => {
			queryState = makeQueryResult({
				data: makeStats({ mean: null, min: null, max: null, std: null })
			});
			renderPanel();
			expect(screen.queryByText('Range')).not.toBeInTheDocument();
		});
	});

	describe('boolean distribution', () => {
		test('shows boolean stats when true_count present', () => {
			queryState = makeQueryResult({
				data: makeStats({
					mean: null,
					std: null,
					min: null,
					max: null,
					true_count: 700,
					false_count: 300
				})
			});
			renderPanel();
			expect(screen.getByText('Boolean Distribution')).toBeInTheDocument();
			expect(screen.getByText('True: 700')).toBeInTheDocument();
			expect(screen.getByText('False: 300')).toBeInTheDocument();
		});
	});

	describe('string length stats', () => {
		test('shows string length section when min_length present', () => {
			queryState = makeQueryResult({
				data: makeStats({
					mean: null,
					std: null,
					min: null,
					max: null,
					min_length: 2,
					max_length: 100,
					avg_length: 45.5
				})
			});
			renderPanel();
			expect(screen.getByText('String Lengths')).toBeInTheDocument();
		});
	});

	describe('histogram', () => {
		test('shows histogram distribution when bins present', () => {
			queryState = makeQueryResult({
				data: makeStats({
					histogram: [
						{ start: 0, end: 10, count: 100 },
						{ start: 10, end: 20, count: 200 }
					]
				})
			});
			renderPanel();
			const distributions = screen.getAllByText('Distribution');
			expect(distributions.length).toBeGreaterThanOrEqual(1);
		});

		test('single-bin histogram does not render chart', () => {
			queryState = makeQueryResult({
				data: makeStats({
					histogram: [{ start: 0, end: 100, count: 1000 }]
				})
			});
			renderPanel();
			const distributions = screen.queryAllByText('Distribution');
			const histogramDistribution = distributions.filter((el) => {
				const parent = el.closest('div');
				return parent?.querySelector('[title]') !== null;
			});
			expect(histogramDistribution.length).toBe(0);
		});

		test('empty histogram does not render chart', () => {
			queryState = makeQueryResult({
				data: makeStats({ histogram: [] })
			});
			renderPanel();
			expect(screen.queryByTitle(/–/)).not.toBeInTheDocument();
		});
	});

	describe('top values', () => {
		test('shows top values section when present', () => {
			queryState = makeQueryResult({
				data: makeStats({
					mean: null,
					top_values: [
						{ price: 'low', count: 500 },
						{ price: 'high', count: 300 }
					]
				})
			});
			renderPanel();
			expect(screen.getByText('Top Values')).toBeInTheDocument();
		});

		test('shows actual values and counts in top values', () => {
			queryState = makeQueryResult({
				data: makeStats({
					mean: null,
					column: 'category',
					top_values: [
						{ category: 'Electronics', count: 1500 },
						{ category: 'Books', count: 800 },
						{ category: 'Clothing', count: 450 }
					]
				})
			});
			renderPanel({ columnName: 'category' });
			expect(screen.getByText('Electronics')).toBeInTheDocument();
			expect(screen.getByText('1,500')).toBeInTheDocument();
			expect(screen.getByText('Books')).toBeInTheDocument();
			expect(screen.getByText('800')).toBeInTheDocument();
			expect(screen.getByText('Clothing')).toBeInTheDocument();
			expect(screen.getByText('450')).toBeInTheDocument();
		});

		test('does not show top values when array is empty', () => {
			queryState = makeQueryResult({
				data: makeStats({ mean: null, top_values: [] })
			});
			renderPanel();
			expect(screen.queryByText('Top Values')).not.toBeInTheDocument();
		});

		test('does not show top values when null', () => {
			queryState = makeQueryResult({
				data: makeStats({ mean: null, top_values: null })
			});
			renderPanel();
			expect(screen.queryByText('Top Values')).not.toBeInTheDocument();
		});
	});
});
