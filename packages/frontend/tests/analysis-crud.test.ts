import { test, expect } from './fixtures.js';
import { createDatasource, createAnalysis } from './utils/api.js';
import {
	createCleanupPage,
	deleteAnalysisViaUI,
	deleteDatasourceViaUI
} from './utils/ui-cleanup.js';
import { uid } from './utils/uid.js';
import { screenshot } from './utils/visual.js';
import {
	gotoAnalysesGallery,
	gotoNewAnalysis,
	waitForAnalysisLoadError,
	waitForLayoutReady
} from './utils/readiness.js';
import { gotoAnalysisEditor } from './utils/analysis.js';
import { dialogByHeading } from './utils/locators.js';

async function expandSidebar(page: Parameters<typeof gotoAnalysesGallery>[0]) {
	const button = page.getByRole('button', { name: 'Expand sidebar' });
	if (await button.isVisible().catch(() => false)) {
		await button.click();
	}
}

test.describe('Analyses – list & gallery', () => {
	test('home page renders main content area', async ({ page }) => {
		await gotoAnalysesGallery(page);
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
			await gotoAnalysesGallery(page);
			await expect(page.locator(`[data-analysis-card="${aName}"]`)).toBeVisible();
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
			await gotoAnalysesGallery(page);
			const card = page.locator(`[data-analysis-card="${analysisName}"]`);
			await expect(card).toBeVisible();

			await page.getByRole('textbox', { name: 'Search analyses' }).fill('ZZZNOMATCH');
			await expect(page.getByText(/No analyses match your search/i)).toBeVisible();
		} finally {
			await deleteAnalysisViaUI(page, analysisName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('favorited analyses appear in the sidebar and persist on reload', async ({
		page,
		request
	}) => {
		const suffix = uid();
		const dsName = `e2e-favorite-ds-${suffix}`;
		const analysisName = `E2E Favorite ${suffix}`;
		const dsId = await createDatasource(request, dsName);
		const aId = await createAnalysis(request, analysisName, dsId);
		try {
			await gotoAnalysesGallery(page);
			await expandSidebar(page);

			const card = page.locator(`[data-analysis-card="${analysisName}"]`);
			await expect(card).toBeVisible();
			await card.getByRole('button', { name: 'Add analysis to favorites' }).click();

			const favorites = page.getByRole('group', { name: 'Favorite analyses' });
			const link = favorites.getByRole('link', { name: analysisName });
			await expect(link).toBeVisible({ timeout: 5_000 });

			await page.reload({ waitUntil: 'networkidle' });
			await gotoAnalysesGallery(page);
			await expandSidebar(page);
			const persistedLink = page
				.getByRole('group', { name: 'Favorite analyses' })
				.getByRole('link', { name: analysisName });
			await expect(persistedLink).toBeVisible({ timeout: 5_000 });
			await persistedLink.click();
			await expect(page).toHaveURL(`/analysis/${aId}`);
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
			await gotoAnalysesGallery(page);
			const card = page.locator(`[data-analysis-card="${aName}"]`);
			await expect(card).toBeVisible();
			const countBefore = await card.count();

			await card.getByRole('button', { name: /Delete analysis/ }).click();

			// Confirm dialog appears
			const dialog = dialogByHeading(page, /Delete Analysis/i);
			await expect(dialog).toBeVisible();
			await dialog.getByRole('button', { name: /^Delete$/ }).click();

			await expect(card).toHaveCount(countBefore - 1, { timeout: 5_000 });
		} finally {
			await deleteDatasourceViaUI(page, dsName);
		}
	});
});

test.describe('Analyses – gallery interactions', () => {
	test('sort dropdown A-Z reorders analysis cards', async ({ page, request }) => {
		const suffix = uid();
		const dsName = `e2e-sort-ds-${suffix}`;
		const alphaName = `Alpha Sort ${suffix}`;
		const zebraName = `Zebra Sort ${suffix}`;
		const dsId = await createDatasource(request, dsName);
		await createAnalysis(request, zebraName, dsId);
		await createAnalysis(request, alphaName, dsId);
		try {
			await gotoAnalysesGallery(page);
			await expect(page.locator(`[data-analysis-card="${zebraName}"]`)).toBeVisible();
			await expect(page.locator(`[data-analysis-card="${alphaName}"]`)).toBeVisible();

			// Switch to A-Z sort and verify Alpha comes first
			await page.locator('#sort-select').selectOption('name-asc');
			await page.waitForTimeout(200);
			await expect
				.poll(
					async () => {
						return await page
							.locator('[data-analysis-card]')
							.first()
							.getAttribute('data-analysis-card');
					},
					{ timeout: 5_000 }
				)
				.toBe(alphaName);

			// Switch to Z-A sort and verify Zebra comes first
			await page.locator('#sort-select').selectOption('name-desc');
			await page.waitForTimeout(200);
			await expect
				.poll(
					async () => {
						return await page
							.locator('[data-analysis-card]')
							.first()
							.getAttribute('data-analysis-card');
					},
					{ timeout: 5_000 }
				)
				.toBe(zebraName);
		} finally {
			await deleteAnalysisViaUI(page, alphaName);
			await deleteAnalysisViaUI(page, zebraName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('duplicate analysis creates a copy via modal', async ({ page, request }) => {
		const suffix = uid();
		const dsName = `e2e-dup-ds-${suffix}`;
		const aName = `E2E Duplicate ${suffix}`;
		const dsId = await createDatasource(request, dsName);
		await createAnalysis(request, aName, dsId);
		try {
			await gotoAnalysesGallery(page);
			const card = page.locator(`[data-analysis-card="${aName}"]`);
			await expect(card).toBeVisible();

			// Click duplicate button on the card
			await card.getByRole('button', { name: /Duplicate analysis/i }).click();

			// Modal opens with pre-filled name
			const modal = page.locator('[role="dialog"]').filter({ hasText: /Duplicate Analysis/i });
			await expect(modal).toBeVisible({ timeout: 5_000 });
			const nameInput = modal.locator('input').first();
			await expect(nameInput).toHaveValue(`Copy of ${aName}`);

			// Click Duplicate
			await modal.getByRole('button', { name: /^Duplicate$/ }).click();

			// Should navigate to the new analysis
			await expect(page).toHaveURL(/\/analysis\//, { timeout: 10_000 });
			await expect(page.getByRole('heading', { name: /Copy of /i, level: 1 })).toBeVisible({
				timeout: 5_000
			});
		} finally {
			await deleteAnalysisViaUI(page, `Copy of ${aName}`);
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('bulk select and delete removes multiple analyses', async ({ page, request }) => {
		const suffix = uid();
		const dsName = `e2e-bulk-ds-${suffix}`;
		const a1 = `Bulk One ${suffix}`;
		const a2 = `Bulk Two ${suffix}`;
		const dsId = await createDatasource(request, dsName);
		const id1 = await createAnalysis(request, a1, dsId);
		const id2 = await createAnalysis(request, a2, dsId);
		try {
			await gotoAnalysesGallery(page);
			await expect(page.locator(`[data-analysis-card="${a1}"]`)).toBeVisible();
			await expect(page.locator(`[data-analysis-card="${a2}"]`)).toBeVisible();

			// Check both test analysis checkboxes individually
			await page.locator(`#analysis-${id1}-select`).check();
			await page.locator(`#analysis-${id2}-select`).check();

			// Bulk action buttons should appear
			await expect(page.getByRole('button', { name: 'Delete', exact: true })).toBeVisible({
				timeout: 3_000
			});

			// Click bulk Delete
			await page.getByRole('button', { name: 'Delete', exact: true }).click();

			// Confirm dialog
			const dialog = dialogByHeading(page, /Delete Analyses/i);
			await expect(dialog).toBeVisible({ timeout: 3_000 });
			await dialog.getByRole('button', { name: /^Delete$/ }).click();

			// Both cards should be removed
			await expect(page.locator(`[data-analysis-card="${a1}"]`)).toBeHidden({ timeout: 10_000 });
			await expect(page.locator(`[data-analysis-card="${a2}"]`)).toBeHidden({ timeout: 10_000 });
		} finally {
			await deleteDatasourceViaUI(page, dsName);
		}
	});
});

test.describe('Analyses – create wizard', () => {
	test('step 1: Next is disabled when name is empty', async ({ page }) => {
		await gotoNewAnalysis(page);
		await expect(page.getByRole('button', { name: /Next/i })).toBeDisabled();
	});

	test('step 1: Next is enabled after typing a name', async ({ page }) => {
		await gotoNewAnalysis(page);
		await page.locator('#name').fill('My E2E Analysis');
		await expect(page.getByRole('button', { name: /Next/i })).toBeEnabled();
	});

	test('step 1 → step 2: shows datasource selection', async ({ page }) => {
		await gotoNewAnalysis(page);
		await page.locator('#name').fill('E2E Wizard Test');
		await page.getByRole('button', { name: /Next/i }).click();
		await expect(page.getByRole('heading', { name: /Select Data Sources/i })).toBeVisible();
		await screenshot(page, 'analysis/crud', 'wizard-step-2');
	});

	test('can navigate Back from step 2 to step 1', async ({ page }) => {
		await gotoNewAnalysis(page);
		await page.locator('#name').fill('Back Test');
		await page.getByRole('button', { name: /Next/i }).click();
		await page.getByRole('button', { name: /Back/i }).click();
		await expect(page.getByRole('heading', { name: /How do you want to start\?/i })).toBeVisible();
	});

	test('Cancel on step 1 returns to home', async ({ page }) => {
		await gotoNewAnalysis(page);
		await page.getByRole('link', { name: /Cancel/i }).click();
		await expect(page).toHaveURL('/', { timeout: 5_000 });
	});

	test('full create flow: wizard → analysis detail page', async ({ page, request }) => {
		const dsName = `e2e-create-ds-${uid()}`;
		const aName = `E2E Created ${uid()}`;
		await createDatasource(request, dsName);
		try {
			await gotoNewAnalysis(page);

			// Step 1 – name
			await page.locator('#name').fill(aName);
			await page.getByRole('button', { name: /Next/i }).click();

			// Step 2 – pick datasource
			await expect(page.getByRole('heading', { name: /Select Data Sources/i })).toBeVisible();
			await page.getByPlaceholder('Search datasources...').click();
			await page.locator(`[data-picker-option="${dsName}"]`).click();
			// Close the dropdown by clicking outside
			await page.getByRole('heading', { name: /Select Data Sources/i }).click();
			await expect(page.getByRole('button', { name: /Next/i })).toBeEnabled();
			await page.getByRole('button', { name: /Next/i }).click();

			// Step 3 – design
			await expect(page.getByRole('heading', { name: /Choose Template/i })).toBeVisible();
			await page.getByRole('button', { name: /Next/i }).click();

			// Step 4 – output
			await expect(page.getByRole('heading', { name: /Configure Outputs/i })).toBeVisible();
			await page.getByRole('button', { name: /Next/i }).click();

			// Step 5 – review
			await expect(page.getByRole('heading', { name: /Review/i })).toBeVisible();
			await expect(page.locator('main')).toContainText(aName);
			await page.getByRole('button', { name: /Create Analysis/i }).click();

			// Redirects to an actual analysis editor, not back to /analysis/new
			await expect(page).toHaveURL(
				(url) => url.pathname.startsWith('/analysis/') && url.pathname !== '/analysis/new',
				{ timeout: 5_000 }
			);
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('template wizard configures ordered sources, outputs, and validated review', async ({
		page,
		request
	}) => {
		const suffix = uid();
		const firstDsName = `e2e-template-first-${suffix}`;
		const secondDsName = `e2e-template-second-${suffix}`;
		const aName = `E2E Template ${uid()}`;
		await createDatasource(request, firstDsName);
		await createDatasource(request, secondDsName);
		try {
			await gotoNewAnalysis(page);
			await page.locator('#name').fill(aName);
			await page.getByRole('button', { name: /Next/i }).click();

			await expect(page.getByRole('heading', { name: /Select Data Sources/i })).toBeVisible();
			await page.getByPlaceholder('Search datasources...').click();
			await page.locator(`[data-picker-option="${firstDsName}"]`).click();
			await page.locator(`[data-picker-option="${secondDsName}"]`).click();
			await page.getByRole('heading', { name: /Select Data Sources/i }).click();

			const firstSource = page.getByRole('listitem', {
				name: `Selected datasource ${firstDsName}`
			});
			const secondSource = page.getByRole('listitem', {
				name: `Selected datasource ${secondDsName}`
			});
			await expect(firstSource.getByRole('combobox')).toHaveValue('master');
			await expect(firstSource.getByRole('button', { name: /Snapshot/i })).toContainText('Latest');
			await firstSource.getByRole('button', { name: /Snapshot/i }).click();
			await expect(page.getByText(/Selected: Latest/i)).toBeVisible();
			await page.keyboard.press('Escape');

			await secondSource.dragTo(firstSource);
			await expect(page.getByRole('listitem').filter({ hasText: secondDsName })).toBeVisible();
			await expect(
				page.getByRole('listitem', { name: /Selected datasource/ }).first()
			).toContainText(secondDsName);
			await page.getByRole('button', { name: /Next/i }).click();

			await expect(page.getByRole('heading', { name: /Choose Template/i })).toBeVisible();
			await page.getByRole('button', { name: 'Data Quality Audit' }).click();
			await expect(page.locator('main')).toContainText('Profile nulls, derive quality flags');
			await expect(page.locator('main')).toContainText(
				/view\s*→\s*filter\s*→\s*with_columns\s*→\s*groupby/
			);
			await page.getByRole('button', { name: /Next/i }).click();

			await expect(page.getByRole('heading', { name: /Configure Outputs/i })).toBeVisible();
			const outputSection = page.locator('section').filter({
				has: page.getByRole('heading', { name: /Configure Outputs/i })
			});
			const firstOutput = outputSection.locator(':scope > div > div').first();
			await firstOutput.getByLabel('Output name').fill('reviewed_output');
			await firstOutput.getByLabel('Namespace').fill('reviewed_namespace');
			await firstOutput.getByLabel('Table name').fill('reviewed_table');
			await firstOutput.getByLabel('Build mode').selectOption('incremental');
			await expect(firstOutput.getByLabel('Build mode')).toHaveValue('incremental');
			await page.getByRole('button', { name: /Next/i }).click();

			await expect(page.getByRole('heading', { name: /Review/i })).toBeVisible();
			await expect(page.locator('main')).toContainText('Sources: 2');
			await expect(page.locator('main')).toContainText('Steps: 8');
			await expect(page.locator('main')).toContainText('Complexity: High');
			await expect(page.locator('main')).toContainText(secondDsName);
			await expect(page.locator('main')).toContainText('view');
			await expect(page.locator('main')).toContainText('reviewed_namespace.reviewed_table');
			await expect(page.getByText('Validation passed.')).toBeVisible({ timeout: 5_000 });
			await page.getByRole('button', { name: /Create Analysis/i }).click();

			await expect(page).toHaveURL(
				(url) => url.pathname.startsWith('/analysis/') && url.pathname !== '/analysis/new',
				{ timeout: 5_000 }
			);
			const match = page.url().match(/\/analysis\/([^/?#]+)/);
			if (!match || match[1] === 'new') {
				throw new Error(`Could not extract analysis id from URL: ${page.url()}`);
			}
			await gotoAnalysisEditor(page, match[1]);
			await expect(page.locator('[role="application"]')).toHaveAttribute(
				'data-editor-access-state',
				'editable'
			);
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, firstDsName);
			await deleteDatasourceViaUI(page, secondDsName);
		}
	});

	test('JSON import remaps a missing datasource and reaches the editor', async ({
		page,
		request
	}) => {
		const suffix = uid();
		const dsName = `e2e-import-ds-${suffix}`;
		const analysisName = `E2E Import ${suffix}`;
		await createDatasource(request, dsName);
		try {
			await gotoNewAnalysis(page);
			await page.getByRole('button', { name: 'Import JSON' }).click();
			await page.locator('#name').fill(analysisName);
			await page.getByRole('button', { name: /Next/i }).click();

			const importedResultId = crypto.randomUUID();
			await page.locator('input[type="file"]').setInputFiles({
				name: 'pipeline.json',
				mimeType: 'application/json',
				buffer: Buffer.from(
					JSON.stringify({
						tabs: [
							{
								id: 'import-tab',
								name: 'Imported Source',
								parent_id: null,
								datasource: {
									id: 'missing-source',
									analysis_tab_id: null,
									config: { branch: 'master' }
								},
								output: {
									result_id: importedResultId,
									datasource_type: 'iceberg',
									format: 'parquet',
									filename: 'imported_output',
									build_mode: 'full',
									iceberg: {
										namespace: 'outputs',
										table_name: 'imported_output',
										branch: 'master'
									}
								},
								steps: []
							}
						]
					})
				)
			});
			await expect(page.getByText('Loaded: pipeline.json')).toBeVisible();
			await expect(page.getByText(/Remap missing datasource references/i)).toBeVisible();
			await page.getByLabel('Remap missing-source').selectOption({ label: dsName });
			await page.getByRole('button', { name: /Next/i }).click();
			await expect(page.getByRole('heading', { name: /Review Import/i })).toBeVisible();
			await expect(page.locator('main')).toContainText('Remapped datasources: 1');
			await page.getByRole('button', { name: /Create Analysis/i }).click();
			await expect(page).toHaveURL(
				(url) => url.pathname.startsWith('/analysis/') && url.pathname !== '/analysis/new',
				{ timeout: 5_000 }
			);
		} finally {
			await deleteAnalysisViaUI(page, analysisName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('description field is optional – can proceed without it', async ({ page }) => {
		await gotoNewAnalysis(page);
		await page.locator('#name').fill('No Desc Analysis');
		// description textarea exists but is empty – should not block Next
		await expect(page.locator('#description')).toBeVisible();
		await expect(page.getByRole('button', { name: /Next/i })).toBeEnabled();
	});

	test('description field accepts multiline text', async ({ page }) => {
		await gotoNewAnalysis(page);
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

	test.afterAll(async ({ browser, workerAuth }) => {
		const { page, context } = await createCleanupPage(browser, workerAuth.sessionState);
		await deleteAnalysisViaUI(page, aName);
		await deleteDatasourceViaUI(page, dsName);
		await page.close();
		await context.close();
	});

	test('analysis detail page loads with step library', async ({ page }) => {
		await gotoAnalysisEditor(page, aId);
		await screenshot(page, 'analysis/crud', 'detail-step-library');
	});

	test('step library shows search box', async ({ page }) => {
		await gotoAnalysisEditor(page, aId);
		await expect(page.getByPlaceholder(/Search operations/i)).toBeVisible({ timeout: 5_000 });
	});

	test('step library search filters operations', async ({ page }) => {
		await gotoAnalysisEditor(page, aId);
		await page.getByPlaceholder(/Search operations/i).fill('filter');
		await expect(page.getByText('Filter', { exact: true })).toBeVisible();
		// Non-matching steps should not show
		await expect(page.getByText('Pivot', { exact: true })).not.toBeVisible();
	});

	test('Save button is present', async ({ page }) => {
		await gotoAnalysisEditor(page, aId);
		await expect(page.getByRole('button', { name: /^(Save|Saved|Saving\.\.\.)$/ })).toBeVisible({
			timeout: 5_000
		});
	});

	test('analysis name is shown in the detail page', async ({ page }) => {
		await page.goto(`/analysis/${aId}`);
		await waitForLayoutReady(page);
		await expect(page.getByRole('heading', { name: aName, level: 1 })).toBeVisible({
			timeout: 5_000
		});
	});
});

test.describe('Analyses – detail error state', () => {
	const BAD_ID = '00000000-0000-0000-0000-000000000000';

	test('bad analysis ID shows error state without crashing the shell', async ({ page }) => {
		await page.goto(`/analysis/${BAD_ID}`);
		await waitForAnalysisLoadError(page);

		await expect(page.getByRole('button', { name: /Create analysis/i })).toBeVisible();

		await screenshot(page, 'analysis/crud', 'detail-load-error');
	});

	test('analysis error page does not crash navigation', async ({ page }) => {
		await page.goto(`/analysis/${BAD_ID}`);
		await waitForAnalysisLoadError(page);

		await page.getByRole('link', { name: 'Analyses' }).click();
		await expect(page).toHaveURL('/');
		await expect(page.getByRole('heading', { name: 'Analyses', level: 1 })).toBeVisible();
	});
});
