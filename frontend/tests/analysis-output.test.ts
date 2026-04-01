import { test, expect } from '@playwright/test';
import { createDatasource, createAnalysis } from './utils/api.js';
import { deleteAnalysisViaUI, deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { screenshot } from './utils/visual.js';

// ── Output visibility toggle ────────────────────────────────────────────────

test.describe('Analyses – output visibility toggle', () => {
	test('OutputNode: visibility toggle button shows initial state', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-vis-toggle-ds');
		const aId = await createAnalysis(request, 'E2E Vis Toggle', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('[data-step-type="view"]')).toBeVisible({ timeout: 15_000 });

			// Toggle button should be visible on the output node
			const toggleBtn = page.locator('[data-testid="output-visibility-toggle"]').first();
			await expect(toggleBtn).toBeVisible({ timeout: 8_000 });

			// Without a saved/built output datasource, toggle shows "hidden" (default)
			// The toggle button is present but not functional until the output datasource exists
			await expect(toggleBtn).toContainText(/hidden|visible/, { timeout: 5_000 });

			await screenshot(page, 'analysis/output', 'output-visibility-toggle');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Vis Toggle');
			await deleteDatasourceViaUI(page, 'e2e-vis-toggle-ds');
		}
	});
});

// ── Output node interactions ────────────────────────────────────────────────

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

			await screenshot(page, 'analysis/output', 'output-node-mode-dropdown');
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

			await screenshot(page, 'analysis/output', 'output-mode-recreate');
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

			// Open Health Checks section — shows health checks manager
			await healthToggle.click();
			await expect(page.getByText(/No health checks configured/i)).toBeVisible({ timeout: 5_000 });

			await screenshot(page, 'analysis/output', 'output-sections-health-open');

			// Close Health Checks
			await healthToggle.click();
			await expect(page.getByText(/No health checks configured/i)).not.toBeVisible({
				timeout: 3_000
			});
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

			await screenshot(page, 'analysis/output', 'output-table-renamed');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Output Rename');
			await deleteDatasourceViaUI(page, 'e2e-output-rename-ds');
		}
	});
});

// ── Output table name edit ──────────────────────────────────────────────────

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

			await screenshot(page, 'analysis/output', 'output-name-edited');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Output Name');
			await deleteDatasourceViaUI(page, 'e2e-output-name-ds');
		}
	});
});

// ── Output persistence ──────────────────────────────────────────────────────

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

			await screenshot(page, 'analysis/output', 'output-mode-persisted');
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

			await screenshot(page, 'analysis/output', 'output-tablename-persisted');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E TableName Persist');
			await deleteDatasourceViaUI(page, 'e2e-tablename-persist-ds');
		}
	});
});

// ── Output build flow ───────────────────────────────────────────────────────

test.describe('Analyses – output build flow', () => {
	test('build button triggers build API and completes', async ({ page, request }) => {
		test.setTimeout(90_000);
		const dsId = await createDatasource(request, 'e2e-build-flow-ds');
		const aId = await createAnalysis(request, 'E2E Build Flow', dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			const buildBtn = page.locator('[data-testid="output-build-button"]');
			await expect(buildBtn).toBeVisible({ timeout: 15_000 });

			// Mock a successful build response so the test is deterministic
			const mockBody = { analysis_id: aId, results: [{ tab: 'Source 1', status: 'ok' }] };
			await page.route('**/api/v1/compute/build', (route) => {
				if (route.request().method() === 'POST') {
					return route.fulfill({
						status: 200,
						contentType: 'application/json',
						body: JSON.stringify(mockBody)
					});
				}
				return route.continue();
			});

			await buildBtn.click();

			// Building state should appear
			await expect(page.locator('[data-testid="output-building"]')).toBeVisible({
				timeout: 5_000
			});

			// Building state should disappear after mock response resolves
			await expect(page.locator('[data-testid="output-building"]')).not.toBeVisible({
				timeout: 15_000
			});

			// No error should be visible
			await expect(page.locator('[data-testid="output-build-error"]')).not.toBeVisible();

			await screenshot(page, 'analysis/output', 'output-build-success');
		} finally {
			await page.unrouteAll({ behavior: 'ignoreErrors' });
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

			await screenshot(page, 'analysis/output', 'output-build-error');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Build Error');
			await deleteDatasourceViaUI(page, 'e2e-build-err-ds');
		}
	});
});

// ── Row count ───────────────────────────────────────────────────────────────

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

			await screenshot(page, 'analysis/output', 'row-count-success');
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

			await screenshot(page, 'analysis/output', 'row-count-error');
		} finally {
			await page.unrouteAll({ behavior: 'ignoreErrors' });
			await deleteAnalysisViaUI(page, 'E2E Row Count Err');
			await deleteDatasourceViaUI(page, 'e2e-rowcount-err-ds');
		}
	});
});

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

			// Configure the filter with a valid condition before applying
			await filterNode.locator('[data-action="edit"]').click();
			const configPanel = page.locator('[data-step-config="filter"]');
			await expect(configPanel).toBeVisible({ timeout: 8_000 });

			// Select column 'id' in the first condition
			const condColumnDropdown = configPanel.locator('button[aria-expanded]').first();
			await condColumnDropdown.click();
			await page.getByRole('option', { name: 'id' }).first().click();

			// Set value
			await configPanel.locator('[data-testid="filter-value-input-0"]').fill('0');

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

			await screenshot(page, 'analysis/output', 'row-count-filter-step');
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

			await screenshot(page, 'analysis/output', 'row-count-limit-step');
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

			await screenshot(page, 'analysis/output', 'row-count-sort-error');
		} finally {
			await page.unrouteAll({ behavior: 'ignoreErrors' });
			await deleteAnalysisViaUI(page, 'E2E Row Count Sort Err');
			await deleteDatasourceViaUI(page, 'e2e-rowcount-sort-err-ds');
		}
	});
});
