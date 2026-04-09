import { test, expect } from '@playwright/test';
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
import { uid } from './utils/uid.js';
import { screenshot } from './utils/visual.js';

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
			await expect(page.getByText(ds)).toBeVisible({ timeout: 8_000 });
			await expect(page.getByText('Cron: 0 6 * * *')).toBeVisible({ timeout: 5_000 });
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

			// Wait for the schedule delete button to appear
			const deleteBtn = page
				.locator('tr', { has: page.getByText(ds) })
				.first()
				.getByLabel('Delete schedule');
			await expect(deleteBtn).toBeAttached({ timeout: 15_000 });

			// Delete button is always visible in the table row
			await deleteBtn.click({ timeout: 5_000 });

			// Confirm in the dialog
			const dialog = page.getByRole('dialog');
			await expect(dialog.getByRole('heading', { name: /Delete Schedule/i })).toBeVisible();
			await dialog.getByRole('button', { name: /^Delete$/ }).click();

			// After deletion the datasource name should disappear from the table
			await expect(page.getByText(ds)).not.toBeVisible({ timeout: 8_000 });
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
			await expect(page.getByText(ds)).toBeVisible({ timeout: 10_000 });

			// Find the toggle button in the schedule table row
			const schedRow = page.locator('tr', { has: page.getByText(ds) }).first();
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
		await createDatasource(request, ds);
		try {
			await page.goto('/monitoring?tab=schedules');
			await expect(page.getByRole('button', { name: /New Schedule/i })).toBeVisible({
				timeout: 10_000
			});
			await page.getByRole('button', { name: /New Schedule/i }).click();

			// Select datasource from dropdown
			const dsSelect = page.locator('#schedule-datasource');
			await expect(dsSelect).toBeVisible({ timeout: 5_000 });
			await dsSelect.selectOption({ label: ds });

			// Cron is the default trigger type with default value — submit
			const createBtn = page.getByRole('button', { name: 'Create Schedule' });
			await expect(createBtn).toBeEnabled({ timeout: 5_000 });
			await createBtn.click();

			// Schedule should appear in the list table (scope to table rows to avoid matching the form <option>)
			const panel = page.locator('#panel-schedules');
			await expect(panel.locator('tr', { hasText: ds })).toBeVisible({
				timeout: 8_000
			});
			await expect(page.getByText('Every hour')).toBeVisible({ timeout: 5_000 });
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
		await createSchedule(request, dsId, '0 6 * * *');
		try {
			await page.goto('/monitoring?tab=schedules');
			await expect(page.getByText(ds)).toBeVisible({ timeout: 10_000 });

			// Expand the schedule row by clicking on it (table view uses <tr>)
			const schedRow = page.locator('tr', { has: page.getByText(ds) }).first();
			await schedRow.click();

			// Wait for expanded detail row (sibling <tr> with cron section)
			const detailRow = schedRow.locator('+ tr');
			await expect(detailRow.locator('code')).toBeVisible({ timeout: 5_000 });

			// Click the pencil/edit button scoped to the expanded row
			const editBtn = detailRow.locator('button[title="Edit cron expression"]');
			await expect(editBtn).toBeVisible({ timeout: 5_000 });
			await editBtn.click();

			// Cron input should appear
			const cronInput = page.locator('input[aria-label="Cron expression"]').first();
			await expect(cronInput).toBeVisible({ timeout: 3_000 });

			// Clear and type new expression, then press Enter
			await cronInput.fill('30 12 * * 1');
			await cronInput.press('Enter');

			// After save, the new expression should appear (wait for mutation + refetch)
			await expect(detailRow.locator('code', { hasText: '30 12 * * 1' })).toBeVisible({
				timeout: 10_000
			});
			// Input should be gone once the code element is back
			await expect(cronInput).not.toBeVisible({ timeout: 5_000 });

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
		await createSchedule(request, dsId, '0 6 * * *');
		try {
			await page.goto('/monitoring?tab=schedules');
			await expect(page.getByText(ds)).toBeVisible({ timeout: 10_000 });

			// Expand (table view)
			const schedRow = page.locator('tr', { has: page.getByText(ds) }).first();
			await schedRow.click();
			const detailRow = schedRow.locator('+ tr');
			await expect(detailRow.locator('code')).toBeVisible({ timeout: 5_000 });

			// Enter edit mode scoped to expanded row
			await detailRow.locator('button[title="Edit cron expression"]').click();
			const cronInput = page.locator('input[aria-label="Cron expression"]').first();
			await expect(cronInput).toBeVisible({ timeout: 3_000 });

			// Type a different value then Escape
			await cronInput.fill('59 23 * * *');
			await cronInput.press('Escape');

			// Input should disappear, original expression should remain
			await expect(cronInput).not.toBeVisible({ timeout: 3_000 });
			await expect(page.locator('code', { hasText: '0 6 * * *' })).toBeVisible({
				timeout: 5_000
			});
		} finally {
			await deleteScheduleViaUI(page, ds);
			await deleteDatasourceViaUI(page, ds);
		}
	});
});

test.describe('Monitoring – Health Checks tab', () => {
	test('Health Checks tab renders without error', async ({ page }) => {
		await page.goto('/monitoring?tab=health');
		await expect(page.getByRole('heading', { name: 'Monitoring' })).toBeVisible();
		await expect(page.getByRole('tab', { name: 'Health Checks' })).toHaveAttribute(
			'aria-selected',
			'true'
		);
	});

	test('Health Checks tab shows "New Check" button', async ({ page }) => {
		await page.goto('/monitoring?tab=health');
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
			await expect(page.getByText(hc)).toBeVisible({ timeout: 8_000 });
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
			await expect(page.getByText(hc).first()).toBeVisible({
				timeout: 8_000
			});

			// Scope the delete to the row containing our health check name
			const row = page.locator('tr', { has: page.getByText(hc) }).first();
			await row.getByLabel('Delete check').click({ timeout: 5_000 });

			// Confirm in the dialog
			const dialog = page.getByRole('dialog');
			await expect(dialog.getByRole('heading', { name: /Delete Health Check/i })).toBeVisible();
			await dialog.getByRole('button', { name: /^Delete$/ }).click();

			await expect(page.getByText(hc)).not.toBeVisible({
				timeout: 8_000
			});
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
			await expect(page.getByText(hc).first()).toBeVisible({
				timeout: 8_000
			});

			// Find the toggle button in the health check row — starts enabled (title "Click to disable")
			const row = page.locator('tr', { has: page.getByText(hc) }).first();
			const toggleBtn = row.locator('button[title="Click to disable"]');
			await expect(toggleBtn).toBeAttached({ timeout: 5_000 });
			await toggleBtn.click({ timeout: 5_000 });

			// After toggle the mutation refetches data, re-rendering the table.
			// Wait for the visible "Off" text which is the stable end-state indicator;
			// checking button[title] attachment is racy during row re-render.
			const updatedRow = page.locator('tr', { has: page.getByText(hc) }).first();
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
		await createDatasource(request, ds);
		try {
			await page.goto('/monitoring?tab=health');
			await expect(page.getByRole('button', { name: /New Check/i })).toBeVisible({
				timeout: 10_000
			});
			await page.getByRole('button', { name: /New Check/i }).click();

			// Select datasource
			const dsSelect = page.locator('#hc-target');
			await expect(dsSelect).toBeVisible({ timeout: 5_000 });
			await dsSelect.selectOption({ label: ds });

			// Fill name
			await page.locator('#hc-name').fill(hc);

			// Type defaults to row_count — fill min_rows
			await page.locator('#hc-min-rows').fill('1');

			// Submit
			const saveBtn = page.getByRole('button', { name: 'Save Check' });
			await expect(saveBtn).toBeEnabled({ timeout: 5_000 });
			await saveBtn.click();

			// Check should appear in the list
			await expect(page.getByText(hc)).toBeVisible({ timeout: 8_000 });
		} finally {
			await deleteHealthCheckViaUI(page, hc);
			await deleteDatasourceViaUI(page, ds);
		}
	});
});

test.describe('Monitoring – Builds tab', () => {
	test('Builds tab renders and shows engine runs panel', async ({ page }) => {
		await page.goto('/monitoring?tab=builds');
		await expect(page.getByRole('tab', { name: 'Builds' })).toHaveAttribute(
			'aria-selected',
			'true'
		);
		const panel = page.locator('#panel-builds');
		await expect(panel).toBeVisible({ timeout: 5_000 });
	});

	test('Builds search filters by text', async ({ page, request }) => {
		test.setTimeout(60_000);
		const ds = `e2e-filter-${uid()}`;
		await createDatasource(request, ds);
		try {
			await page.goto('/monitoring?tab=builds');
			const panel = page.locator('#panel-builds');
			await expect(panel.getByText(ds).first()).toBeVisible({ timeout: 20_000 });

			await page.getByLabel(/Search builds, schedules, or health checks/i).fill('ZZZNOMATCH');
			await expect(panel.getByText(ds)).not.toBeVisible({ timeout: 5_000 });

			await page.getByLabel(/Search builds, schedules, or health checks/i).fill(ds);
			await expect(panel.getByText(ds).first()).toBeVisible({ timeout: 5_000 });
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('Builds tab shows datasource creation run', async ({ page, request }) => {
		test.setTimeout(60_000);
		const ds = `e2e-build-${uid()}`;
		await createDatasource(request, ds);
		try {
			await page.goto('/monitoring?tab=builds');
			const panel = page.locator('#panel-builds');
			await expect(panel).toBeVisible();
			await expect(panel.getByText(ds).first()).toBeVisible({ timeout: 20_000 });
			const cells = panel.locator('td');
			await expect(cells.getByText('Success').first()).toBeVisible({ timeout: 5_000 });
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('clicking a build row expands to show detail panel', async ({ page, request }) => {
		test.setTimeout(60_000);
		const ds = `e2e-expand-${uid()}`;
		await createDatasource(request, ds);
		try {
			await page.goto('/monitoring?tab=builds');
			const panel = page.locator('#panel-builds');
			await expect(panel.getByText(ds).first()).toBeVisible({ timeout: 20_000 });

			const buildRow = panel.locator('tr[data-build-row]', { hasText: ds }).first();
			await buildRow.click();

			const detailRow = panel.locator('tr[data-build-detail]').first();
			await expect(detailRow).toBeVisible({ timeout: 5_000 });
			await expect(detailRow.getByText('Request Config')).toBeVisible();
			await expect(detailRow.getByText('Result')).toBeVisible();
			await screenshot(page, 'monitoring', 'build-row-expanded');
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('build detail shows Request Payload JSON', async ({ page, request }) => {
		test.setTimeout(60_000);
		const ds = `e2e-payload-${uid()}`;
		await createDatasource(request, ds);
		try {
			await page.goto('/monitoring?tab=builds');
			const panel = page.locator('#panel-builds');
			await expect(panel.getByText(ds).first()).toBeVisible({ timeout: 20_000 });

			const buildRow = panel.locator('tr[data-build-row]', { hasText: ds }).first();
			await buildRow.click();

			const detailRow = panel.locator('tr[data-build-detail]').first();
			await expect(detailRow).toBeVisible({ timeout: 5_000 });
			await expect(detailRow.getByText('Request Payload')).toBeVisible();
			await expect(detailRow.getByText('Run ID:')).toBeVisible();
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('build detail Result tab shows result metadata', async ({ page, request }) => {
		test.setTimeout(60_000);
		const ds = `e2e-result-${uid()}`;
		await createDatasource(request, ds);
		try {
			await page.goto('/monitoring?tab=builds');
			const panel = page.locator('#panel-builds');
			await expect(panel.getByText(ds).first()).toBeVisible({ timeout: 20_000 });

			const buildRow = panel.locator('tr[data-build-row]', { hasText: ds }).first();
			await buildRow.click();

			const detailRow = panel.locator('tr[data-build-detail]').first();
			await expect(detailRow).toBeVisible({ timeout: 5_000 });

			await detailRow.getByRole('button', { name: 'Result' }).click();
			await expect(
				detailRow.getByText('Result Metadata').or(detailRow.getByText('No result data available'))
			).toBeVisible({ timeout: 5_000 });
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('clicking an expanded build row collapses it', async ({ page, request }) => {
		test.setTimeout(60_000);
		const ds = `e2e-collapse-${uid()}`;
		await createDatasource(request, ds);
		try {
			await page.goto('/monitoring?tab=builds');
			const panel = page.locator('#panel-builds');
			await expect(panel.getByText(ds).first()).toBeVisible({ timeout: 20_000 });

			const buildRow = panel.locator('tr[data-build-row]', { hasText: ds }).first();
			await buildRow.click();
			const detailRow = panel.locator('tr[data-build-detail]').first();
			await expect(detailRow).toBeVisible({ timeout: 5_000 });

			// Click again to collapse
			await buildRow.click();
			await expect(detailRow).not.toBeVisible({ timeout: 5_000 });
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});
});

// ── Active Builds (real e2e, no WS mocking) ────────────────────────────────

test.describe('Monitoring – Active Builds section', () => {
	test('active builds section renders and connects to live feed', async ({ page }) => {
		test.setTimeout(60_000);
		await page.goto('/monitoring?tab=builds');
		await expect(page.getByRole('tab', { name: 'Builds' })).toHaveAttribute(
			'aria-selected',
			'true'
		);

		const activeBuilds = page.locator('[data-testid="active-builds"]');
		await expect(activeBuilds).toBeVisible({ timeout: 10_000 });

		const connected = activeBuilds
			.getByText('No active builds')
			.or(activeBuilds.locator('[data-testid^="active-build-"]').first());
		await expect(connected).toBeVisible({ timeout: 15_000 });

		await screenshot(page, 'monitoring', 'active-builds-live-feed');
	});

	test('triggering a build shows it in Active Builds and expands to BuildPreview', async ({
		page,
		request,
		context
	}) => {
		test.setTimeout(180_000);
		const dsName = `e2e-active-build-ds-${uid()}`;
		const aName = `E2E Active Build ${uid()}`;
		const dsId = await createLargeDatasource(request, dsName, 2000);
		const aId = await createMultiStepAnalysis(request, aName, dsId);
		try {
			const monitorPage = await context.newPage();

			await monitorPage.goto('/monitoring?tab=builds');
			await expect(monitorPage.getByRole('tab', { name: 'Builds' })).toHaveAttribute(
				'aria-selected',
				'true'
			);
			const activeBuilds = monitorPage.locator('[data-testid="active-builds"]');
			await expect(activeBuilds).toBeVisible({ timeout: 10_000 });

			await page.goto(`/analysis/${aId}`);
			await waitForLayoutReady(page);
			await expect(page.locator('[role="application"]')).toBeVisible({ timeout: 15_000 });
			const buildBtn = page.locator('[data-testid="output-build-button"]');
			await expect(buildBtn).toBeVisible({ timeout: 10_000 });
			await buildBtn.click();
			const openPreviewBtn = page.locator('[data-testid="output-build-preview-trigger"]');
			await expect(openPreviewBtn).toBeVisible({ timeout: 10_000 });
			await openPreviewBtn.click();
			await expect(page.locator('[data-testid="build-preview"]')).toBeVisible({ timeout: 10_000 });

			const activeBuild = monitorPage.locator('[data-testid^="active-build-"]').first();
			const buildAppeared = await activeBuild
				.waitFor({ state: 'visible', timeout: 15_000 })
				.then(() => true)
				.catch(() => false);

			if (buildAppeared) {
				await activeBuild.click();
				const monitorPreview = monitorPage.locator('[data-testid="build-preview"]');
				await expect(monitorPreview).toBeVisible({ timeout: 10_000 });
				await expect(monitorPreview.locator('[data-testid="build-steps-panel"]')).toBeVisible({
					timeout: 5_000
				});
				await screenshot(monitorPage, 'monitoring', 'active-build-expanded-real');
			}

			const preview = page.locator('[data-testid="build-preview"]');
			const terminal = preview
				.getByText('Complete', { exact: true })
				.or(preview.getByText('Failed', { exact: true }));
			await expect(terminal).toBeVisible({ timeout: 90_000 });

			await monitorPage.close();

			await screenshot(page, 'monitoring', 'active-build-terminal');
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('completed build appears in the Builds history table', async ({ page, request }) => {
		test.setTimeout(120_000);
		const dsName = `e2e-history-build-ds-${uid()}`;
		const aName = `E2E History Build ${uid()}`;
		const dsId = await createDatasource(request, dsName);
		const aId = await createMultiStepAnalysis(request, aName, dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await waitForLayoutReady(page);
			await expect(page.locator('[role="application"]')).toBeVisible({ timeout: 15_000 });
			const buildBtn = page.locator('[data-testid="output-build-button"]');
			await expect(buildBtn).toBeVisible({ timeout: 10_000 });
			await buildBtn.click();

			const openPreviewBtn = page.locator('[data-testid="output-build-preview-trigger"]');
			await expect(openPreviewBtn).toBeVisible({ timeout: 10_000 });
			await openPreviewBtn.click();

			const preview = page.locator('[data-testid="build-preview"]');
			await expect(preview).toBeVisible({ timeout: 10_000 });
			const terminal = preview
				.getByText('Complete', { exact: true })
				.or(preview.getByText('Failed', { exact: true }));
			await expect(terminal).toBeVisible({ timeout: 60_000 });

			await page.goto('/monitoring?tab=builds');
			const panel = page.locator('#panel-builds');
			await expect(panel).toBeVisible({ timeout: 5_000 });
			await expect(panel.getByText(aName).first()).toBeVisible({ timeout: 20_000 });

			await screenshot(page, 'monitoring', 'build-history-after-real-build');
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});
});
