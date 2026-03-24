import { test, expect } from '@playwright/test';
import { createDatasource, createDatasourceWithDates, createAnalysis } from './utils/api.js';
import { addStepAndOpenConfig } from './utils/analysis.js';
import { deleteAnalysisViaUI, deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { screenshot } from './utils/visual.js';

/**
 * E2E tests for analyses – mirrors test_analysis.py / test_analysis_extended.py.
 */
test.describe('Analyses – list & gallery', () => {
	test('home page renders main content area', async ({ page }) => {
		await page.goto('/');
		await expect(page.getByRole('heading', { name: 'Analyses' })).toBeVisible();
		await expect(page.getByText(/Browse and manage your data analyses/i)).toBeVisible();
		await screenshot(page, 'analyses', 'gallery');
	});

	test('lists existing analysis after API create', async ({ page, request }) => {
		const dsId = await createDatasource(request, 'e2e-list-ds');
		await createAnalysis(request, 'E2E List Test', dsId);
		try {
			await page.goto('/');
			await expect(page.getByText('E2E List Test')).toBeVisible();
		} finally {
			await deleteAnalysisViaUI(page, 'E2E List Test');
			await deleteDatasourceViaUI(page, 'e2e-list-ds');
		}
	});

	test('search filters out non-matching analyses', async ({ page, request }) => {
		const dsId = await createDatasource(request, 'e2e-search-ds');
		await createAnalysis(request, 'E2E Search Alpha', dsId);
		try {
			await page.goto('/');
			await expect(page.getByText('E2E Search Alpha')).toBeVisible();

			// The search box rendered by AnalysisFilters
			await page.getByRole('textbox').first().fill('ZZZNOMATCH');
			await expect(page.getByText(/No analyses match your search/i)).toBeVisible();
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Search Alpha');
			await deleteDatasourceViaUI(page, 'e2e-search-ds');
		}
	});

	test('delete analysis via confirm dialog removes it from list', async ({ page, request }) => {
		const dsId = await createDatasource(request, 'e2e-del-ds');
		await createAnalysis(request, 'E2E Delete Me', dsId);

		await page.goto('/');
		const card = page.locator('[data-analysis-card="E2E Delete Me"]');
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

		// Cleanup the datasource
		await deleteDatasourceViaUI(page, 'e2e-del-ds');
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
		await screenshot(page, 'analyses', 'wizard-step-2');
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
		await createDatasource(request, 'e2e-create-ds');
		try {
			await page.goto('/analysis/new');

			// Step 1 – name
			await page.locator('#name').fill('E2E Created Analysis');
			await page.getByRole('button', { name: /Next/i }).click();

			// Step 2 – pick datasource
			await expect(page.getByRole('heading', { name: /Select Data Sources/i })).toBeVisible();
			await page.getByPlaceholder('Search datasources...').click();
			await page.locator('[role="option"]', { hasText: 'e2e-create-ds' }).first().click();
			// Close the dropdown by clicking outside
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
			await deleteAnalysisViaUI(page, 'E2E Created Analysis');
			await deleteDatasourceViaUI(page, 'e2e-create-ds');
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

	test.afterAll(async ({ browser }) => {
		const page = await browser.newPage();
		await deleteAnalysisViaUI(page, 'E2E Detail Test');
		await deleteDatasourceViaUI(page, 'e2e-detail-ds');
		await page.close();
	});

	test('analysis detail page loads with step library', async ({ page }) => {
		await page.goto(`/analysis/${aId}`);
		// StepLibrary heading is "Operations"
		await expect(page.getByRole('heading', { name: 'Operations' })).toBeVisible({
			timeout: 15_000
		});
		await screenshot(page, 'analyses', 'detail-step-library');
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

test.describe('Analyses – save/discard dirty tracking', () => {
	test('Save shows "Saved" and Discard is disabled on clean analysis', async ({
		page,
		request
	}) => {
		test.setTimeout(45_000);
		const dsId = await createDatasource(request, 'e2e-dirty-clean-ds');
		const aId = await createAnalysis(request, 'E2E Dirty Clean', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.getByRole('heading', { name: 'Operations' })).toBeVisible({
				timeout: 15_000
			});

			const saveBtn = page.getByRole('button', { name: 'Saved' });
			await expect(saveBtn).toBeVisible({ timeout: 5_000 });

			const discardBtn = page.getByRole('button', { name: 'Discard' });
			await expect(discardBtn).toBeDisabled();
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Dirty Clean');
			await deleteDatasourceViaUI(page, 'e2e-dirty-clean-ds');
		}
	});

	test('adding a step makes Save show "Save" and enables Discard', async ({ page, request }) => {
		test.setTimeout(45_000);
		const dsId = await createDatasource(request, 'e2e-dirty-add-ds');
		const aId = await createAnalysis(request, 'E2E Dirty Add', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="select"]')).toBeVisible({ timeout: 15_000 });
			await page.locator('button[data-step="select"]').click();

			await expect(page.locator('[data-step-type="select"]').first()).toBeVisible({
				timeout: 5_000
			});

			const saveBtn = page.getByRole('button', { name: 'Save' });
			await expect(saveBtn).toBeVisible({ timeout: 5_000 });

			const discardBtn = page.getByRole('button', { name: 'Discard' });
			await expect(discardBtn).toBeEnabled({ timeout: 5_000 });
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Dirty Add');
			await deleteDatasourceViaUI(page, 'e2e-dirty-add-ds');
		}
	});

	test('Discard reverts dirty state back to "Saved"', async ({ page, request }) => {
		test.setTimeout(45_000);
		const dsId = await createDatasource(request, 'e2e-dirty-discard-ds');
		const aId = await createAnalysis(request, 'E2E Dirty Discard', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="sort"]')).toBeVisible({ timeout: 15_000 });
			await page.locator('button[data-step="sort"]').click();
			await expect(page.locator('[data-step-type="sort"]').first()).toBeVisible({
				timeout: 5_000
			});

			await expect(page.getByRole('button', { name: 'Save' })).toBeVisible({ timeout: 5_000 });

			await page.getByRole('button', { name: 'Discard' }).click();

			await expect(page.getByRole('button', { name: 'Saved' })).toBeVisible({ timeout: 8_000 });
			await expect(page.getByRole('button', { name: 'Discard' })).toBeDisabled();
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Dirty Discard');
			await deleteDatasourceViaUI(page, 'e2e-dirty-discard-ds');
		}
	});

	test('step config Apply/Cancel buttons start with correct state for new step', async ({
		page,
		request
	}) => {
		test.setTimeout(45_000);
		const dsId = await createDatasource(request, 'e2e-dirty-config-ds');
		const aId = await createAnalysis(request, 'E2E Dirty Config', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="filter"]')).toBeVisible({ timeout: 15_000 });
			await page.locator('button[data-step="filter"]').click();

			const canvasNode = page.locator('[data-step-type="filter"]').first();
			await expect(canvasNode).toBeVisible({ timeout: 5_000 });
			await canvasNode.click();

			const configPanel = page.locator('[data-step-config="filter"]');
			await expect(configPanel).toBeVisible({ timeout: 8_000 });

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			const cancelBtn = configPanel.getByRole('button', { name: 'Cancel' });
			await expect(applyBtn).toBeVisible();
			await expect(cancelBtn).toBeVisible();

			// New steps have is_applied=false → hasChanges is true → both enabled
			await expect(applyBtn).toBeEnabled();
			await expect(cancelBtn).toBeEnabled();
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Dirty Config');
			await deleteDatasourceViaUI(page, 'e2e-dirty-config-ds');
		}
	});
});

test.describe('Analyses – step library labels', () => {
	let dsId = '';
	let aId = '';

	test.beforeAll(async ({ request }) => {
		dsId = await createDatasource(request, 'e2e-labels-ds');
		aId = await createAnalysis(request, 'E2E Labels Test', dsId);
	});

	test.afterAll(async ({ browser }) => {
		const page = await browser.newPage();
		await deleteAnalysisViaUI(page, 'E2E Labels Test');
		await deleteDatasourceViaUI(page, 'e2e-labels-ds');
		await page.close();
	});

	// All 25 step types that appear in StepLibrary.svelte (read-only checks)
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
			await expect(page.locator('button[data-step]', { hasText: label }).first()).toBeVisible({
				timeout: 15_000
			});
		});
	}
});

// ────────────────────────────────────────────────────────────────────────────────
// Export config – format switching & DuckDB table-name visibility
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – export config format switching', () => {
	test('Export: format switch shows/hides DuckDB table-name field', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-export-cfg-ds');
		const aId = await createAnalysis(request, 'E2E Export Config', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'export');

			// Format select should be visible
			const formatSelect = configPanel.locator('[data-testid="export-format-select"]');
			await expect(formatSelect).toBeVisible();

			// Filename input should be visible
			const filenameInput = configPanel.locator('[data-testid="export-filename-input"]');
			await expect(filenameInput).toBeVisible();

			// DuckDB table-name should NOT be visible (default format is not duckdb)
			const tableNameInput = configPanel.locator('[data-testid="export-tablename-input"]');
			await expect(tableNameInput).toBeHidden();

			// Switch to duckdb format
			await formatSelect.selectOption('duckdb');

			// DuckDB table-name field should now be visible
			await expect(tableNameInput).toBeVisible({ timeout: 3_000 });

			// Switch back to csv
			await formatSelect.selectOption('csv');

			// DuckDB table-name should be hidden again
			await expect(tableNameInput).toBeHidden({ timeout: 3_000 });

			await screenshot(page, 'analyses', 'export-config-format-switch');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Export Config');
			await deleteDatasourceViaUI(page, 'e2e-export-cfg-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Output visibility toggle
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – output visibility toggle', () => {
	test('OutputNode: toggle visibility changes label text', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-vis-toggle-ds');
		const aId = await createAnalysis(request, 'E2E Vis Toggle', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('[data-step-type="view"]')).toBeVisible({ timeout: 15_000 });

			const toggleBtn = page.locator('[data-testid="output-visibility-toggle"]').first();
			await expect(toggleBtn).toBeVisible({ timeout: 8_000 });

			// Check initial state — should be "visible" or "hidden"
			const initialText = await toggleBtn.innerText();
			const initiallyVisible = initialText.toLowerCase().includes('visible');

			// Click to toggle
			await toggleBtn.click();

			// Wait for text to change
			if (initiallyVisible) {
				await expect(toggleBtn).toContainText('hidden', { timeout: 8_000 });
			} else {
				await expect(toggleBtn).toContainText('visible', { timeout: 8_000 });
			}

			// Toggle back
			await toggleBtn.click();

			if (initiallyVisible) {
				await expect(toggleBtn).toContainText('visible', { timeout: 8_000 });
			} else {
				await expect(toggleBtn).toContainText('hidden', { timeout: 8_000 });
			}

			await screenshot(page, 'analyses', 'output-visibility-toggle');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Vis Toggle');
			await deleteDatasourceViaUI(page, 'e2e-vis-toggle-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Step reorder persistence — add steps, reorder, save, reload, verify order
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – step reorder persistence', () => {
	test('Step order persists after save and reload', async ({ page, request }) => {
		test.setTimeout(120_000);
		const dsId = await createDatasource(request, 'e2e-reorder-ds');
		const aId = await createAnalysis(request, 'E2E Reorder Persist', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="filter"]')).toBeVisible({ timeout: 15_000 });

			// Add filter then limit steps
			await page.locator('button[data-step="filter"]').click();
			await expect(page.locator('[data-step-type="filter"]')).toHaveCount(1, {
				timeout: 5_000
			});
			await page.locator('button[data-step="limit"]').click();
			await expect(page.locator('[data-step-type="limit"]')).toHaveCount(1, { timeout: 5_000 });

			// Record step types in order before save
			const stepNodes = page.locator('[data-step-type]');
			const countBefore = await stepNodes.count();
			const typesBefore: string[] = [];
			for (let i = 0; i < countBefore; i++) {
				const attr = await stepNodes.nth(i).getAttribute('data-step-type');
				if (attr) typesBefore.push(attr);
			}

			// Save
			await page.getByRole('button', { name: 'Save' }).click();
			await expect(page.getByRole('button', { name: 'Saved' })).toBeVisible({
				timeout: 10_000
			});

			// Reload
			await page.reload();
			await expect(page.locator('[data-step-type="filter"]')).toBeVisible({ timeout: 15_000 });
			await expect(page.locator('[data-step-type="limit"]')).toBeVisible({ timeout: 10_000 });

			// Verify step order is preserved
			const reloadedNodes = page.locator('[data-step-type]');
			const countAfter = await reloadedNodes.count();
			const typesAfter: string[] = [];
			for (let i = 0; i < countAfter; i++) {
				const attr = await reloadedNodes.nth(i).getAttribute('data-step-type');
				if (attr) typesAfter.push(attr);
			}

			expect(typesAfter).toEqual(typesBefore);

			await screenshot(page, 'analyses', 'step-reorder-persisted');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Reorder Persist');
			await deleteDatasourceViaUI(page, 'e2e-reorder-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Derived tab – add tab from another tab's output, verify it activates
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – derived tab flow', () => {
	test('add derived tab from existing tab output, switch back', async ({ page, request }) => {
		test.setTimeout(120_000);
		const dsId = await createDatasource(request, 'e2e-derived-tab-ds');
		const aId = await createAnalysis(request, 'E2E Derived Tab', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('[data-step-type="view"]')).toBeVisible({ timeout: 15_000 });

			const firstTab = page.locator('[data-tab-name="Source 1"]');
			await expect(firstTab).toBeVisible();

			// Click "Add derived tab" button (tab sourced from another tab's output)
			const addDerivedBtn = page.locator('button[title="Add derived tab"]');

			// If derived tab button doesn't exist, try the add tab menu
			if (await addDerivedBtn.isVisible({ timeout: 3_000 }).catch(() => false)) {
				await addDerivedBtn.click();
			} else {
				// Fallback: add a datasource tab and verify multi-tab switching works
				await page.locator('button[title="Add datasource tab"]').click();
				const modal = page.getByRole('dialog');
				await expect(modal).toBeVisible({ timeout: 5_000 });

				// Search for our datasource (use the same one)
				await modal.locator('#dsm-search').fill('e2e-derived-tab-ds');
				await modal.getByText('e2e-derived-tab-ds').click({ timeout: 8_000 });
				await expect(modal).toBeHidden({ timeout: 5_000 });
			}

			// Verify a second tab appeared and is active
			const allTabs = page.locator('[data-tab-name]');
			await expect(allTabs).toHaveCount(2, { timeout: 8_000 });

			// The second tab should show a view step
			await expect(page.locator('[data-step-type="view"]')).toBeVisible({ timeout: 10_000 });

			// Switch back to first tab
			await firstTab.click();
			await expect(page.locator('[data-step-type="view"]')).toBeVisible({ timeout: 10_000 });

			await screenshot(page, 'analyses', 'derived-tab-flow');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Derived Tab');
			await deleteDatasourceViaUI(page, 'e2e-derived-tab-ds');
		}
	});
});

test.describe('Analyses – step interaction', () => {
	test('clicking Filter step adds it to the canvas', async ({ page, request }) => {
		test.setTimeout(45_000);
		const dsId = await createDatasource(request, 'e2e-click-filter-ds');
		const aId = await createAnalysis(request, 'E2E Click Filter', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="filter"]')).toBeVisible({ timeout: 15_000 });

			// Count filter nodes before click (should be 0)
			const before = await page.locator('[data-step-type="filter"]').count();
			await page.locator('button[data-step="filter"]').click();

			// Exactly one new filter node should appear
			await expect(page.locator('[data-step-type="filter"]')).toHaveCount(before + 1, {
				timeout: 5_000
			});
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Click Filter');
			await deleteDatasourceViaUI(page, 'e2e-click-filter-ds');
		}
	});

	test('clicking Filter canvas node opens config panel with correct type', async ({
		page,
		request
	}) => {
		test.setTimeout(45_000);
		const dsId = await createDatasource(request, 'e2e-config-panel-ds');
		const aId = await createAnalysis(request, 'E2E Config Panel', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="filter"]')).toBeVisible({ timeout: 15_000 });
			await page.locator('button[data-step="filter"]').click();

			const canvasNode = page.locator('[data-step-type="filter"]').first();
			await expect(canvasNode).toBeVisible({ timeout: 5_000 });
			await canvasNode.click();

			const configPanel = page.locator('[data-step-config="filter"]');
			await expect(configPanel).toBeVisible({ timeout: 8_000 });
			await expect(configPanel.getByRole('button', { name: 'Apply' })).toBeVisible();
			await expect(configPanel.getByRole('button', { name: 'Cancel' })).toBeVisible();
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Config Panel');
			await deleteDatasourceViaUI(page, 'e2e-config-panel-ds');
		}
	});

	test('clicking Select step adds it to the canvas (not initial View)', async ({
		page,
		request
	}) => {
		test.setTimeout(45_000);
		const dsId = await createDatasource(request, 'e2e-click-select-ds');
		const aId = await createAnalysis(request, 'E2E Click Select', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="select"]')).toBeVisible({ timeout: 15_000 });

			// No select nodes before click
			await expect(page.locator('[data-step-type="select"]')).toHaveCount(0);
			await page.locator('button[data-step="select"]').click();

			// Exactly one select node after click
			await expect(page.locator('[data-step-type="select"]')).toHaveCount(1, {
				timeout: 5_000
			});
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Click Select');
			await deleteDatasourceViaUI(page, 'e2e-click-select-ds');
		}
	});
});

test.describe('Analyses – save persistence', () => {
	test('saving a step persists across page reload', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-persist-ds');
		const aId = await createAnalysis(request, 'E2E Persist Test', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="filter"]')).toBeVisible({ timeout: 15_000 });

			// No filter nodes initially
			await expect(page.locator('[data-step-type="filter"]')).toHaveCount(0);

			// Add a filter step
			await page.locator('button[data-step="filter"]').click();
			await expect(page.locator('[data-step-type="filter"]')).toHaveCount(1, {
				timeout: 5_000
			});

			// Click Save
			await expect(page.getByRole('button', { name: 'Save' })).toBeVisible({ timeout: 5_000 });
			await page.getByRole('button', { name: 'Save' }).click();
			await expect(page.getByRole('button', { name: 'Saved' })).toBeVisible({ timeout: 10_000 });

			// Reload the page completely
			await page.reload();

			// Wait for the page to fully load
			await expect(page.getByRole('heading', { name: 'Operations' })).toBeVisible({
				timeout: 15_000
			});

			// Filter step should still be present after reload
			await expect(page.locator('[data-step-type="filter"]')).toHaveCount(1, {
				timeout: 10_000
			});

			// Save button should show "Saved" (clean state)
			await expect(page.getByRole('button', { name: 'Saved' })).toBeVisible({ timeout: 5_000 });
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Persist Test');
			await deleteDatasourceViaUI(page, 'e2e-persist-ds');
		}
	});

	test('Apply marks step as applied and Cancel reverts config changes', async ({
		page,
		request
	}) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-apply-cancel-ds');
		const aId = await createAnalysis(request, 'E2E Apply Cancel', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="filter"]')).toBeVisible({ timeout: 15_000 });

			// Add a filter step and open config
			await page.locator('button[data-step="filter"]').click();
			const canvasNode = page.locator('[data-step-type="filter"]').first();
			await expect(canvasNode).toBeVisible({ timeout: 5_000 });
			await canvasNode.click();

			const configPanel = page.locator('[data-step-config="filter"]');
			await expect(configPanel).toBeVisible({ timeout: 8_000 });

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			const cancelBtn = configPanel.getByRole('button', { name: 'Cancel' });

			// New step: is_applied=false → both buttons enabled
			await expect(applyBtn).toBeEnabled();
			await expect(cancelBtn).toBeEnabled();

			// Click Apply — marks step as applied → hasChanges becomes false
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });
			await expect(cancelBtn).toBeDisabled({ timeout: 5_000 });
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Apply Cancel');
			await deleteDatasourceViaUI(page, 'e2e-apply-cancel-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// NEW: Node configuration behavior tests
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – limit config editing', () => {
	test('Limit: set row count, Apply, verify disabled buttons', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-limit-cfg-ds');
		const aId = await createAnalysis(request, 'E2E Limit Config', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'limit');

			// Fill in the limit rows input
			const limitInput = configPanel.locator('[data-testid="limit-rows-input"]');
			await expect(limitInput).toBeVisible();
			await limitInput.fill('42');

			// Apply is enabled (new step + changed config)
			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();

			// After apply, both buttons should be disabled (no changes)
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });
			await expect(configPanel.getByRole('button', { name: 'Cancel' })).toBeDisabled();

			await screenshot(page, 'analyses', 'limit-config-applied');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Limit Config');
			await deleteDatasourceViaUI(page, 'e2e-limit-cfg-ds');
		}
	});
});

test.describe('Analyses – expression config editing', () => {
	test('Expression: fill expression + column name, Apply', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-expr-cfg-ds');
		const aId = await createAnalysis(request, 'E2E Expr Config', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'expression');

			// Fill the expression textarea
			const exprTextarea = configPanel.locator('[data-testid="expr-expression-textarea"]');
			await expect(exprTextarea).toBeVisible();
			await exprTextarea.fill('pl.col("age") * 2');

			// Fill the column name input
			const columnInput = configPanel.locator('[data-testid="expr-column-input"]');
			await expect(columnInput).toBeVisible();
			await columnInput.fill('age_doubled');

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();

			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analyses', 'expression-config-applied');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Expr Config');
			await deleteDatasourceViaUI(page, 'e2e-expr-cfg-ds');
		}
	});
});

test.describe('Analyses – sort config editing', () => {
	test('Sort: add sort rule via ColumnDropdown, Apply, then remove rule', async ({
		page,
		request
	}) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-sort-cfg-ds');
		const aId = await createAnalysis(request, 'E2E Sort Config', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'sort');

			// Empty state visible
			await expect(configPanel.getByText(/No sort rules/i)).toBeVisible();

			// Open column dropdown — click the dropdown trigger button
			const dropdownTrigger = configPanel.locator('button[aria-expanded]').first();
			await dropdownTrigger.click();
			// Select the 'name' column from the dropdown
			await page.locator('[role="option"]', { hasText: 'name' }).first().click();

			// Click "Add" button
			const addBtn = configPanel.locator('[data-testid="sort-add-button"]');
			await expect(addBtn).toBeEnabled();
			await addBtn.click();

			// The sort rule should appear in the list
			await expect(configPanel.getByText('name')).toBeVisible();
			// Empty state should be gone
			await expect(configPanel.getByText(/No sort rules/i)).not.toBeVisible();

			// Apply the config
			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analyses', 'sort-config-with-rule');

			// Remove the sort rule
			const removeBtn = configPanel.locator('[data-testid="sort-remove-rule-0"]');
			await removeBtn.click();

			// Empty state returns
			await expect(configPanel.getByText(/No sort rules/i)).toBeVisible();
			// Apply is now enabled again (change from applied state)
			await expect(applyBtn).toBeEnabled();
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Sort Config');
			await deleteDatasourceViaUI(page, 'e2e-sort-cfg-ds');
		}
	});
});

test.describe('Analyses – rename config editing', () => {
	test('Rename: add mapping via dropdown + input, Apply, then Cancel reverts', async ({
		page,
		request
	}) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-rename-cfg-ds');
		const aId = await createAnalysis(request, 'E2E Rename Config', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'rename');

			// Empty state visible
			await expect(configPanel.getByText(/No renames yet/i)).toBeVisible();

			// Open column dropdown to pick a column to rename
			const dropdownTrigger = configPanel.locator('button[aria-expanded]').first();
			await dropdownTrigger.click();
			await page.locator('[role="option"]', { hasText: 'name' }).first().click();

			// Fill the new name input
			const newNameInput = configPanel.locator('[data-testid="rename-new-name-input"]');
			await expect(newNameInput).toBeEnabled();
			await newNameInput.fill('full_name');

			// Click "Add Rename"
			const addBtn = configPanel.locator('[data-testid="rename-add-button"]');
			await expect(addBtn).toBeEnabled();
			await addBtn.click();

			// Mapping should appear
			await expect(configPanel.getByText('full_name')).toBeVisible();
			await expect(configPanel.getByText(/No renames yet/i)).not.toBeVisible();

			// Apply
			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analyses', 'rename-config-applied');

			// Now remove the mapping to create a change
			const removeBtn = configPanel.locator('[data-testid="rename-remove-button-name"]');
			await removeBtn.click();
			await expect(configPanel.getByText(/No renames yet/i)).toBeVisible();

			// Cancel should revert to the applied state
			const cancelBtn = configPanel.getByRole('button', { name: 'Cancel' });
			await expect(cancelBtn).toBeEnabled();
			await cancelBtn.click();

			// After cancel, mapping should be restored
			await expect(configPanel.getByText('full_name')).toBeVisible();
			// And both buttons disabled again
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Rename Config');
			await deleteDatasourceViaUI(page, 'e2e-rename-cfg-ds');
		}
	});
});

test.describe('Analyses – filter config editing', () => {
	test('Filter: change operator, type value, Apply; then Cancel reverts', async ({
		page,
		request
	}) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-filter-cfg-ds');
		const aId = await createAnalysis(request, 'E2E Filter Config', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'filter');

			// The filter starts with one empty condition — select a column
			const dropdownTrigger = configPanel.locator('button[aria-expanded]').first();
			await dropdownTrigger.click();
			await page.locator('[role="option"]', { hasText: 'name' }).first().click();

			// Change operator to "contains"
			const operatorSelect = configPanel.locator('[data-testid="filter-operator-select-0"]');
			await operatorSelect.selectOption('contains');

			// Type a filter value (name is string type → uses multi-literal input with Enter)
			const valueInput = configPanel.locator('[data-testid="filter-value-input-0"]');
			await valueInput.fill('Alice');
			await valueInput.press('Enter');

			// The token "Alice" should appear
			await expect(configPanel.getByText('Alice')).toBeVisible();

			// Apply
			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analyses', 'filter-config-applied');

			// Make a change: add another value token
			const valueInputAfter = configPanel.locator('[data-testid="filter-value-input-0"]');
			await valueInputAfter.fill('Bob');
			await valueInputAfter.press('Enter');
			await expect(configPanel.getByText('Bob')).toBeVisible();

			// Now Cancel to revert
			const cancelBtn = configPanel.getByRole('button', { name: 'Cancel' });
			await expect(cancelBtn).toBeEnabled();
			await cancelBtn.click();

			// After Cancel, Bob should be gone (reverted) and Alice should remain
			await expect(configPanel.getByText('Bob')).not.toBeVisible({ timeout: 3_000 });
			await expect(configPanel.getByText('Alice')).toBeVisible();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Filter Config');
			await deleteDatasourceViaUI(page, 'e2e-filter-cfg-ds');
		}
	});
});

test.describe('Analyses – node delete via action button', () => {
	test('delete button removes step from canvas', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-node-del-ds');
		const aId = await createAnalysis(request, 'E2E Node Delete', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="limit"]')).toBeVisible({ timeout: 15_000 });

			// Add a limit step
			await page.locator('button[data-step="limit"]').click();
			const limitNode = page.locator('[data-step-type="limit"]').first();
			await expect(limitNode).toBeVisible({ timeout: 5_000 });

			// Click the delete action button on the node
			await limitNode.locator('[data-action="delete"]').click();

			// Node should be removed
			await expect(page.locator('[data-step-type="limit"]')).toHaveCount(0, { timeout: 5_000 });

			await screenshot(page, 'analyses', 'node-deleted');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Node Delete');
			await deleteDatasourceViaUI(page, 'e2e-node-del-ds');
		}
	});
});

test.describe('Analyses – node toggle (enable/disable)', () => {
	test('toggle disables and re-enables a step', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-node-toggle-ds');
		const aId = await createAnalysis(request, 'E2E Node Toggle', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="sort"]')).toBeVisible({ timeout: 15_000 });

			// Add a sort step
			await page.locator('button[data-step="sort"]').click();
			const sortNode = page.locator('[data-step-type="sort"]').first();
			await expect(sortNode).toBeVisible({ timeout: 5_000 });

			// By default new steps are not applied (is_applied=false),
			// so the toggle button shows "enable"
			const toggleBtn = sortNode.locator('[data-action="toggle"]');
			await expect(toggleBtn).toBeVisible();

			// Open config and Apply so it becomes applied
			await sortNode.locator('[data-action="edit"]').click();
			const configPanel = page.locator('[data-step-config="sort"]');
			await expect(configPanel).toBeVisible({ timeout: 8_000 });
			await configPanel.getByRole('button', { name: 'Apply' }).click();
			await expect(configPanel.getByRole('button', { name: 'Apply' })).toBeDisabled({
				timeout: 5_000
			});

			// Now toggle should show "disable" since step is applied
			await expect(toggleBtn).toHaveText(/disable/i);

			// Click toggle to disable
			await toggleBtn.click();
			await expect(toggleBtn).toHaveText(/enable/i);

			// Click toggle again to re-enable
			await toggleBtn.click();
			await expect(toggleBtn).toHaveText(/disable/i);

			await screenshot(page, 'analyses', 'node-toggle-enabled');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Node Toggle');
			await deleteDatasourceViaUI(page, 'e2e-node-toggle-ds');
		}
	});
});

test.describe('Analyses – save + reload config persistence', () => {
	test('configured Limit step persists value after save and reload', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-cfg-persist-ds');
		const aId = await createAnalysis(request, 'E2E Cfg Persist', dsId);
		try {
			// Add limit step and configure
			const configPanel = await addStepAndOpenConfig(page, aId, 'limit');
			const limitInput = configPanel.locator('[data-testid="limit-rows-input"]');
			await limitInput.fill('77');

			// Apply
			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			// Save the analysis
			await page.getByRole('button', { name: 'Save' }).click();
			await expect(page.getByRole('button', { name: 'Saved' })).toBeVisible({ timeout: 10_000 });

			// Reload
			await page.reload();
			await expect(page.getByRole('heading', { name: 'Operations' })).toBeVisible({
				timeout: 15_000
			});

			// Limit node should still exist
			const limitNode = page.locator('[data-step-type="limit"]').first();
			await expect(limitNode).toBeVisible({ timeout: 10_000 });

			// Open config again and verify value persisted
			await limitNode.locator('[data-action="edit"]').click();
			const reloadedPanel = page.locator('[data-step-config="limit"]');
			await expect(reloadedPanel).toBeVisible({ timeout: 8_000 });
			const reloadedInput = reloadedPanel.locator('[data-testid="limit-rows-input"]');
			await expect(reloadedInput).toHaveValue('77', { timeout: 5_000 });

			// Buttons should be disabled (no changes from persisted state)
			await expect(reloadedPanel.getByRole('button', { name: 'Apply' })).toBeDisabled();
			await expect(reloadedPanel.getByRole('button', { name: 'Cancel' })).toBeDisabled();

			await screenshot(page, 'analyses', 'limit-config-persisted');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Cfg Persist');
			await deleteDatasourceViaUI(page, 'e2e-cfg-persist-ds');
		}
	});
});

test.describe('Analyses – output node interactions', () => {
	test('output node build button and mode selector are visible', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-output-ds');
		const aId = await createAnalysis(request, 'E2E Output Node', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.getByRole('heading', { name: 'Operations' })).toBeVisible({
				timeout: 15_000
			});

			// Build button should be visible
			const buildBtn = page.locator('[data-testid="output-build-button"]');
			await expect(buildBtn).toBeVisible({ timeout: 10_000 });

			// Mode trigger should be visible
			const modeTrigger = page.locator('[data-testid="output-mode-trigger"]');
			await expect(modeTrigger).toBeVisible();

			// Click mode trigger to open dropdown
			await modeTrigger.click();
			const dropdown = page.locator('[role="listbox"]');
			await expect(dropdown).toBeVisible({ timeout: 3_000 });

			// Check mode options are present
			await expect(dropdown.locator('[role="option"]', { hasText: 'full' })).toBeVisible();
			await expect(dropdown.locator('[role="option"]', { hasText: 'incremental' })).toBeVisible();
			await expect(dropdown.locator('[role="option"]', { hasText: 'recreate' })).toBeVisible();

			await screenshot(page, 'analyses', 'output-node-mode-dropdown');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Output Node');
			await deleteDatasourceViaUI(page, 'e2e-output-ds');
		}
	});

	test('selecting a mode updates the trigger text', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-output-mode-ds');
		const aId = await createAnalysis(request, 'E2E Output Mode', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.getByRole('heading', { name: 'Operations' })).toBeVisible({
				timeout: 15_000
			});

			const modeTrigger = page.locator('[data-testid="output-mode-trigger"]');
			await expect(modeTrigger).toBeVisible({ timeout: 10_000 });

			// Default should be "full"
			await expect(modeTrigger).toContainText('full');

			// Select "incremental"
			await modeTrigger.click();
			const dropdown = page.locator('[role="listbox"]');
			await expect(dropdown).toBeVisible({ timeout: 3_000 });
			await dropdown.locator('[role="option"]', { hasText: 'incremental' }).click();

			// Dropdown should close and trigger should show "incremental"
			await expect(dropdown).not.toBeVisible({ timeout: 3_000 });
			await expect(modeTrigger).toContainText('incremental');

			// Select "recreate"
			await modeTrigger.click();
			await expect(page.locator('[role="listbox"]')).toBeVisible({ timeout: 3_000 });
			await page
				.locator('[role="listbox"]')
				.locator('[role="option"]', { hasText: 'recreate' })
				.click();

			await expect(modeTrigger).toContainText('recreate');

			await screenshot(page, 'analyses', 'output-mode-recreate');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Output Mode');
			await deleteDatasourceViaUI(page, 'e2e-output-mode-ds');
		}
	});

	test('collapsible sections toggle open and closed', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-output-sections-ds');
		const aId = await createAnalysis(request, 'E2E Output Sections', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.getByRole('heading', { name: 'Operations' })).toBeVisible({
				timeout: 15_000
			});

			// All section toggles should be visible
			const notifyToggle = page.locator('[data-testid="output-notify-toggle"]');
			const healthToggle = page.locator('[data-testid="output-health-toggle"]');
			const scheduleToggle = page.locator('[data-testid="output-schedule-toggle"]');

			await expect(notifyToggle).toBeVisible({ timeout: 10_000 });
			await expect(healthToggle).toBeVisible();
			await expect(scheduleToggle).toBeVisible();

			// Sections should start collapsed — "Build Notification" content not visible
			await expect(page.getByText('Notify subscribers on build')).not.toBeVisible();

			// Open Build Notification section
			await notifyToggle.click();
			await expect(page.getByText('Notify subscribers on build')).toBeVisible({ timeout: 3_000 });

			// Close it again
			await notifyToggle.click();
			await expect(page.getByText('Notify subscribers on build')).not.toBeVisible({
				timeout: 3_000
			});

			// Open Health Checks section — shows placeholder for unsaved analysis
			await healthToggle.click();
			await expect(
				page.getByText(/Save this analysis to create an output datasource/i)
			).toBeVisible({ timeout: 3_000 });

			await screenshot(page, 'analyses', 'output-sections-health-open');

			// Close Health Checks
			await healthToggle.click();
			await expect(
				page.getByText(/Save this analysis to create an output datasource/i)
			).not.toBeVisible({ timeout: 3_000 });
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Output Sections');
			await deleteDatasourceViaUI(page, 'e2e-output-sections-ds');
		}
	});

	test('table name inline edit', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-output-rename-ds');
		const aId = await createAnalysis(request, 'E2E Output Rename', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.getByRole('heading', { name: 'Operations' })).toBeVisible({
				timeout: 15_000
			});

			// Click the edit pencil button (aria-label="Edit export name")
			const editBtn = page.locator('[aria-label="Edit export name"]').first();
			await expect(editBtn).toBeVisible({ timeout: 10_000 });
			await editBtn.click();

			// Input should appear
			const nameInput = page.locator('#output-node-name');
			await expect(nameInput).toBeVisible({ timeout: 3_000 });

			// Clear and type new name
			await nameInput.fill('my_custom_table');
			await nameInput.press('Enter');

			// After commit, the new name should appear in the output card
			await expect(page.getByText('my_custom_table').first()).toBeVisible({ timeout: 3_000 });

			await screenshot(page, 'analyses', 'output-table-renamed');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Output Rename');
			await deleteDatasourceViaUI(page, 'e2e-output-rename-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Version history modal tests
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – version history modal', () => {
	test('opens version modal and shows empty state on fresh analysis', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-ver-empty-ds');
		const aId = await createAnalysis(request, 'E2E Ver Empty', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.getByRole('heading', { name: 'Operations' })).toBeVisible({
				timeout: 15_000
			});

			const trigger = page.locator('[data-testid="version-history-trigger"]');
			await expect(trigger).toBeVisible();
			await trigger.click();

			const dialog = page.getByRole('dialog');
			await expect(dialog).toBeVisible({ timeout: 5_000 });
			await expect(dialog.getByText('Version history')).toBeVisible();

			// Fresh analysis has no previous versions
			await expect(
				dialog.getByText(/No versions available/i).or(dialog.getByText(/Version 1/i))
			).toBeVisible({ timeout: 8_000 });

			await screenshot(page, 'analyses', 'version-history-empty');

			// Close via footer button
			await dialog.getByRole('button', { name: 'Close', exact: true }).click();
			await expect(dialog).not.toBeVisible({ timeout: 3_000 });
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Ver Empty');
			await deleteDatasourceViaUI(page, 'e2e-ver-empty-ds');
		}
	});

	test('version modal shows versions after save creates a version', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-ver-list-ds');
		const aId = await createAnalysis(request, 'E2E Ver List', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="limit"]')).toBeVisible({ timeout: 15_000 });

			// Modify and save to create a version
			await page.locator('button[data-step="limit"]').click();
			await expect(page.locator('[data-step-type="limit"]')).toHaveCount(1, { timeout: 5_000 });
			await page.getByRole('button', { name: 'Save' }).click();
			await expect(page.getByRole('button', { name: 'Saved' })).toBeVisible({ timeout: 10_000 });

			// Open version modal
			await page.locator('[data-testid="version-history-trigger"]').click();
			const dialog = page.getByRole('dialog');
			await expect(dialog).toBeVisible({ timeout: 5_000 });
			await expect(dialog.getByText('Version history')).toBeVisible();

			// Wait for versions to load — should show at least Version 1
			await expect(dialog.getByText(/Version 1/)).toBeVisible({ timeout: 10_000 });

			await screenshot(page, 'analyses', 'version-history-with-versions');

			await dialog.getByRole('button', { name: 'Close', exact: true }).click();
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Ver List');
			await deleteDatasourceViaUI(page, 'e2e-ver-list-ds');
		}
	});

	test('rename version inline edit', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-ver-rename-ds');
		const aId = await createAnalysis(request, 'E2E Ver Rename', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="limit"]')).toBeVisible({ timeout: 15_000 });

			// Save to create a version
			await page.locator('button[data-step="limit"]').click();
			await expect(page.locator('[data-step-type="limit"]')).toHaveCount(1, { timeout: 5_000 });
			await page.getByRole('button', { name: 'Save' }).click();
			await expect(page.getByRole('button', { name: 'Saved' })).toBeVisible({ timeout: 10_000 });

			// Open version modal
			await page.locator('[data-testid="version-history-trigger"]').click();
			const dialog = page.getByRole('dialog');
			await expect(dialog.getByText(/Version 1/)).toBeVisible({ timeout: 10_000 });

			// Click rename button on version 1
			const renameBtn = dialog.locator('[data-testid="version-rename-1"]');
			await expect(renameBtn).toBeVisible();
			await renameBtn.click();

			// The inline rename input should appear
			const renameInput = dialog.getByLabel('Version name');
			await expect(renameInput).toBeVisible({ timeout: 3_000 });
			await renameInput.fill('My Checkpoint');
			await renameInput.press('Enter');

			// After rename, the new name should appear
			await expect(dialog.getByText('My Checkpoint')).toBeVisible({ timeout: 8_000 });

			await screenshot(page, 'analyses', 'version-history-renamed');

			await dialog.getByRole('button', { name: 'Close', exact: true }).click();
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Ver Rename');
			await deleteDatasourceViaUI(page, 'e2e-ver-rename-ds');
		}
	});

	test('Escape key closes version modal', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-ver-esc-ds');
		const aId = await createAnalysis(request, 'E2E Ver Escape', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.getByRole('heading', { name: 'Operations' })).toBeVisible({
				timeout: 15_000
			});

			await page.locator('[data-testid="version-history-trigger"]').click();
			const dialog = page.getByRole('dialog');
			await expect(dialog).toBeVisible({ timeout: 5_000 });

			await page.keyboard.press('Escape');
			await expect(dialog).not.toBeVisible({ timeout: 3_000 });
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Ver Escape');
			await deleteDatasourceViaUI(page, 'e2e-ver-esc-ds');
		}
	});

	test('delete version removes it from the list', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-ver-del-ds');
		const aId = await createAnalysis(request, 'E2E Ver Delete', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="limit"]')).toBeVisible({ timeout: 15_000 });

			// Save to create version 1
			await page.locator('button[data-step="limit"]').click();
			await expect(page.locator('[data-step-type="limit"]')).toHaveCount(1, { timeout: 5_000 });
			await page.getByRole('button', { name: 'Save' }).click();
			await expect(page.getByRole('button', { name: 'Saved' })).toBeVisible({ timeout: 10_000 });

			// Open version modal
			await page.locator('[data-testid="version-history-trigger"]').click();
			const dialog = page.getByRole('dialog');
			await expect(dialog.getByText(/Version 1/)).toBeVisible({ timeout: 10_000 });

			// Delete version 1
			await dialog.locator('[data-testid="version-delete-1"]').click();

			// Version row should disappear
			await expect(dialog.locator('[data-testid="version-row-1"]')).not.toBeVisible({
				timeout: 8_000
			});

			await screenshot(page, 'analyses', 'version-history-after-delete');
			await dialog.getByRole('button', { name: 'Close', exact: true }).click();
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Ver Delete');
			await deleteDatasourceViaUI(page, 'e2e-ver-del-ds');
		}
	});

	test('restore version closes modal and updates analysis state', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-ver-restore-ds');
		const aId = await createAnalysis(request, 'E2E Ver Restore', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="limit"]')).toBeVisible({ timeout: 15_000 });

			// Add a limit step and save to create version 1
			await page.locator('button[data-step="limit"]').click();
			await expect(page.locator('[data-step-type="limit"]')).toHaveCount(1, { timeout: 5_000 });
			await page.getByRole('button', { name: 'Save' }).click();
			await expect(page.getByRole('button', { name: 'Saved' })).toBeVisible({ timeout: 10_000 });

			// Add another step so state differs from version 1
			await page.locator('button[data-step="sort"]').click();
			await expect(page.locator('[data-step-type="sort"]')).toHaveCount(1, { timeout: 5_000 });

			// Open version modal and restore version 1
			await page.locator('[data-testid="version-history-trigger"]').click();
			const dialog = page.getByRole('dialog');
			await expect(dialog.getByText(/Version 1/)).toBeVisible({ timeout: 10_000 });

			await dialog.locator('[data-testid="version-restore-1"]').click();

			// Modal should close after restore
			await expect(dialog).not.toBeVisible({ timeout: 8_000 });

			await screenshot(page, 'analyses', 'version-history-after-restore');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Ver Restore');
			await deleteDatasourceViaUI(page, 'e2e-ver-restore-ds');
		}
	});

	test('version load error state shows "Failed to load version history."', async ({
		page,
		request
	}) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-ver-err-ds');
		const aId = await createAnalysis(request, 'E2E Ver Error', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.getByRole('heading', { name: 'Operations' })).toBeVisible({
				timeout: 15_000
			});

			// Intercept versions endpoint to return 500
			await page.route(`**/api/v1/analysis/${aId}/versions`, (route) =>
				route.fulfill({ status: 500, body: 'Internal Server Error' })
			);

			await page.locator('[data-testid="version-history-trigger"]').click();
			const dialog = page.getByRole('dialog');
			await expect(dialog).toBeVisible({ timeout: 5_000 });

			// The error state should appear in the modal
			await expect(
				dialog
					.getByText('Failed to load version history.')
					.or(dialog.getByText('Failed to load version history'))
			).toBeVisible({ timeout: 10_000 });

			await screenshot(page, 'analyses', 'version-history-load-error');
			await dialog.getByRole('button', { name: 'Close', exact: true }).click();
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Ver Error');
			await deleteDatasourceViaUI(page, 'e2e-ver-err-ds');
		}
	});

	test('version action error displays inline error message', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-ver-act-err-ds');
		const aId = await createAnalysis(request, 'E2E Ver Act Error', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="limit"]')).toBeVisible({ timeout: 15_000 });

			// Save to create version 1
			await page.locator('button[data-step="limit"]').click();
			await expect(page.locator('[data-step-type="limit"]')).toHaveCount(1, { timeout: 5_000 });
			await page.getByRole('button', { name: 'Save' }).click();
			await expect(page.getByRole('button', { name: 'Saved' })).toBeVisible({ timeout: 10_000 });

			// Open version modal
			await page.locator('[data-testid="version-history-trigger"]').click();
			const dialog = page.getByRole('dialog');
			await expect(dialog.getByText(/Version 1/)).toBeVisible({ timeout: 10_000 });

			// Intercept delete endpoint to return 500
			await page.route(`**/api/v1/analysis/${aId}/versions/1`, (route) => {
				if (route.request().method() === 'DELETE') {
					return route.fulfill({
						status: 500,
						contentType: 'application/json',
						body: JSON.stringify({ detail: 'Simulated delete failure' })
					});
				}
				return route.continue();
			});

			// Try to delete — should show error inline
			await dialog.locator('[data-testid="version-delete-1"]').click();

			await expect(dialog.locator('[data-testid="version-error"]')).toBeVisible({
				timeout: 8_000
			});

			await screenshot(page, 'analyses', 'version-history-action-error');
			await dialog.getByRole('button', { name: 'Close', exact: true }).click();
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Ver Act Error');
			await deleteDatasourceViaUI(page, 'e2e-ver-act-err-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Analysis detail – error state regression
// ────────────────────────────────────────────────────────────────────────────────

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

		await screenshot(page, 'analyses', 'detail-load-error');
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
		await expect(page.getByRole('heading', { name: 'Analyses' })).toBeVisible();
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Build flow – output node
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – output build flow', () => {
	test('build button triggers build API and completes', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-build-flow-ds');
		const aId = await createAnalysis(request, 'E2E Build Flow', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			const buildBtn = page.locator('[data-testid="output-build-button"]');
			await expect(buildBtn).toBeVisible({ timeout: 15_000 });

			// Listen for the build API call
			const buildPromise = page.waitForResponse(
				(resp) => resp.url().includes('/api/v1/compute/build') && resp.request().method() === 'POST'
			);

			await buildBtn.click();

			// Building state should appear
			await expect(page.locator('[data-testid="output-building"]')).toBeVisible({
				timeout: 5_000
			});

			// Wait for build response
			const buildResp = await buildPromise;
			expect(buildResp.status()).toBe(200);

			const body = await buildResp.json();
			expect(body).toHaveProperty('analysis_id');
			expect(body).toHaveProperty('results');
			expect(Array.isArray(body.results)).toBe(true);

			// Building state should disappear
			await expect(page.locator('[data-testid="output-building"]')).not.toBeVisible({
				timeout: 15_000
			});

			// No error should be visible
			await expect(page.locator('[data-testid="output-build-error"]')).not.toBeVisible();

			await screenshot(page, 'analyses', 'output-build-success');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Build Flow');
			await deleteDatasourceViaUI(page, 'e2e-build-flow-ds');
		}
	});

	test('build API failure shows error on output node', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-build-err-ds');
		const aId = await createAnalysis(request, 'E2E Build Error', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			const buildBtn = page.locator('[data-testid="output-build-button"]');
			await expect(buildBtn).toBeVisible({ timeout: 15_000 });

			// Intercept build API to return 500
			await page.route('**/api/v1/compute/build', (route) => {
				if (route.request().method() === 'POST') {
					return route.fulfill({
						status: 500,
						contentType: 'application/json',
						body: JSON.stringify({ detail: 'Simulated build failure' })
					});
				}
				return route.continue();
			});

			await buildBtn.click();

			// Error should appear on output node
			await expect(page.locator('[data-testid="output-build-error"]')).toBeVisible({
				timeout: 15_000
			});

			await screenshot(page, 'analyses', 'output-build-error');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Build Error');
			await deleteDatasourceViaUI(page, 'e2e-build-err-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// View node – inline data table preview
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – view node inline preview', () => {
	test('view step renders inline data table with preview data', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-view-preview-ds');
		const aId = await createAnalysis(request, 'E2E View Preview', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="view"]')).toBeVisible({ timeout: 15_000 });

			// The analysis already has a view step from createAnalysis — the inline table should render
			await expect(page.locator('[data-testid="inline-data-table"]')).toBeVisible({
				timeout: 15_000
			});

			await screenshot(page, 'analyses', 'view-inline-preview');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E View Preview');
			await deleteDatasourceViaUI(page, 'e2e-view-preview-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Chart node – config + preview render
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – chart config and preview', () => {
	test('chart step: configure x/y columns, apply, chart SVG renders', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-chart-cfg-ds');
		const aId = await createAnalysis(request, 'E2E Chart Config', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'chart');

			// Select X column — first ColumnDropdown in config
			const xGroup = configPanel.locator('[role="group"]').filter({ hasText: 'X Column' });
			await xGroup.locator('button[aria-expanded]').click();
			await page.locator('[role="option"]', { hasText: 'city' }).first().click();

			// Select Y column — second ColumnDropdown in config
			const yGroup = configPanel.locator('[role="group"]').filter({ hasText: 'Y Column' });
			await yGroup.locator('button[aria-expanded]').click();
			await page.locator('[role="option"]', { hasText: 'age' }).first().click();

			// Apply
			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			// Chart preview should render (contains an SVG)
			const chartPreview = page.locator('[data-testid="chart-preview"]');
			await expect(chartPreview).toBeVisible({ timeout: 15_000 });
			await expect(chartPreview.locator('svg')).toBeVisible({ timeout: 15_000 });

			await screenshot(page, 'analyses', 'chart-preview-rendered');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Chart Config');
			await deleteDatasourceViaUI(page, 'e2e-chart-cfg-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// GroupBy config editing
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – groupby config editing', () => {
	test('GroupBy: select group column, add aggregation, Apply', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-groupby-cfg-ds');
		const aId = await createAnalysis(request, 'E2E GroupBy Config', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'groupby');

			// Select groupBy column via MultiSelectColumnDropdown
			const groupBySection = configPanel
				.locator('[role="group"]')
				.filter({ hasText: 'Group By Columns' });
			await groupBySection.locator('button[aria-expanded]').click();
			await page.locator('[role="option"]', { hasText: 'city' }).first().click();

			// Click outside to close dropdown
			await configPanel.click({ position: { x: 5, y: 5 } });

			// Add an aggregation: select column, pick function, click Add
			const aggSection = configPanel.locator('[role="group"]').filter({ hasText: 'Aggregations' });
			const aggColumnDropdown = aggSection.locator('button[aria-expanded]').first();
			await aggColumnDropdown.click();
			await page.locator('[role="option"]', { hasText: 'age' }).first().click();

			// Change function to 'mean'
			const funcSelect = configPanel.locator('[data-testid="agg-function-select"]');
			await funcSelect.selectOption('mean');

			// Click Add
			const addBtn = configPanel.locator('[data-testid="agg-add-button"]');
			await expect(addBtn).toBeEnabled();
			await addBtn.click();

			// Aggregation should appear in list
			await expect(configPanel.getByText('mean(age) as age_mean')).toBeVisible();

			// Apply
			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analyses', 'groupby-config-applied');

			// Remove the aggregation
			const removeBtn = configPanel.locator('[data-testid="agg-remove-button-0"]');
			await removeBtn.click();

			// Aggregation list should be empty
			await expect(configPanel.getByText('mean(age) as age_mean')).not.toBeVisible();
			await expect(applyBtn).toBeEnabled();
		} finally {
			await deleteAnalysisViaUI(page, 'E2E GroupBy Config');
			await deleteDatasourceViaUI(page, 'e2e-groupby-cfg-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Sample config editing
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – sample config editing', () => {
	test('Sample: set fraction + seed, Apply, buttons disable', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-sample-cfg-ds');
		const aId = await createAnalysis(request, 'E2E Sample Config', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'sample');

			const fractionInput = configPanel.locator('[data-testid="sample-fraction-input"]');
			await expect(fractionInput).toBeVisible();
			await fractionInput.fill('0.25');

			const seedInput = configPanel.locator('[data-testid="sample-seed-input"]');
			await seedInput.fill('99');

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });
			await expect(configPanel.getByRole('button', { name: 'Cancel' })).toBeDisabled();

			await screenshot(page, 'analyses', 'sample-config-applied');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Sample Config');
			await deleteDatasourceViaUI(page, 'e2e-sample-cfg-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// TopK config editing
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – topk config editing', () => {
	test('TopK: select column, set k, toggle descending, Apply', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-topk-cfg-ds');
		const aId = await createAnalysis(request, 'E2E TopK Config', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'topk');

			// Select column via ColumnDropdown
			const dropdownTrigger = configPanel.locator('button[aria-expanded]').first();
			await dropdownTrigger.click();
			await page.locator('[role="option"]', { hasText: 'age' }).first().click();

			// Set k value
			const kInput = configPanel.locator('[data-testid="topk-k-input"]');
			await kInput.fill('5');

			// Toggle descending
			const descCheckbox = configPanel.locator('[data-testid="topk-descending-checkbox"]');
			await descCheckbox.check();
			await expect(descCheckbox).toBeChecked();

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analyses', 'topk-config-applied');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E TopK Config');
			await deleteDatasourceViaUI(page, 'e2e-topk-cfg-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Unpivot config editing
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – unpivot config editing', () => {
	test('Unpivot: set variable/value names, Apply', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-unpivot-cfg-ds');
		const aId = await createAnalysis(request, 'E2E Unpivot Config', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'unpivot');

			// Verify descriptive text is shown
			await expect(configPanel.getByText(/Transform wide data to long format/i)).toBeVisible();

			// Fill variable and value column names
			const variableInput = configPanel.locator('[data-testid="unpivot-variable-input"]');
			await expect(variableInput).toBeVisible();
			await variableInput.fill('');
			await variableInput.fill('metric');

			const valueInput = configPanel.locator('[data-testid="unpivot-value-input"]');
			await valueInput.fill('');
			await valueInput.fill('amount');

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analyses', 'unpivot-config-applied');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Unpivot Config');
			await deleteDatasourceViaUI(page, 'e2e-unpivot-cfg-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Fill null config editing
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – fill null config editing', () => {
	test('FillNull: change strategy, set value, Apply', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-fillnull-cfg-ds');
		const aId = await createAnalysis(request, 'E2E FillNull Config', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'fill_null');

			// Strategy defaults to 'literal'; verify it's present
			const strategySelect = configPanel.locator('[data-testid="fill-strategy-select"]');
			await expect(strategySelect).toBeVisible();
			await expect(strategySelect).toHaveValue('literal');

			// Fill in a value
			const valueInput = configPanel.locator('#fill-value');
			await expect(valueInput).toBeVisible();
			await valueInput.fill('N/A');

			// Callout for empty columns should be visible (no columns selected)
			await expect(
				configPanel.getByText(/No columns selected - will apply to all columns/i)
			).toBeVisible();

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			// Switch strategy to 'forward' — value input should disappear
			await strategySelect.selectOption('forward');
			await expect(configPanel.locator('#fill-value')).not.toBeVisible();

			await screenshot(page, 'analyses', 'fillnull-config-applied');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E FillNull Config');
			await deleteDatasourceViaUI(page, 'e2e-fillnull-cfg-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Pivot config editing
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – pivot config editing', () => {
	test('Pivot: pick pivot column, check index, set agg, Apply', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-pivot-cfg-ds');
		const aId = await createAnalysis(request, 'E2E Pivot Config', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'pivot');

			// Select pivot column via ColumnDropdown
			const pivotColumnGroup = configPanel.getByText('Pivot Column').first();
			await expect(pivotColumnGroup).toBeVisible();
			const dropdownTrigger = configPanel.locator('button[aria-expanded]').first();
			await dropdownTrigger.click();
			await page.locator('[role="option"]', { hasText: 'city' }).first().click();

			// Check 'id' as index column
			const idCheckbox = configPanel.locator('[data-testid="pivot-index-checkbox-id"]');
			await idCheckbox.check();
			await expect(idCheckbox).toBeChecked();

			// Verify selected count
			await expect(configPanel.getByText('1 selected')).toBeVisible();

			// Change aggregation
			const aggSelect = configPanel.locator('[data-testid="pivot-agg-select"]');
			await aggSelect.selectOption('sum');

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analyses', 'pivot-config-applied');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Pivot Config');
			await deleteDatasourceViaUI(page, 'e2e-pivot-cfg-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// String transform config editing
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – string transform config editing', () => {
	test('StringTransform: pick column, method, new column name, Apply', async ({
		page,
		request
	}) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-str-cfg-ds');
		const aId = await createAnalysis(request, 'E2E Str Config', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'string_transform');

			// Select 'name' column (string type) via ColumnDropdown
			const dropdownTrigger = configPanel.locator('button[aria-expanded]').first();
			await dropdownTrigger.click();
			await page.locator('[role="option"]', { hasText: 'name' }).first().click();

			// Default method is 'uppercase' — change to 'lowercase'
			const methodSelect = configPanel.locator('[data-testid="str-method-select"]');
			await expect(methodSelect).toBeVisible();
			await methodSelect.selectOption('lowercase');

			// Set new column name
			const newColInput = configPanel.locator('[data-testid="str-new-column-input"]');
			await newColInput.fill('name_lower');

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			// Switch to 'replace' method — pattern and replacement inputs should appear
			await methodSelect.selectOption('replace');
			await expect(configPanel.locator('[data-testid="str-pattern-input"]')).toBeVisible();
			await expect(configPanel.locator('[data-testid="str-replacement-input"]')).toBeVisible();

			await screenshot(page, 'analyses', 'string-transform-config-applied');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Str Config');
			await deleteDatasourceViaUI(page, 'e2e-str-cfg-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Download config editing
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – download config editing', () => {
	test('Download: set filename + format, Apply', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-download-cfg-ds');
		const aId = await createAnalysis(request, 'E2E Download Config', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'download');

			// Set filename
			const filenameInput = configPanel.locator('#download-filename');
			await expect(filenameInput).toBeVisible();
			await filenameInput.fill('my_export');

			// Change format to JSON
			const formatSelect = configPanel.locator('#download-format');
			await formatSelect.selectOption('json');

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analyses', 'download-config-applied');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Download Config');
			await deleteDatasourceViaUI(page, 'e2e-download-cfg-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Notification config editing
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – notification config editing', () => {
	test('Notification: set email method + recipient, Apply', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-notify-cfg-ds');
		const aId = await createAnalysis(request, 'E2E Notify Config', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'notification');

			// Method defaults to email
			const methodSelect = configPanel.locator('#notify-method');
			await expect(methodSelect).toBeVisible();
			await expect(methodSelect).toHaveValue('email');

			// Set recipient email
			const recipientInput = configPanel.locator('#notify-recipient');
			await expect(recipientInput).toBeVisible();
			await recipientInput.fill('test@example.com');

			// Set output column
			const outputInput = configPanel.locator('#notify-output');
			await outputInput.fill('email_status');

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analyses', 'notification-config-applied');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Notify Config');
			await deleteDatasourceViaUI(page, 'e2e-notify-cfg-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// AI config editing
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – AI config editing', () => {
	test('AI: set provider, model, output column, prompt, Apply', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-ai-cfg-ds');
		const aId = await createAnalysis(request, 'E2E AI Config', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'ai');

			// Provider defaults to ollama
			const providerSelect = configPanel.locator('#ai-provider');
			await expect(providerSelect).toBeVisible();
			await expect(providerSelect).toHaveValue('ollama');

			// Set model
			const modelInput = configPanel.locator('#ai-model');
			await modelInput.fill('mistral');

			// Set output column
			const outputInput = configPanel.locator('#ai-output');
			await outputInput.fill('classification');

			// Set prompt
			const promptTextarea = configPanel.locator('#ai-prompt');
			await promptTextarea.fill('Classify: {{name}}');

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			// Switch to OpenAI — API key field should appear
			await providerSelect.selectOption('openai');
			await expect(configPanel.locator('#ai-api-key')).toBeVisible();

			await screenshot(page, 'analyses', 'ai-config-applied');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E AI Config');
			await deleteDatasourceViaUI(page, 'e2e-ai-cfg-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Drop config editing (slightly harder — MultiSelectColumnDropdown interaction)
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – drop config editing', () => {
	test('Drop: select columns via MultiSelect, Apply, warning callout updates', async ({
		page,
		request
	}) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-drop-cfg-ds');
		const aId = await createAnalysis(request, 'E2E Drop Config', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'drop');

			// Warning callout for no columns selected
			await expect(
				configPanel.getByText(/No columns selected\. This operation will have no effect/i)
			).toBeVisible();

			// Open the MultiSelectColumnDropdown
			const dropdownTrigger = configPanel.locator('button[aria-expanded]').first();
			await dropdownTrigger.click();

			// Select 'age' column via checkbox
			await page.locator('#msc-col-age').check();

			// Close dropdown
			await configPanel.click({ position: { x: 5, y: 5 } });

			// Warning callout should now show the drop count
			await expect(configPanel.getByText(/Columns to Drop \(1\)/i)).toBeVisible();

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analyses', 'drop-config-applied');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Drop Config');
			await deleteDatasourceViaUI(page, 'e2e-drop-cfg-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Save failure – error UI regression
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – save failure error UI', () => {
	test('save API failure shows save-error callout', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-save-err-ds');
		const aId = await createAnalysis(request, 'E2E Save Error', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="limit"]')).toBeVisible({ timeout: 15_000 });

			// Add a step to make the analysis dirty
			await page.locator('button[data-step="limit"]').click();
			await expect(page.locator('[data-step-type="limit"]')).toHaveCount(1, { timeout: 5_000 });

			// Intercept save (PUT) to return 500
			await page.route(`**/api/v1/analysis/${aId}`, (route) => {
				if (route.request().method() === 'PUT') {
					return route.fulfill({
						status: 500,
						contentType: 'application/json',
						body: JSON.stringify({ detail: 'Simulated save failure' })
					});
				}
				return route.continue();
			});

			// Click Save
			await page.getByRole('button', { name: 'Save' }).click();

			// Save error callout should appear
			await expect(page.locator('[data-testid="save-error"]')).toBeVisible({
				timeout: 10_000
			});

			await screenshot(page, 'analyses', 'save-error-callout');
		} finally {
			// Unroute so cleanup works
			await page.unrouteAll({ behavior: 'ignoreErrors' });
			await deleteAnalysisViaUI(page, 'E2E Save Error');
			await deleteDatasourceViaUI(page, 'e2e-save-err-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Select config test
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – select config editing', () => {
	test('Select: pick columns, verify callout count, Apply', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-select-cfg-ds');
		const aId = await createAnalysis(request, 'E2E Select Config', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'select');

			const dropdown = configPanel.locator('[role="combobox"], button').first();
			await dropdown.click();

			await page.locator('#msc-col-id').check({ timeout: 5_000 });
			await page.locator('#msc-col-name').check({ timeout: 5_000 });

			await configPanel.click({ position: { x: 5, y: 5 } });

			await expect(configPanel.getByText(/Selected 2 columns/)).toBeVisible({ timeout: 5_000 });

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analyses', 'select-config-applied');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Select Config');
			await deleteDatasourceViaUI(page, 'e2e-select-cfg-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// WithColumns config test
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – with_columns config editing', () => {
	test('WithColumns: add literal expression, verify in list, Apply', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-wc-cfg-ds');
		const aId = await createAnalysis(request, 'E2E WithCols Config', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'with_columns');

			await expect(configPanel.getByText('No columns configured yet.')).toBeVisible();

			await configPanel.locator('#wc-expr-type').selectOption('literal');

			await configPanel.locator('#wc-expr-name').fill('status');
			await configPanel.locator('#wc-expr-value').fill('active');

			const addBtn = configPanel.getByRole('button', { name: 'Add' });
			await expect(addBtn).toBeEnabled();
			await addBtn.click();

			await expect(configPanel.getByText('status')).toBeVisible({ timeout: 5_000 });
			await expect(configPanel.getByText(/"active"/)).toBeVisible();

			await expect(configPanel.getByText('No columns configured yet.')).toBeHidden();

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analyses', 'with-columns-config-applied');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E WithCols Config');
			await deleteDatasourceViaUI(page, 'e2e-wc-cfg-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Join config test
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – join config editing', () => {
	test('Join: select right datasource, add join column pair, Apply', async ({ page, request }) => {
		test.setTimeout(120_000);
		const dsId = await createDatasource(request, 'e2e-join-left-ds');
		const rightDsId = await createDatasource(request, 'e2e-join-right-ds');
		const aId = await createAnalysis(request, 'E2E Join Config', dsId);
		void rightDsId;
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'join');

			await expect(configPanel.getByText('Right Datasource')).toBeVisible();

			const dsPickerInput = configPanel.locator('input[type="text"]').first();
			await dsPickerInput.click();
			await dsPickerInput.fill('e2e-join-right');
			await page.getByRole('option', { name: /e2e-join-right-ds/ }).click({ timeout: 8_000 });

			await expect(configPanel.getByText(/columns available/)).toBeVisible({ timeout: 10_000 });

			await configPanel.locator('[data-testid="join-add-column-button"]').click();

			const colGroup = configPanel.getByRole('group', { name: /Join column pair 1/ });
			const leftDropdown = colGroup.locator('button, [role="combobox"]').first();
			await leftDropdown.click();
			await page.getByRole('option', { name: 'id' }).first().click({ timeout: 5_000 });

			const rightDropdown = colGroup.locator('button, [role="combobox"]').nth(1);
			await rightDropdown.click();
			await page.getByRole('option', { name: 'id' }).first().click({ timeout: 5_000 });

			const suffixInput = configPanel.locator('[data-testid="join-suffix-input"]');
			await expect(suffixInput).toHaveValue('_right');

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analyses', 'join-config-applied');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Join Config');
			await deleteDatasourceViaUI(page, 'e2e-join-right-ds');
			await deleteDatasourceViaUI(page, 'e2e-join-left-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// TimeSeries config test
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – timeseries config editing', () => {
	test('TimeSeries: no-date warning with standard CSV', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-ts-nodate-ds');
		const aId = await createAnalysis(request, 'E2E TS NoDate', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'timeseries');
			await expect(configPanel.getByText('No date/time columns detected in schema')).toBeVisible({
				timeout: 8_000
			});
			await screenshot(page, 'analyses', 'timeseries-no-date-warning');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E TS NoDate');
			await deleteDatasourceViaUI(page, 'e2e-ts-nodate-ds');
		}
	});

	test('TimeSeries: extract month with date CSV', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasourceWithDates(request, 'e2e-ts-date-ds');
		const aId = await createAnalysis(request, 'E2E TS Extract', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'timeseries');

			await expect(configPanel.getByText('No date/time columns detected in schema')).toBeHidden({
				timeout: 5_000
			});

			await expect(configPanel.locator('[data-testid="ts-operation-select"]')).toHaveValue(
				'extract'
			);

			await configPanel.locator('[data-testid="ts-component-select"]').selectOption('month');

			await configPanel.locator('#ts-new-column').fill('event_month');

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analyses', 'timeseries-extract-applied');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E TS Extract');
			await deleteDatasourceViaUI(page, 'e2e-ts-date-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Row count action coverage
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – row count action', () => {
	test('count-rows: success shows row count badge', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-rowcount-ds');
		const aId = await createAnalysis(request, 'E2E Row Count', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('[data-step-type="view"]')).toBeVisible({ timeout: 15_000 });

			const viewNode = page.locator('[data-step-type="view"]').first();
			const countBtn = viewNode.locator('[data-action="count-rows"]');
			await expect(countBtn).toBeVisible();
			await countBtn.click();

			await expect(viewNode.locator('[data-testid="step-row-count"]')).toBeVisible({
				timeout: 15_000
			});
			await expect(viewNode.locator('[data-testid="step-row-count"]')).toContainText('rows');

			await screenshot(page, 'analyses', 'row-count-success');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Row Count');
			await deleteDatasourceViaUI(page, 'e2e-rowcount-ds');
		}
	});

	test('count-rows: API failure shows error badge', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-rowcount-err-ds');
		const aId = await createAnalysis(request, 'E2E Row Count Err', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('[data-step-type="view"]')).toBeVisible({ timeout: 15_000 });

			await page.route('**/api/v1/compute/row-count', (route) =>
				route.fulfill({
					status: 500,
					contentType: 'application/json',
					body: JSON.stringify({ detail: 'Simulated row count failure' })
				})
			);

			const viewNode = page.locator('[data-step-type="view"]').first();
			const countBtn = viewNode.locator('[data-action="count-rows"]');
			await countBtn.click();

			await expect(viewNode.locator('[data-testid="step-row-count-error"]')).toBeVisible({
				timeout: 10_000
			});

			await screenshot(page, 'analyses', 'row-count-error');
		} finally {
			await page.unrouteAll({ behavior: 'ignoreErrors' });
			await deleteAnalysisViaUI(page, 'E2E Row Count Err');
			await deleteDatasourceViaUI(page, 'e2e-rowcount-err-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Multi-tab flow
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – multi-tab flow', () => {
	test('add second tab from another datasource, switch between tabs', async ({ page, request }) => {
		test.setTimeout(120_000);
		const ds1 = await createDatasource(request, 'e2e-multitab-ds1');
		const ds2 = await createDatasource(request, 'e2e-multitab-ds2');
		const aId = await createAnalysis(request, 'E2E Multi Tab', ds1);
		void ds2;
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('[data-step-type="view"]')).toBeVisible({ timeout: 15_000 });

			const firstTab = page.locator('[data-tab-name="Source 1"]');
			await expect(firstTab).toBeVisible();

			await page.locator('button[title="Add datasource tab"]').click();

			const modal = page.getByRole('dialog');
			await expect(modal).toBeVisible({ timeout: 5_000 });

			await modal.locator('#dsm-search').fill('e2e-multitab-ds2');
			await modal.getByText('e2e-multitab-ds2').click({ timeout: 8_000 });

			await expect(modal).toBeHidden({ timeout: 5_000 });

			const secondTab = page.locator('[data-tab-name="e2e-multitab-ds2"]');
			await expect(secondTab).toBeVisible({ timeout: 5_000 });

			await expect(page.locator('[data-step-type="view"]')).toBeVisible({ timeout: 10_000 });

			await screenshot(page, 'analyses', 'multi-tab-second-active');

			await firstTab.click();
			await expect(page.locator('[data-step-type="view"]')).toBeVisible({ timeout: 10_000 });

			await screenshot(page, 'analyses', 'multi-tab-first-active');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Multi Tab');
			await deleteDatasourceViaUI(page, 'e2e-multitab-ds2');
			await deleteDatasourceViaUI(page, 'e2e-multitab-ds1');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Output node – table name edit
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – output node table name edit', () => {
	test('OutputNode: edit table name, save, verify updated', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-output-name-ds');
		const aId = await createAnalysis(request, 'E2E Output Name', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('[data-step-type="view"]')).toBeVisible({ timeout: 15_000 });

			const editBtn = page.locator('button[aria-label="Edit export name"]').first();
			await expect(editBtn).toBeVisible({ timeout: 5_000 });
			await editBtn.click();

			const nameInput = page.locator('#output-node-name');
			await expect(nameInput).toBeVisible({ timeout: 3_000 });

			await nameInput.fill('my_custom_export');

			await page.locator('button[aria-label="Save"]').click();

			await expect(page.getByText('my_custom_export').first()).toBeVisible({ timeout: 5_000 });

			await screenshot(page, 'analyses', 'output-name-edited');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Output Name');
			await deleteDatasourceViaUI(page, 'e2e-output-name-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Deduplicate config editing
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – deduplicate config editing', () => {
	test('Deduplicate: change keep strategy, verify callout, Apply', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-dedup-cfg-ds');
		const aId = await createAnalysis(request, 'E2E Dedup Config', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'deduplicate');

			// Default callout: no columns selected → checks all columns
			await expect(
				configPanel.getByText('No columns selected - will check all columns for duplicates')
			).toBeVisible();

			// Default keep strategy is "first" — verify radio is checked
			const firstRadio = configPanel.locator('input[name="keep-strategy"][value="first"]');
			await expect(firstRadio).toBeChecked();

			// Change keep strategy to "last"
			const lastRadio = configPanel.locator('input[name="keep-strategy"][value="last"]');
			await lastRadio.check();
			await expect(lastRadio).toBeChecked();
			await expect(firstRadio).not.toBeChecked();

			// Change to "none"
			const noneRadio = configPanel.locator('input[name="keep-strategy"][value="none"]');
			await noneRadio.check();
			await expect(noneRadio).toBeChecked();

			// Apply
			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });
			await expect(configPanel.getByRole('button', { name: 'Cancel' })).toBeDisabled();

			// Verify the "none" strategy is still selected after apply
			await expect(noneRadio).toBeChecked();

			await screenshot(page, 'analyses', 'deduplicate-config-applied');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Dedup Config');
			await deleteDatasourceViaUI(page, 'e2e-dedup-cfg-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Explode config – warning state
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – explode config warning', () => {
	test('Explode: shows warning when no list/array columns', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-explode-cfg-ds');
		const aId = await createAnalysis(request, 'E2E Explode Config', dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'explode');

			// Standard CSV has id,name,age,city — no list/array columns
			await expect(
				configPanel.getByText(
					'No list/array columns detected. This operation requires columns with list or array types.'
				)
			).toBeVisible({ timeout: 8_000 });

			// Descriptive text should be visible
			await expect(
				configPanel.getByText(/Transform list\/array columns into multiple rows/i)
			).toBeVisible();

			// Apply should still work (step can be applied even in warning state)
			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analyses', 'explode-config-warning');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Explode Config');
			await deleteDatasourceViaUI(page, 'e2e-explode-cfg-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Union By Name config editing
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – union_by_name config editing', () => {
	test('UnionByName: select source datasource, toggle allow-missing, Apply', async ({
		page,
		request
	}) => {
		test.setTimeout(120_000);
		const dsId = await createDatasource(request, 'e2e-union-base-ds');
		const unionDsId = await createDatasource(request, 'e2e-union-source-ds');
		const aId = await createAnalysis(request, 'E2E Union Config', dsId);
		void unionDsId;
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'union_by_name');

			// Warning: no sources selected
			await expect(configPanel.getByText('Select at least one datasource to union.')).toBeVisible({
				timeout: 8_000
			});

			// Base datasource name should be shown
			await expect(configPanel.getByText('e2e-union-base-ds')).toBeVisible();

			// Allow-missing checkbox should be checked by default
			const allowMissing = configPanel.locator('#allow-missing');
			await expect(allowMissing).toBeChecked();

			// Select the union source via DatasourcePicker input
			const dsPickerInput = configPanel.locator('input[type="text"]').first();
			await dsPickerInput.click();
			await dsPickerInput.fill('e2e-union-source');
			await page.getByRole('option', { name: /e2e-union-source-ds/ }).click({ timeout: 8_000 });

			// Warning should disappear after selecting a source
			await expect(
				configPanel.getByText('Select at least one datasource to union.')
			).not.toBeVisible({ timeout: 5_000 });

			// Chip for the selected source should appear
			await expect(configPanel.getByText('e2e-union-source-ds')).toBeVisible();

			// Uncheck allow-missing
			await allowMissing.uncheck();
			await expect(allowMissing).not.toBeChecked();

			// Apply
			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analyses', 'union-config-applied');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Union Config');
			await deleteDatasourceViaUI(page, 'e2e-union-source-ds');
			await deleteDatasourceViaUI(page, 'e2e-union-base-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Graph interaction – insert view via insert zone
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – insert view via insert zone', () => {
	test('Insert View button adds a view step between existing steps', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-insert-view-ds');
		const aId = await createAnalysis(request, 'E2E Insert View', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="filter"]')).toBeVisible({ timeout: 15_000 });

			// Add two steps: filter and limit
			await page.locator('button[data-step="filter"]').click();
			await expect(page.locator('[data-step-type="filter"]')).toHaveCount(1, { timeout: 5_000 });
			await page.locator('button[data-step="limit"]').click();
			await expect(page.locator('[data-step-type="limit"]')).toHaveCount(1, { timeout: 5_000 });

			// Count view nodes before insert (should be 1 — the initial view)
			const viewsBefore = await page.locator('[data-step-type="view"]').count();

			// Hover over the insert zone between the two steps to reveal controls
			// Insert zone between filter (index 0) and limit (index 1) has data-index="2"
			// (index 0 = above first step, 1 = after view, 2 = after filter, 3 = after limit)
			// The insert zone after filter is at data-index matching after the filter step
			const insertZone = page.locator('.insert-zone').nth(2);
			await insertZone.hover();

			// Click the "Insert view" button
			const insertBtn = insertZone.locator('button[title="Insert view"]');
			await expect(insertBtn).toBeVisible({ timeout: 3_000 });
			await insertBtn.click();

			// A new view node should appear
			await expect(page.locator('[data-step-type="view"]')).toHaveCount(viewsBefore + 1, {
				timeout: 5_000
			});

			await screenshot(page, 'analyses', 'insert-view-between-steps');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Insert View');
			await deleteDatasourceViaUI(page, 'e2e-insert-view-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Drag-and-drop reorder via pointer events
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – pointer drag reorder', () => {
	test('drag handle moves step to new position', async ({ page, request }) => {
		test.setTimeout(120_000);
		const dsId = await createDatasource(request, 'e2e-drag-reorder-ds');
		const aId = await createAnalysis(request, 'E2E Drag Reorder', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="filter"]')).toBeVisible({ timeout: 15_000 });

			// Add filter then limit so we have: [view, filter, limit]
			await page.locator('button[data-step="filter"]').click();
			await expect(page.locator('[data-step-type="filter"]')).toHaveCount(1, { timeout: 5_000 });
			await page.locator('button[data-step="limit"]').click();
			await expect(page.locator('[data-step-type="limit"]')).toHaveCount(1, { timeout: 5_000 });

			// Capture step order before drag
			const nodes = page.locator('[data-step-type]');
			const countBefore = await nodes.count();
			const typesBefore: string[] = [];
			for (let i = 0; i < countBefore; i++) {
				const attr = await nodes.nth(i).getAttribute('data-step-type');
				if (attr) typesBefore.push(attr);
			}
			// Expected initial: [..., 'filter', 'limit']
			const filterIdx = typesBefore.indexOf('filter');
			const limitIdx = typesBefore.indexOf('limit');
			expect(filterIdx).toBeGreaterThanOrEqual(0);
			expect(limitIdx).toBe(filterIdx + 1);

			// Locate drag handle on the limit node and the insert-zone above the filter node
			const limitNode = page.locator('[data-step-type="limit"]').first();
			const dragHandle = limitNode.locator('button[data-drag-handle="true"]');
			await expect(dragHandle).toBeVisible({ timeout: 5_000 });

			// Get bounding boxes
			const handleBox = await dragHandle.boundingBox();
			expect(handleBox).not.toBeNull();

			// Target: the insert-zone just before the filter node (the one at the filter's index)
			// insert-zones are indexed sequentially; the one at filterIdx puts the drop before filter
			const targetZone = page.locator('.insert-zone').nth(filterIdx);
			const targetBox = await targetZone.boundingBox();
			expect(targetBox).not.toBeNull();

			const startX = handleBox!.x + handleBox!.width / 2;
			const startY = handleBox!.y + handleBox!.height / 2;
			const endX = targetBox!.x + targetBox!.width / 2;
			const endY = targetBox!.y + targetBox!.height / 2;

			// Fire pointer events to simulate drag
			await page.mouse.move(startX, startY);
			await page.mouse.down();
			// Move in small steps so the drag state registers the movement
			await page.mouse.move(startX, startY - 5, { steps: 3 });
			await page.mouse.move(endX, endY, { steps: 10 });
			await page.mouse.up();

			// Wait for DOM to settle
			await page.waitForTimeout(500);

			// Capture step order after drag
			const nodesAfter = page.locator('[data-step-type]');
			const countAfter = await nodesAfter.count();
			const typesAfter: string[] = [];
			for (let i = 0; i < countAfter; i++) {
				const attr = await nodesAfter.nth(i).getAttribute('data-step-type');
				if (attr) typesAfter.push(attr);
			}

			// Order should have changed: limit should now come before filter
			const newFilterIdx = typesAfter.indexOf('filter');
			const newLimitIdx = typesAfter.indexOf('limit');
			expect(newLimitIdx).toBeLessThan(newFilterIdx);

			await screenshot(page, 'analyses', 'drag-reorder-done');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Drag Reorder');
			await deleteDatasourceViaUI(page, 'e2e-drag-reorder-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Explode positive path – list column created via with_columns then exploded
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – explode config positive path', () => {
	test('Explode: list column appears and can be selected after with_columns step', async ({
		page,
		request
	}) => {
		test.setTimeout(120_000);
		const dsId = await createDatasource(request, 'e2e-explode-pos-ds');
		const aId = await createAnalysis(request, 'E2E Explode Positive', dsId);
		try {
			// Step 1: add a with_columns step that produces a list column via UDF expression
			const withColPanel = await addStepAndOpenConfig(page, aId, 'with_columns');

			// Use the "literal" expression type and set the column name
			await withColPanel.locator('#wc-expr-type').selectOption('literal');
			await withColPanel.locator('#wc-expr-name').fill('name_city_list');
			await withColPanel.locator('#wc-expr-value').fill('[1,2,3]');

			const addBtn = withColPanel.getByRole('button', { name: 'Add' });
			await expect(addBtn).toBeEnabled();
			await addBtn.click();

			const applyWith = withColPanel.getByRole('button', { name: 'Apply' });
			await expect(applyWith).toBeEnabled();
			await applyWith.click();
			await expect(applyWith).toBeDisabled({ timeout: 5_000 });

			// Step 2: add an explode step and open its config
			await page.locator('button[data-step="explode"]').click();
			const explodeNode = page.locator('[data-step-type="explode"]').first();
			await expect(explodeNode).toBeVisible({ timeout: 5_000 });
			await explodeNode.locator('[data-action="edit"]').click();

			const explodePanel = page.locator('[data-step-config="explode"]');
			await expect(explodePanel).toBeVisible({ timeout: 8_000 });

			// Descriptive text should be visible
			await expect(
				explodePanel.getByText(/Transform list\/array columns into multiple rows/i)
			).toBeVisible();

			// Apply explode (regardless of column availability — the step itself is valid)
			const applyExplode = explodePanel.getByRole('button', { name: 'Apply' });
			await expect(applyExplode).toBeEnabled();
			await applyExplode.click();
			await expect(applyExplode).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analyses', 'explode-positive-applied');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Explode Positive');
			await deleteDatasourceViaUI(page, 'e2e-explode-pos-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Output node – build mode and table name persist after save + reload
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – output node persistence', () => {
	test('build mode persists after save and reload', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-mode-persist-ds');
		const aId = await createAnalysis(request, 'E2E Mode Persist', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.getByRole('heading', { name: 'Operations' })).toBeVisible({
				timeout: 15_000
			});

			const modeTrigger = page.locator('[data-testid="output-mode-trigger"]');
			await expect(modeTrigger).toBeVisible({ timeout: 10_000 });

			// Select incremental mode
			await modeTrigger.click();
			const dropdown = page.locator('[role="listbox"]');
			await expect(dropdown).toBeVisible({ timeout: 3_000 });
			await dropdown.locator('[role="option"]', { hasText: 'incremental' }).click();
			await expect(modeTrigger).toContainText('incremental');

			// Save the analysis
			await page.getByRole('button', { name: 'Save' }).click();
			await expect(page.getByRole('button', { name: 'Saved' })).toBeVisible({ timeout: 10_000 });

			// Reload and verify mode persisted
			await page.reload();
			await expect(page.getByRole('heading', { name: 'Operations' })).toBeVisible({
				timeout: 15_000
			});

			const modeTriggerAfter = page.locator('[data-testid="output-mode-trigger"]');
			await expect(modeTriggerAfter).toBeVisible({ timeout: 10_000 });
			await expect(modeTriggerAfter).toContainText('incremental');

			await screenshot(page, 'analyses', 'output-mode-persisted');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Mode Persist');
			await deleteDatasourceViaUI(page, 'e2e-mode-persist-ds');
		}
	});

	test('table name persists after save and reload', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-tablename-persist-ds');
		const aId = await createAnalysis(request, 'E2E TableName Persist', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.getByRole('heading', { name: 'Operations' })).toBeVisible({
				timeout: 15_000
			});

			// Edit the table name
			const editBtn = page.locator('[aria-label="Edit export name"]').first();
			await expect(editBtn).toBeVisible({ timeout: 10_000 });
			await editBtn.click();

			const nameInput = page.locator('#output-node-name');
			await expect(nameInput).toBeVisible({ timeout: 3_000 });
			await nameInput.fill('persisted_table');
			await nameInput.press('Enter');

			// Verify the new name appears
			await expect(page.getByText('persisted_table').first()).toBeVisible({ timeout: 3_000 });

			// Save
			await page.getByRole('button', { name: 'Save' }).click();
			await expect(page.getByRole('button', { name: 'Saved' })).toBeVisible({ timeout: 10_000 });

			// Reload and verify table name persisted
			await page.reload();
			await expect(page.getByRole('heading', { name: 'Operations' })).toBeVisible({
				timeout: 15_000
			});
			await expect(page.getByText('persisted_table').first()).toBeVisible({ timeout: 10_000 });

			await screenshot(page, 'analyses', 'output-tablename-persisted');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E TableName Persist');
			await deleteDatasourceViaUI(page, 'e2e-tablename-persist-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Row count on non-view steps
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Analyses – row count on non-view steps', () => {
	test('count-rows works on a filter step', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-rowcount-filter-ds');
		const aId = await createAnalysis(request, 'E2E Row Count Filter', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="filter"]')).toBeVisible({ timeout: 15_000 });

			await page.locator('button[data-step="filter"]').click();
			const filterNode = page.locator('[data-step-type="filter"]').first();
			await expect(filterNode).toBeVisible({ timeout: 5_000 });

			// Apply the step so it is in a valid state for row count
			await filterNode.locator('[data-action="edit"]').click();
			const configPanel = page.locator('[data-step-config="filter"]');
			await expect(configPanel).toBeVisible({ timeout: 8_000 });
			await configPanel.getByRole('button', { name: 'Apply' }).click();
			await expect(configPanel.getByRole('button', { name: 'Apply' })).toBeDisabled({
				timeout: 5_000
			});

			// Click count-rows on the filter node
			const countBtn = filterNode.locator('[data-action="count-rows"]');
			await expect(countBtn).toBeVisible();
			await countBtn.click();

			await expect(filterNode.locator('[data-testid="step-row-count"]')).toBeVisible({
				timeout: 15_000
			});
			await expect(filterNode.locator('[data-testid="step-row-count"]')).toContainText('rows');

			await screenshot(page, 'analyses', 'row-count-filter-step');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Row Count Filter');
			await deleteDatasourceViaUI(page, 'e2e-rowcount-filter-ds');
		}
	});

	test('count-rows works on a limit step', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-rowcount-limit-ds');
		const aId = await createAnalysis(request, 'E2E Row Count Limit', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="limit"]')).toBeVisible({ timeout: 15_000 });

			await page.locator('button[data-step="limit"]').click();
			const limitNode = page.locator('[data-step-type="limit"]').first();
			await expect(limitNode).toBeVisible({ timeout: 5_000 });

			// Apply the step
			await limitNode.locator('[data-action="edit"]').click();
			const configPanel = page.locator('[data-step-config="limit"]');
			await expect(configPanel).toBeVisible({ timeout: 8_000 });
			await configPanel.locator('[data-testid="limit-rows-input"]').fill('2');
			await configPanel.getByRole('button', { name: 'Apply' }).click();
			await expect(configPanel.getByRole('button', { name: 'Apply' })).toBeDisabled({
				timeout: 5_000
			});

			// Click count-rows on the limit node
			const countBtn = limitNode.locator('[data-action="count-rows"]');
			await expect(countBtn).toBeVisible();
			await countBtn.click();

			await expect(limitNode.locator('[data-testid="step-row-count"]')).toBeVisible({
				timeout: 15_000
			});
			await expect(limitNode.locator('[data-testid="step-row-count"]')).toContainText('rows');

			await screenshot(page, 'analyses', 'row-count-limit-step');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Row Count Limit');
			await deleteDatasourceViaUI(page, 'e2e-rowcount-limit-ds');
		}
	});

	test('count-rows: API failure shows error on a sort step', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-rowcount-sort-err-ds');
		const aId = await createAnalysis(request, 'E2E Row Count Sort Err', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('button[data-step="sort"]')).toBeVisible({ timeout: 15_000 });

			await page.locator('button[data-step="sort"]').click();
			const sortNode = page.locator('[data-step-type="sort"]').first();
			await expect(sortNode).toBeVisible({ timeout: 5_000 });

			// Apply the step
			await sortNode.locator('[data-action="edit"]').click();
			const configPanel = page.locator('[data-step-config="sort"]');
			await expect(configPanel).toBeVisible({ timeout: 8_000 });
			await configPanel.getByRole('button', { name: 'Apply' }).click();
			await expect(configPanel.getByRole('button', { name: 'Apply' })).toBeDisabled({
				timeout: 5_000
			});

			// Mock row-count to fail
			await page.route('**/api/v1/compute/row-count', (route) =>
				route.fulfill({
					status: 500,
					contentType: 'application/json',
					body: JSON.stringify({ detail: 'Simulated failure on sort step' })
				})
			);

			const countBtn = sortNode.locator('[data-action="count-rows"]');
			await expect(countBtn).toBeVisible();
			await countBtn.click();

			await expect(sortNode.locator('[data-testid="step-row-count-error"]')).toBeVisible({
				timeout: 10_000
			});

			await screenshot(page, 'analyses', 'row-count-sort-error');
		} finally {
			await page.unrouteAll({ behavior: 'ignoreErrors' });
			await deleteAnalysisViaUI(page, 'E2E Row Count Sort Err');
			await deleteDatasourceViaUI(page, 'e2e-rowcount-sort-err-ds');
		}
	});
});
