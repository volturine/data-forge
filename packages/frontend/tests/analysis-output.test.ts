import { test, expect } from './fixtures.js';
import { createDatasource, createAnalysis, shutdownEngine } from './utils/api.js';
import { deleteAnalysisViaUI, deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { addStepAndOpenConfig, gotoAnalysisEditor, waitForEditorReload } from './utils/analysis.js';
import { uid } from './utils/uid.js';
import { screenshot } from './utils/visual.js';
// ── Output visibility toggle ────────────────────────────────────────────────

test.describe('Analyses – output visibility toggle', () => {
	test('OutputNode: visibility toggle button shows initial state', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsName = `e2e-vis-toggle-ds-${uid()}`;
		const aName = `E2E Vis Toggle ${uid()}`;
		const dsId = await createDatasource(request, dsName);
		const aId = await createAnalysis(request, aName, dsId);
		try {
			await gotoAnalysisEditor(page, aId);

			// Toggle button should be visible on the output node
			const toggleBtn = page.locator('[data-testid="output-visibility-toggle"]');
			await expect(toggleBtn).toBeVisible({ timeout: 8_000 });

			// Without a saved/built output datasource, toggle shows "hidden" (default)
			// The toggle button is present but not functional until the output datasource exists
			await expect(toggleBtn).toContainText('hidden', { timeout: 5_000 });

			await screenshot(page, 'analysis/output', 'output-visibility-toggle');
		} finally {
			await shutdownEngine(request, aId);
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});
});

// ── Output node interactions ────────────────────────────────────────────────

test.describe('Analyses – output node interactions', () => {
	test('output node build button and mode selector are visible', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsName = `e2e-output-ds-${uid()}`;
		const aName = `E2E Output Node ${uid()}`;
		const dsId = await createDatasource(request, dsName);
		const aId = await createAnalysis(request, aName, dsId);
		try {
			await gotoAnalysisEditor(page, aId);

			// Build button should be visible
			const buildBtn = page.locator('[data-testid="output-build-button"]');
			await expect(buildBtn).toBeVisible({ timeout: 10_000 });

			// Mode trigger should be visible
			const modeTrigger = page.locator('[data-testid="output-mode-trigger"]');
			await expect(modeTrigger).toBeVisible();

			// Click mode trigger to open dropdown
			await modeTrigger.click();
			const dropdown = page.locator('[data-testid="output-mode-listbox"]');
			await expect(dropdown).toBeVisible({ timeout: 3_000 });

			// Check mode options are present
			await expect(dropdown.locator('[data-testid="output-mode-option-full"]')).toBeVisible();
			await expect(
				dropdown.locator('[data-testid="output-mode-option-incremental"]')
			).toBeVisible();
			await expect(dropdown.locator('[data-testid="output-mode-option-recreate"]')).toBeVisible();

			await screenshot(page, 'analysis/output', 'output-node-mode-dropdown');
		} finally {
			await shutdownEngine(request, aId);
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('selecting a mode updates the trigger text', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsName = `e2e-output-mode-ds-${uid()}`;
		const aName = `E2E Output Mode ${uid()}`;
		const dsId = await createDatasource(request, dsName);
		const aId = await createAnalysis(request, aName, dsId);
		try {
			await gotoAnalysisEditor(page, aId);

			const buildBtn = page.locator('[data-testid="output-build-button"]');
			await expect(buildBtn).toBeVisible({ timeout: 10_000 });

			const modeTrigger = page.locator('[data-testid="output-mode-trigger"]');
			await expect(modeTrigger).toBeVisible({ timeout: 10_000 });

			// Default should be "full"
			await expect(modeTrigger).toContainText('full');

			// Select "incremental"
			await modeTrigger.click();
			const dropdown = page.locator('[data-testid="output-mode-listbox"]');
			await expect(dropdown).toBeVisible({ timeout: 3_000 });
			await dropdown.locator('[data-testid="output-mode-option-incremental"]').click();

			// Dropdown should close and trigger should show "incremental"
			await expect(dropdown).not.toBeVisible({ timeout: 3_000 });
			await expect(modeTrigger).toContainText('incremental');

			// Select "recreate"
			await modeTrigger.click();
			await expect(page.locator('[data-testid="output-mode-listbox"]')).toBeVisible({
				timeout: 3_000
			});
			await page.locator('[data-testid="output-mode-option-recreate"]').click();

			await expect(modeTrigger).toContainText('recreate');

			await screenshot(page, 'analysis/output', 'output-mode-recreate');
		} finally {
			await shutdownEngine(request, aId);
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('collapsible sections toggle open and closed', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsName = `e2e-output-sections-ds-${uid()}`;
		const aName = `E2E Output Sections ${uid()}`;
		const dsId = await createDatasource(request, dsName);
		const aId = await createAnalysis(request, aName, dsId);
		try {
			await gotoAnalysisEditor(page, aId);

			// All section toggles should be visible
			const notifyToggle = page.locator('[data-testid="output-notify-toggle"]');
			const healthToggle = page.locator('[data-testid="output-health-toggle"]');
			const scheduleToggle = page.locator('[data-testid="output-schedule-toggle"]');

			await expect(notifyToggle).toBeVisible({ timeout: 10_000 });
			await expect(healthToggle).toBeVisible();
			await expect(scheduleToggle).toBeVisible();

			// Sections should start collapsed — "Build Notification" content not visible
			const notifyPanel = page.locator('[data-testid="output-notify-panel"]');
			const healthEmptyState = page.locator('[data-testid="output-health-empty-state"]');

			await expect(notifyPanel).not.toBeVisible();

			// Open Build Notification section
			await notifyToggle.click();
			await expect(notifyPanel).toBeVisible({ timeout: 3_000 });

			// Close it again
			await notifyToggle.click();
			await expect(notifyPanel).not.toBeVisible({ timeout: 3_000 });

			// Open Health Checks section — prompts to build first when output datasource is not materialized
			await healthToggle.click();
			await expect(healthEmptyState).toContainText(
				'Build this output once to materialize its datasource before adding health checks.',
				{
					timeout: 5_000
				}
			);

			await screenshot(page, 'analysis/output', 'output-sections-health-open');

			// Close Health Checks
			await healthToggle.click();
			await expect(healthEmptyState).not.toBeVisible({ timeout: 3_000 });
		} finally {
			await shutdownEngine(request, aId);
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('table name inline edit', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsName = `e2e-output-rename-ds-${uid()}`;
		const aName = `E2E Output Rename ${uid()}`;
		const dsId = await createDatasource(request, dsName);
		const aId = await createAnalysis(request, aName, dsId);
		try {
			await gotoAnalysisEditor(page, aId);

			// Click the edit pencil button (aria-label="Edit export name")
			const editBtn = page.locator('[data-testid="output-table-name-inline-edit"]');
			await expect(editBtn).toBeVisible({ timeout: 10_000 });
			await editBtn.click();

			// Input should appear
			const nameInput = page.locator('#output-node-name');
			await expect(nameInput).toBeVisible({ timeout: 3_000 });

			// Clear and type new name
			await nameInput.fill('my_custom_table');
			await nameInput.press('Enter');

			// After commit, the new name should appear in the output card
			await expect(page.locator('[data-testid="output-table-name-inline"]')).toHaveText(
				'my_custom_table',
				{ timeout: 3_000 }
			);

			await screenshot(page, 'analysis/output', 'output-table-renamed');
		} finally {
			await shutdownEngine(request, aId);
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});
});

// ── Output table name edit ──────────────────────────────────────────────────

test.describe('Analyses – output node table name edit', () => {
	test('OutputNode: edit table name, save, verify updated', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsName = `e2e-output-name-ds-${uid()}`;
		const aName = `E2E Output Name ${uid()}`;
		const dsId = await createDatasource(request, dsName);
		const aId = await createAnalysis(request, aName, dsId);
		try {
			await gotoAnalysisEditor(page, aId);

			const editBtn = page.locator('[data-testid="output-table-name-inline-edit"]');
			await expect(editBtn).toBeVisible({ timeout: 5_000 });
			await editBtn.click();

			const nameInput = page.locator('#output-node-name');
			await expect(nameInput).toBeVisible({ timeout: 3_000 });

			await nameInput.fill('my_custom_export');

			await page.locator('button[aria-label="Save"]').click();

			await expect(page.locator('[data-testid="output-table-name-inline"]')).toHaveText(
				'my_custom_export',
				{ timeout: 5_000 }
			);

			await screenshot(page, 'analysis/output', 'output-name-edited');
		} finally {
			await shutdownEngine(request, aId);
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});
});

// ── Output persistence ──────────────────────────────────────────────────────

test.describe('Analyses – output node persistence', () => {
	test('build mode persists after save and reload', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsName = `e2e-mode-persist-ds-${uid()}`;
		const aName = `E2E Mode Persist ${uid()}`;
		const dsId = await createDatasource(request, dsName);
		const aId = await createAnalysis(request, aName, dsId);
		try {
			await gotoAnalysisEditor(page, aId);

			const modeTrigger = page.locator('[data-testid="output-mode-trigger"]');
			await expect(modeTrigger).toBeVisible({ timeout: 10_000 });

			// Select incremental mode
			await modeTrigger.click();
			const dropdown = page.locator('[data-testid="output-mode-listbox"]');
			await expect(dropdown).toBeVisible({ timeout: 3_000 });
			await dropdown.locator('[data-testid="output-mode-option-incremental"]').click();
			await expect(modeTrigger).toContainText('incremental');

			// Save the analysis
			await page.getByRole('button', { name: 'Save' }).click();
			await expect(page.getByRole('button', { name: 'Saved' })).toBeVisible({ timeout: 10_000 });

			// Reload and verify mode persisted
			await page.reload();
			await waitForEditorReload(page);

			const modeTriggerAfter = page.locator('[data-testid="output-mode-trigger"]');
			await expect(modeTriggerAfter).toBeVisible({ timeout: 10_000 });
			await expect(modeTriggerAfter).toContainText('incremental');

			await screenshot(page, 'analysis/output', 'output-mode-persisted');
		} finally {
			await shutdownEngine(request, aId);
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('table name persists after save and reload', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsName = `e2e-tablename-persist-ds-${uid()}`;
		const aName = `E2E TableName Persist ${uid()}`;
		const dsId = await createDatasource(request, dsName);
		const aId = await createAnalysis(request, aName, dsId);
		try {
			await gotoAnalysisEditor(page, aId);

			// Edit the table name
			const editBtn = page.locator('[data-testid="output-table-name-inline-edit"]');
			await expect(editBtn).toBeVisible({ timeout: 10_000 });
			await editBtn.click();

			const nameInput = page.locator('#output-node-name');
			await expect(nameInput).toBeVisible({ timeout: 3_000 });
			await nameInput.fill('persisted_table');
			await nameInput.press('Enter');

			// Verify the new name appears
			await expect(page.locator('[data-testid="output-table-name-inline"]')).toHaveText(
				'persisted_table',
				{ timeout: 3_000 }
			);

			// Save
			await page.getByRole('button', { name: 'Save' }).click();
			await expect(page.getByRole('button', { name: 'Saved' })).toBeVisible({ timeout: 10_000 });

			// Reload and verify table name persisted
			await page.reload();
			await waitForEditorReload(page);
			await expect(page.locator('[data-testid="output-table-name-inline"]')).toHaveText(
				'persisted_table',
				{ timeout: 10_000 }
			);

			await screenshot(page, 'analysis/output', 'output-tablename-persisted');
		} finally {
			await shutdownEngine(request, aId);
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});
});

// ── Row count ───────────────────────────────────────────────────────────────

test.describe('Analyses – row count action', () => {
	test('count-rows: success shows row count badge', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsName = `e2e-rowcount-ds-${uid()}`;
		const aName = `E2E Row Count ${uid()}`;
		const dsId = await createDatasource(request, dsName);
		const aId = await createAnalysis(request, aName, dsId);
		try {
			await gotoAnalysisEditor(page, aId);

			const viewNode = page.locator('[data-step-type="view"]');
			await expect(viewNode).toHaveCount(1, { timeout: 15_000 });
			const countBtn = viewNode.locator('[data-testid="step-row-count-button"]');
			await expect(countBtn).toBeEnabled({ timeout: 15_000 });

			await countBtn.click();

			await expect(viewNode.locator('[data-testid="step-row-count"]')).toBeVisible({
				timeout: 15_000
			});
			await expect(viewNode.locator('[data-testid="step-row-count"]')).toContainText('rows');

			await screenshot(page, 'analysis/output', 'row-count-success');
		} finally {
			await shutdownEngine(request, aId);
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});
});

test.describe('Analyses – row count on non-view steps', () => {
	test('count-rows works on a filter step', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsName = `e2e-rowcount-filter-ds-${uid()}`;
		const aName = `E2E Row Count Filter ${uid()}`;
		const dsId = await createDatasource(request, dsName);
		const aId = await createAnalysis(request, aName, dsId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'filter');
			const filterNode = page.locator('[data-step-type="filter"]');

			// Select column 'id' in the first condition
			const condColumnDropdown = configPanel.locator('button[aria-expanded]');
			await expect(condColumnDropdown).toHaveCount(1);
			await condColumnDropdown.click();
			await page.getByRole('option', { name: 'id', exact: true }).click();

			// Set value
			await configPanel.locator('[data-testid="filter-value-input-0"]').fill('0');

			await configPanel.getByRole('button', { name: 'Apply' }).click();
			await expect(configPanel.getByRole('button', { name: 'Apply' })).toBeDisabled({
				timeout: 5_000
			});

			// Click count-rows on the filter node
			const countBtn = filterNode.locator('[data-testid="step-row-count-button"]');
			await expect(countBtn).toBeEnabled({ timeout: 15_000 });
			await countBtn.click();

			await expect(filterNode.locator('[data-testid="step-row-count"]')).toBeVisible({
				timeout: 15_000
			});
			await expect(filterNode.locator('[data-testid="step-row-count"]')).toContainText('rows');

			await screenshot(page, 'analysis/output', 'row-count-filter-step');
		} finally {
			await shutdownEngine(request, aId);
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('count-rows works on a limit step', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsName = `e2e-rowcount-limit-ds-${uid()}`;
		const aName = `E2E Row Count Limit ${uid()}`;
		const dsId = await createDatasource(request, dsName);
		const aId = await createAnalysis(request, aName, dsId);
		try {
			await gotoAnalysisEditor(page, aId);

			await page.locator('button[data-step="limit"]').click();
			const limitNode = page.locator('[data-step-type="limit"]');
			await expect(limitNode).toHaveCount(1, { timeout: 5_000 });
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
			const countBtn = limitNode.locator('[data-testid="step-row-count-button"]');
			await expect(countBtn).toBeEnabled({ timeout: 15_000 });
			await countBtn.click();

			await expect(limitNode.locator('[data-testid="step-row-count"]')).toBeVisible({
				timeout: 15_000
			});
			await expect(limitNode.locator('[data-testid="step-row-count"]')).toContainText('rows');

			await screenshot(page, 'analysis/output', 'row-count-limit-step');
		} finally {
			await shutdownEngine(request, aId);
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});
});
