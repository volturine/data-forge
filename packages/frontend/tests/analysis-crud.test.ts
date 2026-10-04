import { test, expect } from './fixtures.js';
import { createAnalysis } from './utils/api.js';
import { deleteAnalysisViaUI } from './utils/ui-cleanup.js';
import { uid } from './utils/uid.js';
import { screenshot } from './utils/visual.js';
import {
	gotoAnalysesGallery,
	gotoNewAnalysis,
	waitForAnalysisLoadError,
	readyTimeoutMs
} from './utils/readiness.js';
import { gotoAnalysisEditor, waitForCurrentAnalysisEditor } from './utils/analysis.js';
import { dialogByHeading } from './utils/locators.js';

async function expandSidebar(page: Parameters<typeof gotoAnalysesGallery>[0]) {
	const button = page.getByRole('button', { name: 'Expand sidebar' });
	if (await button.isVisible().catch(() => false)) {
		await button.click();
	}
}

test.describe('Analyses – list & gallery', () => {
	let sharedDatasourceId = '';

	test.beforeEach(async ({ sharedDatasource }) => {
		sharedDatasourceId = sharedDatasource.id;
	});

	test('home page renders main content area', async ({ page }) => {
		await gotoAnalysesGallery(page);
		await expect(page.getByRole('heading', { name: 'Analyses', level: 1 })).toBeVisible();
		await expect(page.getByText(/Browse and manage your data analyses/i)).toBeVisible();
		await screenshot(page, 'analysis/crud', 'gallery');
	});

	test('lists existing analysis after API create', async ({ page, request }) => {
		const aName = `E2E List ${uid()}`;
		await createAnalysis(request, aName, sharedDatasourceId);
		try {
			await gotoAnalysesGallery(page);
			await expect(page.locator(`[data-analysis-card="${aName}"]`)).toBeVisible();
		} finally {
			await deleteAnalysisViaUI(page, aName);
		}
	});

	test('search filters out non-matching analyses', async ({ page, request }) => {
		const suffix = uid();
		const analysisName = `E2E Search Alpha ${suffix}`;
		await createAnalysis(request, analysisName, sharedDatasourceId);
		try {
			await gotoAnalysesGallery(page);
			const card = page.locator(`[data-analysis-card="${analysisName}"]`);
			await expect(card).toBeVisible();

			await page.getByRole('textbox', { name: 'Search analyses' }).fill('ZZZNOMATCH');
			await expect(page.getByText(/No analyses match your search/i)).toBeVisible();
		} finally {
			await deleteAnalysisViaUI(page, analysisName);
		}
	});

	test('favorited analyses appear in the sidebar and persist on reload', async ({
		page,
		request
	}) => {
		const suffix = uid();
		const analysisName = `E2E Favorite ${suffix}`;
		const aId = await createAnalysis(request, analysisName, sharedDatasourceId);
		try {
			await gotoAnalysesGallery(page);
			await expandSidebar(page);

			const card = page.locator(`[data-analysis-card="${analysisName}"]`);
			await expect(card).toBeVisible();
			const favoriteResponse = page.waitForResponse(
				(response) =>
					new URL(response.url()).pathname === `/api/v1/analysis/${aId}/favorite` &&
					response.request().method() === 'POST'
			);
			await card.getByRole('button', { name: 'Add analysis to favorites' }).click();
			expect((await favoriteResponse).status()).toBe(200);

			const favorites = page.getByRole('group', { name: 'Favorite analyses' });
			const link = favorites.getByRole('link', { name: analysisName });
			await expect(link).toBeVisible({ timeout: readyTimeoutMs() });

			await page.reload();
			await gotoAnalysesGallery(page);
			await expandSidebar(page);
			const persistedLink = page
				.getByRole('group', { name: 'Favorite analyses' })
				.getByRole('link', { name: analysisName });
			await expect(persistedLink).toBeVisible({ timeout: readyTimeoutMs() });
			await persistedLink.click();
			await expect(page).toHaveURL(`/analysis/${aId}`);
		} finally {
			await deleteAnalysisViaUI(page, analysisName);
		}
	});

	test('delete analysis via confirm dialog removes it from list', async ({ page, request }) => {
		const aName = `E2E Delete ${uid()}`;
		await createAnalysis(request, aName, sharedDatasourceId);
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
			await deleteAnalysisViaUI(page, aName).catch(() => undefined);
		}
	});
});

test.describe('Analyses – gallery interactions', () => {
	test('opens prefetched analyses when switching between analysis cards', async ({
		page,
		request,
		sharedDatasource
	}) => {
		const suffix = uid();
		const firstName = `Prefetched First ${suffix}`;
		const secondName = `Prefetched Second ${suffix}`;
		const firstId = await createAnalysis(request, firstName, sharedDatasource.id);
		const secondId = await createAnalysis(request, secondName, sharedDatasource.id);

		try {
			for (const [name, id] of [
				[firstName, firstId],
				[secondName, secondId]
			] as const) {
				await gotoAnalysesGallery(page);
				const card = page.locator(`[data-analysis-card="${name}"]`);
				const prefetch = page.waitForResponse(
					(response) =>
						new URL(response.url()).pathname === `/api/v1/analysis/${id}` &&
						response.request().method() === 'GET'
				);
				await card.hover();
				expect((await prefetch).status()).toBe(200);
				await card.click();
				expect(await waitForCurrentAnalysisEditor(page, readyTimeoutMs())).toBe(id);
			}
		} finally {
			await deleteAnalysisViaUI(page, firstName).catch(() => undefined);
			await deleteAnalysisViaUI(page, secondName).catch(() => undefined);
		}
	});

	test('sort dropdown A-Z reorders analysis cards', async ({ page, request, sharedDatasource }) => {
		const suffix = uid();
		const alphaName = `Alpha Sort ${suffix}`;
		const zebraName = `Zebra Sort ${suffix}`;
		await createAnalysis(request, zebraName, sharedDatasource.id);
		await createAnalysis(request, alphaName, sharedDatasource.id);
		try {
			await gotoAnalysesGallery(page);
			await expect(page.locator(`[data-analysis-card="${zebraName}"]`)).toBeVisible();
			await expect(page.locator(`[data-analysis-card="${alphaName}"]`)).toBeVisible();

			// Switch to A-Z sort and verify Alpha comes first
			await page.locator('#sort-select').selectOption('name-asc');
			await expect(page.locator('[data-analysis-card]').first()).toHaveAttribute(
				'data-analysis-card',
				alphaName,
				{ timeout: 5_000 }
			);

			// Switch to Z-A sort and verify Zebra comes first
			await page.locator('#sort-select').selectOption('name-desc');
			await expect(page.locator('[data-analysis-card]').first()).toHaveAttribute(
				'data-analysis-card',
				zebraName,
				{ timeout: 5_000 }
			);
		} finally {
			await deleteAnalysisViaUI(page, alphaName);
			await deleteAnalysisViaUI(page, zebraName);
		}
	});

	test('duplicate analysis creates a copy via modal', async ({
		page,
		request,
		sharedDatasource
	}) => {
		const suffix = uid();
		const aName = `E2E Duplicate ${suffix}`;
		await createAnalysis(request, aName, sharedDatasource.id);
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
				timeout: 10_000
			});
		} finally {
			await deleteAnalysisViaUI(page, `Copy of ${aName}`);
			await deleteAnalysisViaUI(page, aName);
		}
	});

	test('bulk select and delete removes multiple analyses', async ({
		page,
		request,
		sharedDatasource
	}) => {
		const suffix = uid();
		const a1 = `Bulk One ${suffix}`;
		const a2 = `Bulk Two ${suffix}`;
		const id1 = await createAnalysis(request, a1, sharedDatasource.id);
		const id2 = await createAnalysis(request, a2, sharedDatasource.id);
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
			await deleteAnalysisViaUI(page, a1).catch(() => undefined);
			await deleteAnalysisViaUI(page, a2).catch(() => undefined);
		}
	});
});

test.describe('Analyses – blank creation', () => {
	test('requires a datasource before creating an analysis', async ({ page }) => {
		await gotoNewAnalysis(page);
		await expect(page.getByRole('heading', { name: 'Select a datasource' })).toBeVisible();
		await expect(page.getByPlaceholder('Search datasources...')).toBeVisible();
		await expect(page.getByRole('button', { name: 'Create Analysis' })).toBeDisabled();
	});

	test('creates a top-aligned blank pipeline with centered insert controls', async ({
		page,
		sharedDatasource
	}) => {
		const analysisName = `${sharedDatasource.name} Analysis`;
		let analysisId: string | undefined;
		await page.setViewportSize({ width: 1280, height: 1600 });

		try {
			await gotoNewAnalysis(page);
			await page.getByPlaceholder('Search datasources...').click();
			await page.locator(`[data-picker-option="${sharedDatasource.name}"]`).click();
			const createButton = page.getByRole('button', { name: 'Create Analysis' });
			await expect(createButton).toBeEnabled();
			const createResponsePromise = page.waitForResponse(
				(response) =>
					response.url().endsWith('/api/v1/analysis') && response.request().method() === 'POST'
			);
			await createButton.click();
			const createResponse = await createResponsePromise;
			if (!createResponse.ok()) {
				throw new Error(`Create analysis failed: HTTP ${createResponse.status()}`);
			}

			const created = (await createResponse.json()) as {
				id: string;
				pipeline_definition: {
					tabs: Array<{
						datasource: { id: string };
						steps: unknown[];
						output: { result_id: string; iceberg?: { table_name?: string } };
					}>;
				};
			};
			analysisId = created.id;
			const tab = created.pipeline_definition.tabs[0];
			if (!tab) throw new Error('Created analysis did not contain its source tab');
			expect(created.pipeline_definition.tabs).toHaveLength(1);
			expect(tab.datasource.id).toBe(sharedDatasource.id);
			expect(tab.steps).toEqual([]);
			expect(tab.output.iceberg?.table_name).toContain(tab.output.result_id.slice(0, 8));

			await expect(page).toHaveURL((url) => url.pathname === `/analysis/${analysisId}`, {
				timeout: readyTimeoutMs()
			});
			await waitForCurrentAnalysisEditor(page, readyTimeoutMs());
			await expect(page.locator('[data-step-type]')).toHaveCount(0);

			const canvas = page.locator('.pipeline-canvas');
			const flow = canvas.locator(':scope > div[role="list"]');
			const canvasBounds = await canvas.boundingBox();
			const flowBounds = await flow.boundingBox();
			if (!canvasBounds || !flowBounds)
				throw new Error('Could not measure the empty pipeline canvas');
			expect(flowBounds.y - canvasBounds.y).toBeLessThan(80);

			const insertZone = canvas.locator('[data-hook="insert-zone"]').first();
			await insertZone.hover();
			const connection = insertZone.locator('.connection-line');
			await expect(canvas.locator('.connection-line')).toHaveCount(1);
			const connectionBounds = await connection.boundingBox();
			if (!connectionBounds) throw new Error('Could not measure the empty pipeline connection');

			const controls = insertZone.locator('.insert-controls-group > *');
			await expect(controls).toHaveCount(3);
			const controlBounds = await Promise.all(
				Array.from({ length: await controls.count() }, (_, index) =>
					controls.nth(index).boundingBox()
				)
			);
			const visibleControlBounds = controlBounds.filter((bounds) => bounds !== null);
			expect(visibleControlBounds).toHaveLength(3);
			const controlsTop = Math.min(...visibleControlBounds.map((bounds) => bounds.y));
			const controlsBottom = Math.max(
				...visibleControlBounds.map((bounds) => bounds.y + bounds.height)
			);
			expect(
				Math.abs(
					(controlsTop + controlsBottom) / 2 - (connectionBounds.y + connectionBounds.height / 2)
				)
			).toBeLessThan(1);
		} finally {
			if (analysisId) {
				await deleteAnalysisViaUI(page, analysisName, { id: analysisId }).catch(() => undefined);
			}
		}
	});

	test('empty-gallery Create Analysis opens the datasource picker', async ({ page }) => {
		await page.route('**/api/v1/analysis', async (route) => {
			if (route.request().method() === 'GET') {
				await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
				return;
			}
			await route.continue();
		});

		await gotoAnalysesGallery(page);
		await expect(page.getByRole('heading', { name: 'No analyses yet' })).toBeVisible();
		await page.getByRole('button', { name: 'Create Analysis' }).click();
		await expect(page).toHaveURL(/\/analysis\/new$/);
		await expect(page.getByRole('heading', { name: 'Select a datasource' })).toBeVisible();
	});

	test('Cancel returns to the analyses gallery', async ({ page }) => {
		await gotoNewAnalysis(page);
		await page.getByRole('link', { name: 'Cancel', exact: true }).click();
		await expect(page).toHaveURL('/', { timeout: 5_000 });
	});
});

test.describe('Analyses – detail page', () => {
	let dsId = '';
	let aId = '';
	let aName: string;

	test.beforeEach(async ({ request, sharedDatasource }) => {
		aName = `E2E Detail ${uid()}`;
		dsId = sharedDatasource.id;
		aId = await createAnalysis(request, aName, dsId);
	});

	test.afterEach(async ({ page }) => {
		await deleteAnalysisViaUI(page, aName, { id: aId });
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
		await gotoAnalysisEditor(page, aId);
		await expect(page.getByRole('heading', { name: aName, level: 1 })).toBeVisible({
			timeout: readyTimeoutMs()
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
