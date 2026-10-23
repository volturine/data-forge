import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { AnalysisTab } from '#lib/types/analysis.js';
import type { DataSource } from '#lib/types/datasource.js';
import { datasourceStore } from '#lib/stores/datasource.svelte.js';
import DatasourceNode from './DatasourceNode.svelte';

const { capturedQueryOptions } = vi.hoisted(() => ({
	capturedQueryOptions: [] as (() => Record<string, unknown>)[]
}));

vi.mock('@tanstack/svelte-query', () => ({
	createQuery: (options: () => Record<string, unknown>) => {
		capturedQueryOptions.push(options);
		return { data: undefined };
	}
}));

vi.mock('#lib/stores/namespace.svelte.js', () => ({
	useNamespace: () => ({ value: 'test-namespace' })
}));

function makeDatasource(overrides: Partial<DataSource> = {}): DataSource {
	return {
		id: 'ds-1',
		name: 'Stored datasource',
		description: null,
		source_type: 'database',
		config: { connection_string: 'postgres://example', query: 'select 1' },
		schema_cache: null,
		created_at: '2024-01-01',
		created_by: 'import',
		is_hidden: false,
		...overrides
	} as DataSource;
}

function makeActiveTab(
	datasource: AnalysisTab['datasource'] = {
		id: 'ds-1',
		analysis_tab_id: null,
		config: { branch: 'main' }
	}
): AnalysisTab {
	return {
		id: 'tab-1',
		name: 'Source',
		parent_id: null,
		datasource,
		output: { result_id: 'result-1', format: 'parquet', filename: 'source' },
		steps: []
	};
}

function getDatasourceQueryOptions(): Record<string, unknown> {
	const options = capturedQueryOptions
		.map((getOptions) => getOptions())
		.find((queryOptions) => {
			const queryKey = queryOptions.queryKey;
			return Array.isArray(queryKey) && queryKey[0] === 'datasource';
		});
	if (!options) throw new Error('Datasource query options were not captured');
	return options;
}

function renderNode(activeTab = makeActiveTab()) {
	return render(DatasourceNode, {
		props: {
			datasource: null,
			datasourceLabel: 'Input',
			activeTab
		}
	});
}

beforeEach(() => {
	datasourceStore.reset();
	capturedQueryOptions.length = 0;
});

afterEach(() => {
	cleanup();
	datasourceStore.reset();
});

describe('DatasourceNode datasource fallback', () => {
	test('uses stored metadata and skips fallback when the loaded store already has the datasource', () => {
		const storedDatasource = makeDatasource();
		datasourceStore.datasources = [storedDatasource];
		datasourceStore.loaded = true;

		renderNode();

		expect(getDatasourceQueryOptions().enabled).toBe(false);
		expect(screen.getByRole('img', { name: 'Database file type' })).toBeInTheDocument();
	});

	test('does not enable fallback when the list arrives before the datasource prop', async () => {
		renderNode();
		expect(getDatasourceQueryOptions().enabled).toBe(false);

		datasourceStore.datasources = [makeDatasource()];
		datasourceStore.loaded = true;
		await tick();

		expect(getDatasourceQueryOptions().enabled).toBe(false);
		expect(screen.getByRole('img', { name: 'Database file type' })).toBeInTheDocument();
	});

	test('keeps fallback enabled for an ID missing from the loaded datasource list', () => {
		datasourceStore.loaded = true;

		renderNode();

		expect(getDatasourceQueryOptions().enabled).toBe(true);
	});

	test('keeps fallback disabled until the datasource list has loaded', () => {
		renderNode();

		expect(getDatasourceQueryOptions().enabled).toBe(false);
	});

	test('does not query a derived tab source', () => {
		datasourceStore.loaded = true;

		renderNode(
			makeActiveTab({
				id: 'ds-derived',
				analysis_tab_id: 'upstream-tab',
				config: { branch: 'main' }
			})
		);

		expect(getDatasourceQueryOptions().enabled).toBe(false);
	});
});
