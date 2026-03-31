import { test, expect } from '@playwright/test';
import { createDatasource, createAnalysis } from './utils/api.js';
import { deleteAnalysisViaUI, deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { uid } from './utils/uid.js';
import { screenshot } from './utils/visual.js';

test.describe('Analyses – list & gallery', () => {
	test('home page renders main content area', async ({ page }) => {
		await page.goto('/');
		await expect(page.getByRole('heading', { name: 'Analyses', level: 1 })).toBeVisible();
		await expect(page.getByText(/Browse and manage your data analyses/i)).toBeVisible();
		await screenshot(page, 'analysis/crud', 'gallery');
	});

	test('lists existing analysis after API create', async ({ page, request }) => {
		const dsName = `e2e-list-ds-${uid()}`;
		const aName = `E2E List ${uid()}`;
		const dsId = await createDatasource(request, dsName);
		await createAnalysis(request, aName, dsId);
		try {
			await page.goto('/');
			await expect(page.getByText(aName)).toBeVisible();
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('search filters out non-matching analyses', async ({ page, request }) => {
		const suffix = uid();
		const dsName = `e2e-search-ds-${suffix}`;
		const analysisName = `E2E Search Alpha ${suffix}`;
		const dsId = await createDatasource(request, dsName);
		await createAnalysis(request, analysisName, dsId);
		try {
			await page.goto('/');
			const card = page.locator(`[data-analysis-card="${analysisName}"]`);
			await expect(card).toBeVisible();

			// The search box rendered by AnalysisFilters
			await page.getByRole('textbox').first().fill('ZZZNOMATCH');
			await expect(page.getByText(/No analyses match your search/i)).toBeVisible();
		} finally {
			await deleteAnalysisViaUI(page, analysisName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('delete analysis via confirm dialog removes it from list', async ({ page, request }) => {
		const dsName = `e2e-del-ds-${uid()}`;
		const aName = `E2E Delete ${uid()}`;
		const dsId = await createDatasource(request, dsName);
		await createAnalysis(request, aName, dsId);
		try {
			await page.goto('/');
			const card = page.locator(`[data-analysis-card="${aName}"]`);
			await expect(card.first()).toBeVisible();
			const countBefore = await card.count();

			await card
				.first()
				.getByRole('button', { name: /Delete analysis/ })
				.click();

			// Confirm dialog appears
			const dialog = page.getByRole('dialog');
			await expect(dialog.getByRole('heading', { name: /Delete Analysis/i })).toBeVisible();
			await dialog.getByRole('button', { name: /^Delete$/ }).click();

			await expect(card).toHaveCount(countBefore - 1, { timeout: 8_000 });
		} finally {
			await deleteDatasourceViaUI(page, dsName);
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
		await screenshot(page, 'analysis/crud', 'wizard-step-2');
	});

	test('step 2: shows "No data sources available" when none exist', async ({ page }) => {
		await page.route('**/api/v1/datasource', (route) => {
			if (route.request().method() === 'GET') {
				return route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify([])
				});
			}
			return route.continue();
		});

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
		const dsName = `e2e-create-ds-${uid()}`;
		const aName = `E2E Created ${uid()}`;
		await createDatasource(request, dsName);
		try {
			await page.goto('/analysis/new');

			// Step 1 – name
			await page.locator('#name').fill(aName);
			await page.getByRole('button', { name: /Next/i }).click();

			// Step 2 – pick datasource
			await expect(page.getByRole('heading', { name: /Select Data Sources/i })).toBeVisible();
			await page.getByPlaceholder('Search datasources...').click();
			await page.locator('[role="option"]', { hasText: dsName }).first().click();
			// Close the dropdown by clicking outside
			await page.getByRole('heading', { name: /Select Data Sources/i }).click();
			await expect(page.getByRole('button', { name: /Next/i })).toBeEnabled();
			await page.getByRole('button', { name: /Next/i }).click();

			// Step 3 – review
			await expect(page.getByRole('heading', { name: /Review/i })).toBeVisible();
			await expect(page.getByText(aName).first()).toBeVisible();
			await page.getByRole('button', { name: /Create Analysis/i }).click();

			// Redirects to analysis editor
			await page.waitForURL(/\/analysis\/.+/, { timeout: 20_000 });
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
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
	let dsName: string;
	let aName: string;

	test.beforeAll(async ({ request }) => {
		dsName = `e2e-detail-ds-${uid()}`;
		aName = `E2E Detail ${uid()}`;
		dsId = await createDatasource(request, dsName);
		aId = await createAnalysis(request, aName, dsId);
	});

	test.afterAll(async ({ browser }) => {
		const page = await browser.newPage();
		await deleteAnalysisViaUI(page, aName);
		await deleteDatasourceViaUI(page, dsName);
		await page.close();
	});

	test('analysis detail page loads with step library', async ({ page }) => {
		await page.goto(`/analysis/${aId}`);
		// StepLibrary heading is "Operations"
		await expect(page.getByRole('heading', { name: 'Operations' })).toBeVisible({
			timeout: 15_000
		});
		await screenshot(page, 'analysis/crud', 'detail-step-library');
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
		await expect(page.getByRole('heading', { name: 'Operations' })).toBeVisible({
			timeout: 15_000
		});
		await expect(page.getByRole('button', { name: /^(Save|Saved|Saving\.\.\.)$/ })).toBeVisible({
			timeout: 10_000
		});
	});

	test('analysis name is shown in the detail page', async ({ page }) => {
		await page.goto(`/analysis/${aId}`);
		await expect(page.getByText(aName)).toBeVisible({ timeout: 10_000 });
	});
});

test.describe('Analyses – detail error state', () => {
	test('bad analysis ID shows error state without crashing the shell', async ({ page }) => {
		// Intercept the analysis fetch to simulate a 500 error
		await page.route('**/api/v1/analysis/bad-id-000*', (route) => {
			if (route.request().method() === 'GET') {
				return route.fulfill({ status: 500, body: 'Internal Server Error' });
			}
			return route.continue();
		});

		await page.goto('/analysis/bad-id-000');

		// Error state should render
		await expect(page.locator('[data-testid="analysis-load-error"]')).toBeVisible({
			timeout: 15_000
		});
		await expect(page.getByText('Error loading analysis')).toBeVisible();

		// "Create analysis" recovery button should be present
		await expect(page.getByRole('button', { name: /Create analysis/i })).toBeVisible();

		await screenshot(page, 'analysis/crud', 'detail-load-error');
	});

	test('analysis error page does not crash navigation', async ({ page }) => {
		await page.route('**/api/v1/analysis/bad-id-nav*', (route) => {
			if (route.request().method() === 'GET') {
				return route.fulfill({ status: 500, body: 'Internal Server Error' });
			}
			return route.continue();
		});

		await page.goto('/analysis/bad-id-nav');
		await expect(page.locator('[data-testid="analysis-load-error"]')).toBeVisible({
			timeout: 15_000
		});

		// Navigate home — shell should still work
		await page.locator('a[href="/"]').first().click();
		await expect(page).toHaveURL('/');
		await expect(page.getByRole('heading', { name: 'Analyses', level: 1 })).toBeVisible();
	});
});
