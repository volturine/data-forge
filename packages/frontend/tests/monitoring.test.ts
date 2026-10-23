import { test, expect } from './fixtures.js';
import type { Locator, Page } from '@playwright/test';
import { createSchedule, createHealthCheck, createMultiStepAnalysis } from './utils/api.js';
import {
	deleteScheduleById,
	deleteHealthCheckById,
	deleteAnalysisViaUI,
	freeWarmComputeWorkers
} from './utils/ui-cleanup.js';
import {
	buildTimeoutMs,
	gotoMonitoringTab,
	readyTimeoutMs,
	waitForDatasourcePreviewReady,
	waitForLayoutReady
} from './utils/readiness.js';
import { uid } from './utils/uid.js';
import { screenshot } from './utils/visual.js';
import { dialogByHeading } from './utils/locators.js';
import {
	gotoMonitoringBuilds,
	startBuildFromAnalysisPage,
	waitForBuildPreview,
	waitForBuildRow,
	waitForBuildRowById
} from './utils/builds.js';

async function waitForHealthChecksList(page: import('@playwright/test').Page, timeout = 5_000) {
	const panel = page.locator('#panel-health');
	await expect(panel).toBeVisible({ timeout });
	const terminal = panel.locator(
		'[data-healthcheck-row], :text("No health checks configured."), :text("No health checks match your search."), :text("Failed to load health checks.")'
	);
	await expect(terminal.filter({ visible: true }).first()).toBeVisible({ timeout });
	return panel;
}

async function waitForHealthCheckRow(
	page: import('@playwright/test').Page,
	name: string,
	timeout = 5_000
) {
	const panel = await waitForHealthChecksList(page, timeout);
	await expect(page.getByRole('button', { name: /New Check/i })).toBeVisible({ timeout });
	const row = panel.locator(`[data-healthcheck-name="${name}"]`);
	await expect(row).toBeVisible({ timeout });
	return row;
}

async function waitForSelectOption(
	select: import('@playwright/test').Locator,
	value: string,
	timeout = 5_000
) {
	await expect(select.locator(`option[value="${value}"]`).first()).toBeAttached({ timeout });
}

async function waitForBuildCompletionOrExplainFailure(
	page: import('@playwright/test').Page,
	buildId: string,
	timeout: number
): Promise<void> {
	const preview = await waitForBuildPreview(page, timeout);
	await expect(preview.locator('[data-testid="build-preview-id"]')).toHaveText(buildId);
	let terminalStatus: 'completed' | 'failed' | null = null;
	await expect
		.poll(
			async () => {
				if (
					await preview
						.getByText('Build failed', { exact: true })
						.isVisible()
						.catch(() => false)
				) {
					terminalStatus = 'failed';
					return true;
				}
				if (
					await preview
						.getByText(/Finished in/)
						.isVisible()
						.catch(() => false)
				) {
					terminalStatus = 'completed';
					return true;
				}
				return false;
			},
			{ timeout, intervals: [250, 500, 1_000] }
		)
		.toBe(true);

	if (terminalStatus === 'failed') {
		await preview.getByRole('tab', { name: /Logs/ }).click();
		const logs = await preview
			.locator('[data-testid="build-logs-panel"]')
			.innerText()
			.catch(() => 'Build logs unavailable');
		throw new Error(`Build ${buildId} failed:\n${logs}`);
	}
}

async function waitForDatasourceBuildRow(
	page: Page,
	panel: Locator,
	datasourceId: string,
	timeout = 15_000
) {
	// The shared immutable datasource intentionally accumulates preview runs.
	// Select the semantic kind before looking for an onboarding/build row so
	// unrelated preview history cannot displace the row from the 50-item page.
	await page.locator('#builds-kind-filter').selectOption('build');
	const row = panel
		.locator(`[data-build-kind="build"][data-build-datasource-id="${datasourceId}"]`)
		.first();
	return waitForBuildRow(panel, row, `datasource row ${datasourceId}`, timeout);
}

async function waitForDatasourcePreviewRow(panel: Locator, datasourceId: string, timeout = 15_000) {
	const row = panel
		.locator(`[data-build-kind="preview"][data-build-datasource-id="${datasourceId}"]`)
		.first();
	return waitForBuildRow(panel, row, `preview row ${datasourceId}`, timeout);
}

/**
 * Opens the Builds tab filtered by the datasource name, which keeps the row inside the
 * 50-item page when many parallel workers create builds. Returns the datasource's build
 * row and the locator of its expanded detail panel.
 */
async function openSharedDatasourceBuildRow(
	page: Page,
	datasourceName: string,
	datasourceId: string,
	timeout: number
) {
	await gotoMonitoringTab(page, 'builds');
	const panel = page.locator('#panel-builds');
	await page.getByLabel(/Search builds/i).fill(datasourceName);
	const buildRow = await waitForDatasourceBuildRow(page, panel, datasourceId, timeout);
	const buildRowId = await buildRow.getAttribute('data-build-row');
	if (!buildRowId) throw new Error('Expected build row id');
	return { buildRow, detailRow: panel.locator(`[data-build-detail="${buildRowId}"]`) };
}

/** E2E tests for the monitoring page: builds, schedules and health checks. */
test.describe('Monitoring – page structure', () => {
	test.beforeEach(async ({ page }) => {
		await page.goto('/monitoring');
		await waitForLayoutReady(page);
		await expect(page.getByRole('heading', { name: 'Monitoring' })).toBeVisible();
		await expect(page.getByRole('tab', { name: 'Builds' })).toBeVisible();
		await expect(page.getByRole('tab', { name: 'Builds' })).toHaveAttribute(
			'aria-selected',
			'true'
		);
	});

	// The beforeEach hook already asserts that the Builds tab is selected by default.
	// gotoMonitoringTab asserts the selected tab and its panel for each tab visit below.
	test('renders the page structure, tab switching, and each tab section', async ({ page }) => {
		await test.step('renders Monitoring heading and description', async () => {
			await expect(page.getByRole('heading', { name: 'Monitoring' })).toBeVisible();
			await expect(page.getByText(/Review builds, schedules, and health checks/i)).toBeVisible();
		});

		await test.step('shows all three tabs: Builds, Schedules, Health Checks', async () => {
			await expect(page.getByRole('tab', { name: 'Builds' })).toBeVisible();
			await expect(page.getByRole('tab', { name: 'Schedules' })).toBeVisible();
			await expect(page.getByRole('tab', { name: 'Health Checks' })).toBeVisible();
			await screenshot(page, 'monitoring', 'tabs-overview');
		});

		await test.step('can switch between all tabs without error', async () => {
			const tabMap = [
				{ label: 'Schedules', key: 'schedules' },
				{ label: 'Health Checks', key: 'health' },
				{ label: 'Builds', key: 'builds' }
			] as const;
			for (const { label, key } of tabMap) {
				await page.getByRole('tab', { name: label }).click();
				await expect(page.getByRole('tab', { name: label })).toHaveAttribute(
					'aria-selected',
					'true'
				);
				if (key === 'builds') {
					await expect(page).toHaveURL(/\/monitoring/);
				} else {
					await expect(page).toHaveURL(new RegExp(`tab=${key}`));
				}
			}
		});

		await test.step('each tab has its own search input', async () => {
			await gotoMonitoringTab(page, 'builds');
			await expect(page.getByLabel(/Search builds/i)).toBeVisible();

			await gotoMonitoringTab(page, 'schedules');
			await expect(page.getByLabel(/Search schedules/i)).toBeVisible();

			await gotoMonitoringTab(page, 'health');
			await expect(page.getByLabel(/Search health checks/i)).toBeVisible();
		});

		await test.step('Schedules tab shows schedule list or empty state', async () => {
			await gotoMonitoringTab(page, 'schedules');
			await screenshot(page, 'monitoring', 'schedules-tab');
		});

		await test.step('Health Checks tab renders without error', async () => {
			await gotoMonitoringTab(page, 'health');
			await waitForHealthChecksList(page);
			await expect(page.getByRole('heading', { name: 'Monitoring' })).toBeVisible();
			await screenshot(page, 'monitoring', 'health-checks-tab');
		});

		await test.step('Builds tab renders and shows builds panel', async () => {
			await gotoMonitoringTab(page, 'builds');
		});
	});
});

test.describe('Monitoring – Schedules tab', () => {
	test('created schedule appears in the Schedules tab', async ({
		page,
		request,
		sharedDatasource
	}) => {
		const dsId = sharedDatasource.id;
		const scheduleId = await createSchedule(request, dsId, '0 6 * * *');
		try {
			await gotoMonitoringTab(page, 'schedules');
			const schedRow = page.locator(`[data-schedule-row="${scheduleId}"]`);
			await expect(schedRow).toBeVisible({ timeout: 5_000 });
			await expect(schedRow).toContainText('Cron: 0 6 * * *', { timeout: 5_000 });
		} finally {
			await deleteScheduleById(page, scheduleId);
		}
	});

	test('schedules search filters by datasource name', async ({
		page,
		request,
		sharedDatasource
	}) => {
		const ds = sharedDatasource.name;
		const dsId = sharedDatasource.id;
		const scheduleId = await createSchedule(request, dsId, '0 9 * * *');
		try {
			await gotoMonitoringTab(page, 'schedules');
			const schedRow = page.locator(`[data-schedule-row="${scheduleId}"]`);
			await expect(schedRow).toBeVisible({ timeout: 5_000 });

			// Search for the datasource name should show the schedule
			await page.getByLabel(/Search schedules/i).fill(ds);
			await expect(schedRow).toBeVisible({ timeout: 5_000 });

			// Search for non-matching term should show empty state
			await page.getByLabel(/Search schedules/i).fill('ZZZNOMATCH');
			await expect(page.getByText('No schedules match your search.')).toBeVisible({
				timeout: 5_000
			});
		} finally {
			await deleteScheduleById(page, scheduleId);
		}
	});

	test('schedule can be deleted via UI', async ({ page, request, sharedDatasource }) => {
		const dsId = sharedDatasource.id;
		const scheduleId = await createSchedule(request, dsId, '0 7 * * *');

		try {
			await gotoMonitoringTab(page, 'schedules');

			const schedRow = page.locator(`[data-schedule-row="${scheduleId}"]`);
			const deleteBtn = schedRow.getByLabel('Delete schedule');
			await expect(deleteBtn).toBeAttached({ timeout: 5_000 });

			// Delete button is always visible in the table row
			await deleteBtn.click({ timeout: 5_000 });

			// Confirm in the dialog
			const dialog = dialogByHeading(page, /Delete Schedule/i);
			await expect(dialog).toBeVisible();
			await dialog.getByRole('button', { name: /^Delete$/ }).click();

			await expect(schedRow).toHaveCount(0, { timeout: 5_000 });
		} finally {
			await deleteScheduleById(page, scheduleId);
		}
	});

	test('schedule enable/disable toggle works', async ({ page, request, sharedDatasource }) => {
		const dsId = sharedDatasource.id;
		const scheduleId = await createSchedule(request, dsId, '0 8 * * *');
		try {
			await gotoMonitoringTab(page, 'schedules');
			const schedRow = page.locator(`[data-schedule-row="${scheduleId}"]`);
			await expect(schedRow).toBeVisible({ timeout: 5_000 });

			const toggleBtn = schedRow.locator('button[title="Click to disable"]');
			await expect(toggleBtn).toBeAttached({ timeout: 5_000 });
			await toggleBtn.click({ timeout: 5_000 });

			// After toggle, the button title should change to "Click to enable"
			await expect(schedRow.locator('button[title="Click to enable"]')).toBeAttached({
				timeout: 5_000
			});
		} finally {
			await deleteScheduleById(page, scheduleId);
		}
	});
});

test.describe('Monitoring – Schedule create flow', () => {
	test('create schedule via UI form', async ({ page, sharedDatasource }) => {
		const dsId = sharedDatasource.id;
		let scheduleId: string | undefined;
		try {
			await gotoMonitoringTab(page, 'schedules');

			await test.step('schedule create form Cancel closes form without creating', async () => {
				await expect(page.getByRole('button', { name: /New Schedule/i })).toBeVisible({
					timeout: 5_000
				});
				await page.getByRole('button', { name: /New Schedule/i }).click({ timeout: 5_000 });
				await expect(page.locator('#schedule-datasource')).toBeVisible({ timeout: 5_000 });

				// Click Cancel
				await page.getByRole('button', { name: 'Cancel' }).click();

				// Form should be gone — the datasource dropdown should not be visible
				await expect(page.locator('#schedule-datasource')).not.toBeVisible({ timeout: 5_000 });
			});

			// Reopen the form that Cancel just closed
			await page.getByRole('button', { name: /New Schedule/i }).click();

			// Select datasource from dropdown
			const dsSelect = page.locator('#schedule-datasource');
			await expect(dsSelect).toBeVisible({ timeout: 5_000 });
			await waitForSelectOption(dsSelect, dsId, 5_000);
			await dsSelect.selectOption(dsId);

			// Cron is the default trigger type with default value — submit
			const createBtn = page.getByRole('button', { name: 'Create Schedule' });
			await expect(createBtn).toBeEnabled({ timeout: 5_000 });
			const createResponse = page.waitForResponse(
				(response) =>
					response.url().includes('/api/v1/schedules') &&
					response.request().method() === 'POST' &&
					response.ok()
			);
			await createBtn.click();
			scheduleId = ((await (await createResponse).json()) as { id: string }).id;

			// Datasource name resolution can lag the row render, but datasource_id is stable immediately.
			const schedRow = page.locator(`[data-schedule-row="${scheduleId}"]`);
			await expect(schedRow).toBeVisible({ timeout: 5_000 });
			await expect(schedRow).toContainText('Every hour', { timeout: 5_000 });
		} finally {
			if (scheduleId) await deleteScheduleById(page, scheduleId);
		}
	});
});

test.describe('Monitoring – Schedule inline cron edit', () => {
	test('inline cron edit: pencil → input → Enter saves new expression', async ({
		page,
		request,
		sharedDatasource
	}) => {
		const dsId = sharedDatasource.id;
		const scheduleId = await createSchedule(request, dsId, '0 6 * * *');
		try {
			await gotoMonitoringTab(page, 'schedules');

			// Expand the schedule row by clicking on it (table view uses <tr>)
			const schedRow = page.locator(`[data-schedule-row="${scheduleId}"]`);
			await expect(schedRow).toBeVisible({ timeout: 5_000 });
			await schedRow.click();

			const detailRow = page.locator(`[data-schedule-detail="${scheduleId}"]`);
			await expect(detailRow.locator('code')).toBeVisible({ timeout: 5_000 });

			// Click the pencil/edit button scoped to the expanded row
			const editBtn = detailRow.locator('button[title="Edit cron expression"]');
			await expect(editBtn).toBeVisible({ timeout: 5_000 });
			await editBtn.click();

			// Cron input should appear
			const cronInput = detailRow.locator('input[aria-label="Cron expression"]');
			await expect(cronInput).toBeVisible({ timeout: 3_000 });

			// Clear and type new expression, then press Enter
			await cronInput.fill('30 12 * * 1');
			const saveResponse = page.waitForResponse(
				(response) =>
					response.url().includes(`/v1/schedules/${scheduleId}`) &&
					response.request().method() === 'PUT'
			);
			await cronInput.press('Enter');
			await expect((await saveResponse).ok()).toBe(true);

			// The expanded row must keep showing the persisted expression after the refetch.
			await expect(detailRow.locator('code')).toContainText('30 12 * * 1', { timeout: 5_000 });

			await screenshot(page, 'monitoring', 'schedule-cron-edited');
		} finally {
			await deleteScheduleById(page, scheduleId);
		}
	});

	test('inline cron edit: Escape cancels without saving', async ({
		page,
		request,
		sharedDatasource
	}) => {
		const dsId = sharedDatasource.id;
		const scheduleId = await createSchedule(request, dsId, '0 6 * * *');
		try {
			await gotoMonitoringTab(page, 'schedules');

			// Expand (table view)
			const schedRow = page.locator(`[data-schedule-row="${scheduleId}"]`);
			await expect(schedRow).toBeVisible({ timeout: 5_000 });
			await schedRow.click();
			const detailRow = page.locator(`[data-schedule-detail="${scheduleId}"]`);
			await expect(detailRow.locator('code')).toBeVisible({ timeout: 5_000 });

			// Enter edit mode scoped to expanded row
			await detailRow.locator('button[title="Edit cron expression"]').click();
			const cronInput = detailRow.locator('input[aria-label="Cron expression"]');
			await expect(cronInput).toBeVisible({ timeout: 3_000 });

			// Type a different value then Escape
			await cronInput.fill('59 23 * * *');
			await cronInput.press('Escape');

			// Input should disappear, original expression should remain
			await expect(cronInput).not.toBeVisible({ timeout: 3_000 });
			await expect(detailRow.locator('code')).toContainText('0 6 * * *', { timeout: 5_000 });
		} finally {
			await deleteScheduleById(page, scheduleId);
		}
	});
});

test.describe('Monitoring – Health Checks tab', () => {
	test('created health check appears in list', async ({ page, request, sharedDatasource }) => {
		const id = uid();
		const hc = `e2e Row Count ${id}`;
		const healthCheckId = await createHealthCheck(request, sharedDatasource.id, hc);
		try {
			await gotoMonitoringTab(page, 'health');
			await waitForHealthCheckRow(page, hc);
		} finally {
			await deleteHealthCheckById(page, healthCheckId);
		}
	});

	test('health checks search filters by check name', async ({
		page,
		request,
		sharedAuxDatasource
	}) => {
		const id = uid();
		const hc = `e2e Searchable HC ${id}`;
		const healthCheckId = await createHealthCheck(request, sharedAuxDatasource.id, hc);
		try {
			await gotoMonitoringTab(page, 'health');
			const row = await waitForHealthCheckRow(page, hc);
			await expect(row).toBeVisible({ timeout: 5_000 });

			// Search for the check name should show it
			await page.getByLabel(/Search health checks/i).fill(hc);
			await expect(row).toBeVisible({ timeout: 5_000 });

			// Search for non-matching term should show empty state
			await page.getByLabel(/Search health checks/i).fill('ZZZNOMATCH');
			await expect(page.getByText('No health checks match your search.')).toBeVisible({
				timeout: 5_000
			});
		} finally {
			await deleteHealthCheckById(page, healthCheckId);
		}
	});

	test('health check delete button removes it from list', async ({
		page,
		request,
		sharedDateDatasource
	}) => {
		const id = uid();
		const hc = `e2e Delete HC ${id}`;
		const healthCheckId = await createHealthCheck(request, sharedDateDatasource.id, hc);

		try {
			await gotoMonitoringTab(page, 'health');
			const row = await waitForHealthCheckRow(page, hc);
			await row.getByLabel('Delete check').click({ timeout: 5_000 });

			// Confirm in the dialog
			const dialog = dialogByHeading(page, /Delete Health Check/i);
			await expect(dialog).toBeVisible();
			await dialog.getByRole('button', { name: /^Delete$/ }).click();

			await expect(row).toHaveCount(0, { timeout: 5_000 });
		} finally {
			await deleteHealthCheckById(page, healthCheckId);
		}
	});

	test('health check enable/disable toggle works', async ({
		page,
		request,
		sharedBulkDatasource
	}) => {
		const id = uid();
		const hc = `e2e Toggle HC ${id}`;
		const healthCheckId = await createHealthCheck(request, sharedBulkDatasource.id, hc);
		try {
			await gotoMonitoringTab(page, 'health');
			const row = await waitForHealthCheckRow(page, hc);
			const toggleBtn = row.locator('button[title="Click to disable"]');
			await expect(toggleBtn).toBeAttached({ timeout: 5_000 });
			await toggleBtn.click({ timeout: 5_000 });

			await waitForHealthChecksList(page);
			const updatedRow = await waitForHealthCheckRow(page, hc);
			await expect(updatedRow.getByText('Off')).toBeVisible({ timeout: 5_000 });

			await screenshot(page, 'monitoring', 'health-check-toggled-off');
		} finally {
			await deleteHealthCheckById(page, healthCheckId);
		}
	});
});

test.describe('Monitoring – Health Check create flow', () => {
	test('create health check via UI form', async ({ page, sharedHealthCheckDatasource }) => {
		const id = uid();
		const hc = `e2e UI Check ${id}`;
		const dsId = sharedHealthCheckDatasource.id;
		let healthCheckId: string | undefined;
		try {
			await gotoMonitoringTab(page, 'health');
			await expect(page.getByRole('button', { name: /New Check/i })).toBeVisible({
				timeout: 5_000
			});
			await page.getByRole('button', { name: /New Check/i }).click();

			// Select datasource
			const dsSelect = page.locator('#hc-target');
			await expect(dsSelect).toBeVisible({ timeout: 5_000 });
			await waitForSelectOption(dsSelect, dsId);
			await dsSelect.selectOption(dsId);

			// Fill name
			await page.locator('#hc-name').fill(hc);

			// Type defaults to row_count — fill min_rows
			await page.locator('#hc-min-rows').fill('1');

			// Submit
			const saveBtn = page.getByRole('button', { name: 'Save Check' });
			await expect(saveBtn).toBeEnabled({ timeout: 5_000 });
			const createResponse = page.waitForResponse(
				(response) =>
					response.url().includes('/api/v1/healthchecks') &&
					response.request().method() === 'POST' &&
					response.ok()
			);
			await saveBtn.click();
			healthCheckId = ((await (await createResponse).json()) as { id: string }).id;
			await waitForHealthCheckRow(page, hc);
		} finally {
			if (healthCheckId) await deleteHealthCheckById(page, healthCheckId);
		}
	});
});

test.describe('Monitoring – Builds tab', () => {
	test('shared datasource build history shows Preview and Build rows, search, and row detail tabs', async ({
		page,
		sharedDatasource
	}) => {
		// Read-only checks. Each step re-opens the Builds tab so expanded rows and search
		// text from earlier steps do not leak into later ones. Each build row wait can use
		// up to buildTimeoutMs(), so the merged journey gets the slow test budget.
		test.slow();
		const ds = sharedDatasource.name;
		const dsId = sharedDatasource.id;

		await test.step('datasource preview runs appear as one Preview row', async () => {
			// Open the datasource in the library so a human-visible preview loads.
			await page.goto(`/datasources?id=${dsId}`);
			await waitForDatasourcePreviewReady(page);

			await gotoMonitoringTab(page, 'builds');
			const panel = page.locator('#panel-builds');
			await page.getByLabel(/Search builds/i).fill(ds);
			const previewRow = await waitForDatasourcePreviewRow(panel, dsId, readyTimeoutMs());
			await expect(previewRow).toContainText('Preview');
			await expect(previewRow).toHaveAttribute('data-build-kind', 'preview');
		});

		await test.step('external datasource onboarding appears as Build rows', async () => {
			const { buildRow } = await openSharedDatasourceBuildRow(page, ds, dsId, 15_000);
			await expect(buildRow).toContainText('Build');
			await expect(buildRow).not.toContainText('Preview');
		});

		await test.step('Builds search filters by text', async () => {
			const { buildRow } = await openSharedDatasourceBuildRow(page, ds, dsId, buildTimeoutMs());
			await expect(buildRow).toBeVisible({ timeout: 5_000 });

			await page.getByLabel(/Search builds/i).fill('ZZZNOMATCH');
			await expect(buildRow).not.toBeVisible({ timeout: 5_000 });

			await page.getByLabel(/Search builds/i).fill(ds);
			await expect(buildRow).toBeVisible({ timeout: 5_000 });
		});

		await test.step('clicking a build row expands to show a stable detail panel', async () => {
			const { buildRow, detailRow } = await openSharedDatasourceBuildRow(
				page,
				ds,
				dsId,
				buildTimeoutMs()
			);

			await buildRow.click();
			await expect(detailRow).toBeVisible({ timeout: 5_000 });
			await expect(detailRow.locator('[data-testid="build-preview"]')).toBeVisible({
				timeout: 5_000
			});
			await expect(detailRow.getByRole('tab', { name: 'Steps' })).toBeVisible();
			await expect(detailRow.getByRole('tab', { name: 'Logs' })).toBeVisible();
			await detailRow.getByRole('tab', { name: 'Logs' }).click();
			await expect(detailRow.locator('[data-testid="build-logs-panel"]')).toBeVisible();
			await expect(detailRow.getByRole('tab', { name: 'Payload' })).toBeVisible();
			// Stay expanded after interacting with tabs (no expand/collapse thrash).
			await expect(detailRow).toBeVisible();
			await expect(detailRow.locator('[data-testid="build-preview"]')).toBeVisible();
			await screenshot(page, 'monitoring', 'build-row-expanded');
		});

		await test.step('build row toggles expand and collapse on click', async () => {
			const { buildRow, detailRow } = await openSharedDatasourceBuildRow(
				page,
				ds,
				dsId,
				buildTimeoutMs()
			);

			// First click expands
			await buildRow.click();
			await expect(detailRow).toBeVisible({ timeout: 5_000 });

			// Second click collapses
			await buildRow.click();
			await expect(detailRow).not.toBeVisible({ timeout: 5_000 });
		});

		await test.step('build detail Steps tab shows step content', async () => {
			const { buildRow, detailRow } = await openSharedDatasourceBuildRow(
				page,
				ds,
				dsId,
				buildTimeoutMs()
			);

			await buildRow.click();
			await expect(detailRow).toBeVisible({ timeout: 5_000 });

			const stepsTab = detailRow.getByRole('tab', { name: 'Steps' });
			await expect(stepsTab).toBeVisible();
			await stepsTab.click();

			// Steps panel should show build progress or step names
			await expect(detailRow.locator('[data-testid="build-steps-panel"]')).toBeVisible({
				timeout: 5_000
			});
			// Verify at least some step-related content is rendered
			await expect(detailRow.getByText(/Build ID:|step|progress/i).first()).toBeVisible({
				timeout: 5_000
			});
		});

		await test.step('build detail Logs tab shows log entries', async () => {
			const { buildRow, detailRow } = await openSharedDatasourceBuildRow(
				page,
				ds,
				dsId,
				buildTimeoutMs()
			);

			await buildRow.click();
			await expect(detailRow).toBeVisible({ timeout: 5_000 });

			const logsTab = detailRow.getByRole('tab', { name: 'Logs' });
			await expect(logsTab).toBeVisible();
			await logsTab.click();

			// Logs panel should render
			await expect(detailRow.locator('[data-testid="build-logs-panel"]')).toBeVisible({
				timeout: 5_000
			});

			// Verify log level filter buttons and either log entries or "No logs" state
			await expect(detailRow.locator('[data-testid="log-level-filter"]')).toBeVisible({
				timeout: 5_000
			});
			const hasLogs = await detailRow
				.locator(':text("No logs captured")')
				.isVisible()
				.catch(() => false);
			if (!hasLogs) {
				// If logs exist, verify at least one log entry format marker
				await expect(detailRow.locator(':text("[")').first()).toBeVisible({ timeout: 5_000 });
			}
		});
	});

	test('repeated builds complete successfully as Build rows while preview rows remain Preview-kind', async ({
		page,
		request,
		sharedDatasource
	}, testInfo) => {
		// This test runs two cold builds. The first build also checks its single history row,
		// its duration, and its request payload before the repeat. The datasource preview is
		// opened last to verify that its row remains Preview-kind. Each build still has its
		// own 120s bound below.
		testInfo.setTimeout(300_000);
		const ds = sharedDatasource.name;
		const analysisName = `E2E Build Determinism ${uid()}`;
		const dsId = sharedDatasource.id;
		const analysisId = await createMultiStepAnalysis(request, analysisName, dsId);
		try {
			const monitorPage = await page.context().newPage();
			await monitorPage.goto(`/monitoring?tab=builds&analysis_id=${analysisId}`);
			await waitForLayoutReady(monitorPage);
			const panel = monitorPage.locator('#panel-builds');
			await expect(panel).toBeVisible({ timeout: readyTimeoutMs() });

			for (let i = 0; i < 2; i += 1) {
				const buildId = await startBuildFromAnalysisPage(page, analysisId);
				await waitForBuildCompletionOrExplainFailure(page, buildId, 120_000);
				const row = await waitForBuildRowById(monitorPage, panel, buildId, ['completed'], 15_000);
				await expect(row).toHaveAttribute('data-build-kind', 'build');
				await expect(row).toHaveAttribute('data-build-status', 'completed');
				await expect(row).toContainText('Build');
				await expect(row).not.toContainText('Preview');
				// Free the exclusive build engine once the run is terminal.
				await freeWarmComputeWorkers(page, { buildIds: [buildId] });

				if (i === 0) {
					// Checked before the second build starts, so the analysis has exactly one build row.
					await test.step('single build appears once in Monitoring history', async () => {
						await gotoMonitoringBuilds(monitorPage, analysisId);
						const historyRow = await waitForBuildRowById(
							monitorPage,
							panel,
							buildId,
							['queued', 'running', 'completed', 'failed'],
							15_000
						);
						await expect(historyRow).toHaveAttribute('data-build-kind', 'build');
						await expect(
							panel.locator(`[data-build-kind="build"][data-build-analysis-id="${analysisId}"]`)
						).toHaveCount(1);
					});

					await test.step('build history shows duration and duration trend for analysis builds', async () => {
						await gotoMonitoringBuilds(monitorPage, analysisId);
						const buildRow = await waitForBuildRowById(
							monitorPage,
							panel,
							buildId,
							['completed'],
							buildTimeoutMs()
						);
						const durationCell = panel.locator(`[data-testid="build-row-duration-${buildId}"]`);
						await expect(durationCell).toBeVisible({ timeout: 5_000 });
						await expect(durationCell).not.toHaveText('-');
						// Terminal builds should show a formatted duration value.
						await expect(durationCell).toHaveText(/(ms|s|m|h)/);

						// Expand for step timing bars when the build has finished.
						await buildRow.click();
						const detail = panel.locator(`[data-build-detail="${buildId}"]`);
						await expect(detail.locator('[data-testid="build-preview"]')).toBeVisible({
							timeout: 5_000
						});
						await expect(detail.locator('[data-testid="build-elapsed-timer"]')).toBeVisible();
						await expect(detail.getByRole('tab', { name: 'Steps' })).toBeVisible();

						// Duration trend chart is the human-visible surface for compute-worker-run stats
						// (avg/p50/p95 and/or empty/insufficient-data states).
						const trendChart = monitorPage.locator('[data-testid="duration-trend-chart"]');
						await expect(trendChart).toBeVisible({ timeout: 10_000 });
						const trendStats = trendChart.locator('[data-testid="duration-trend-stats"]');
						const trendEmpty = trendChart.locator('[data-testid="duration-trend-empty"]');
						const trendLabel = trendChart.locator('[data-testid="duration-trend-label"]');
						await expect(trendStats.or(trendEmpty).or(trendLabel).first()).toBeVisible({
							timeout: 10_000
						});
					});

					await test.step('build detail shows Request Payload JSON', async () => {
						await gotoMonitoringBuilds(monitorPage, analysisId);
						const buildRow = await waitForBuildRowById(
							monitorPage,
							panel,
							buildId,
							['completed'],
							buildTimeoutMs()
						);
						await buildRow.click();
						const detailRow = panel.locator(`[data-build-detail="${buildId}"]`);
						await expect(detailRow).toBeVisible({ timeout: 5_000 });
						await detailRow.getByRole('tab', { name: 'Payload' }).click();
						const payloadPanel = detailRow.locator('[data-testid="build-payload-panel"]');
						await expect(payloadPanel).toBeVisible({ timeout: 5_000 });
						await expect(payloadPanel.getByText('Request', { exact: true })).toBeVisible({
							timeout: 5_000
						});
						const payloadRequest = payloadPanel.locator('[data-testid="build-payload-request"]');
						await expect(payloadRequest).toBeVisible({ timeout: 5_000 });
					});
				}
			}

			await page.goto(`/datasources?id=${dsId}`);
			await waitForDatasourcePreviewReady(page);
			await gotoMonitoringTab(monitorPage, 'builds');
			await monitorPage.getByLabel(/Search builds/i).fill(ds);
			const previewRow = await waitForDatasourcePreviewRow(panel, dsId);
			await expect(previewRow).toContainText('Preview');
			await monitorPage.close();
		} finally {
			await deleteAnalysisViaUI(page, analysisName).catch(() => undefined);
		}
	});
});

// ── Live build history (real e2e, no WS mocking) ───────────────────────────

test.describe('Monitoring – live build history', () => {
	test('triggering a build uses the normal output row and expands to BuildPreview', async ({
		page,
		request,
		sharedLargeBuildDatasource
	}) => {
		const aName = `E2E Active Build ${uid()}`;
		const aId = await createMultiStepAnalysis(request, aName, sharedLargeBuildDatasource.id);
		let buildId: string | undefined;
		try {
			const monitorPage = await page.context().newPage();

			await monitorPage.goto(`/monitoring?tab=builds&analysis_id=${aId}`);
			await waitForLayoutReady(monitorPage);
			await expect(monitorPage.getByRole('tab', { name: 'Builds' })).toHaveAttribute(
				'aria-selected',
				'true'
			);
			const monitorPanel = monitorPage.locator('#panel-builds');
			await expect(monitorPanel).toBeVisible({ timeout: 5_000 });

			buildId = await startBuildFromAnalysisPage(page, aId);

			const monitorBuildRow = await waitForBuildRowById(monitorPage, monitorPanel, buildId, [
				'queued',
				'running',
				'completed',
				'failed'
			]);
			await monitorBuildRow.click();
			const monitorBuildRowId = await monitorBuildRow.getAttribute('data-build-row');
			if (!monitorBuildRowId) throw new Error('Expected monitor build row id');
			const monitorPreview = monitorPanel
				.locator(`[data-build-detail="${monitorBuildRowId}"]`)
				.locator('[data-testid="build-preview"]');
			await expect(monitorPreview).toBeVisible({ timeout: 5_000 });
			await expect(monitorPreview.locator('[data-testid="build-steps-panel"]')).toBeVisible({
				timeout: 5_000
			});
			await screenshot(monitorPage, 'monitoring', 'build-history-expanded-real');

			await monitorPage.close();

			await screenshot(page, 'monitoring', 'build-history-terminal');
		} finally {
			await deleteAnalysisViaUI(page, aName).catch(() => undefined);
		}
	});
});
