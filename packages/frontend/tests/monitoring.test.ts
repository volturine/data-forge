import { test, expect } from './fixtures.js';
import {
	createDatasource,
	createSchedule,
	createHealthCheck,
	createLargeDatasource,
	createMultiStepAnalysis
} from './utils/api.js';
import {
	deleteDatasourceViaUI,
	deleteScheduleViaUI,
	deleteHealthCheckViaUI,
	deleteAnalysisViaUI,
	shutdownBuildEngineViaUI
} from './utils/ui-cleanup.js';
import {
	buildTimeoutMs,
	gotoMonitoringTab,
	readyTimeoutMs,
	waitForLayoutReady
} from './utils/readiness.js';
import { gotoAnalysisEditor } from './utils/analysis.js';
import { uid } from './utils/uid.js';
import { screenshot } from './utils/visual.js';
import { dialogByHeading } from './utils/locators.js';
import { waitForBuildPreview, waitForBuildPreviewId } from './utils/builds.js';

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

async function startBuildFromAnalysisPage(
	page: import('@playwright/test').Page,
	analysisId: string,
	previousBuildId?: string | null
): Promise<string> {
	await gotoAnalysisEditor(page, analysisId);
	const buildBtn = page.locator('[data-testid="output-build-button"]');
	await expect(buildBtn).toBeVisible({ timeout: 5_000 });
	await buildBtn.click({ timeout: 5_000 });
	await expect(page.locator('[data-testid="output-build-preview-trigger"]')).toBeVisible({
		timeout: 5_000
	});
	const buildId = await previewBuildId(page);
	if (previousBuildId && buildId === previousBuildId) {
		throw new Error(`Build preview did not advance past build ${previousBuildId}`);
	}
	return buildId;
}

async function openBuildPreview(page: import('@playwright/test').Page) {
	const existingPreview = page.locator('[data-testid="build-preview"]');
	if (await existingPreview.isVisible().catch(() => false)) {
		return existingPreview;
	}
	const openPreviewBtn = page.locator('[data-testid="output-build-preview-trigger"]');
	await expect(openPreviewBtn).toBeVisible({ timeout: 5_000 });
	await openPreviewBtn.click();
	return waitForBuildPreview(page);
}

async function previewBuildId(page: import('@playwright/test').Page): Promise<string> {
	await openBuildPreview(page);
	return waitForBuildPreviewId(page);
}

async function refreshBuildHistory(page: import('@playwright/test').Page) {
	const responsePromise = page
		.waitForResponse(
			(response) =>
				response.url().includes('/api/v1/compute/builds') &&
				response.request().method() === 'GET' &&
				response.ok(),
			{ timeout: 5_000 }
		)
		.catch(() => null);
	await page.getByRole('button', { name: /Refresh History/i }).click();
	await responsePromise;
}

async function waitForBuildRowById(
	page: import('@playwright/test').Page,
	panel: ReturnType<import('@playwright/test').Page['locator']>,
	buildId: string,
	statuses: Array<'queued' | 'running' | 'completed' | 'failed' | 'cancelled'>,
	timeout = 15_000
) {
	const row = panel.locator(
		statuses
			.map((status) => `[data-build-row="${buildId}"][data-build-status="${status}"]`)
			.join(', ')
	);
	await expect
		.poll(
			async () => {
				const failedToLoad = panel.getByText(/Failed to load builds/i).first();
				if (await failedToLoad.isVisible().catch(() => false)) {
					throw new Error(`Build history failed while waiting for build row ${buildId}`);
				}
				await refreshBuildHistory(page);
				return row.isVisible().catch(() => false);
			},
			{ timeout, intervals: [100, 250, 500] }
		)
		.toBe(true);
	return row.first();
}

async function waitForDatasourceBuildRow(
	page: import('@playwright/test').Page,
	panel: ReturnType<import('@playwright/test').Page['locator']>,
	datasourceId: string,
	timeout = 15_000
) {
	const row = panel
		.locator(`[data-build-kind="build"][data-build-datasource-id="${datasourceId}"]`)
		.first();
	await expect
		.poll(
			async () => {
				const failedToLoad = panel.getByText(/Failed to load builds/i).first();
				if (await failedToLoad.isVisible().catch(() => false)) {
					throw new Error(`Build history failed while waiting for datasource row ${datasourceId}`);
				}
				await refreshBuildHistory(page);
				return row.isVisible().catch(() => false);
			},
			{ timeout, intervals: [100, 250, 500] }
		)
		.toBe(true);
	return row;
}

async function waitForDatasourcePreviewRow(
	page: import('@playwright/test').Page,
	panel: ReturnType<import('@playwright/test').Page['locator']>,
	datasourceId: string,
	timeout = 15_000
) {
	const row = panel
		.locator(`[data-build-kind="preview"][data-build-datasource-id="${datasourceId}"]`)
		.first();
	await expect
		.poll(
			async () => {
				const failedToLoad = panel.getByText(/Failed to load builds/i).first();
				if (await failedToLoad.isVisible().catch(() => false)) {
					throw new Error(`Build history failed while waiting for preview row ${datasourceId}`);
				}
				await refreshBuildHistory(page);
				return row.isVisible().catch(() => false);
			},
			{ timeout, intervals: [100, 250, 500] }
		)
		.toBe(true);
	return row;
}

async function waitForBuildRowEventually(
	page: import('@playwright/test').Page,
	panel: ReturnType<import('@playwright/test').Page['locator']>,
	buildId: string,
	statuses: Array<'queued' | 'running' | 'completed' | 'failed' | 'cancelled'>
) {
	return waitForBuildRowById(page, panel, buildId, statuses, buildTimeoutMs());
}

/**
 * E2E tests for the monitoring page – mirrors test_healthchecks.py /
 * test_scheduler.py / test_engine_runs.py.
 */
test.describe('Monitoring – page structure', () => {
	test.beforeEach(async ({ page }) => {
		await page.goto('/monitoring');
		await expect(page.getByRole('heading', { name: 'Monitoring' })).toBeVisible();
		await expect(page.getByRole('tab', { name: 'Builds' })).toBeVisible();
		await expect(page.getByRole('tab', { name: 'Builds' })).toHaveAttribute(
			'aria-selected',
			'true'
		);
	});

	test('renders Monitoring heading and description', async ({ page }) => {
		await expect(page.getByRole('heading', { name: 'Monitoring' })).toBeVisible();
		await expect(page.getByText(/Review builds, schedules, and health checks/i)).toBeVisible();
	});

	test('shows all three tabs: Builds, Schedules, Health Checks', async ({ page }) => {
		await expect(page.getByRole('tab', { name: 'Builds' })).toBeVisible();
		await expect(page.getByRole('tab', { name: 'Schedules' })).toBeVisible();
		await expect(page.getByRole('tab', { name: 'Health Checks' })).toBeVisible();
		await screenshot(page, 'monitoring', 'tabs-overview');
	});

	test('Builds tab is active by default', async ({ page }) => {
		const buildsTab = page.getByRole('tab', { name: 'Builds' });
		await expect(buildsTab).toHaveAttribute('aria-selected', 'true');
	});

	test('can switch between all tabs without error', async ({ page }) => {
		const tabMap = [
			{ label: 'Schedules', key: 'schedules' },
			{ label: 'Health Checks', key: 'health' },
			{ label: 'Builds', key: 'builds' }
		] as const;
		for (const { label, key } of tabMap) {
			await page.getByRole('tab', { name: label }).click();
			await expect(page.getByRole('tab', { name: label })).toHaveAttribute('aria-selected', 'true');
			if (key === 'builds') {
				await expect(page).toHaveURL(/\/monitoring/);
			} else {
				await expect(page).toHaveURL(new RegExp(`tab=${key}`));
			}
		}
	});

	test('each tab has its own search input', async ({ page }) => {
		await gotoMonitoringTab(page, 'builds');
		await expect(page.getByLabel(/Search builds/i)).toBeVisible();

		await gotoMonitoringTab(page, 'schedules');
		await expect(page.getByLabel(/Search schedules/i)).toBeVisible();

		await gotoMonitoringTab(page, 'health');
		await expect(page.getByLabel(/Search health checks/i)).toBeVisible();
	});
});

test.describe('Monitoring – Schedules tab', () => {
	test('Schedules tab shows schedule list or empty state', async ({ page }) => {
		await gotoMonitoringTab(page, 'schedules');
		// Either a schedule list or an empty/create state
		const panel = page.locator('#panel-schedules');
		await expect(panel).toBeVisible();
	});

	test('Schedules tab shows "New Schedule" button', async ({ page }) => {
		await gotoMonitoringTab(page, 'schedules');
		await expect(page.getByRole('button', { name: /New Schedule/i })).toBeVisible({
			timeout: readyTimeoutMs()
		});
		await screenshot(page, 'monitoring', 'schedules-tab');
	});

	test('created schedule appears in the Schedules tab', async ({ page, request }) => {
		const ds = `e2e-sched-${uid()}`;
		const dsId = await createDatasource(request, ds);
		await createSchedule(request, dsId, '0 6 * * *');
		try {
			await gotoMonitoringTab(page, 'schedules');
			const schedRow = page.locator(`tr[data-datasource-id="${dsId}"]`);
			await expect(schedRow).toBeVisible({ timeout: 5_000 });
			await expect(schedRow).toContainText('Cron: 0 6 * * *', { timeout: 5_000 });
		} finally {
			await deleteScheduleViaUI(page, ds);
		}
	});

	test('schedules search filters by datasource name', async ({ page, request }) => {
		const ds = `e2e-sched-search-${uid()}`;
		const dsId = await createDatasource(request, ds);
		await createSchedule(request, dsId, '0 9 * * *');
		try {
			await gotoMonitoringTab(page, 'schedules');
			const schedRow = page.locator(`tr[data-datasource-id="${dsId}"]`);
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
			await deleteScheduleViaUI(page, ds);
		}
	});

	test('schedule can be deleted via UI', async ({ page, request }) => {
		const ds = `e2e-sched-del-${uid()}`;
		const dsId = await createDatasource(request, ds);
		await createSchedule(request, dsId, '0 7 * * *');

		try {
			await gotoMonitoringTab(page, 'schedules');

			const schedRow = page.locator(`tr[data-datasource-id="${dsId}"]`);
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
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('schedule enable/disable toggle works', async ({ page, request }) => {
		const ds = `e2e-sched-toggle-${uid()}`;
		const dsId = await createDatasource(request, ds);
		await createSchedule(request, dsId, '0 8 * * *');
		try {
			await gotoMonitoringTab(page, 'schedules');
			const schedRow = page.locator(`tr[data-datasource-id="${dsId}"]`);
			await expect(schedRow).toBeVisible({ timeout: 5_000 });

			const toggleBtn = schedRow.locator('button[title="Click to disable"]');
			await expect(toggleBtn).toBeAttached({ timeout: 5_000 });
			await toggleBtn.click({ timeout: 5_000 });

			// After toggle, the button title should change to "Click to enable"
			await expect(schedRow.locator('button[title="Click to enable"]')).toBeAttached({
				timeout: 5_000
			});
		} finally {
			await deleteScheduleViaUI(page, ds);
		}
	});
});

test.describe('Monitoring – Schedule create flow', () => {
	test('create schedule via UI form', async ({ page, request }) => {
		const ds = `e2e-sched-create-${uid()}`;
		const dsId = await createDatasource(request, ds);
		try {
			await gotoMonitoringTab(page, 'schedules');
			await expect(page.getByRole('button', { name: /New Schedule/i })).toBeVisible({
				timeout: 5_000
			});
			await page.getByRole('button', { name: /New Schedule/i }).click();

			// Select datasource from dropdown
			const dsSelect = page.locator('#schedule-datasource');
			await expect(dsSelect).toBeVisible({ timeout: 5_000 });
			await waitForSelectOption(dsSelect, dsId, 5_000);
			await dsSelect.selectOption(dsId);

			// Cron is the default trigger type with default value — submit
			const createBtn = page.getByRole('button', { name: 'Create Schedule' });
			await expect(createBtn).toBeEnabled({ timeout: 5_000 });
			await createBtn.click();

			// Datasource name resolution can lag the row render, but datasource_id is stable immediately.
			const schedRow = page.locator(`tr[data-datasource-id="${dsId}"]`);
			await expect(schedRow).toBeVisible({ timeout: 5_000 });
			await expect(schedRow).toContainText('Every hour', { timeout: 5_000 });
		} finally {
			await deleteScheduleViaUI(page, ds);
		}
	});

	test('schedule create form Cancel closes form without creating', async ({ page, request }) => {
		const ds = `e2e-sched-cancel-${uid()}`;
		await createDatasource(request, ds);
		try {
			await gotoMonitoringTab(page, 'schedules');
			await page.getByRole('button', { name: /New Schedule/i }).click({ timeout: 5_000 });

			await expect(page.locator('#schedule-datasource')).toBeVisible({ timeout: 5_000 });

			// Click Cancel
			await page.getByRole('button', { name: 'Cancel' }).click();

			// Form should be gone — the datasource dropdown should not be visible
			await expect(page.locator('#schedule-datasource')).not.toBeVisible({ timeout: 5_000 });
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});
});

test.describe('Monitoring – Schedule inline cron edit', () => {
	test('inline cron edit: pencil → input → Enter saves new expression', async ({
		page,
		request
	}) => {
		const ds = `e2e-sched-cron-${uid()}`;
		const dsId = await createDatasource(request, ds);
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
			await deleteScheduleViaUI(page, ds);
		}
	});

	test('inline cron edit: Escape cancels without saving', async ({ page, request }) => {
		const ds = `e2e-sched-cron-esc-${uid()}`;
		const dsId = await createDatasource(request, ds);
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
			await deleteScheduleViaUI(page, ds);
		}
	});
});

test.describe('Monitoring – Health Checks tab', () => {
	test('Health Checks tab renders without error', async ({ page }) => {
		await gotoMonitoringTab(page, 'health');
		await waitForHealthChecksList(page);
		await expect(page.getByRole('heading', { name: 'Monitoring' })).toBeVisible();
		await expect(page.getByRole('tab', { name: 'Health Checks' })).toHaveAttribute(
			'aria-selected',
			'true'
		);
	});

	test('Health Checks tab shows "New Check" button', async ({ page }) => {
		await gotoMonitoringTab(page, 'health');
		await waitForHealthChecksList(page);
		await expect(page.getByRole('button', { name: /New Check/i })).toBeVisible({ timeout: 5_000 });
		await screenshot(page, 'monitoring', 'health-checks-tab');
	});

	test('created health check appears in list', async ({ page, request }) => {
		const id = uid();
		const ds = `e2e-hc-${id}`;
		const hc = `e2e Row Count ${id}`;
		const dsId = await createDatasource(request, ds);
		await createHealthCheck(request, dsId, hc);
		try {
			await gotoMonitoringTab(page, 'health');
			await waitForHealthCheckRow(page, hc);
		} finally {
			await deleteHealthCheckViaUI(page, hc);
		}
	});

	test('health checks search filters by check name', async ({ page, request }) => {
		const id = uid();
		const ds = `e2e-hc-search-${id}`;
		const hc = `e2e Searchable HC ${id}`;
		const dsId = await createDatasource(request, ds);
		await createHealthCheck(request, dsId, hc);
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
			await deleteHealthCheckViaUI(page, hc);
		}
	});

	test('health check delete button removes it from list', async ({ page, request }) => {
		const id = uid();
		const ds = `e2e-hc-del-${id}`;
		const hc = `e2e Delete HC ${id}`;
		const dsId = await createDatasource(request, ds);
		await createHealthCheck(request, dsId, hc);

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
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('health check enable/disable toggle works', async ({ page, request }) => {
		const id = uid();
		const ds = `e2e-hc-toggle-${id}`;
		const hc = `e2e Toggle HC ${id}`;
		const dsId = await createDatasource(request, ds);
		await createHealthCheck(request, dsId, hc);
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
			await deleteHealthCheckViaUI(page, hc);
		}
	});
});

test.describe('Monitoring – Health Check create flow', () => {
	test('create health check via UI form', async ({ page, request }) => {
		const id = uid();
		const ds = `e2e-hc-create-${id}`;
		const hc = `e2e UI Check ${id}`;
		const dsId = await createDatasource(request, ds);
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
			await saveBtn.click();
			await waitForHealthCheckRow(page, hc);
		} finally {
			await deleteHealthCheckViaUI(page, hc);
		}
	});
});

test.describe('Monitoring – Builds tab', () => {
	test('Builds tab renders and shows builds panel', async ({ page }) => {
		await gotoMonitoringTab(page, 'builds');
		await expect(page.getByRole('tab', { name: 'Builds' })).toHaveAttribute(
			'aria-selected',
			'true'
		);
		const panel = page.locator('#panel-builds');
		await expect(panel).toBeVisible({ timeout: 5_000 });
	});

	test('datasource preview runs appear as one Preview row', async ({ page, request }) => {
		const ds = `e2e-preview-${uid()}`;
		const dsId = await createDatasource(request, ds);
		let previewRequests = 0;
		page.on('request', (req) => {
			if (req.url().includes('/api/v1/compute/preview')) previewRequests += 1;
		});
		try {
			await page.goto(`/datasources?id=${dsId}`);
			await page.waitForResponse((resp) => resp.url().includes('/api/v1/compute/preview'), {
				timeout: 15_000
			});
			expect(previewRequests).toBe(1);

			await gotoMonitoringTab(page, 'builds');
			const panel = page.locator('#panel-builds');
			await expect(panel).toBeVisible({ timeout: 5_000 });
			await page.getByLabel(/Search builds/i).fill(ds);
			const previewRow = await waitForDatasourcePreviewRow(page, panel, dsId);
			await expect(previewRow).toContainText('Preview');
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('external datasource onboarding appears as Build rows', async ({ page, request }) => {
		const ds = `e2e-onboard-build-${uid()}`;
		const dsId = await createDatasource(request, ds);
		try {
			await gotoMonitoringTab(page, 'builds');
			const panel = page.locator('#panel-builds');
			await expect(panel).toBeVisible({ timeout: 5_000 });
			await page.getByLabel(/Search builds/i).fill(ds);
			const buildRow = await waitForDatasourceBuildRow(page, panel, dsId);
			await expect(buildRow).toContainText('Build');
			await expect(buildRow).not.toContainText('Preview');
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('Builds search filters by text', async ({ page, request }) => {
		const ds = `e2e-filter-${uid()}`;
		const dsId = await createDatasource(request, ds);
		try {
			await gotoMonitoringTab(page, 'builds');
			const panel = page.locator('#panel-builds');
			// Search by unique name so the row is not lost under the unfiltered
			// 50-row page limit when many parallel workers create builds.
			await page.getByLabel(/Search builds/i).fill(ds);
			const buildRow = await waitForDatasourceBuildRow(page, panel, dsId, 15_000);
			await expect(buildRow).toBeVisible({ timeout: 5_000 });

			await page.getByLabel(/Search builds/i).fill('ZZZNOMATCH');
			await expect(buildRow).not.toBeVisible({ timeout: 5_000 });

			await page.getByLabel(/Search builds/i).fill(ds);
			await expect(buildRow).toBeVisible({ timeout: 5_000 });
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('clicking a build row expands to show detail panel without request loop', async ({
		page,
		request
	}) => {
		const ds = `e2e-expand-${uid()}`;
		const dsId = await createDatasource(request, ds);
		try {
			await gotoMonitoringTab(page, 'builds');
			const panel = page.locator('#panel-builds');
			await page.getByLabel(/Search builds/i).fill(ds);
			const buildRow = await waitForDatasourceBuildRow(page, panel, dsId, 15_000);
			await expect(buildRow).toHaveAttribute('data-build-kind', 'build');
			await expect(buildRow).toContainText('Build');
			await expect(buildRow).not.toContainText('Preview');

			const buildRowId = await buildRow.getAttribute('data-build-row');
			if (!buildRowId) throw new Error('Expected build row id');
			let detailRequests = 0;
			page.on('request', (req) => {
				if (req.url().includes(`/api/v1/compute/builds/${buildRowId}`)) detailRequests += 1;
			});

			await buildRow.click();
			const detailRow = panel.locator(`[data-build-detail="${buildRowId}"]`);
			await expect(detailRow).toBeVisible({ timeout: 5_000 });
			await expect(detailRow.locator('[data-testid="build-preview"]')).toBeVisible({
				timeout: 5_000
			});
			await expect(detailRow.getByRole('tab', { name: 'Steps' })).toBeVisible();
			await expect(detailRow.getByRole('tab', { name: 'Logs' })).toBeVisible();
			await detailRow.getByRole('tab', { name: 'Logs' }).click();
			await expect(detailRow.locator('[data-testid="build-logs-panel"]')).toBeVisible();
			await expect(detailRow.getByRole('tab', { name: 'Payload' })).toBeVisible();
			expect(detailRequests).toBeLessThanOrEqual(2);
			await screenshot(page, 'monitoring', 'build-row-expanded');
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('build history shows duration and duration trend for analysis builds', async ({
		page,
		request
	}) => {
		const ds = `e2e-duration-${uid()}`;
		const analysisName = `E2E Duration ${uid()}`;
		const dsId = await createDatasource(request, ds);
		const analysisId = await createMultiStepAnalysis(request, analysisName, dsId);
		let buildId: string | undefined;
		try {
			buildId = await startBuildFromAnalysisPage(page, analysisId);
			await page.goto(`/monitoring?tab=builds&analysis_id=${analysisId}`);
			const panel = page.locator('#panel-builds');
			await expect(panel).toBeVisible({ timeout: 5_000 });

			await expect(page.locator('[data-testid="duration-trend-chart"]')).toBeVisible({
				timeout: 10_000
			});

			const buildRow = await waitForBuildRowEventually(page, panel, buildId, [
				'completed',
				'failed',
				'cancelled',
				'running',
				'queued'
			]);
			const durationCell = panel.locator(`[data-testid="build-row-duration-${buildId}"]`);
			await expect(durationCell).toBeVisible({ timeout: 5_000 });
			await expect(durationCell).not.toHaveText('-');

			const status = await buildRow.getAttribute('data-build-status');
			if (status === 'running' || status === 'queued') {
				await expect(durationCell).toBeVisible();
			} else {
				// Terminal builds should show a formatted duration value.
				await expect(durationCell).toHaveText(/(ms|s|m|h)/);
			}

			// Expand for step timing bars when the build has finished.
			if (status === 'completed' || status === 'failed' || status === 'cancelled') {
				await buildRow.click();
				const detail = panel.locator(`[data-build-detail="${buildId}"]`);
				await expect(detail.locator('[data-testid="build-preview"]')).toBeVisible({
					timeout: 5_000
				});
				await expect(detail.locator('[data-testid="build-elapsed-timer"]')).toBeVisible();
				await expect(detail.getByRole('tab', { name: 'Steps' })).toBeVisible();
			}

			const statsResponse = await page.request.get(
				`/api/v1/engine-runs/stats?analysis_id=${analysisId}&kind=build&limit=20`
			);
			expect(statsResponse.ok()).toBe(true);
			const stats = await statsResponse.json();
			expect(stats).toHaveProperty('trend');
			expect(stats).toHaveProperty('runs');
		} finally {
			if (buildId) {
				await shutdownBuildEngineViaUI(page, buildId).catch(() => undefined);
			}
			await deleteAnalysisViaUI(page, analysisName);
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('build detail shows Request Payload JSON', async ({ page, request }) => {
		const ds = `e2e-payload-${uid()}`;
		const analysisName = `E2E Builds Payload ${uid()}`;
		const dsId = await createDatasource(request, ds);
		const analysisId = await createMultiStepAnalysis(request, analysisName, dsId);
		let buildId: string | undefined;
		try {
			buildId = await startBuildFromAnalysisPage(page, analysisId);
			await page.goto(`/monitoring?tab=builds&analysis_id=${analysisId}`);
			const panel = page.locator('#panel-builds');
			const buildRow = await waitForBuildRowEventually(page, panel, buildId, [
				'queued',
				'running',
				'completed',
				'failed'
			]);

			await buildRow.click();
			const buildRowId = await buildRow.getAttribute('data-build-row');
			if (!buildRowId) throw new Error('Expected build row id');

			const detailRow = panel.locator(`[data-build-detail="${buildRowId}"]`);
			await expect(detailRow).toBeVisible({ timeout: 5_000 });
			await detailRow.getByRole('tab', { name: 'Payload' }).click();
			const payloadPanel = detailRow.locator('[data-testid="build-payload-panel"]');
			await expect(payloadPanel).toBeVisible({ timeout: 5_000 });
			await expect(payloadPanel.getByText('Request', { exact: true })).toBeVisible({
				timeout: 5_000
			});
			await expect(payloadPanel.locator('[data-testid="build-payload-request"]')).toBeVisible({
				timeout: 5_000
			});
		} finally {
			if (buildId) {
				await shutdownBuildEngineViaUI(page, buildId).catch(() => undefined);
			}
			await deleteAnalysisViaUI(page, analysisName);
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('single build appears once in Monitoring history', async ({ page, request }) => {
		const ds = `e2e-build-once-${uid()}`;
		const analysisName = `E2E Single Build Row ${uid()}`;
		const dsId = await createDatasource(request, ds);
		const analysisId = await createMultiStepAnalysis(request, analysisName, dsId);
		let buildId: string | undefined;
		try {
			buildId = await startBuildFromAnalysisPage(page, analysisId);
			await page.goto(`/monitoring?tab=builds&analysis_id=${analysisId}`);
			const panel = page.locator('#panel-builds');
			const buildRow = await waitForBuildRowById(
				page,
				panel,
				buildId,
				['queued', 'running', 'completed', 'failed'],
				15_000
			);
			await expect(buildRow).toHaveAttribute('data-build-kind', 'build');
			await expect(
				panel.locator(`[data-build-kind="build"][data-build-analysis-id="${analysisId}"]`)
			).toHaveCount(1);
		} finally {
			if (buildId) {
				await shutdownBuildEngineViaUI(page, buildId).catch(() => undefined);
			}
			await deleteAnalysisViaUI(page, analysisName);
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('repeated builds complete successfully as Build rows while preview rows remain Preview-kind', async ({
		page,
		request
	}) => {
		const ds = `e2e-build-vs-preview-${uid()}`;
		const analysisName = `E2E Build Determinism ${uid()}`;
		const dsId = await createDatasource(request, ds);
		const analysisId = await createMultiStepAnalysis(request, analysisName, dsId);
		const startedBuildIds: string[] = [];
		try {
			const monitorPage = await page.context().newPage();
			await monitorPage.goto(`/monitoring?tab=builds&analysis_id=${analysisId}`);
			await waitForLayoutReady(monitorPage);
			const panel = monitorPage.locator('#panel-builds');
			await expect(panel).toBeVisible({ timeout: readyTimeoutMs() });

			let previousBuildId: string | null = null;
			for (let i = 0; i < 2; i += 1) {
				const buildId = await startBuildFromAnalysisPage(page, analysisId, previousBuildId);
				previousBuildId = buildId;
				startedBuildIds.push(buildId);
				const row = await waitForBuildRowEventually(monitorPage, panel, buildId, ['completed']);
				await expect(row).toHaveAttribute('data-build-kind', 'build');
				await expect(row).toHaveAttribute('data-build-status', 'completed');
				await expect(row).toContainText('Build');
				await expect(row).not.toContainText('Preview');
				// Free the exclusive build engine before starting the next one.
				await shutdownBuildEngineViaUI(page, buildId).catch(() => undefined);
			}

			let previewRequests = 0;
			page.on('request', (req) => {
				if (req.url().includes('/api/v1/compute/preview')) previewRequests += 1;
			});
			await page.goto(`/datasources?id=${dsId}`);
			await page.waitForResponse((resp) => resp.url().includes('/api/v1/compute/preview'), {
				timeout: 15_000
			});
			expect(previewRequests).toBe(1);

			await gotoMonitoringTab(monitorPage, 'builds');
			await monitorPage.getByLabel(/Search builds/i).fill(ds);
			const previewRow = await waitForDatasourcePreviewRow(monitorPage, panel, dsId);
			await expect(previewRow).toContainText('Preview');
			await monitorPage.close();
		} finally {
			// Free engines even when assertions fail; keep cleanup cheap under budget.
			for (const buildId of startedBuildIds) {
				await shutdownBuildEngineViaUI(page, buildId).catch(() => undefined);
			}
			await deleteAnalysisViaUI(page, analysisName).catch(() => undefined);
			await deleteDatasourceViaUI(page, ds).catch(() => undefined);
		}
	});

	test('build row toggles expand and collapse on click', async ({ page, request }) => {
		const ds = `e2e-expand-toggle-${uid()}`;
		const dsId = await createDatasource(request, ds);
		try {
			await gotoMonitoringTab(page, 'builds');
			const panel = page.locator('#panel-builds');
			await page.getByLabel(/Search builds/i).fill(ds);
			const buildRow = await waitForDatasourceBuildRow(page, panel, dsId, 15_000);
			const buildRowId = await buildRow.getAttribute('data-build-row');
			if (!buildRowId) throw new Error('Expected build row id');

			// First click expands
			await buildRow.click();
			const detailRow = panel.locator(`[data-build-detail="${buildRowId}"]`);
			await expect(detailRow).toBeVisible({ timeout: 5_000 });

			// Second click collapses
			await buildRow.click();
			await expect(detailRow).not.toBeVisible({ timeout: 5_000 });
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('build detail Steps tab shows step content', async ({ page, request }) => {
		const ds = `e2e-steps-${uid()}`;
		const dsId = await createDatasource(request, ds);
		try {
			await gotoMonitoringTab(page, 'builds');
			const panel = page.locator('#panel-builds');
			await page.getByLabel(/Search builds/i).fill(ds);
			const buildRow = await waitForDatasourceBuildRow(page, panel, dsId, 15_000);
			const buildRowId = await buildRow.getAttribute('data-build-row');
			if (!buildRowId) throw new Error('Expected build row id');

			await buildRow.click();
			const detailRow = panel.locator(`[data-build-detail="${buildRowId}"]`);
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
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('build detail Logs tab shows log entries', async ({ page, request }) => {
		const ds = `e2e-logs-${uid()}`;
		const dsId = await createDatasource(request, ds);
		try {
			await gotoMonitoringTab(page, 'builds');
			const panel = page.locator('#panel-builds');
			await page.getByLabel(/Search builds/i).fill(ds);
			const buildRow = await waitForDatasourceBuildRow(page, panel, dsId, 15_000);
			const buildRowId = await buildRow.getAttribute('data-build-row');
			if (!buildRowId) throw new Error('Expected build row id');

			await buildRow.click();
			const detailRow = panel.locator(`[data-build-detail="${buildRowId}"]`);
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
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});
});

// ── Live build history (real e2e, no WS mocking) ───────────────────────────

test.describe('Monitoring – live build history', () => {
	test('triggering a build uses the normal output row and expands to BuildPreview', async ({
		page,
		request
	}) => {
		const dsName = `e2e-active-build-ds-${uid()}`;
		const aName = `E2E Active Build ${uid()}`;
		const dsId = await createLargeDatasource(request, dsName, 2000);
		const aId = await createMultiStepAnalysis(request, aName, dsId);
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
			if (buildId) {
				await shutdownBuildEngineViaUI(page, buildId).catch(() => undefined);
			}
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});
});
