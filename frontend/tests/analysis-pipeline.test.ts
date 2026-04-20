import { test, expect } from './fixtures.js';
import type { Page, APIRequestContext } from '@playwright/test';
import { createDatasource, createDatasourceWithDates, API_BASE } from './utils/api.js';
import { gotoAnalysisEditor } from './utils/analysis.js';
import {
	createCleanupPage,
	deleteAnalysisViaUI,
	deleteDatasourceViaUI
} from './utils/ui-cleanup.js';
import { uid } from './utils/uid.js';
import { screenshot } from './utils/visual.js';

// ────────────────────────────────────────────────────────────────────────────────
// Helpers
// ────────────────────────────────────────────────────────────────────────────────

interface PipelineStep {
	id: string;
	type: string;
	config: Record<string, unknown>;
	depends_on: string[];
	is_applied: boolean;
}

interface PipelineAnalysisResult {
	analysisId: string;
	viewStepId: string;
	tabId: string;
	resultId: string;
	dsId: string;
	steps: PipelineStep[];
}

/**
 * Create an analysis with pre-configured steps via API.
 * A view step is always appended so the inline preview auto-triggers.
 */
async function createPipelineAnalysis(
	request: APIRequestContext,
	name: string,
	dsId: string,
	steps: Array<{ type: string; config: Record<string, unknown> }>
): Promise<PipelineAnalysisResult> {
	const viewStepId = crypto.randomUUID();
	const tabId = crypto.randomUUID();
	const resultId = crypto.randomUUID();
	const pipelineSteps: PipelineStep[] = [];
	let prevId: string | null = null;
	for (const s of steps) {
		const stepId = crypto.randomUUID();
		pipelineSteps.push({
			id: stepId,
			type: s.type,
			config: s.config,
			depends_on: prevId ? [prevId] : [],
			is_applied: true
		});
		prevId = stepId;
	}
	pipelineSteps.push({
		id: viewStepId,
		type: 'view',
		config: {},
		depends_on: prevId ? [prevId] : [],
		is_applied: true
	});

	const response = await request.post(`${API_BASE}/analysis`, {
		data: {
			name,
			description: null,
			tabs: [
				{
					id: tabId,
					name: 'Source 1',
					parent_id: null,
					datasource: {
						id: dsId,
						analysis_tab_id: null,
						config: { branch: 'master' }
					},
					output: {
						result_id: resultId,
						datasource_type: 'iceberg',
						format: 'parquet',
						filename: 'source_1',
						build_mode: 'full',
						iceberg: {
							namespace: 'outputs',
							table_name: 'source_1',
							branch: 'master'
						}
					},
					steps: pipelineSteps
				}
			]
		}
	});
	if (!response.ok()) {
		throw new Error(`createPipelineAnalysis: ${response.status()} ${await response.text()}`);
	}
	const created = (await response.json()) as { id: string };
	return { analysisId: created.id, viewStepId, tabId, resultId, dsId, steps: pipelineSteps };
}

/**
 * Navigate away from the analysis page. Safe to call if the page is
 * already closed (e.g. after a timeout).
 */
async function leaveAnalysisPage(page: Page): Promise<void> {
	try {
		if (page.isClosed()) return;
		await page.goto('/');
		await expect(page).toHaveURL('/');
	} catch {
		// Page may have been torn down by a timeout — swallow to avoid masking the real error.
	}
}

/**
 * Navigate to the analysis editor using the standard readiness flow,
 * then wait for the inline data table to render.
 */
async function navigateAndWaitForTable(page: Page, analysisId: string): Promise<void> {
	await gotoAnalysisEditor(page, analysisId);
	const table = page.locator('[data-testid="inline-data-table"]');
	await expect(table).toBeVisible({ timeout: 30_000 });
}

// ────────────────────────────────────────────────────────────────────────────────
// Test data reference — SAMPLE_CSV:
//   id(Int64) | name(Utf8) | age(Int64) | city(Utf8)
//   1         | Alice      | 30         | London
//   2         | Bob        | 25         | Paris
//   3         | Charlie    | 35         | Berlin
//
// DATE_CSV:
//   id(Int64) | name(Utf8) | event_date(Date) | amount(Int64)
//   1         | Alice      | 2024-01-15       | 100
//   2         | Bob        | 2024-03-22       | 250
//   3         | Charlie    | 2024-06-10       | 75
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Pipeline data verification', () => {
	test.setTimeout(60_000);

	let dsId: string;
	let dsName: string;

	test.beforeAll(async ({ request }) => {
		dsName = `e2e-pipe-ds-${uid()}`;
		dsId = await createDatasource(request, dsName);
	});

	test.afterAll(async ({ browser, workerAuth }) => {
		const { page, context } = await createCleanupPage(browser, workerAuth.workerIndex);
		await deleteDatasourceViaUI(page, dsName);
		await page.close();
		await context.close();
	});

	// ── Baseline ──────────────────────────────────────────────────────────────

	test('view passthrough returns all original data', async ({ page, request }) => {
		const aName = `E2E Pipe View ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, []);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			await expect(table.locator('[data-column-id="id"]')).toBeVisible();
			await expect(table.locator('[data-column-id="name"]')).toBeVisible();
			await expect(table.locator('[data-column-id="age"]')).toBeVisible();
			await expect(table.locator('[data-column-id="city"]')).toBeVisible();

			await expect(table.locator('tbody tr')).toHaveCount(3);

			await expect(table.getByText('Alice', { exact: true })).toBeVisible();
			await expect(table.getByText('Bob', { exact: true })).toBeVisible();
			await expect(table.getByText('Charlie', { exact: true })).toBeVisible();
			await expect(table.getByText('Berlin', { exact: true })).toBeVisible();

			await screenshot(page, 'analysis/pipeline', 'view-passthrough');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	// ── Row operations ────────────────────────────────────────────────────────

	test('filter removes rows not matching condition', async ({ page, request }) => {
		const aName = `E2E Pipe Filter ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, [
			{
				type: 'filter',
				config: {
					conditions: [{ column: 'age', operator: '>', value: '28', value_type: 'number' }],
					logic: 'AND'
				}
			}
		]);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			await expect(table.locator('[data-column-id="id"]')).toBeVisible();
			await expect(table.locator('[data-column-id="name"]')).toBeVisible();
			await expect(table.locator('[data-column-id="age"]')).toBeVisible();
			await expect(table.locator('[data-column-id="city"]')).toBeVisible();

			await expect(table.locator('tbody tr')).toHaveCount(2);

			await expect(table.getByText('Alice', { exact: true })).toBeVisible();
			await expect(table.getByText('Charlie', { exact: true })).toBeVisible();
			await expect(table.getByText('Bob', { exact: true })).not.toBeVisible();

			await screenshot(page, 'analysis/pipeline', 'filter');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	test('limit keeps only first N rows', async ({ page, request }) => {
		const aName = `E2E Pipe Limit ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, [
			{ type: 'limit', config: { n: 2 } }
		]);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			await expect(table.locator('[data-column-id="id"]')).toBeVisible();
			await expect(table.locator('[data-column-id="name"]')).toBeVisible();
			await expect(table.locator('[data-column-id="age"]')).toBeVisible();
			await expect(table.locator('[data-column-id="city"]')).toBeVisible();

			await expect(table.locator('tbody tr')).toHaveCount(2);

			await screenshot(page, 'analysis/pipeline', 'limit');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	test('topk returns rows with largest values', async ({ page, request }) => {
		const aName = `E2E Pipe TopK ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, [
			{ type: 'topk', config: { column: 'age', k: 2, descending: true } }
		]);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			const rows = table.locator('tbody tr');
			await expect(rows).toHaveCount(2);
			await expect(rows.nth(0)).toContainText('Charlie');
			await expect(rows.nth(1)).toContainText('Alice');
			await expect(table.getByText('Bob', { exact: true })).not.toBeVisible();

			await screenshot(page, 'analysis/pipeline', 'topk');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	test('sample with fraction 1.0 returns all rows', async ({ page, request }) => {
		const aName = `E2E Pipe Sample ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, [
			{ type: 'sample', config: { fraction: 1.0, seed: 42 } }
		]);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			await expect(table.locator('tbody tr')).toHaveCount(3);
			await expect(table.getByText('Alice', { exact: true })).toBeVisible();
			await expect(table.getByText('Bob', { exact: true })).toBeVisible();
			await expect(table.getByText('Charlie', { exact: true })).toBeVisible();

			await screenshot(page, 'analysis/pipeline', 'sample');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	test('deduplicate preserves unique rows', async ({ page, request }) => {
		const aName = `E2E Pipe Dedup ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, [
			{ type: 'deduplicate', config: {} }
		]);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			await expect(table.locator('[data-column-id="id"]')).toBeVisible();
			await expect(table.locator('[data-column-id="name"]')).toBeVisible();
			await expect(table.locator('[data-column-id="age"]')).toBeVisible();
			await expect(table.locator('[data-column-id="city"]')).toBeVisible();

			await expect(table.locator('tbody tr')).toHaveCount(3);

			await screenshot(page, 'analysis/pipeline', 'deduplicate');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	// ── Column operations ─────────────────────────────────────────────────────

	test('select keeps only specified columns', async ({ page, request }) => {
		const aName = `E2E Pipe Select ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, [
			{ type: 'select', config: { columns: ['name', 'age'] } }
		]);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			await expect(table.locator('[data-column-id="name"]')).toBeVisible();
			await expect(table.locator('[data-column-id="age"]')).toBeVisible();
			await expect(table.locator('[data-column-id="id"]')).not.toBeVisible();
			await expect(table.locator('[data-column-id="city"]')).not.toBeVisible();

			await expect(table.locator('tbody tr')).toHaveCount(3);

			await screenshot(page, 'analysis/pipeline', 'select');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	test('drop removes specified columns', async ({ page, request }) => {
		const aName = `E2E Pipe Drop ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, [
			{ type: 'drop', config: { columns: ['city'] } }
		]);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			await expect(table.locator('[data-column-id="id"]')).toBeVisible();
			await expect(table.locator('[data-column-id="name"]')).toBeVisible();
			await expect(table.locator('[data-column-id="age"]')).toBeVisible();
			await expect(table.locator('[data-column-id="city"]')).not.toBeVisible();

			await expect(table.locator('tbody tr')).toHaveCount(3);

			await screenshot(page, 'analysis/pipeline', 'drop');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	test('rename changes column names', async ({ page, request }) => {
		const aName = `E2E Pipe Rename ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, [
			{ type: 'rename', config: { column_mapping: { name: 'full_name' } } }
		]);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			await expect(table.locator('[data-column-id="full_name"]')).toBeVisible();
			await expect(table.locator('[data-column-id="name"]')).not.toBeVisible();

			await expect(table.locator('tbody tr')).toHaveCount(3);
			await expect(table.getByText('Alice', { exact: true })).toBeVisible();

			await screenshot(page, 'analysis/pipeline', 'rename');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	// ── Data transformations ──────────────────────────────────────────────────

	test('sort reorders rows by column value', async ({ page, request }) => {
		const aName = `E2E Pipe Sort ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, [
			{ type: 'sort', config: { columns: ['age'], descending: [false] } }
		]);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			const rows = table.locator('tbody tr');
			await expect(rows).toHaveCount(3);
			await expect(rows.nth(0)).toContainText('Bob');
			await expect(rows.nth(1)).toContainText('Alice');
			await expect(rows.nth(2)).toContainText('Charlie');

			await screenshot(page, 'analysis/pipeline', 'sort');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	test('expression adds computed column', async ({ page, request }) => {
		const aName = `E2E Pipe Expr ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, [
			{
				type: 'expression',
				config: { expression: 'pl.col("age") + 1', column_name: 'age_plus_one' }
			}
		]);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			await expect(table.locator('[data-column-id="age_plus_one"]')).toBeVisible();
			await expect(table.locator('[data-column-id="age"]')).toBeVisible();

			const rows = table.locator('tbody tr');
			await expect(rows).toHaveCount(3);

			await expect(table.locator('tbody tr', { hasText: 'Alice' })).toContainText('31');
			await expect(table.locator('tbody tr', { hasText: 'Bob' })).toContainText('26');
			await expect(table.locator('tbody tr', { hasText: 'Charlie' })).toContainText('36');

			await screenshot(page, 'analysis/pipeline', 'expression');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	test('with_columns adds literal column', async ({ page, request }) => {
		const aName = `E2E Pipe WithCols ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, [
			{
				type: 'with_columns',
				config: {
					expressions: [{ name: 'tag', type: 'literal', value: 'test' }]
				}
			}
		]);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			await expect(table.locator('[data-column-id="tag"]')).toBeVisible();

			const rows = table.locator('tbody tr');
			await expect(rows).toHaveCount(3);
			for (let i = 0; i < 3; i++) {
				await expect(rows.nth(i)).toContainText('test');
			}

			await screenshot(page, 'analysis/pipeline', 'with-columns');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	test('string_transform applies string operation', async ({ page, request }) => {
		const aName = `E2E Pipe StrXform ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, [
			{
				type: 'string_transform',
				config: { column: 'name', method: 'uppercase', new_column: 'name_upper' }
			}
		]);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			await expect(table.locator('[data-column-id="name_upper"]')).toBeVisible();

			await expect(table.locator('tbody tr')).toHaveCount(3);
			await expect(table.getByText('ALICE', { exact: true })).toBeVisible();
			await expect(table.getByText('BOB', { exact: true })).toBeVisible();
			await expect(table.getByText('CHARLIE', { exact: true })).toBeVisible();

			await screenshot(page, 'analysis/pipeline', 'string-transform');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	test('groupby aggregates data by group', async ({ page, request }) => {
		const aName = `E2E Pipe GroupBy ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, [
			{
				type: 'groupby',
				config: {
					group_by: ['city'],
					aggregations: [{ column: 'age', function: 'sum', alias: 'total_age' }]
				}
			}
		]);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			await expect(table.locator('[data-column-id="city"]')).toBeVisible();
			await expect(table.locator('[data-column-id="total_age"]')).toBeVisible();

			await expect(table.locator('tbody tr')).toHaveCount(3);

			await expect(table.locator('tbody tr', { hasText: 'London' })).toContainText('30');
			await expect(table.locator('tbody tr', { hasText: 'Paris' })).toContainText('25');
			await expect(table.locator('tbody tr', { hasText: 'Berlin' })).toContainText('35');

			await screenshot(page, 'analysis/pipeline', 'groupby');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	// ── Reshaping ─────────────────────────────────────────────────────────────

	test('unpivot converts wide format to long format', async ({ page, request }) => {
		const aName = `E2E Pipe Unpivot ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, [
			{
				type: 'unpivot',
				config: {
					index: ['name', 'city'],
					on: ['id', 'age'],
					variable_name: 'field',
					value_name: 'val'
				}
			}
		]);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			await expect(table.locator('tbody tr')).toHaveCount(6);
			await expect(table.locator('[data-column-id="field"]')).toBeVisible();
			await expect(table.locator('[data-column-id="val"]')).toBeVisible();
			await expect(table.locator('[data-column-id="name"]')).toBeVisible();
			await expect(table.locator('[data-column-id="city"]')).toBeVisible();

			await screenshot(page, 'analysis/pipeline', 'unpivot');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	test('pivot converts long format to wide format', async ({ page, request }) => {
		const aName = `E2E Pipe Pivot ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, [
			{
				type: 'pivot',
				config: {
					index: ['name'],
					columns: 'city',
					values: 'age',
					aggregate_function: 'first'
				}
			}
		]);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			await expect(table.locator('[data-column-id="London"]')).toBeVisible();
			await expect(table.locator('[data-column-id="Paris"]')).toBeVisible();
			await expect(table.locator('[data-column-id="Berlin"]')).toBeVisible();

			await expect(table.locator('tbody tr')).toHaveCount(3);
			await expect(table.locator('tbody tr', { hasText: 'Alice' })).toContainText('30');

			await screenshot(page, 'analysis/pipeline', 'pivot');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	// ── Special operations ────────────────────────────────────────────────────

	test('fill_null with zero strategy preserves clean data', async ({ page, request }) => {
		const aName = `E2E Pipe FillNull ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, [
			{ type: 'fill_null', config: { strategy: 'zero' } }
		]);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			await expect(table.locator('[data-column-id="id"]')).toBeVisible();
			await expect(table.locator('[data-column-id="name"]')).toBeVisible();
			await expect(table.locator('[data-column-id="age"]')).toBeVisible();
			await expect(table.locator('[data-column-id="city"]')).toBeVisible();

			await expect(table.locator('tbody tr')).toHaveCount(3);

			await screenshot(page, 'analysis/pipeline', 'fill-null');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	test('join self-join matches rows by column', async ({ page, request }) => {
		const aName = `E2E Pipe Join ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, [
			{
				type: 'join',
				config: {
					how: 'inner',
					right_source: dsId,
					join_columns: [{ id: 'jc1', left_column: 'city', right_column: 'city' }],
					suffix: '_right'
				}
			}
		]);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			await expect(table.locator('tbody tr')).toHaveCount(3);
			await expect(table.locator('[data-column-id="id_right"]')).toBeVisible();
			await expect(table.locator('[data-column-id="name_right"]')).toBeVisible();

			await screenshot(page, 'analysis/pipeline', 'join');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	// ── Multi-step chain ──────────────────────────────────────────────────────

	test('chained pipeline: filter → sort → limit', async ({ page, request }) => {
		const aName = `E2E Pipe Chain ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, [
			{
				type: 'filter',
				config: {
					conditions: [{ column: 'age', operator: '>=', value: '25', value_type: 'number' }],
					logic: 'AND'
				}
			},
			{ type: 'sort', config: { columns: ['age'], descending: [true] } },
			{ type: 'limit', config: { n: 2 } }
		]);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			const rows = table.locator('tbody tr');
			await expect(rows).toHaveCount(2);
			await expect(rows.nth(0)).toContainText('Charlie');
			await expect(rows.nth(1)).toContainText('Alice');

			await expect(page.locator('[data-step-type="filter"]')).toBeVisible();
			await expect(page.locator('[data-step-type="sort"]')).toBeVisible();
			await expect(page.locator('[data-step-type="limit"]')).toBeVisible();
			await expect(page.locator('[data-step-type="view"]')).toBeVisible();

			await expect(table.getByText('Charlie', { exact: true })).toBeVisible();
			await expect(table.getByText('Alice', { exact: true })).toBeVisible();

			await screenshot(page, 'analysis/pipeline', 'chained-filter-sort-limit');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Pass-through operations: chart, export, download
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Pipeline data – pass-through operations', () => {
	test.setTimeout(60_000);

	let dsId: string;
	let dsName: string;

	test.beforeAll(async ({ request }) => {
		dsName = `e2e-pipe-passthrough-ds-${uid()}`;
		dsId = await createDatasource(request, dsName);
	});

	test.afterAll(async ({ browser, workerAuth }) => {
		const { page, context } = await createCleanupPage(browser, workerAuth.workerIndex);
		await deleteDatasourceViaUI(page, dsName);
		await page.close();
		await context.close();
	});

	test('chart (plot_bar) computes aggregated visualization data', async ({ page, request }) => {
		const aName = `E2E Pipe Chart ${uid()}`;
		const chartStepId = crypto.randomUUID();
		const chartTabId = crypto.randomUUID();
		const chartResultId = crypto.randomUUID();
		const chartSteps: PipelineStep[] = [
			{
				id: chartStepId,
				type: 'plot_bar',
				config: {
					chart_type: 'bar',
					x_column: 'city',
					y_column: 'age',
					aggregation: 'sum'
				},
				depends_on: [],
				is_applied: true
			}
		];
		const response = await request.post(`${API_BASE}/analysis`, {
			data: {
				name: aName,
				description: null,
				tabs: [
					{
						id: chartTabId,
						name: 'Source 1',
						parent_id: null,
						datasource: {
							id: dsId,
							analysis_tab_id: null,
							config: { branch: 'master' }
						},
						output: {
							result_id: chartResultId,
							datasource_type: 'iceberg',
							format: 'parquet',
							filename: 'source_1',
							build_mode: 'full',
							iceberg: {
								namespace: 'outputs',
								table_name: 'source_1',
								branch: 'master'
							}
						},
						steps: chartSteps
					}
				]
			}
		});
		if (!response.ok()) {
			throw new Error(`createPipelineAnalysis: ${response.status()} ${await response.text()}`);
		}
		const aId = ((await response.json()) as { id: string }).id;
		try {
			await gotoAnalysisEditor(page, aId);
			const chart = page.locator('[data-testid="chart-preview"]');
			await expect(chart).toBeVisible({ timeout: 30_000 });
			await expect(chart.locator('svg')).toBeVisible({ timeout: 10_000 });

			await screenshot(page, 'analysis/pipeline', 'chart-plot-bar');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	test('export passes data through unchanged', async ({ page, request }) => {
		const aName = `E2E Pipe Export ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, [
			{
				type: 'export',
				config: {
					format: 'csv',
					filename: 'test_export',
					destination: 'download'
				}
			}
		]);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			await expect(table.locator('[data-column-id="id"]')).toBeVisible();
			await expect(table.locator('[data-column-id="name"]')).toBeVisible();
			await expect(table.locator('[data-column-id="age"]')).toBeVisible();
			await expect(table.locator('[data-column-id="city"]')).toBeVisible();

			await expect(table.locator('tbody tr')).toHaveCount(3);

			await screenshot(page, 'analysis/pipeline', 'export');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	test('download passes data through unchanged', async ({ page, request }) => {
		const aName = `E2E Pipe Download ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, [
			{
				type: 'download',
				config: {
					format: 'parquet',
					filename: 'test_download'
				}
			}
		]);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			await expect(table.locator('[data-column-id="id"]')).toBeVisible();
			await expect(table.locator('[data-column-id="name"]')).toBeVisible();
			await expect(table.locator('[data-column-id="age"]')).toBeVisible();
			await expect(table.locator('[data-column-id="city"]')).toBeVisible();

			await expect(table.locator('tbody tr')).toHaveCount(3);

			await screenshot(page, 'analysis/pipeline', 'download');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	test('explode expands list column into rows', async ({ page, request }) => {
		const aName = `E2E Pipe Explode ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, [
			{
				type: 'expression',
				config: {
					expression: 'pl.concat_str([pl.col("name"), pl.col("city")], separator=",")',
					column_name: 'tags'
				}
			},
			{
				type: 'expression',
				config: {
					expression: 'pl.col("tags").str.split(",")',
					column_name: 'tags'
				}
			},
			{
				type: 'explode',
				config: { columns: ['tags'] }
			}
		]);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			await expect(table.locator('tbody tr')).toHaveCount(6);
			await expect(table.locator('[data-column-id="tags"]')).toBeVisible();
			await expect(table.getByText('Alice', { exact: true }).first()).toBeVisible();
			await expect(table.getByText('London', { exact: true }).first()).toBeVisible();
			await expect(table.getByText('Bob', { exact: true }).first()).toBeVisible();
			await expect(table.getByText('Paris', { exact: true }).first()).toBeVisible();

			await screenshot(page, 'analysis/pipeline', 'explode');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Timeseries — needs date column datasource
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Pipeline data – timeseries', () => {
	test.setTimeout(60_000);

	let dateDsId: string;
	let dateDsName: string;

	test.beforeAll(async ({ request }) => {
		dateDsName = `e2e-pipe-date-ds-${uid()}`;
		dateDsId = await createDatasourceWithDates(request, dateDsName);
	});

	test.afterAll(async ({ browser, workerAuth }) => {
		const { page, context } = await createCleanupPage(browser, workerAuth.workerIndex);
		await deleteDatasourceViaUI(page, dateDsName);
		await page.close();
		await context.close();
	});

	test('timeseries extracts month from date column', async ({ page, request }) => {
		const aName = `E2E Pipe TimeSeries ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dateDsId, [
			{
				type: 'select',
				config: {
					columns: ['id', 'name', 'event_date', 'amount'],
					cast_map: { event_date: 'Date' }
				}
			},
			{
				type: 'timeseries',
				config: {
					column: 'event_date',
					operation_type: 'extract',
					component: 'month',
					new_column: 'event_month'
				}
			}
		]);
		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			await expect(table.locator('[data-column-id="event_month"]')).toBeVisible();
			await expect(table.locator('tbody tr')).toHaveCount(3);

			await expect(table.locator('tbody tr', { hasText: 'Alice' })).toContainText('1');
			await expect(table.locator('tbody tr', { hasText: 'Bob' })).toContainText('3');
			await expect(table.locator('tbody tr', { hasText: 'Charlie' })).toContainText('6');

			await screenshot(page, 'analysis/pipeline', 'timeseries');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Union by name — needs two datasources in a multi-tab analysis
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Pipeline data – union by name', () => {
	test.setTimeout(60_000);

	let dsId1: string;
	let dsId2: string;
	let dsName1: string;
	let dsName2: string;

	test.beforeAll(async ({ request }) => {
		dsName1 = `e2e-pipe-union-ds1-${uid()}`;
		dsName2 = `e2e-pipe-union-ds2-${uid()}`;
		dsId1 = await createDatasource(request, dsName1);
		dsId2 = await createDatasource(request, dsName2);
	});

	test.afterAll(async ({ browser, workerAuth }) => {
		const { page, context } = await createCleanupPage(browser, workerAuth.workerIndex);
		await deleteDatasourceViaUI(page, dsName1);
		await deleteDatasourceViaUI(page, dsName2);
		await page.close();
		await context.close();
	});

	test('union_by_name combines rows from two datasources', async ({ page, request }) => {
		const aName = `E2E Pipe Union ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId1, [
			{
				type: 'union_by_name',
				config: { sources: [dsId2], allow_missing: true }
			}
		]);

		try {
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');

			await expect(table.locator('[data-column-id="id"]')).toBeVisible();
			await expect(table.locator('[data-column-id="name"]')).toBeVisible();
			await expect(table.locator('[data-column-id="age"]')).toBeVisible();
			await expect(table.locator('[data-column-id="city"]')).toBeVisible();

			await expect(table.locator('tbody tr')).toHaveCount(6);

			await screenshot(page, 'analysis/pipeline', 'union-by-name');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});
});
