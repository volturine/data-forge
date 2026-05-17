import { test, expect } from './fixtures.js';
import type { APIRequestContext } from '@playwright/test';
import { createDatasource, createImportedAnalysis } from './utils/api.js';
import { gotoAnalysisEditor } from './utils/analysis.js';
import { deleteAnalysisViaUI, deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { uid } from './utils/uid.js';

async function createSnippetAnalysis(
	request: APIRequestContext,
	name: string,
	leftDatasourceId: string,
	rightDatasourceId: string
): Promise<string> {
	const leftRef = `left-${crypto.randomUUID()}`;
	const rightRef = `right-${crypto.randomUUID()}`;
	return createImportedAnalysis(
		request,
		name,
		{
			tabs: [
				{
					id: 'tab-right',
					name: 'Right Source',
					parent_id: null,
					datasource: {
						id: rightRef,
						analysis_tab_id: null,
						config: { branch: 'master' }
					},
					output: {
						result_id: crypto.randomUUID(),
						datasource_type: 'iceberg',
						format: 'parquet',
						filename: 'right_source',
						build_mode: 'full',
						iceberg: {
							namespace: 'outputs',
							table_name: 'right_source',
							branch: 'master'
						}
					},
					steps: [{ id: 'view-right', type: 'view', config: {}, depends_on: [], is_applied: true }]
				},
				{
					id: 'tab-left',
					name: 'Left Source',
					parent_id: null,
					datasource: {
						id: leftRef,
						analysis_tab_id: null,
						config: { branch: 'master' }
					},
					output: {
						result_id: crypto.randomUUID(),
						datasource_type: 'iceberg',
						format: 'parquet',
						filename: 'left_source',
						build_mode: 'full',
						iceberg: {
							namespace: 'outputs',
							table_name: 'left_source',
							branch: 'master'
						}
					},
					steps: [
						{ id: 'view-left', type: 'view', config: {}, depends_on: [], is_applied: true },
						{
							id: 'filter-left',
							type: 'filter',
							config: {
								conditions: [{ column: 'age', operator: '>', value: 20, value_type: 'number' }],
								logic: 'AND'
							},
							depends_on: ['view-left'],
							is_applied: true
						},
						{
							id: 'join-left',
							type: 'join',
							config: {
								how: 'left',
								right_source: 'tab-right',
								join_columns: [{ id: 'join-id', left_column: 'id', right_column: 'id' }],
								right_columns: ['name'],
								suffix: '_right'
							},
							depends_on: ['filter-left'],
							is_applied: true
						},
						{
							id: 'groupby-left',
							type: 'groupby',
							config: {
								group_by: ['city'],
								aggregations: [{ column: 'age', function: 'count', alias: 'row_count' }]
							},
							depends_on: ['join-left'],
							is_applied: true
						},
						{
							id: 'sort-left',
							type: 'sort',
							config: { columns: ['row_count'], descending: [true] },
							depends_on: ['groupby-left'],
							is_applied: true
						}
					]
				}
			]
		},
		{ [leftRef]: leftDatasourceId, [rightRef]: rightDatasourceId },
		'SQL/Polars snippet export e2e'
	);
}

async function createUnsupportedAnalysis(
	request: APIRequestContext,
	name: string,
	datasourceId: string
): Promise<string> {
	const datasourceRef = `source-${crypto.randomUUID()}`;
	return createImportedAnalysis(
		request,
		name,
		{
			tabs: [
				{
					id: 'tab-unsupported',
					name: 'Unsupported Tab',
					parent_id: null,
					datasource: {
						id: datasourceRef,
						analysis_tab_id: null,
						config: { branch: 'master' }
					},
					output: {
						result_id: crypto.randomUUID(),
						datasource_type: 'iceberg',
						format: 'parquet',
						filename: 'unsupported',
						build_mode: 'full',
						iceberg: {
							namespace: 'outputs',
							table_name: 'unsupported',
							branch: 'master'
						}
					},
					steps: [
						{ id: 'view', type: 'view', config: {}, depends_on: [], is_applied: true },
						{ id: 'ai', type: 'ai', config: {}, depends_on: ['view'], is_applied: true }
					]
				}
			]
		},
		{ [datasourceRef]: datasourceId }
	);
}

test.describe('Analyses – SQL/Polars snippet export', () => {
	test.describe.configure({ mode: 'serial' });

	test('toolbar export renders both Polars and SQL snippets for pipeline steps', async ({
		page,
		request
	}) => {
		test.setTimeout(90_000);
		const id = uid();
		const leftDsName = `e2e-snippet-left-${id}`;
		const rightDsName = `e2e-snippet-right-${id}`;
		const analysisName = `E2E Snippet Toolbar ${id}`;
		const leftDsId = await createDatasource(request, leftDsName);
		const rightDsId = await createDatasource(request, rightDsName);
		const analysisId = await createSnippetAnalysis(request, analysisName, leftDsId, rightDsId);
		try {
			await gotoAnalysisEditor(page, analysisId);
			await page.getByTestId('analysis-export-toolbar-button').click();

			const code = page.getByTestId('analysis-export-code');
			await expect(code).toBeVisible({ timeout: 10_000 });
			await expect
				.poll(async () => (await code.textContent())?.trim() ?? '', { timeout: 10_000 })
				.not.toBe('');
			await expect(code).toContainText('import polars as pl');
			await expect(code).toContainText('.join(');
			await expect(code).toContainText('.group_by(');
			await expect(code).toContainText('.sort(');

			await page.getByTestId('analysis-export-format-sql').click();
			await expect(code).toContainText('WITH');
			await expect(code).toContainText('JOIN');
			await expect(code).toContainText('GROUP BY');
			await expect(code).toContainText('ORDER BY');
		} finally {
			await deleteAnalysisViaUI(page, analysisName);
			await deleteDatasourceViaUI(page, leftDsName);
			await deleteDatasourceViaUI(page, rightDsName);
		}
	});

	test('tab context export supports copy/download and tab-scoped filename', async ({
		page,
		request
	}) => {
		test.setTimeout(90_000);
		await page.addInitScript(() => {
			Object.defineProperty(navigator, 'clipboard', {
				configurable: true,
				value: {
					writeText: async (text: string) => {
						(window as Window & { __copied_export?: string }).__copied_export = text;
					},
					readText: async () => ''
				}
			});
		});

		const id = uid();
		const leftDsName = `e2e-snippet-copy-left-${id}`;
		const rightDsName = `e2e-snippet-copy-right-${id}`;
		const analysisName = `E2E Snippet Context ${id}`;
		const leftDsId = await createDatasource(request, leftDsName);
		const rightDsId = await createDatasource(request, rightDsName);
		const analysisId = await createSnippetAnalysis(request, analysisName, leftDsId, rightDsId);
		try {
			await gotoAnalysisEditor(page, analysisId);

			const leftTabButton = page.locator('button[data-tab-name="Left Source"]');
			await expect(leftTabButton).toBeVisible({ timeout: 8_000 });
			await leftTabButton.click({ button: 'right' });
			await page.getByTestId('analysis-tab-context-export').click();

			const code = page.getByTestId('analysis-export-code');
			await expect
				.poll(async () => (await code.textContent())?.trim() ?? '', { timeout: 10_000 })
				.not.toBe('');
			await expect(code).toContainText('SOURCE_RIGHT_SOURCE_PATH');
			await expect(code).toContainText('SOURCE_LEFT_SOURCE_PATH');

			await page.getByTestId('analysis-export-copy').click();
			const copied = await page.evaluate(
				() => (window as Window & { __copied_export?: string }).__copied_export ?? ''
			);
			expect(copied.length).toBeGreaterThan(20);
			expect(copied).toContain('import polars as pl');

			const [pyDownload] = await Promise.all([
				page.waitForEvent('download'),
				page.getByTestId('analysis-export-download').click()
			]);
			expect(pyDownload.suggestedFilename()).toMatch(/_left_source\.py$/);

			await page.getByTestId('analysis-export-format-sql').click();
			await expect(code).toContainText('WITH');
			const [sqlDownload] = await Promise.all([
				page.waitForEvent('download'),
				page.getByTestId('analysis-export-download').click()
			]);
			expect(sqlDownload.suggestedFilename()).toMatch(/_left_source\.sql$/);
		} finally {
			await deleteAnalysisViaUI(page, analysisName);
			await deleteDatasourceViaUI(page, leftDsName);
			await deleteDatasourceViaUI(page, rightDsName);
		}
	});

	test('untranslatable steps surface warnings in export modal', async ({ page, request }) => {
		test.setTimeout(90_000);
		const id = uid();
		const dsName = `e2e-snippet-warn-${id}`;
		const analysisName = `E2E Snippet Warnings ${id}`;
		const dsId = await createDatasource(request, dsName);
		const analysisId = await createUnsupportedAnalysis(request, analysisName, dsId);
		try {
			await gotoAnalysisEditor(page, analysisId);
			await page.getByTestId('analysis-export-toolbar-button').click();
			await page.getByTestId('analysis-export-format-sql').click();
			const warnings = page.getByTestId('analysis-export-warnings');
			await expect(warnings).toBeVisible({ timeout: 10_000 });
			await expect(warnings).toContainText(/ai/i);
			await expect(page.getByTestId('analysis-export-code')).toContainText('-- WARNING:');
			await expect(page.getByTestId('analysis-export-code')).toContainText('Original config');
		} finally {
			await deleteAnalysisViaUI(page, analysisName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});
});
