import { describe, expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import type { DataSource } from '$lib/types/datasource';
import NewAnalysisPage from './+page.svelte';

const datasources: DataSource[] = Array.from(
	{ length: 2_000 },
	(_, index) =>
		({
			id: `ds-${index}`,
			name: `dataset_${index}`,
			description: null,
			source_type: 'iceberg',
			config: {},
			created_by: 'import',
			is_hidden: false,
			created_at: new Date(Date.UTC(2026, 0, 1) + index * 60_000).toISOString()
		}) as DataSource
);

vi.mock('$lib/stores/namespace.svelte', () => ({
	useNamespace: () => ({ value: 'default', switching: false })
}));
vi.mock('$lib/stores/config.svelte', () => ({ configStore: { config: null } }));
vi.mock('$lib/api/analysis', () => ({ createAnalysis: vi.fn() }));
vi.mock('$lib/api/datasource', () => ({ listDatasources: vi.fn() }));
vi.mock('$lib/components/datasources/DatasourcePreview.svelte', async () => ({
	default: (await import('$lib/test-utils/stubs/IconStub.svelte')).default
}));
vi.mock('@tanstack/svelte-query', () => ({
	createQuery: () => ({ data: datasources, isPending: false, isError: false, error: null })
}));

const rows = () => document.querySelectorAll('[data-ds-option]');

describe('new analysis datasource picker', () => {
	test('renders a capped, freshest-first page of thousands of datasources', async () => {
		render(NewAnalysisPage);

		expect(rows()).toHaveLength(50);
		expect(rows()[0]).toHaveAttribute('data-ds-option', 'dataset_1999');
		expect(screen.getAllByRole('button', { name: 'Create analysis' })).toHaveLength(50);
		expect(screen.getByTestId('datasource-picker-count')).toHaveTextContent(
			'Showing 50 of 2,000 datasources'
		);

		await fireEvent.click(screen.getByRole('button', { name: 'Show 50 more' }));

		expect(rows()).toHaveLength(100);
	});

	test('searching resets the cap and narrows to matching names', async () => {
		render(NewAnalysisPage);
		await fireEvent.click(screen.getByRole('button', { name: 'Show 50 more' }));

		const search = screen.getByLabelText('Search datasources');
		await fireEvent.input(search, { target: { value: 'dataset_19' } });

		expect(rows()).toHaveLength(50);
		expect(rows()[0]).toHaveAttribute('data-ds-option', 'dataset_1999');
		expect(screen.getByTestId('datasource-picker-count')).toHaveTextContent(
			'Showing 50 of 111 matches'
		);

		await fireEvent.input(search, { target: { value: 'dataset_1234' } });

		expect(rows()).toHaveLength(1);
		expect(screen.queryByTestId('datasource-picker-count')).not.toBeInTheDocument();
	});
});
