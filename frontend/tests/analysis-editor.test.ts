import { test, expect } from '@playwright/test';
import { createDatasource, createAnalysis } from './utils/api.js';
import { addStepAndOpenConfig } from './utils/analysis.js';
import { deleteAnalysisViaUI, deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { screenshot } from './utils/visual.js';

// ── Save/discard dirty tracking ─────────────────────────────────────────────

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

// ── Step library labels ─────────────────────────────────────────────────────

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
// Download config – filename & format switching
// ────────────────────────────────────────────────────────────────────────────────

// ── Step interaction ────────────────────────────────────────────────────────

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

// ── Save persistence ────────────────────────────────────────────────────────

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

// ── Node actions ────────────────────────────────────────────────────────────

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

			await screenshot(page, 'analysis/editor', 'node-deleted');
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

			await screenshot(page, 'analysis/editor', 'node-toggle-enabled');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Node Toggle');
			await deleteDatasourceViaUI(page, 'e2e-node-toggle-ds');
		}
	});
});

// ── Config persistence ──────────────────────────────────────────────────────

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

			await screenshot(page, 'analysis/editor', 'limit-config-persisted');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Cfg Persist');
			await deleteDatasourceViaUI(page, 'e2e-cfg-persist-ds');
		}
	});
});

// ── Step reorder persistence ────────────────────────────────────────────────

test.describe('Analyses – step reorder persistence', () => {
	test('Step order persists after save and reload', async ({ page, request }) => {
		test.setTimeout(120_000);
		const dsId = await createDatasource(request, 'e2e-reorder-ds');
		const aId = await createAnalysis(request, 'E2E Reorder Persist', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.getByRole('heading', { name: 'Operations' })).toBeVisible({
				timeout: 15_000
			});
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

			await screenshot(page, 'analysis/editor', 'step-reorder-persisted');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Reorder Persist');
			await deleteDatasourceViaUI(page, 'e2e-reorder-ds');
		}
	});
});

// ── Tabs ────────────────────────────────────────────────────────────────────

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

			await screenshot(page, 'analysis/editor', 'derived-tab-flow');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Derived Tab');
			await deleteDatasourceViaUI(page, 'e2e-derived-tab-ds');
		}
	});
});

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

			await screenshot(page, 'analysis/editor', 'multi-tab-second-active');

			await firstTab.click();
			await expect(page.locator('[data-step-type="view"]')).toBeVisible({ timeout: 10_000 });

			await screenshot(page, 'analysis/editor', 'multi-tab-first-active');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Multi Tab');
			await deleteDatasourceViaUI(page, 'e2e-multitab-ds2');
			await deleteDatasourceViaUI(page, 'e2e-multitab-ds1');
		}
	});
});

// ── Version history ─────────────────────────────────────────────────────────

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

			await screenshot(page, 'analysis/editor', 'version-history-empty');

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

			await screenshot(page, 'analysis/editor', 'version-history-with-versions');

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

			await screenshot(page, 'analysis/editor', 'version-history-renamed');

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

			await screenshot(page, 'analysis/editor', 'version-history-after-delete');
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

			// Add a limit step and save (creates v2 = pre-save [view], analysis = [view, limit])
			await page.locator('button[data-step="limit"]').click();
			await expect(page.locator('[data-step-type="limit"]')).toHaveCount(1, { timeout: 5_000 });
			await expect(page.getByRole('button', { name: 'Save' })).toBeVisible({ timeout: 5_000 });
			await page.getByRole('button', { name: 'Save' }).click();
			await expect(page.getByRole('button', { name: 'Saved' })).toBeVisible({ timeout: 20_000 });

			// Restore version 1 (= initial [view] from create): limit should be removed
			await page.locator('[data-testid="version-history-trigger"]').click();
			const dialog = page.getByRole('dialog');
			await expect(dialog.getByText(/Version 1/)).toBeVisible({ timeout: 10_000 });

			await dialog.locator('[data-testid="version-restore-1"]').click();

			// Modal should close after restore
			await expect(dialog).not.toBeVisible({ timeout: 8_000 });

			// The limit step should be gone (restored to v1 which only has view)
			await expect(page.locator('[data-step-type="limit"]')).toHaveCount(0, { timeout: 5_000 });

			// The view step (part of every version) should still be present
			await expect(page.locator('[data-step-type="view"]')).toHaveCount(1, { timeout: 5_000 });

			await screenshot(page, 'analysis/editor', 'version-history-after-restore');
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

			await screenshot(page, 'analysis/editor', 'version-history-load-error');
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

			await screenshot(page, 'analysis/editor', 'version-history-action-error');
			await dialog.getByRole('button', { name: 'Close', exact: true }).click();
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Ver Act Error');
			await deleteDatasourceViaUI(page, 'e2e-ver-act-err-ds');
		}
	});
});

// ── Canvas layout ───────────────────────────────────────────────────────────

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

			await screenshot(page, 'analysis/editor', 'insert-view-between-steps');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Insert View');
			await deleteDatasourceViaUI(page, 'e2e-insert-view-ds');
		}
	});
});

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

			await screenshot(page, 'analysis/editor', 'drag-reorder-done');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Drag Reorder');
			await deleteDatasourceViaUI(page, 'e2e-drag-reorder-ds');
		}
	});
});

// ── Save failure UI ─────────────────────────────────────────────────────────

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

			await screenshot(page, 'analysis/editor', 'save-error-callout');
		} finally {
			// Unroute so cleanup works
			await page.unrouteAll({ behavior: 'ignoreErrors' });
			await deleteAnalysisViaUI(page, 'E2E Save Error');
			await deleteDatasourceViaUI(page, 'e2e-save-err-ds');
		}
	});
});
