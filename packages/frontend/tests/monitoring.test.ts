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
	deleteAnalysisViaUI
} from './utils/ui-cleanup.js';
import { waitForLayoutReady } from './utils/readiness.js';
import { gotoAnalysisEditor } from './utils/analysis.js';
import { uid } from './utils/uid.js';
import { screenshot } from './utils/visual.js';
import { dialogByHeading } from './utils/locators.js';

async function waitForHealthChecksList(page: import('@playwright/test').Page, timeout = 30_000) {
	const panel = page.locator('#panel-health');
	await expect(panel).toBeVisible({ timeout });
	const terminal = panel.locator(
		'[data-healthcheck-row], :text("No health checks configured."), :text("No health checks match your search."), :text("Failed to load health checks.")'
	);
	await expect
		.poll(
			async () => {
				const count = await terminal.count();
				for (let index = 0; index < count; index += 1) {
					if (
						await terminal
							.nth(index)
							.isVisible()
							.catch(() => false)
					) {
						return true;
					}
				}
				return false;
			},
			{ timeout }
		)
		.toBe(true);
	return panel;
}

async function waitForHealthCheckRow(
	page: import('@playwright/test').Page,
	name: string,
	timeout = 30_000
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
	timeout = 30_000
) {
	await expect
		.poll(
			async () => {
				return select.evaluate(
					(node, optionValue) =>
						Array.from((node as HTMLSelectElement).options).some(
							(option) => option.value === optionValue
						),
					value
				);
			},
			{ timeout }
		)
		.toBe(true);
}

async function startBuildFromAnalysisPage(
	page: import('@playwright/test').Page,
	analysisId: string,
	previousBuildId?: string | null
): Promise<string> {
	await gotoAnalysisEditor(page, analysisId);
	const buildBtn = page.locator('[data-testid="output-build-button"]');
	await expect(buildBtn).toBeVisible({ timeout: 10_000 });
	await buildBtn.click({ timeout: 30_000 });
	await expect(page.locator('[data-testid="output-build-preview-trigger"]')).toBeVisible({
		timeout: 30_000
	});
	await expect
		.poll(
			async () => {
				const buildId = await previewBuildId(page);
				return buildId && buildId !== previousBuildId ? buildId : null;
			},
			{ timeout: 30_000 }
		)
		.toBeTruthy();
	return (await previewBuildId(page)).trim();
}

async function openBuildPreview(page: import('@playwright/test').Page) {
	const preview = page.locator('[data-testid="build-preview"]');
	if (await preview.isVisible().catch(() => false)) {
		return preview;
	}
	const openPreviewBtn = page.locator('[data-testid="output-build-preview-trigger"]');
	await expect(openPreviewBtn).toBeVisible({ timeout: 10_000 });
	await openPreviewBtn.click();
	await expect(preview).toBeVisible({ timeout: 10_000 });
	return preview;
}

async function previewBuildId(page: import('@playwright/test').Page): Promise<string> {
	const preview = await openBuildPreview(page);
	const id = preview.locator('[data-testid="build-preview-id"]');
	await expect(id).toHaveText(/\S+/, { timeout: 30_000 });
	return (await id.textContent())?.trim() ?? '';
}

async function refreshBuildHistory(page: import('@playwright/test').Page) {
	await page.getByRole('button', { name: /Refresh History/i }).click();
}

async function waitForBuildRowById(
	page: import('@playwright/test').Page,
	panel: ReturnType<import('@playwright/test').Page['locator']>,
	buildId: string,
	statuses: Array<'queued' | 'running' | 'completed' | 'failed' | 'cancelled'>,
	timeout = 120_000
) {
	const started = Date.now();
	while (Date.now() - started < timeout) {
		for (const status of statuses) {
			const row = panel.locator(`[data-build-row="${buildId}"][data-build-status="${status}"]`);
			if (await row.isVisible().catch(() => false)) {
				return row;
			}
		}
		await refreshBuildHistory(page);
		await page.waitForTimeout(1_000);
	}
	throw new Error(`Timed out waiting for build row ${buildId}`);
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

	test('search input is present', async ({ page }) => {
		await expect(page.getByLabel(/Search builds, schedules, or health checks/i)).toBeVisible();
	});

	test('typing in search does not crash the page', async ({ page }) => {
		await page.getByLabel(/Search builds, schedules, or health checks/i).fill('test query');
		await expect(page.getByRole('heading', { name: 'Monitoring' })).toBeVisible();
	});
});

test.describe('Monitoring – Schedules tab', () => {
	test('Schedules tab shows schedule list or empty state', async ({ page }) => {
		await page.goto('/monitoring?tab=schedules');
		// Either a schedule list or an empty/create state
		const panel = page.locator('#panel-schedules');
		await expect(panel).toBeVisible();
	});

	test('Schedules tab shows "New Schedule" button', async ({ page }) => {
		await page.goto('/monitoring?tab=schedules');
		await expect(page.getByRole('button', { name: /New Schedule/i })).toBeVisible({
			timeout: 10_000
		});
		await screenshot(page, 'monitoring', 'schedules-tab');
	});

	test('created schedule appears in the Schedules tab', async ({ page, request }) => {
		const ds = `e2e-sched-${uid()}`;
		const dsId = await createDatasource(request, ds);
		await createSchedule(request, dsId, '0 6 * * *');
		try {
			await page.goto('/monitoring?tab=schedules');
			const schedRow = page.locator(`tr[data-datasource-id="${dsId}"]`);
			await expect(schedRow).toBeVisible({ timeout: 8_000 });
			await expect(schedRow).toContainText('Cron: 0 6 * * *', { timeout: 5_000 });
		} finally {
			await deleteScheduleViaUI(page, ds);
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('schedule can be deleted via UI', async ({ page, request }) => {
		test.setTimeout(60_000);
		const ds = `e2e-sched-del-${uid()}`;
		const dsId = await createDatasource(request, ds);
		await createSchedule(request, dsId, '0 7 * * *');

		try {
			await page.goto('/monitoring?tab=schedules');

			const schedRow = page.locator(`tr[data-datasource-id="${dsId}"]`);
			const deleteBtn = schedRow.getByLabel('Delete schedule');
			await expect(deleteBtn).toBeAttached({ timeout: 15_000 });

			// Delete button is always visible in the table row
			await deleteBtn.click({ timeout: 5_000 });

			// Confirm in the dialog
			const dialog = dialogByHeading(page, /Delete Schedule/i);
			await expect(dialog).toBeVisible();
			await dialog.getByRole('button', { name: /^Delete$/ }).click();

			await expect(schedRow).toHaveCount(0, { timeout: 8_000 });
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('schedule enable/disable toggle works', async ({ page, request }) => {
		test.setTimeout(60_000);
		const ds = `e2e-sched-toggle-${uid()}`;
		const dsId = await createDatasource(request, ds);
		await createSchedule(request, dsId, '0 8 * * *');
		try {
			await page.goto('/monitoring?tab=schedules');
			const schedRow = page.locator(`tr[data-datasource-id="${dsId}"]`);
			await expect(schedRow).toBeVisible({ timeout: 10_000 });

			const toggleBtn = schedRow.locator('button[title="Click to disable"]');
			await expect(toggleBtn).toBeAttached({ timeout: 5_000 });
			await toggleBtn.click({ timeout: 5_000 });

			// After toggle, the button title should change to "Click to enable"
			await expect(schedRow.locator('button[title="Click to enable"]')).toBeAttached({
				timeout: 8_000
			});
		} finally {
			await deleteScheduleViaUI(page, ds);
			await deleteDatasourceViaUI(page, ds);
		}
	});
});

test.describe('Monitoring – Schedule create flow', () => {
	test('create schedule via UI form', async ({ page, request }) => {
		test.setTimeout(60_000);
		const ds = `e2e-sched-create-${uid()}`;
		const dsId = await createDatasource(request, ds);
		try {
			await page.goto('/monitoring?tab=schedules');
			await expect(page.getByRole('button', { name: /New Schedule/i })).toBeVisible({
				timeout: 10_000
			});
			await page.getByRole('button', { name: /New Schedule/i }).click();

			// Select datasource from dropdown
			const dsSelect = page.locator('#schedule-datasource');
			await expect(dsSelect).toBeVisible({ timeout: 5_000 });
			await waitForSelectOption(dsSelect, dsId, 10_000);
			await dsSelect.selectOption(dsId);

			// Cron is the default trigger type with default value — submit
			const createBtn = page.getByRole('button', { name: 'Create Schedule' });
			await expect(createBtn).toBeEnabled({ timeout: 5_000 });
			await createBtn.click();

			// Datasource name resolution can lag the row render, but datasource_id is stable immediately.
			const schedRow = page.locator(`tr[data-datasource-id="${dsId}"]`);
			await expect(schedRow).toBeVisible({ timeout: 8_000 });
			await expect(schedRow).toContainText('Every hour', { timeout: 5_000 });
		} finally {
			await deleteScheduleViaUI(page, ds);
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('schedule create form Cancel closes form without creating', async ({ page, request }) => {
		test.setTimeout(60_000);
		const ds = `e2e-sched-cancel-${uid()}`;
		await createDatasource(request, ds);
		try {
			await page.goto('/monitoring?tab=schedules');
			await page.getByRole('button', { name: /New Schedule/i }).click({ timeout: 10_000 });

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
		test.setTimeout(60_000);
		const ds = `e2e-sched-cron-${uid()}`;
		const dsId = await createDatasource(request, ds);
		const scheduleId = await createSchedule(request, dsId, '0 6 * * *');
		try {
			await page.goto('/monitoring?tab=schedules');

			// Expand the schedule row by clicking on it (table view uses <tr>)
			const schedRow = page.locator(`[data-schedule-row="${scheduleId}"]`);
			await expect(schedRow).toBeVisible({ timeout: 10_000 });
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
			await cronInput.press('Enter');

			// Refetch re-renders the expanded row, so re-open it before checking persisted text.
			await page.goto('/monitoring?tab=schedules');
			await expect(schedRow).toBeVisible({ timeout: 10_000 });
			await schedRow.click();
			await expect(page.locator(`[data-schedule-detail="${scheduleId}"] code`)).toContainText(
				'30 12 * * 1',
				{ timeout: 10_000 }
			);

			await screenshot(page, 'monitoring', 'schedule-cron-edited');
		} finally {
			await deleteScheduleViaUI(page, ds);
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('inline cron edit: Escape cancels without saving', async ({ page, request }) => {
		test.setTimeout(60_000);
		const ds = `e2e-sched-cron-esc-${uid()}`;
		const dsId = await createDatasource(request, ds);
		const scheduleId = await createSchedule(request, dsId, '0 6 * * *');
		try {
			await page.goto('/monitoring?tab=schedules');

			// Expand (table view)
			const schedRow = page.locator(`[data-schedule-row="${scheduleId}"]`);
			await expect(schedRow).toBeVisible({ timeout: 10_000 });
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
			await deleteDatasourceViaUI(page, ds);
		}
	});
});

test.describe('Monitoring – Health Checks tab', () => {
	test('Health Checks tab renders without error', async ({ page }) => {
		await page.goto('/monitoring?tab=health');
		await waitForHealthChecksList(page);
		await expect(page.getByRole('heading', { name: 'Monitoring' })).toBeVisible();
		await expect(page.getByRole('tab', { name: 'Health Checks' })).toHaveAttribute(
			'aria-selected',
			'true'
		);
	});

	test('Health Checks tab shows "New Check" button', async ({ page }) => {
		await page.goto('/monitoring?tab=health');
		await waitForHealthChecksList(page);
		await expect(page.getByRole('button', { name: /New Check/i })).toBeVisible({ timeout: 8_000 });
		await screenshot(page, 'monitoring', 'health-checks-tab');
	});

	test('created health check appears in list', async ({ page, request }) => {
		const id = uid();
		const ds = `e2e-hc-${id}`;
		const hc = `e2e Row Count ${id}`;
		const dsId = await createDatasource(request, ds);
		await createHealthCheck(request, dsId, hc);
		try {
			await page.goto('/monitoring?tab=health');
			await waitForHealthCheckRow(page, hc);
		} finally {
			await deleteHealthCheckViaUI(page, hc);
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('health check delete button removes it from list', async ({ page, request }) => {
		const id = uid();
		const ds = `e2e-hc-del-${id}`;
		const hc = `e2e Delete HC ${id}`;
		const dsId = await createDatasource(request, ds);
		await createHealthCheck(request, dsId, hc);

		try {
			await page.goto('/monitoring?tab=health');
			const row = await waitForHealthCheckRow(page, hc);
			await row.getByLabel('Delete check').click({ timeout: 5_000 });

			// Confirm in the dialog
			const dialog = dialogByHeading(page, /Delete Health Check/i);
			await expect(dialog).toBeVisible();
			await dialog.getByRole('button', { name: /^Delete$/ }).click();

			await expect(row).toHaveCount(0, { timeout: 8_000 });
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('health check enable/disable toggle works', async ({ page, request }) => {
		test.setTimeout(60_000);
		const id = uid();
		const ds = `e2e-hc-toggle-${id}`;
		const hc = `e2e Toggle HC ${id}`;
		const dsId = await createDatasource(request, ds);
		await createHealthCheck(request, dsId, hc);
		try {
			await page.goto('/monitoring?tab=health');
			const row = await waitForHealthCheckRow(page, hc);
			const toggleBtn = row.locator('button[title="Click to disable"]');
			await expect(toggleBtn).toBeAttached({ timeout: 5_000 });
			await toggleBtn.click({ timeout: 5_000 });

			await waitForHealthChecksList(page);
			const updatedRow = await waitForHealthCheckRow(page, hc);
			await expect(updatedRow.getByText('Off')).toBeVisible({ timeout: 10_000 });

			await screenshot(page, 'monitoring', 'health-check-toggled-off');
		} finally {
			await deleteHealthCheckViaUI(page, hc);
			await deleteDatasourceViaUI(page, ds);
		}
	});
});

test.describe('Monitoring – Health Check create flow', () => {
	test('create health check via UI form', async ({ page, request }) => {
		test.setTimeout(60_000);
		const id = uid();
		const ds = `e2e-hc-create-${id}`;
		const hc = `e2e UI Check ${id}`;
		const dsId = await createDatasource(request, ds);
		try {
			await page.goto('/monitoring?tab=health');
			await expect(page.getByRole('button', { name: /New Check/i })).toBeVisible({
				timeout: 10_000
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
			await deleteDatasourceViaUI(page, ds);
		}
	});
});

test.describe('Monitoring – Builds tab', () => {
	test('Builds tab renders and shows builds panel', async ({ page }) => {
		await page.goto('/monitoring?tab=builds');
		await expect(page.getByRole('tab', { name: 'Builds' })).toHaveAttribute(
			'aria-selected',
			'true'
		);
		const panel = page.locator('#panel-builds');
		await expect(panel).toBeVisible({ timeout: 5_000 });
	});

	test('datasource preview runs appear as Preview rows', async ({ page, request }) => {
		test.setTimeout(120_000);
		const ds = `e2e-preview-${uid()}`;
		const dsId = await createDatasource(request, ds);
		try {
			await page.goto(`/datasources?id=${dsId}`);
			await expect(page.locator('[data-preview-ready="true"]')).toBeVisible({ timeout: 60_000 });

			await page.goto('/monitoring?tab=builds');
			const panel = page.locator('#panel-builds');
			await expect(panel).toBeVisible({ timeout: 10_000 });
			await page.getByLabel(/Search builds, schedules, or health checks/i).fill(ds);
			const previewRow = panel
				.locator(`[data-build-kind="preview"][data-build-datasource-id="${dsId}"]`)
				.first();
			await expect(previewRow).toBeVisible({ timeout: 30_000 });
			await expect(previewRow).toContainText('Preview');
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('Builds search filters by text', async ({ page, request }) => {
		test.setTimeout(180_000);
		const ds = `e2e-filter-${uid()}`;
		const analysisName = `E2E Builds Filter ${uid()}`;
		const dsId = await createDatasource(request, ds);
		const analysisId = await createMultiStepAnalysis(request, analysisName, dsId);
		try {
			const buildId = await startBuildFromAnalysisPage(page, analysisId);
			await page.goto(`/monitoring?tab=builds&analysis_id=${analysisId}`);
			const panel = page.locator('#panel-builds');
			const buildRow = await waitForBuildRowById(page, panel, buildId, ['completed', 'failed']);
			await expect(buildRow).toBeVisible({ timeout: 20_000 });

			await page.getByLabel(/Search builds, schedules, or health checks/i).fill('ZZZNOMATCH');
			await expect(buildRow).not.toBeVisible({ timeout: 5_000 });

			await page.getByLabel(/Search builds, schedules, or health checks/i).fill(analysisName);
			await expect(buildRow).toBeVisible({ timeout: 5_000 });
		} finally {
			await deleteAnalysisViaUI(page, analysisName);
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('clicking a build row expands to show detail panel without request loop', async ({
		page,
		request
	}) => {
		test.setTimeout(180_000);
		const ds = `e2e-expand-${uid()}`;
		const analysisName = `E2E Builds Expand ${uid()}`;
		const dsId = await createDatasource(request, ds);
		const analysisId = await createMultiStepAnalysis(request, analysisName, dsId);
		try {
			const buildId = await startBuildFromAnalysisPage(page, analysisId);
			await page.goto(`/monitoring?tab=builds&analysis_id=${analysisId}`);
			const panel = page.locator('#panel-builds');
			const buildRow = await waitForBuildRowById(page, panel, buildId, ['completed', 'failed']);
			await expect(buildRow).toHaveAttribute('data-build-kind', 'build');
			await expect(buildRow).toContainText('Build');
			await expect(buildRow).not.toContainText('Preview');

			let detailRequests = 0;
			page.on('request', (req) => {
				if (req.url().includes(`/api/v1/compute/builds/${buildId}`)) detailRequests += 1;
			});

			await buildRow.click();
			const buildRowId = await buildRow.getAttribute('data-build-row');
			if (!buildRowId) throw new Error('Expected build row id');

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
			await page.waitForTimeout(2_000);
			expect(detailRequests).toBeLessThanOrEqual(2);
			await screenshot(page, 'monitoring', 'build-row-expanded');
		} finally {
			await deleteAnalysisViaUI(page, analysisName);
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('build detail shows Request Payload JSON', async ({ page, request }) => {
		test.setTimeout(180_000);
		const ds = `e2e-payload-${uid()}`;
		const analysisName = `E2E Builds Payload ${uid()}`;
		const dsId = await createDatasource(request, ds);
		const analysisId = await createMultiStepAnalysis(request, analysisName, dsId);
		try {
			const buildId = await startBuildFromAnalysisPage(page, analysisId);
			await page.goto(`/monitoring?tab=builds&analysis_id=${analysisId}`);
			const panel = page.locator('#panel-builds');
			const buildRow = await waitForBuildRowById(page, panel, buildId, [
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
			await deleteAnalysisViaUI(page, analysisName);
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('single build appears once in Monitoring history', async ({ page, request }) => {
		test.setTimeout(180_000);
		const ds = `e2e-build-once-${uid()}`;
		const analysisName = `E2E Single Build Row ${uid()}`;
		const dsId = await createDatasource(request, ds);
		const analysisId = await createMultiStepAnalysis(request, analysisName, dsId);
		try {
			const buildId = await startBuildFromAnalysisPage(page, analysisId);
			await page.goto(`/monitoring?tab=builds&analysis_id=${analysisId}`);
			const panel = page.locator('#panel-builds');
			const buildRow = await waitForBuildRowById(page, panel, buildId, [
				'queued',
				'running',
				'completed',
				'failed'
			]);
			await expect(buildRow).toHaveAttribute('data-build-kind', 'build');
			await expect(
				panel.locator(`[data-build-kind="build"][data-build-analysis-id="${analysisId}"]`)
			).toHaveCount(1);
		} finally {
			await deleteAnalysisViaUI(page, analysisName);
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('four consecutive builds complete successfully as Build rows while preview rows remain Preview-kind', async ({
		page,
		request
	}) => {
		test.setTimeout(360_000);
		const ds = `e2e-build-vs-preview-${uid()}`;
		const analysisName = `E2E Build Determinism ${uid()}`;
		const dsId = await createDatasource(request, ds);
		const analysisId = await createMultiStepAnalysis(request, analysisName, dsId);
		try {
			const monitorPage = await page.context().newPage();
			await monitorPage.goto(`/monitoring?tab=builds&analysis_id=${analysisId}`);
			const panel = monitorPage.locator('#panel-builds');
			await expect(panel).toBeVisible({ timeout: 10_000 });

			let previousBuildId: string | null = null;
			for (let i = 0; i < 4; i += 1) {
				const buildId = await startBuildFromAnalysisPage(page, analysisId, previousBuildId);
				previousBuildId = buildId;
				const row = await waitForBuildRowById(monitorPage, panel, buildId, ['completed'], 180_000);
				await expect(row).toHaveAttribute('data-build-kind', 'build');
				await expect(row).toHaveAttribute('data-build-status', 'completed');
				await expect(row).toContainText('Build');
				await expect(row).not.toContainText('Preview');
				await row.click();
				const rowId = await row.getAttribute('data-build-row');
				if (!rowId) throw new Error('Expected build row id');
				const detailRow = panel.locator(`[data-build-detail="${rowId}"]`);
				await expect(detailRow.locator('[data-testid="build-preview"]')).toBeVisible({
					timeout: 8_000
				});
			}

			await page.goto('/datasources');
			await page.locator(`[data-ds-row="${ds}"]`).click();
			await expect(page.locator('[data-preview-ready="true"]')).toBeVisible({ timeout: 60_000 });

			await monitorPage.goto('/monitoring?tab=builds');
			await monitorPage.getByLabel(/Search builds, schedules, or health checks/i).fill(ds);
			const previewRow = panel
				.locator(`[data-build-kind="preview"][data-build-datasource-id="${dsId}"]`)
				.first();
			await expect(previewRow).toBeVisible({ timeout: 30_000 });
			await expect(previewRow).toContainText('Preview');
			await monitorPage.close();
		} finally {
			await deleteAnalysisViaUI(page, analysisName);
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
		test.setTimeout(240_000);
		const dsName = `e2e-active-build-ds-${uid()}`;
		const aName = `E2E Active Build ${uid()}`;
		const dsId = await createLargeDatasource(request, dsName, 2000);
		const aId = await createMultiStepAnalysis(request, aName, dsId);
		try {
			const monitorPage = await page.context().newPage();

			await monitorPage.goto(`/monitoring?tab=builds&analysis_id=${aId}`);
			await waitForLayoutReady(monitorPage);
			await expect(monitorPage.getByRole('tab', { name: 'Builds' })).toHaveAttribute(
				'aria-selected',
				'true'
			);
			const monitorPanel = monitorPage.locator('#panel-builds');
			await expect(monitorPanel).toBeVisible({ timeout: 10_000 });

			const buildId = await startBuildFromAnalysisPage(page, aId);

			const monitorBuildRow = await waitForBuildRowById(
				monitorPage,
				monitorPanel,
				buildId,
				['queued', 'running', 'completed', 'failed'],
				180_000
			);
			await monitorBuildRow.click();
			const monitorBuildRowId = await monitorBuildRow.getAttribute('data-build-row');
			if (!monitorBuildRowId) throw new Error('Expected monitor build row id');
			const monitorPreview = monitorPanel
				.locator(`[data-build-detail="${monitorBuildRowId}"]`)
				.locator('[data-testid="build-preview"]');
			await expect(monitorPreview).toBeVisible({ timeout: 10_000 });
			await expect(monitorPreview.locator('[data-testid="build-steps-panel"]')).toBeVisible({
				timeout: 5_000
			});
			await screenshot(monitorPage, 'monitoring', 'build-history-expanded-real');

			await monitorPage.close();

			await screenshot(page, 'monitoring', 'build-history-terminal');
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});
});
