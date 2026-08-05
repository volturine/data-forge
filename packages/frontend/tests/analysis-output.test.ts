import type { Locator, Page } from '@playwright/test';

import { test, expect } from './fixtures.js';
import { createDatasource, createAnalysis, deleteAnalysisByApi } from './utils/api.js';
import { createCleanupPage, deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { addStepAndOpenConfig, gotoAnalysisEditor, waitForEditorReload } from './utils/analysis.js';
import { uid } from './utils/uid.js';
import { screenshot } from './utils/visual.js';

let sharedDatasourceId = '';
let sharedDatasourceName = '';

test.beforeAll(async ({ request }) => {
	sharedDatasourceName = `e2e-output-shared-ds-${uid()}`;
	sharedDatasourceId = await createDatasource(request, sharedDatasourceName);
});

test.afterAll(async ({ browser, workerAuth }) => {
	const { page, context } = await createCleanupPage(
		browser,
		workerAuth.workerIndex,
		workerAuth.sessionState
	);
	await deleteDatasourceViaUI(page, sharedDatasourceName);
	await page.close();
	await context.close();
});

// ── Output visibility toggle ────────────────────────────────────────────────

async function expectCompletedEventually(locator: Locator) {
	let lastError: unknown;
	for (let attempt = 0; attempt < 3; attempt += 1) {
		try {
			await expect(locator).toContainText(/Completed/i, { timeout: 5_000 });
			return;
		} catch (error) {
			lastError = error;
		}
	}
	throw lastError;
}

async function deleteBestEffort(
	page: Page,
	endpoint: string,
	expectedStatuses: Set<number>
): Promise<void> {
	const response = await page.request.delete(endpoint, { timeout: 5_000 }).catch(() => null);
	if (!response || expectedStatuses.has(response.status())) return;
	throw new Error(`Cleanup DELETE ${endpoint} returned HTTP ${response.status()}`);
}

async function cleanupAnalysis(page: Page, analysisId: string): Promise<void> {
	await deleteBestEffort(
		page,
		`/api/v1/compute/engine/analysis/${analysisId}`,
		new Set([204, 404, 409])
	);
	const analysisDeleteStatus = await deleteAnalysisByApi(page, analysisId);
	if (![204, 404].includes(analysisDeleteStatus)) {
		throw new Error(
			`Cleanup DELETE /api/v1/analysis/${analysisId} returned HTTP ${analysisDeleteStatus}`
		);
	}
}

test.describe('Analyses – output visibility toggle', () => {
	test('OutputNode: unbuilt output does not GET reserved result_id', async ({ page, request }) => {
		const aName = `E2E Unbuilt Output ${uid()}`;
		const aId = await createAnalysis(request, aName, sharedDatasourceId);
		const probedIds = new Set<string>();
		page.on('request', (req) => {
			const match = req.url().match(/\/api\/v1\/datasource\/([0-9a-f-]{36})(?:\?|$)/i);
			if (match && req.method() === 'GET') {
				probedIds.add(match[1]);
			}
		});
		try {
			const analysisResp = await page.request.get(`/api/v1/analysis/${aId}`);
			expect(analysisResp.ok()).toBeTruthy();
			const analysisBody = await analysisResp.json();
			const resultId = analysisBody.pipeline_definition?.tabs?.[0]?.output?.result_id as string;
			expect(resultId).toMatch(
				/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
			);
			// No materialization flag on the analysis contract.
			expect(analysisBody.pipeline_definition.tabs[0].output).not.toHaveProperty('materialized');

			await gotoAnalysisEditor(page, aId);
			await expect(page.locator('[data-testid="output-visibility-toggle"]')).toBeVisible({
				timeout: 5_000
			});
			// Explicit unbuilt UI for health checks.
			await page.locator('[data-testid="output-health-toggle"]').click();
			await expect(page.locator('[data-testid="output-health-empty-state"]')).toContainText(
				/Build this output once to create its datasource/i,
				{ timeout: 5_000 }
			);
			// Settle network so a late probe would still be observed.
			await page.waitForLoadState('networkidle').catch(() => undefined);
			await page.waitForTimeout(500);
			// Reserved result_id must not be fetched before first build (list-membership gate).
			expect(probedIds.has(resultId)).toBe(false);
		} finally {
			await cleanupAnalysis(page, aId);
		}
	});

	test('OutputNode: successful build creates output datasource and allows GET', async ({
		page,
		request
	}) => {
		const aName = `E2E Build Creates Output ${uid()}`;
		const aId = await createAnalysis(request, aName, sharedDatasourceId);
		const probedIds = new Set<string>();
		page.on('request', (req) => {
			const match = req.url().match(/\/api\/v1\/datasource\/([0-9a-f-]{36})(?:\?|$)/i);
			if (match && req.method() === 'GET') {
				probedIds.add(match[1]);
			}
		});
		try {
			const before = await page.request.get(`/api/v1/analysis/${aId}`);
			expect(before.ok()).toBeTruthy();
			const beforeBody = await before.json();
			const resultId = beforeBody.pipeline_definition?.tabs?.[0]?.output?.result_id as string;
			expect(beforeBody.pipeline_definition.tabs[0].output).not.toHaveProperty('materialized');

			await gotoAnalysisEditor(page, aId);
			// No probe of the reserved output before build.
			await expect(page.locator('[data-testid="output-visibility-toggle"]')).toBeVisible({
				timeout: 5_000
			});
			expect(probedIds.has(resultId)).toBe(false);

			const buildBtn = page.locator('[data-testid="output-build-button"]');
			await expect(buildBtn).toBeVisible({ timeout: 5_000 });
			await buildBtn.click({ timeout: 5_000 });
			const buildTrigger = page.locator('[data-testid="output-build-preview-trigger"]');
			await expect(buildTrigger).toBeVisible({ timeout: 5_000 });
			await expectCompletedEventually(buildTrigger);

			// Wait until the reserved output exists as a real datasource.
			await expect
				.poll(
					async () => {
						const ds = await page.request.get(`/api/v1/datasource/${resultId}`);
						return ds.status();
					},
					{ timeout: 15_000 }
				)
				.toBe(200);

			// After the row exists, list membership enables GET of the output datasource.
			await expect.poll(() => probedIds.has(resultId), { timeout: 15_000 }).toBe(true);
		} finally {
			await cleanupAnalysis(page, aId);
		}
	});

	test('OutputNode: visibility toggle button shows initial state', async ({ page, request }) => {
		const aName = `E2E Vis Toggle ${uid()}`;
		const aId = await createAnalysis(request, aName, sharedDatasourceId);
		try {
			await gotoAnalysisEditor(page, aId);

			// Toggle button should be visible on the output node
			const toggleBtn = page.locator('[data-testid="output-visibility-toggle"]');
			await expect(toggleBtn).toBeVisible({ timeout: 5_000 });

			// Without a saved/built output datasource, toggle shows "hidden" (default)
			// The toggle button is present but not functional until the output datasource exists
			await expect(toggleBtn).toContainText('hidden', { timeout: 5_000 });

			await screenshot(page, 'analysis/output', 'output-visibility-toggle');
		} finally {
			await cleanupAnalysis(page, aId);
		}
	});

	test('OutputNode: visibility toggle updates after the output datasource exists', async ({
		page,
		request
	}) => {
		const aName = `E2E Vis Build ${uid()}`;
		const aId = await createAnalysis(request, aName, sharedDatasourceId);
		try {
			await gotoAnalysisEditor(page, aId);

			const buildBtn = page.locator('[data-testid="output-build-button"]');
			await expect(buildBtn).toBeVisible({ timeout: 5_000 });
			await buildBtn.click();
			const buildTrigger = page.locator('[data-testid="output-build-preview-trigger"]');
			await expect(buildTrigger).toBeVisible({ timeout: 5_000 });
			await expectCompletedEventually(buildTrigger);

			const toggleBtn = page.locator('[data-testid="output-visibility-toggle"]');
			await expect(toggleBtn).toBeEnabled({ timeout: 5_000 });
			await expect(toggleBtn).toContainText('hidden');

			await toggleBtn.click();
			await expect(toggleBtn).toContainText('visible', { timeout: 5_000 });

			await toggleBtn.click();
			await expect(toggleBtn).toContainText('hidden', { timeout: 5_000 });
		} finally {
			await cleanupAnalysis(page, aId);
		}
	});

	test('OutputNode: rebuilding recreates a deleted output datasource', async ({
		page,
		request
	}) => {
		const aName = `E2E Output Rebuild ${uid()}`;
		const aId = await createAnalysis(request, aName, sharedDatasourceId);
		try {
			await gotoAnalysisEditor(page, aId);
			const outputName = (
				await page.locator('[data-testid="output-table-name-card"]').textContent()
			)?.trim();
			expect(outputName).toBeTruthy();
			const outputId = await page
				.locator('[data-testid="output-visibility-toggle"]')
				.getAttribute('data-output-datasource-id');
			expect(outputId).toBeTruthy();

			const buildBtn = page.locator('[data-testid="output-build-button"]');
			await expect(buildBtn).toBeVisible({ timeout: 5_000 });
			await buildBtn.click();
			const initialBuildTrigger = page.locator('[data-testid="output-build-preview-trigger"]');
			await expect(initialBuildTrigger).toBeVisible({ timeout: 5_000 });
			await expectCompletedEventually(initialBuildTrigger);

			await deleteDatasourceViaUI(page, outputName!, { id: outputId! });
			await gotoAnalysisEditor(page, aId);

			const rebuiltBuildBtn = page.locator('[data-testid="output-build-button"]');
			await expect(rebuiltBuildBtn).toBeVisible({ timeout: 5_000 });
			await rebuiltBuildBtn.click();
			const rebuiltBuildTrigger = page.locator('[data-testid="output-build-preview-trigger"]');
			await expect(rebuiltBuildTrigger).toBeVisible({ timeout: 5_000 });
			await expectCompletedEventually(rebuiltBuildTrigger);

			const rebuiltToggleBtn = page.locator('[data-testid="output-visibility-toggle"]');
			await expect(rebuiltToggleBtn).toBeEnabled({ timeout: 5_000 });
			await rebuiltToggleBtn.click();
			await expect(rebuiltToggleBtn).toContainText('visible', { timeout: 5_000 });
			await rebuiltToggleBtn.click();
			await expect(rebuiltToggleBtn).toContainText('hidden', { timeout: 5_000 });
		} finally {
			await cleanupAnalysis(page, aId);
		}
	});
});

// ── Output node interactions ────────────────────────────────────────────────

test.describe('Analyses – output node interactions', () => {
	test('output node build button and mode selector are visible', async ({ page, request }) => {
		const aName = `E2E Output Node ${uid()}`;
		const aId = await createAnalysis(request, aName, sharedDatasourceId);
		try {
			await gotoAnalysisEditor(page, aId);

			// Build button should be visible
			const buildBtn = page.locator('[data-testid="output-build-button"]');
			await expect(buildBtn).toBeVisible({ timeout: 5_000 });

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
			await cleanupAnalysis(page, aId);
		}
	});

	test('selecting a mode updates the trigger text', async ({ page, request }) => {
		const aName = `E2E Output Mode ${uid()}`;
		const aId = await createAnalysis(request, aName, sharedDatasourceId);
		try {
			await gotoAnalysisEditor(page, aId);

			const buildBtn = page.locator('[data-testid="output-build-button"]');
			await expect(buildBtn).toBeVisible({ timeout: 5_000 });

			const modeTrigger = page.locator('[data-testid="output-mode-trigger"]');
			await expect(modeTrigger).toBeVisible({ timeout: 5_000 });

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
			await cleanupAnalysis(page, aId);
		}
	});

	test('collapsible sections toggle open and closed', async ({ page, request }) => {
		const aName = `E2E Output Sections ${uid()}`;
		const aId = await createAnalysis(request, aName, sharedDatasourceId);
		try {
			await gotoAnalysisEditor(page, aId);

			// All section toggles should be visible
			const notifyToggle = page.locator('[data-testid="output-notify-toggle"]');
			const healthToggle = page.locator('[data-testid="output-health-toggle"]');
			const scheduleToggle = page.locator('[data-testid="output-schedule-toggle"]');

			await expect(notifyToggle).toBeVisible({ timeout: 5_000 });
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

			// Open Health Checks section — prompts to build first when output datasource row is missing
			await healthToggle.click();
			await expect(healthEmptyState).toContainText(
				'Build this output once to create its datasource before adding health checks.',
				{
					timeout: 5_000
				}
			);

			await screenshot(page, 'analysis/output', 'output-sections-health-open');

			// Close Health Checks
			await healthToggle.click();
			await expect(healthEmptyState).not.toBeVisible({ timeout: 3_000 });
		} finally {
			await cleanupAnalysis(page, aId);
		}
	});

	test('notification toggle enable and disable updates chip', async ({ page, request }) => {
		const aName = `E2E Notify Toggle ${uid()}`;
		const aId = await createAnalysis(request, aName, sharedDatasourceId);
		try {
			await gotoAnalysisEditor(page, aId);

			// Expand notification section
			const notifyToggle = page.locator('[data-testid="output-notify-toggle"]');
			await expect(notifyToggle).toBeVisible({ timeout: 5_000 });
			await notifyToggle.click();

			const notifyPanel = page.locator('[data-testid="output-notify-panel"]');
			await expect(notifyPanel).toBeVisible({ timeout: 3_000 });

			// Check the "Notify subscribers on build" checkbox
			const checkbox = notifyPanel.locator('input[name="notify_enabled"]');
			await checkbox.check();

			// Chip showing subscriber count should appear in the toggle button
			await expect(notifyToggle).toContainText('/');

			// Uncheck
			await checkbox.uncheck();

			// Chip should disappear
			await expect(notifyToggle).not.toContainText('/', { timeout: 3_000 });
		} finally {
			await cleanupAnalysis(page, aId);
		}
	});

	test('schedule section toggle opens and shows empty state', async ({ page, request }) => {
		const aName = `E2E Schedule Toggle ${uid()}`;
		const aId = await createAnalysis(request, aName, sharedDatasourceId);
		try {
			await gotoAnalysisEditor(page, aId);

			const scheduleToggle = page.locator('[data-testid="output-schedule-toggle"]');
			await expect(scheduleToggle).toBeVisible({ timeout: 5_000 });

			// Schedule section should start collapsed
			await expect(
				page.getByText(/Save this analysis to create an output datasource/i)
			).not.toBeVisible();

			// Open schedule section
			await scheduleToggle.click();
			await expect(
				page.getByText(/Build this output once to create its datasource before adding schedules/i)
			).toBeVisible({
				timeout: 5_000
			});

			// Close it
			await scheduleToggle.click();
			await expect(
				page.getByText(/Build this output once to create its datasource before adding schedules/i)
			).not.toBeVisible({
				timeout: 3_000
			});
		} finally {
			await cleanupAnalysis(page, aId);
		}
	});

	test('table name inline edit', async ({ page, request }) => {
		const aName = `E2E Output Rename ${uid()}`;
		const aId = await createAnalysis(request, aName, sharedDatasourceId);
		try {
			await gotoAnalysisEditor(page, aId);

			// Click the edit pencil button (aria-label="Edit export name")
			const editBtn = page.locator('[data-testid="output-table-name-inline-edit"]');
			await expect(editBtn).toBeVisible({ timeout: 5_000 });
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
			await cleanupAnalysis(page, aId);
		}
	});
});

// ── Output table name edit ──────────────────────────────────────────────────

test.describe('Analyses – output node table name edit', () => {
	test('OutputNode: edit table name, save, verify updated', async ({ page, request }) => {
		const aName = `E2E Output Name ${uid()}`;
		const aId = await createAnalysis(request, aName, sharedDatasourceId);
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
			await cleanupAnalysis(page, aId);
		}
	});
});

// ── Output persistence ──────────────────────────────────────────────────────

test.describe('Analyses – output node persistence', () => {
	test('build mode persists after save and reload', async ({ page, request }) => {
		const aName = `E2E Mode Persist ${uid()}`;
		const aId = await createAnalysis(request, aName, sharedDatasourceId);
		try {
			await gotoAnalysisEditor(page, aId);

			const modeTrigger = page.locator('[data-testid="output-mode-trigger"]');
			await expect(modeTrigger).toBeVisible({ timeout: 5_000 });

			// Select incremental mode
			await modeTrigger.click();
			const dropdown = page.locator('[data-testid="output-mode-listbox"]');
			await expect(dropdown).toBeVisible({ timeout: 3_000 });
			await dropdown.locator('[data-testid="output-mode-option-incremental"]').click();
			await expect(modeTrigger).toContainText('incremental');

			// Save the analysis
			await page.getByRole('button', { name: 'Save' }).click();
			await expect(page.getByRole('button', { name: 'Saved' })).toBeVisible({ timeout: 5_000 });

			// Verify mode is still correct immediately after save (before reload)
			await expect(modeTrigger).toContainText('incremental');

			// Reload and verify mode persisted
			await page.reload();
			await waitForEditorReload(page);

			const modeTriggerAfter = page.locator('[data-testid="output-mode-trigger"]');
			await expect(modeTriggerAfter).toBeVisible({ timeout: 5_000 });
			await expect(modeTriggerAfter).toContainText('incremental');

			await screenshot(page, 'analysis/output', 'output-mode-persisted');
		} finally {
			await cleanupAnalysis(page, aId);
		}
	});

	test('table name persists after save and reload', async ({ page, request }) => {
		const aName = `E2E TableName Persist ${uid()}`;
		const aId = await createAnalysis(request, aName, sharedDatasourceId);
		try {
			await gotoAnalysisEditor(page, aId);

			// Edit the table name
			const editBtn = page.locator('[data-testid="output-table-name-inline-edit"]');
			await expect(editBtn).toBeVisible({ timeout: 5_000 });
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
			await expect(page.getByRole('button', { name: 'Saved' })).toBeVisible({ timeout: 5_000 });

			// Verify table name is still correct immediately after save (before reload)
			await expect(page.locator('[data-testid="output-table-name-inline"]')).toHaveText(
				'persisted_table',
				{ timeout: 3_000 }
			);

			// Reload and verify table name persisted
			await page.reload();
			await waitForEditorReload(page);
			await expect(page.locator('[data-testid="output-table-name-inline"]')).toHaveText(
				'persisted_table',
				{ timeout: 5_000 }
			);

			await screenshot(page, 'analysis/output', 'output-tablename-persisted');
		} finally {
			await cleanupAnalysis(page, aId);
		}
	});
});

// ── Row count ───────────────────────────────────────────────────────────────

test.describe('Analyses – row count action', () => {
	test('count-rows: success shows row count badge', async ({ page, request }) => {
		const aName = `E2E Row Count ${uid()}`;
		const aId = await createAnalysis(request, aName, sharedDatasourceId);
		try {
			await gotoAnalysisEditor(page, aId);

			const viewNode = page.locator('[data-step-type="view"]');
			await expect(viewNode).toHaveCount(1, { timeout: 5_000 });
			const countBtn = viewNode.locator('[data-testid="step-row-count-button"]');
			await expect(countBtn).toBeEnabled({ timeout: 15_000 });

			await countBtn.click();

			const badge = viewNode.locator('[data-testid="step-row-count"]');
			const error = viewNode.locator('[data-testid="step-row-count-error"]');
			await expect
				.poll(
					async () => {
						if (await badge.isVisible().catch(() => false)) return 'ok';
						if (await error.isVisible().catch(() => false)) {
							return `error:${(await error.textContent()) ?? ''}`;
						}
						return 'pending';
					},
					{ timeout: 15_000 }
				)
				.toBe('ok');
			await expect(badge).toContainText('rows');

			await screenshot(page, 'analysis/output', 'row-count-success');
		} finally {
			await cleanupAnalysis(page, aId);
		}
	});
});

test.describe('Analyses – row count on non-view steps', () => {
	test('count-rows works on a filter step', async ({ page, request }) => {
		const aName = `E2E Row Count Filter ${uid()}`;
		const aId = await createAnalysis(request, aName, sharedDatasourceId);
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

			const badge = filterNode.locator('[data-testid="step-row-count"]');
			const error = filterNode.locator('[data-testid="step-row-count-error"]');
			await expect
				.poll(
					async () => {
						if (await badge.isVisible().catch(() => false)) return 'ok';
						if (await error.isVisible().catch(() => false)) {
							return `error:${(await error.textContent()) ?? ''}`;
						}
						return 'pending';
					},
					{ timeout: 15_000 }
				)
				.toBe('ok');
			await expect(badge).toContainText('rows');

			await screenshot(page, 'analysis/output', 'row-count-filter-step');
		} finally {
			await cleanupAnalysis(page, aId);
		}
	});

	test('count-rows works on a limit step', async ({ page, request }) => {
		const aName = `E2E Row Count Limit ${uid()}`;
		const aId = await createAnalysis(request, aName, sharedDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'limit');
			const limitNode = page.locator('[data-step-type="limit"]');
			await expect(limitNode).toHaveCount(1, { timeout: 5_000 });
			await expect(limitNode).toBeVisible({ timeout: 5_000 });

			// Apply the step
			await expect(configPanel).toBeVisible({ timeout: 5_000 });
			await configPanel.locator('[data-testid="limit-rows-input"]').fill('2');
			await configPanel.getByRole('button', { name: 'Apply' }).click();
			await expect(configPanel.getByRole('button', { name: 'Apply' })).toBeDisabled({
				timeout: 5_000
			});

			// Click count-rows on the limit node
			const countBtn = limitNode.locator('[data-testid="step-row-count-button"]');
			await expect(countBtn).toBeEnabled({ timeout: 15_000 });
			await countBtn.click();

			const badge = limitNode.locator('[data-testid="step-row-count"]');
			const error = limitNode.locator('[data-testid="step-row-count-error"]');
			await expect
				.poll(
					async () => {
						if (await badge.isVisible().catch(() => false)) return 'ok';
						if (await error.isVisible().catch(() => false)) {
							return `error:${(await error.textContent()) ?? ''}`;
						}
						return 'pending';
					},
					{ timeout: 15_000 }
				)
				.toBe('ok');
			await expect(badge).toContainText('rows');

			await screenshot(page, 'analysis/output', 'row-count-limit-step');
		} finally {
			await cleanupAnalysis(page, aId);
		}
	});
});
