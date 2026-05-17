import { describe, test, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import DataTable from './DataTable.svelte';

const columns = ['name', 'age', 'active'];
const data = [
	{ name: 'Alice', age: 30, active: true },
	{ name: 'Bob', age: 25, active: false }
];

function renderTable(props: Record<string, unknown> = {}) {
	return render(DataTable, {
		props: {
			columns,
			data,
			...props
		}
	});
}

describe('DataTable', () => {
	describe('loading state', () => {
		test('shows loading indicator', () => {
			renderTable({ loading: true });
			expect(screen.getByText('Loading')).toBeInTheDocument();
		});

		test('shows loading indicator alongside table when data present', () => {
			renderTable({ loading: true });
			expect(screen.getByText('Loading')).toBeInTheDocument();
			expect(screen.getByRole('table')).toBeInTheDocument();
		});
	});

	describe('error state', () => {
		test('shows error message', () => {
			renderTable({ error: new Error('Something broke') });
			expect(screen.getByText('Something broke')).toBeInTheDocument();
		});

		test('shows generic message for JSON-like errors', () => {
			renderTable({ error: new Error('{"detail":"not found"}') });
			expect(screen.getByText('An error occurred while loading the data.')).toBeInTheDocument();
		});

		test('shows generic message for path-like errors', () => {
			renderTable({ error: new Error('/api/v1/some/endpoint') });
			expect(screen.getByText('An error occurred while loading the data.')).toBeInTheDocument();
		});

		test('renders error container with testid', () => {
			renderTable({ error: new Error('fail') });
			expect(screen.getByTestId('preview-error')).toBeInTheDocument();
		});
	});

	describe('empty state', () => {
		test('shows "No data available" when data is empty', () => {
			renderTable({ data: [] });
			expect(screen.getByText('No data available')).toBeInTheDocument();
		});

		test('shows "Preview" in analysis mode when data is empty', () => {
			renderTable({ data: [], analysis: true });
			expect(screen.getByText('Preview')).toBeInTheDocument();
		});

		test('calls onPreview when clicking preview button', async () => {
			const onPreview = vi.fn();
			renderTable({ data: [], analysis: true, onPreview });
			await fireEvent.click(screen.getByText('Preview'));
			expect(onPreview).toHaveBeenCalledOnce();
		});

		test('handles Enter keydown on preview button', async () => {
			const onPreview = vi.fn();
			renderTable({ data: [], analysis: true, onPreview });
			const button = screen.getByRole('button');
			await fireEvent.keyDown(button, { key: 'Enter' });
			expect(onPreview).toHaveBeenCalledOnce();
		});

		test('handles Space keydown on preview button', async () => {
			const onPreview = vi.fn();
			renderTable({ data: [], analysis: true, onPreview });
			const button = screen.getByRole('button');
			await fireEvent.keyDown(button, { key: ' ' });
			expect(onPreview).toHaveBeenCalledOnce();
		});
	});

	describe('data rendering', () => {
		test('renders table with data', () => {
			renderTable();
			expect(screen.getByRole('table')).toBeInTheDocument();
		});

		test('renders column headers', () => {
			renderTable();
			expect(screen.getByText('name')).toBeInTheDocument();
			expect(screen.getByText('age')).toBeInTheDocument();
			expect(screen.getByText('active')).toBeInTheDocument();
		});

		test('renders cell values', () => {
			renderTable();
			expect(screen.getByText('Alice')).toBeInTheDocument();
			expect(screen.getByText('Bob')).toBeInTheDocument();
		});

		test('formats boolean values', () => {
			renderTable();
			expect(screen.getByText('true')).toBeInTheDocument();
			expect(screen.getByText('false')).toBeInTheDocument();
		});

		test('formats null values as dash', () => {
			renderTable({
				columns: ['val'],
				data: [{ val: null }]
			});
			expect(screen.getByText('-')).toBeInTheDocument();
		});

		test('formats number values with locale string', () => {
			renderTable({
				columns: ['count'],
				data: [{ count: 1234567 }]
			});
			expect(screen.getByText('1,234,567')).toBeInTheDocument();
		});

		test('formats array values', () => {
			renderTable({
				columns: ['tags'],
				data: [{ tags: [1, 2, 3] }],
				columnTypes: { tags: 'List(Int64)' }
			});
			expect(screen.getByText('[1, 2, 3]')).toBeInTheDocument();
		});
	});

	describe('footer', () => {
		test('shows row count in footer by default', () => {
			renderTable();
			expect(screen.getByText('Showing 2 rows')).toBeInTheDocument();
		});

		test('shows singular "row" for single row', () => {
			renderTable({ data: [{ name: 'Alice', age: 30, active: true }] });
			expect(screen.getByText('Showing 1 row')).toBeInTheDocument();
		});

		test('hides footer when showFooter is false', () => {
			renderTable({ showFooter: false });
			expect(screen.queryByText(/Showing/)).not.toBeInTheDocument();
		});

		test('hides footer when loading', () => {
			renderTable({ loading: true });
			expect(screen.queryByText(/Showing/)).not.toBeInTheDocument();
		});
	});

	describe('header bar', () => {
		test('shows header with column filter when showHeader is true', () => {
			renderTable({ showHeader: true });
			expect(screen.getByLabelText('Filter columns')).toBeInTheDocument();
		});

		test('hides header bar by default', () => {
			renderTable();
			expect(screen.queryByLabelText('Filter columns')).not.toBeInTheDocument();
		});
	});

	describe('pagination', () => {
		test('renders pagination controls when enabled', () => {
			const pagination = {
				page: 1,
				canPrev: false,
				canNext: true,
				onPrev: vi.fn(),
				onNext: vi.fn()
			};
			renderTable({ showHeader: true, showPagination: true, pagination });
			expect(screen.getByTestId('pagination-prev')).toBeInTheDocument();
			expect(screen.getByTestId('pagination-next')).toBeInTheDocument();
			expect(screen.getByTestId('pagination-page')).toHaveTextContent('Page 1');
		});

		test('disables prev button when canPrev is false', () => {
			const pagination = {
				page: 1,
				canPrev: false,
				canNext: true,
				onPrev: vi.fn(),
				onNext: vi.fn()
			};
			renderTable({ showHeader: true, showPagination: true, pagination });
			expect(screen.getByTestId('pagination-prev')).toBeDisabled();
		});

		test('disables next button when canNext is false', () => {
			const pagination = {
				page: 3,
				canPrev: true,
				canNext: false,
				onPrev: vi.fn(),
				onNext: vi.fn()
			};
			renderTable({ showHeader: true, showPagination: true, pagination });
			expect(screen.getByTestId('pagination-next')).toBeDisabled();
		});

		test('calls onPrev when prev clicked', async () => {
			const onPrev = vi.fn();
			const pagination = {
				page: 2,
				canPrev: true,
				canNext: true,
				onPrev,
				onNext: vi.fn()
			};
			renderTable({ showHeader: true, showPagination: true, pagination });
			await fireEvent.click(screen.getByTestId('pagination-prev'));
			expect(onPrev).toHaveBeenCalledOnce();
		});

		test('calls onNext when next clicked', async () => {
			const onNext = vi.fn();
			const pagination = {
				page: 1,
				canPrev: false,
				canNext: true,
				onPrev: vi.fn(),
				onNext
			};
			renderTable({ showHeader: true, showPagination: true, pagination });
			await fireEvent.click(screen.getByTestId('pagination-next'));
			expect(onNext).toHaveBeenCalledOnce();
		});
	});

	describe('column menu', () => {
		test('shows column options button', () => {
			renderTable();
			const buttons = screen.getAllByLabelText('Column options');
			expect(buttons.length).toBe(3);
		});

		test('opens column menu on click', async () => {
			renderTable();
			const buttons = screen.getAllByLabelText('Column options');
			await fireEvent.click(buttons[0]);
			expect(screen.getByText('Sort A-Z')).toBeInTheDocument();
			expect(screen.getByText('Sort Z-A')).toBeInTheDocument();
			expect(screen.getByText('Clear sort')).toBeInTheDocument();
			expect(screen.getByText('Pin left')).toBeInTheDocument();
			expect(screen.getByText('Pin right')).toBeInTheDocument();
			expect(screen.getByText('Unpin')).toBeInTheDocument();
			expect(screen.getByText('Hide column')).toBeInTheDocument();
		});

		test('toggles column menu closed on second click', async () => {
			renderTable();
			const buttons = screen.getAllByLabelText('Column options');
			await fireEvent.click(buttons[0]);
			expect(screen.getByText('Sort A-Z')).toBeInTheDocument();
			await fireEvent.click(buttons[0]);
			expect(screen.queryByText('Sort A-Z')).not.toBeInTheDocument();
		});
	});

	describe('resize handles', () => {
		test('shows resize handles by default', () => {
			renderTable();
			const handles = screen.getAllByLabelText('Resize column');
			expect(handles.length).toBe(3);
		});

		test('hides resize handles when enableResize is false', () => {
			renderTable({ enableResize: false });
			expect(screen.queryByLabelText('Resize column')).not.toBeInTheDocument();
		});
	});

	describe('drag handles', () => {
		test('shows drag-to-reorder handles', () => {
			renderTable();
			const handles = screen.getAllByLabelText('Drag to reorder');
			expect(handles.length).toBe(3);
		});
	});
});
