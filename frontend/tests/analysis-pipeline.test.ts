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
 * Returns enough info to call `fetchPreviewViaAPI` without re-fetching
 * the analysis.
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

interface PreviewData {
	step_id: string;
	columns: string[];
	column_types: Record<string, string>;
	data: Array<Record<string, unknown>>;
	total_rows: number;
}

/**
 * Fetch preview data deterministically via the HTTP API.
 *
 * Builds the same pipeline payload the browser would send, but calls
 * `/compute/preview` directly through Playwright's `APIRequestContext`.
 * No browser network interception, no WebSocket race — fully deterministic.
 *
 * `extraDsIds` — additional datasource IDs referenced by steps (e.g. join
 * right_source, union sources) that need to be included in the sources map.
 */
async function fetchPreviewViaAPI(
	request: APIRequestContext,
	info: PipelineAnalysisResult,
	targetStepId: string,
	extraDsIds: string[] = []
): Promise<PreviewData> {
	const allDsIds = [info.dsId, ...extraDsIds.filter((id) => id !== info.dsId)];

	const sources: Record<string, Record<string, unknown>> = {
		[info.resultId]: {
			source_type: 'analysis',
			analysis_id: info.analysisId,
			analysis_tab_id: info.tabId
		}
	};

	for (const id of allDsIds) {
		const dsResp = await request.get(`${API_BASE}/datasource/${id}`);
		if (!dsResp.ok()) {
			throw new Error(
				`fetchPreviewViaAPI: datasource GET ${id} ${dsResp.status()} ${await dsResp.text()}`
			);
		}
		const ds = (await dsResp.json()) as {
			id: string;
			source_type: string;
			config: Record<string, unknown>;
		};
		sources[ds.id] = { source_type: ds.source_type, ...ds.config };
	}

	const previewResp = await request.post(`${API_BASE}/compute/preview`, {
		data: {
			analysis_id: info.analysisId,
			target_step_id: targetStepId,
			analysis_pipeline: {
				analysis_id: info.analysisId,
				tabs: [
					{
						id: info.tabId,
						name: 'Source 1',
						datasource: {
							id: info.dsId,
							analysis_tab_id: null,
							config: { branch: 'master' }
						},
						output: {
							result_id: info.resultId,
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
						steps: info.steps
					}
				],
				sources
			}
		}
	});
	if (!previewResp.ok()) {
		throw new Error(
			`fetchPreviewViaAPI: preview POST ${previewResp.status()} ${await previewResp.text()}`
		);
	}
	return (await previewResp.json()) as PreviewData;
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
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			expect(preview.columns).toEqual(['id', 'name', 'age', 'city']);
			expect(preview.total_rows).toBe(3);
			expect(preview.data).toHaveLength(3);

			const names = preview.data.map((r) => r.name);
			expect(names).toContain('Alice');
			expect(names).toContain('Bob');
			expect(names).toContain('Charlie');

			// UI: column headers rendered
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');
			await expect(table.locator('[data-column-id="id"]')).toBeVisible();
			await expect(table.locator('[data-column-id="name"]')).toBeVisible();
			await expect(table.locator('[data-column-id="age"]')).toBeVisible();
			await expect(table.locator('[data-column-id="city"]')).toBeVisible();

			// UI: data values visible
			await expect(table.getByText('Alice', { exact: true })).toBeVisible();
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
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			expect(preview.columns).toEqual(['id', 'name', 'age', 'city']);
			expect(preview.total_rows).toBe(2);

			const names = preview.data.map((r) => r.name);
			expect(names).toContain('Alice');
			expect(names).toContain('Charlie');
			expect(names).not.toContain('Bob');

			// UI: Bob should not appear in the table
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');
			await expect(table.getByText('Alice', { exact: true })).toBeVisible();
			await expect(table.getByText('Charlie', { exact: true })).toBeVisible();

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
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			expect(preview.columns).toEqual(['id', 'name', 'age', 'city']);
			expect(preview.total_rows).toBe(2);
			expect(preview.data).toHaveLength(2);

			await navigateAndWaitForTable(page, info.analysisId);
			await screenshot(page, 'analysis/pipeline', 'limit');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	test('topk returns rows with largest values', async ({ page, request }) => {
		// descending=true → sort descending, take head(k) → 2 largest
		const aName = `E2E Pipe TopK ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId, [
			{ type: 'topk', config: { column: 'age', k: 2, descending: true } }
		]);
		try {
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			expect(preview.total_rows).toBe(2);

			const names = preview.data.map((r) => r.name);
			expect(names).toContain('Charlie'); // age 35
			expect(names).toContain('Alice'); // age 30
			expect(names).not.toContain('Bob'); // age 25 excluded

			// First row should be highest age (descending sort)
			expect(preview.data[0].name).toBe('Charlie');

			await navigateAndWaitForTable(page, info.analysisId);
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
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			expect(preview.total_rows).toBe(3);
			const names = preview.data.map((r) => r.name);
			expect(names).toContain('Alice');
			expect(names).toContain('Bob');
			expect(names).toContain('Charlie');

			await navigateAndWaitForTable(page, info.analysisId);
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
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			expect(preview.columns).toEqual(['id', 'name', 'age', 'city']);
			expect(preview.total_rows).toBe(3);

			await navigateAndWaitForTable(page, info.analysisId);
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
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			expect(preview.columns).toEqual(['name', 'age']);
			expect(preview.total_rows).toBe(3);

			// UI: only name and age columns visible
			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');
			await expect(table.locator('[data-column-id="name"]')).toBeVisible();
			await expect(table.locator('[data-column-id="age"]')).toBeVisible();
			await expect(table.locator('[data-column-id="id"]')).not.toBeVisible();
			await expect(table.locator('[data-column-id="city"]')).not.toBeVisible();

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
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			expect(preview.columns).toEqual(['id', 'name', 'age']);
			expect(preview.total_rows).toBe(3);

			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');
			await expect(table.locator('[data-column-id="city"]')).not.toBeVisible();
			await expect(table.locator('[data-column-id="name"]')).toBeVisible();

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
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			expect(preview.columns).toContain('full_name');
			expect(preview.columns).not.toContain('name');
			expect(preview.total_rows).toBe(3);

			// Data still has the right values under the new column name
			expect(preview.data.map((r) => r.full_name)).toContain('Alice');

			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');
			await expect(table.locator('[data-column-id="full_name"]')).toBeVisible();
			await expect(table.locator('[data-column-id="name"]')).not.toBeVisible();

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
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			expect(preview.total_rows).toBe(3);

			// Ascending age order: Bob(25) → Alice(30) → Charlie(35)
			expect(preview.data[0].name).toBe('Bob');
			expect(preview.data[1].name).toBe('Alice');
			expect(preview.data[2].name).toBe('Charlie');

			await navigateAndWaitForTable(page, info.analysisId);
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
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			expect(preview.columns).toContain('age_plus_one');
			expect(preview.columns).toContain('age');
			expect(preview.total_rows).toBe(3);

			// Verify computed values
			for (const row of preview.data) {
				expect(row.age_plus_one).toBe((row.age as number) + 1);
			}

			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');
			await expect(table.locator('[data-column-id="age_plus_one"]')).toBeVisible();

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
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			expect(preview.columns).toContain('tag');
			expect(preview.total_rows).toBe(3);

			// Every row should have tag = 'test'
			for (const row of preview.data) {
				expect(row.tag).toBe('test');
			}

			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');
			await expect(table.locator('[data-column-id="tag"]')).toBeVisible();

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
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			expect(preview.columns).toContain('name_upper');
			expect(preview.total_rows).toBe(3);

			const uppers = preview.data.map((r) => r.name_upper);
			expect(uppers).toContain('ALICE');
			expect(uppers).toContain('BOB');
			expect(uppers).toContain('CHARLIE');

			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');
			await expect(table.getByText('ALICE', { exact: true })).toBeVisible();

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
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			// 2 columns: city, total_age (original id/name dropped by groupby)
			expect(preview.columns).toContain('city');
			expect(preview.columns).toContain('total_age');
			expect(preview.columns).toHaveLength(2);
			expect(preview.total_rows).toBe(3); // 3 unique cities

			// Each city has 1 row → sum = individual age
			const lookup = Object.fromEntries(preview.data.map((r) => [r.city, r.total_age]));
			expect(lookup['London']).toBe(30);
			expect(lookup['Paris']).toBe(25);
			expect(lookup['Berlin']).toBe(35);

			await navigateAndWaitForTable(page, info.analysisId);
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
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			expect(preview.columns).toEqual(expect.arrayContaining(['name', 'city', 'field', 'val']));
			// 3 rows × 2 unpivoted columns = 6 rows
			expect(preview.total_rows).toBe(6);

			const fields = preview.data.map((r) => r.field);
			expect(fields).toContain('id');
			expect(fields).toContain('age');

			await navigateAndWaitForTable(page, info.analysisId);
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
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			// City values become column names
			expect(preview.columns).toContain('name');
			expect(preview.columns).toContain('London');
			expect(preview.columns).toContain('Paris');
			expect(preview.columns).toContain('Berlin');
			expect(preview.total_rows).toBe(3);

			// Alice has London=30, Bob has Paris=25, Charlie has Berlin=35
			const alice = preview.data.find((r) => r.name === 'Alice');
			expect(alice?.London).toBe(30);
			const bob = preview.data.find((r) => r.name === 'Bob');
			expect(bob?.Paris).toBe(25);

			await navigateAndWaitForTable(page, info.analysisId);
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
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			// No nulls in sample data → structure unchanged
			expect(preview.columns).toEqual(['id', 'name', 'age', 'city']);
			expect(preview.total_rows).toBe(3);

			await navigateAndWaitForTable(page, info.analysisId);
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
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			// Self-join on city: each city matches once → 3 rows
			expect(preview.total_rows).toBe(3);
			// Right columns get suffix: id_right, name_right, age_right
			expect(preview.columns).toContain('id');
			expect(preview.columns).toContain('id_right');
			expect(preview.columns).toContain('name_right');

			// Self-join: left and right values should match
			for (const row of preview.data) {
				expect(row.name).toBe(row.name_right);
				expect(row.age).toBe(row.age_right);
			}

			await navigateAndWaitForTable(page, info.analysisId);
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
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			// All 3 rows match age >= 25, sorted desc: Charlie(35), Alice(30), Bob(25)
			// Then limited to 2: Charlie, Alice
			expect(preview.total_rows).toBe(2);
			expect(preview.data[0].name).toBe('Charlie');
			expect(preview.data[1].name).toBe('Alice');

			// UI: verify the step nodes are all present on canvas
			await navigateAndWaitForTable(page, info.analysisId);
			await expect(page.locator('[data-step-type="filter"]')).toBeVisible();
			await expect(page.locator('[data-step-type="sort"]')).toBeVisible();
			await expect(page.locator('[data-step-type="limit"]')).toBeVisible();
			await expect(page.locator('[data-step-type="view"]')).toBeVisible();

			// UI: verify table shows correct data
			const table = page.locator('[data-testid="inline-data-table"]');
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
		// Chart steps produce x/y visualization columns. The trailing view step
		// added by createPipelineAnalysis would override the chart preview with
		// the original schema, so we build the pipeline without a trailing view.
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
		const chartInfo: PipelineAnalysisResult = {
			analysisId: aId,
			viewStepId: chartStepId,
			tabId: chartTabId,
			resultId: chartResultId,
			dsId,
			steps: chartSteps
		};
		try {
			const preview = await fetchPreviewViaAPI(request, chartInfo, chartStepId);

			// Chart preview returns aggregated data with x/y columns
			expect(preview.columns).toContain('x');
			expect(preview.columns).toContain('y');
			expect(preview.total_rows).toBe(3); // 3 unique cities

			// Each city sums to its single age value
			const lookup = Object.fromEntries(preview.data.map((r) => [r.x, r.y]));
			expect(lookup['London']).toBe(30);
			expect(lookup['Paris']).toBe(25);
			expect(lookup['Berlin']).toBe(35);

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
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			expect(preview.columns).toEqual(['id', 'name', 'age', 'city']);
			expect(preview.total_rows).toBe(3);

			await navigateAndWaitForTable(page, info.analysisId);
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
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			expect(preview.columns).toEqual(['id', 'name', 'age', 'city']);
			expect(preview.total_rows).toBe(3);

			await navigateAndWaitForTable(page, info.analysisId);
			await screenshot(page, 'analysis/pipeline', 'download');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});

	test('explode expands list column into rows', async ({ page, request }) => {
		// Create a list column via expression, then explode it
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
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			// Each row had 2 elements in tags (name,city) → 3×2 = 6 rows
			expect(preview.total_rows).toBe(6);
			expect(preview.columns).toContain('tags');

			const tags = preview.data.map((r) => r.tags);
			expect(tags).toContain('Alice');
			expect(tags).toContain('London');
			expect(tags).toContain('Bob');
			expect(tags).toContain('Paris');

			await navigateAndWaitForTable(page, info.analysisId);
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
			// Cast event_date from string to Date before timeseries operation
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
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId);

			expect(preview.columns).toContain('event_month');
			expect(preview.total_rows).toBe(3);

			// Months: Jan(1), Mar(3), Jun(6)
			const months = preview.data.map((r) => r.event_month);
			expect(months).toContain(1);
			expect(months).toContain(3);
			expect(months).toContain(6);

			await navigateAndWaitForTable(page, info.analysisId);
			const table = page.locator('[data-testid="inline-data-table"]');
			await expect(table.locator('[data-column-id="event_month"]')).toBeVisible();

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
		// Union step references the second datasource by its ID (same as UI behavior)
		const aName = `E2E Pipe Union ${uid()}`;
		const info = await createPipelineAnalysis(request, aName, dsId1, [
			{
				type: 'union_by_name',
				config: { sources: [dsId2], allow_missing: true }
			}
		]);

		try {
			const preview = await fetchPreviewViaAPI(request, info, info.viewStepId, [dsId2]);

			// Both datasources have same SAMPLE_CSV (3 rows each) → 6 rows total
			expect(preview.columns).toEqual(['id', 'name', 'age', 'city']);
			expect(preview.total_rows).toBe(6);

			// All names appear twice (once from each source)
			const names = preview.data.map((r) => r.name);
			expect(names.filter((n) => n === 'Alice')).toHaveLength(2);
			expect(names.filter((n) => n === 'Bob')).toHaveLength(2);
			expect(names.filter((n) => n === 'Charlie')).toHaveLength(2);

			await navigateAndWaitForTable(page, info.analysisId);
			await screenshot(page, 'analysis/pipeline', 'union-by-name');
		} finally {
			await leaveAnalysisPage(page);
			await deleteAnalysisViaUI(page, aName, { skipNavigation: true });
		}
	});
});
