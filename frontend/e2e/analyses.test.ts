import { test, expect } from '@playwright/test';
import { createDatasource, deleteDatasource, createAnalysis, deleteAnalysis } from './utils/api.js';

/**
 * E2E tests for analyses – mirrors test_analysis.py / test_analysis_extended.py.
 */
test.describe('Analyses – list & gallery', () => {
	test('home page renders main content area', async ({ page }) => {
		await page.goto('/');
		await expect(page.getByRole('heading', { name: 'Analyses' })).toBeVisible();
		await expect(page.getByText(/Browse and manage your data analyses/i)).toBeVisible();
	});

	test('lists existing analysis after API create', async ({ page, request }) => {
		const dsId = await createDatasource(request, 'e2e-list-ds');
		const aId = await createAnalysis(request, 'E2E List Test', dsId);
		try {
			await page.goto('/');
			await expect(page.getByText('E2E List Test')).toBeVisible();
		} finally {
			await deleteAnalysis(request, aId);
			await deleteDatasource(request, dsId);
		}
	});

	test('search filters out non-matching analyses', async ({ page, request }) => {
		const dsId = await createDatasource(request, 'e2e-search-ds');
		const aId = await createAnalysis(request, 'E2E Search Alpha', dsId);
		try {
			await page.goto('/');
			await expect(page.getByText('E2E Search Alpha')).toBeVisible();

			// The search box rendered by AnalysisFilters
			await page.getByRole('textbox').first().fill('ZZZNOMATCH');
			await expect(page.getByText(/No analyses match your search/i)).toBeVisible();
		} finally {
			await deleteAnalysis(request, aId);
			await deleteDatasource(request, dsId);
		}
	});

	test('delete analysis via confirm dialog removes it from list', async ({ page, request }) => {
		const dsId = await createDatasource(request, 'e2e-del-ds');
		const aId = await createAnalysis(request, 'E2E Delete Me', dsId);
		try {
			await page.goto('/');
			const h3 = page.locator('h3', { hasText: 'E2E Delete Me' });
			await expect(h3.first()).toBeVisible();
			const countBefore = await h3.count();

			// Trash2 is an SVG with onclick on the card (not a button element)
			await h3.first().locator('..').locator('svg').click();

			// Confirm dialog appears
			await expect(page.getByRole('heading', { name: /Delete Analysis/i })).toBeVisible();
			await page.getByRole('button', { name: /^Delete$/ }).click();

			await expect(h3).toHaveCount(countBefore - 1, { timeout: 8_000 });
		} finally {
			await deleteAnalysis(request, aId).catch(() => undefined);
			await deleteDatasource(request, dsId);
		}
	});
});

test.describe('Analyses – create wizard', () => {
	test('step 1: Next is disabled when name is empty', async ({ page }) => {
		await page.goto('/analysis/new');
		await expect(page.getByRole('button', { name: /Next/i })).toBeDisabled();
	});

	test('step 1: Next is enabled after typing a name', async ({ page }) => {
		await page.goto('/analysis/new');
		await page.locator('#name').fill('My E2E Analysis');
		await expect(page.getByRole('button', { name: /Next/i })).toBeEnabled();
	});

	test('step 1 → step 2: shows datasource selection', async ({ page }) => {
		await page.goto('/analysis/new');
		await page.locator('#name').fill('E2E Wizard Test');
		await page.getByRole('button', { name: /Next/i }).click();
		await expect(page.getByRole('heading', { name: /Select Data Sources/i })).toBeVisible();
	});

	test('step 2: shows "No data sources available" when none exist', async ({ page, request }) => {
		const resp = await request.get('http://localhost:8000/api/v1/datasource');
		const datasources = (await resp.json()) as unknown[];
		test.skip(datasources.length > 0, 'Datasources exist – skipping empty-state check');

		await page.goto('/analysis/new');
		await page.locator('#name').fill('E2E No DS');
		await page.getByRole('button', { name: /Next/i }).click();
		await expect(page.getByText(/No data sources available/i)).toBeVisible();
	});

	test('can navigate Back from step 2 to step 1', async ({ page }) => {
		await page.goto('/analysis/new');
		await page.locator('#name').fill('Back Test');
		await page.getByRole('button', { name: /Next/i }).click();
		await page.getByRole('button', { name: /Back/i }).click();
		await expect(page.getByRole('heading', { name: /Analysis Details/i })).toBeVisible();
	});

	test('Cancel on step 1 returns to home', async ({ page }) => {
		await page.goto('/analysis/new');
		await page.getByRole('link', { name: /Cancel/i }).click();
		await page.waitForURL('/', { timeout: 8_000 });
	});

	test('full create flow: wizard → analysis detail page', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-create-ds');
		try {
			await page.goto('/analysis/new');

			// Step 1 – name
			await page.locator('#name').fill('E2E Created Analysis');
			await page.getByRole('button', { name: /Next/i }).click();

			// Step 2 – pick datasource
			// The DatasourcePicker is a SearchableDropdown: options only render when open.
			// We must focus the input to open the dropdown, then click the option.
			await expect(page.getByRole('heading', { name: /Select Data Sources/i })).toBeVisible();
			await page.getByPlaceholder('Search datasources...').click();
			await page.locator('[role="option"]', { hasText: 'e2e-create-ds' }).first().click();
			// Close the dropdown (it stays open in multi-select mode) by clicking outside
			await page.getByRole('heading', { name: /Select Data Sources/i }).click();
			await expect(page.getByRole('button', { name: /Next/i })).toBeEnabled();
			await page.getByRole('button', { name: /Next/i }).click();

			// Step 3 – review
			await expect(page.getByRole('heading', { name: /Review/i })).toBeVisible();
			await expect(page.getByText('E2E Created Analysis').first()).toBeVisible();
			await page.getByRole('button', { name: /Create Analysis/i }).click();

			// Redirects to analysis editor
			await page.waitForURL(/\/analysis\/.+/, { timeout: 20_000 });
		} finally {
			try {
				const listResp = await request.get('http://localhost:8000/api/v1/analysis');
				const analyses = (await listResp.json()) as Array<{ id: string; name: string }>;
				const created = analyses.find((a) => a.name === 'E2E Created Analysis');
				if (created) await deleteAnalysis(request, created.id);
				await deleteDatasource(request, dsId);
			} catch {
				// Cleanup best-effort — context may be closed if test timed out
			}
		}
	});

	test('description field is optional – can proceed without it', async ({ page }) => {
		await page.goto('/analysis/new');
		await page.locator('#name').fill('No Desc Analysis');
		// description textarea exists but is empty – should not block Next
		await expect(page.locator('#description')).toBeVisible();
		await expect(page.getByRole('button', { name: /Next/i })).toBeEnabled();
	});

	test('description field accepts multiline text', async ({ page }) => {
		await page.goto('/analysis/new');
		await page.locator('#description').fill('Line 1\nLine 2\nLine 3');
		const value = await page.locator('#description').inputValue();
		expect(value).toContain('Line 1');
	});
});

test.describe('Analyses – detail page', () => {
	let dsId = '';
	let aId = '';

	test.beforeAll(async ({ request }) => {
		dsId = await createDatasource(request, 'e2e-detail-ds');
		aId = await createAnalysis(request, 'E2E Detail Test', dsId);
	});

	test.afterAll(async ({ request }) => {
		await deleteAnalysis(request, aId);
		await deleteDatasource(request, dsId);
	});

	test('analysis detail page loads with step library', async ({ page }) => {
		await page.goto(`/analysis/${aId}`);
		// StepLibrary heading is "Operations"
		await expect(page.getByRole('heading', { name: 'Operations' })).toBeVisible({
			timeout: 15_000
		});
	});

	test('step library shows search box', async ({ page }) => {
		await page.goto(`/analysis/${aId}`);
		await expect(page.getByPlaceholder(/Search operations/i)).toBeVisible({ timeout: 10_000 });
	});

	test('step library search filters operations', async ({ page }) => {
		await page.goto(`/analysis/${aId}`);
		await page.getByPlaceholder(/Search operations/i).fill('filter');
		await expect(page.getByText('Filter', { exact: true })).toBeVisible();
		// Non-matching steps should not show
		await expect(page.getByText('Pivot', { exact: true })).not.toBeVisible();
	});

	test('Save button is present', async ({ page }) => {
		await page.goto(`/analysis/${aId}`);
		await expect(
			page.getByRole('button', { name: /Save/i }).or(page.getByTitle(/Save/i))
		).toBeVisible({ timeout: 10_000 });
	});

	test('analysis name is shown in the detail page', async ({ page }) => {
		await page.goto(`/analysis/${aId}`);
		await expect(page.getByText('E2E Detail Test')).toBeVisible({ timeout: 10_000 });
	});
});

test.describe('Analyses – step library nodes', () => {
	let dsId = '';
	let aId = '';

	test.beforeAll(async ({ request }) => {
		dsId = await createDatasource(request, 'e2e-nodes-ds');
		aId = await createAnalysis(request, 'E2E Nodes Test', dsId);
	});

	test.afterAll(async ({ request }) => {
		await deleteAnalysis(request, aId);
		await deleteDatasource(request, dsId);
	});

	// All 24 step types that appear in StepLibrary.svelte
	const ALL_STEP_LABELS = [
		'Filter',
		'Select',
		'Group By',
		'Sort',
		'Rename',
		'Drop',
		'Join',
		'Expression',
		'With Columns',
		'Pivot',
		'Unpivot',
		'Fill Null',
		'Deduplicate',
		'Explode',
		'Time Series',
		'String Transform',
		'Sample',
		'Limit',
		'Top K',
		'Chart',
		'Notify',
		'AI',
		'View',
		'Union By Name',
		'Download'
	];

	for (const label of ALL_STEP_LABELS) {
		test(`step type "${label}" is visible in library`, async ({ page }) => {
			await page.goto(`/analysis/${aId}`);
			// Use button[data-step] to target only step library buttons (not canvas nodes)
			await expect(page.locator('button[data-step]', { hasText: label }).first()).toBeVisible({
				timeout: 15_000
			});
		});
	}

	test('clicking Filter step adds it to the canvas', async ({ page }) => {
		await page.goto(`/analysis/${aId}`);
		await expect(page.locator('button[data-step="filter"]')).toBeVisible({ timeout: 15_000 });
		await page.locator('button[data-step="filter"]').click();
		// A Filter node should now appear on the canvas
		await expect(page.locator('[data-step-type="filter"]').first()).toBeVisible({ timeout: 5_000 });
	});

	test('clicking View step adds it to the canvas', async ({ page }) => {
		await page.goto(`/analysis/${aId}`);
		await expect(page.locator('button[data-step="view"]')).toBeVisible({ timeout: 15_000 });
		await page.locator('button[data-step="view"]').click();
		// Canvas should show a View node
		await expect(page.locator('[data-step-type="view"]').first()).toBeVisible({ timeout: 5_000 });
	});
});
