import { test, expect } from '@playwright/test';
import { createDatasource, createSchedule, createHealthCheck } from './utils/api.js';
import {
	deleteDatasourceViaUI,
	deleteScheduleViaUI,
	deleteHealthCheckViaUI
} from './utils/ui-cleanup.js';
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
		const dsId = await createDatasource(request, 'e2e-sched-ds');
		await createSchedule(request, dsId, '0 6 * * *');
		try {
			await page.goto('/monitoring?tab=schedules');
			await expect(page.getByText('e2e-sched-ds')).toBeVisible({ timeout: 8_000 });
			await expect(page.getByText('Cron: 0 6 * * *')).toBeVisible({ timeout: 5_000 });
		} finally {
			await deleteScheduleViaUI(page, 'e2e-sched-ds');
			await deleteDatasourceViaUI(page, 'e2e-sched-ds');
		}
	});

	test('schedule can be deleted via UI', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-sched-del-ds');
		await createSchedule(request, dsId, '0 7 * * *');

		await page.goto('/monitoring?tab=schedules');

		// Wait for the schedule delete button to appear
		const deleteBtn = page
			.locator('tr', { has: page.getByText('e2e-sched-del-ds') })
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
		await expect(page.getByText('e2e-sched-del-ds')).not.toBeVisible({ timeout: 8_000 });

		// Cleanup the datasource
		await deleteDatasourceViaUI(page, 'e2e-sched-del-ds');
	});

	test('schedule enable/disable toggle works', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-sched-toggle-ds');
		await createSchedule(request, dsId, '0 8 * * *');
		try {
			await page.goto('/monitoring?tab=schedules');
			await expect(page.getByText('e2e-sched-toggle-ds')).toBeVisible({ timeout: 10_000 });

			// Find the toggle button in the schedule table row
			const schedRow = page.locator('tr', { has: page.getByText('e2e-sched-toggle-ds') }).first();
			const toggleBtn = schedRow.locator('button[title="Click to disable"]');
			await expect(toggleBtn).toBeAttached({ timeout: 5_000 });
			await toggleBtn.click({ timeout: 5_000 });

			// After toggle, the button title should change to "Click to enable"
			await expect(schedRow.locator('button[title="Click to enable"]')).toBeAttached({
				timeout: 8_000
			});
		} finally {
			await deleteScheduleViaUI(page, 'e2e-sched-toggle-ds');
			await deleteDatasourceViaUI(page, 'e2e-sched-toggle-ds');
		}
	});
});

test.describe('Monitoring – Schedule create flow', () => {
	test('create schedule via UI form', async ({ page, request }) => {
		test.setTimeout(60_000);
		await createDatasource(request, 'e2e-sched-create-ds');
		try {
			await page.goto('/monitoring?tab=schedules', { waitUntil: 'networkidle' });
			await expect(page.getByRole('button', { name: /New Schedule/i })).toBeVisible({
				timeout: 10_000
			});
			await page.getByRole('button', { name: /New Schedule/i }).click();

			// Select datasource from dropdown
			const dsSelect = page.locator('#schedule-datasource');
			await expect(dsSelect).toBeVisible({ timeout: 5_000 });
			await dsSelect.selectOption({ label: 'e2e-sched-create-ds' });

			// Cron is the default trigger type with default value — submit
			const createBtn = page.getByRole('button', { name: 'Create Schedule' });
			await expect(createBtn).toBeEnabled({ timeout: 5_000 });
			await createBtn.click();

			// Schedule should appear in the list table (scope to table rows to avoid matching the form <option>)
			const panel = page.locator('#panel-schedules');
			await expect(panel.locator('tr', { hasText: 'e2e-sched-create-ds' })).toBeVisible({
				timeout: 8_000
			});
			await expect(page.getByText('Every hour')).toBeVisible({ timeout: 5_000 });
		} finally {
			await deleteScheduleViaUI(page, 'e2e-sched-create-ds');
			await deleteDatasourceViaUI(page, 'e2e-sched-create-ds');
		}
	});

	test('schedule create form Cancel closes form without creating', async ({ page, request }) => {
		test.setTimeout(60_000);
		await createDatasource(request, 'e2e-sched-cancel-ds');
		try {
			await page.goto('/monitoring?tab=schedules');
			await page.getByRole('button', { name: /New Schedule/i }).click({ timeout: 10_000 });

			await expect(page.locator('#schedule-datasource')).toBeVisible({ timeout: 5_000 });

			// Click Cancel
			await page.getByRole('button', { name: 'Cancel' }).click();

			// Form should be gone — the datasource dropdown should not be visible
			await expect(page.locator('#schedule-datasource')).not.toBeVisible({ timeout: 5_000 });
		} finally {
			await deleteDatasourceViaUI(page, 'e2e-sched-cancel-ds');
		}
	});
});

test.describe('Monitoring – Schedule inline cron edit', () => {
	test('inline cron edit: pencil → input → Enter saves new expression', async ({
		page,
		request
	}) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-sched-cron-ds');
		await createSchedule(request, dsId, '0 6 * * *');
		try {
			await page.goto('/monitoring?tab=schedules');
			await expect(page.getByText('e2e-sched-cron-ds')).toBeVisible({ timeout: 10_000 });

			// Expand the schedule row by clicking on it (table view uses <tr>)
			const schedRow = page.locator('tr', { has: page.getByText('e2e-sched-cron-ds') }).first();
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

			// After save, the input should disappear and new expression should show
			await expect(cronInput).not.toBeVisible({ timeout: 5_000 });
			await expect(detailRow.locator('code', { hasText: '30 12 * * 1' })).toBeVisible({
				timeout: 5_000
			});

			await screenshot(page, 'monitoring', 'schedule-cron-edited');
		} finally {
			await deleteScheduleViaUI(page, 'e2e-sched-cron-ds');
			await deleteDatasourceViaUI(page, 'e2e-sched-cron-ds');
		}
	});

	test('inline cron edit: Escape cancels without saving', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-sched-cron-esc-ds');
		await createSchedule(request, dsId, '0 6 * * *');
		try {
			await page.goto('/monitoring?tab=schedules');
			await expect(page.getByText('e2e-sched-cron-esc-ds')).toBeVisible({ timeout: 10_000 });

			// Expand (table view)
			const schedRow = page.locator('tr', { has: page.getByText('e2e-sched-cron-esc-ds') }).first();
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
			await deleteScheduleViaUI(page, 'e2e-sched-cron-esc-ds');
			await deleteDatasourceViaUI(page, 'e2e-sched-cron-esc-ds');
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
		const dsId = await createDatasource(request, 'e2e-hc-ds');
		await createHealthCheck(request, dsId, 'e2e Row Count Check');
		try {
			await page.goto('/monitoring?tab=health');
			await expect(page.getByText('e2e Row Count Check')).toBeVisible({ timeout: 8_000 });
		} finally {
			await deleteHealthCheckViaUI(page, 'e2e Row Count Check');
			await deleteDatasourceViaUI(page, 'e2e-hc-ds');
		}
	});

	test('health check delete button removes it from list', async ({ page, request }) => {
		const dsId = await createDatasource(request, 'e2e-hc-del-ds');
		await createHealthCheck(request, dsId, 'e2e Delete Health Check');

		await page.goto('/monitoring?tab=health');
		await expect(page.getByText('e2e Delete Health Check').first()).toBeVisible({
			timeout: 8_000
		});

		// Scope the delete to the row containing our health check name
		const row = page.locator('tr', { has: page.getByText('e2e Delete Health Check') }).first();
		await row.getByLabel('Delete check').click({ timeout: 5_000 });

		// Confirm in the dialog
		const dialog = page.getByRole('dialog');
		await expect(dialog.getByRole('heading', { name: /Delete Health Check/i })).toBeVisible();
		await dialog.getByRole('button', { name: /^Delete$/ }).click();

		await expect(page.getByText('e2e Delete Health Check')).not.toBeVisible({
			timeout: 8_000
		});

		// Cleanup the datasource
		await deleteDatasourceViaUI(page, 'e2e-hc-del-ds');
	});

	test('health check enable/disable toggle works', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsId = await createDatasource(request, 'e2e-hc-toggle-ds');
		await createHealthCheck(request, dsId, 'e2e Toggle Health Check');
		try {
			await page.goto('/monitoring?tab=health');
			await expect(page.getByText('e2e Toggle Health Check').first()).toBeVisible({
				timeout: 8_000
			});

			// Find the toggle button in the health check row — starts enabled (title "Click to disable")
			const row = page.locator('tr', { has: page.getByText('e2e Toggle Health Check') }).first();
			const toggleBtn = row.locator('button[title="Click to disable"]');
			await expect(toggleBtn).toBeAttached({ timeout: 5_000 });
			await toggleBtn.click({ timeout: 5_000 });

			// After toggle, the button should change to "Click to enable" and show "Off"
			await expect(row.locator('button[title="Click to enable"]')).toBeAttached({
				timeout: 8_000
			});
			await expect(row.getByText('Off')).toBeVisible({ timeout: 5_000 });

			await screenshot(page, 'monitoring', 'health-check-toggled-off');
		} finally {
			await deleteHealthCheckViaUI(page, 'e2e Toggle Health Check');
			await deleteDatasourceViaUI(page, 'e2e-hc-toggle-ds');
		}
	});
});

test.describe('Monitoring – Health Check create flow', () => {
	test('create health check via UI form', async ({ page, request }) => {
		test.setTimeout(60_000);
		await createDatasource(request, 'e2e-hc-create-ds');
		try {
			await page.goto('/monitoring?tab=health');
			await expect(page.getByRole('button', { name: /New Check/i })).toBeVisible({
				timeout: 10_000
			});
			await page.getByRole('button', { name: /New Check/i }).click();

			// Select datasource
			const dsSelect = page.locator('#hc-target');
			await expect(dsSelect).toBeVisible({ timeout: 5_000 });
			await dsSelect.selectOption({ label: 'e2e-hc-create-ds' });

			// Fill name
			await page.locator('#hc-name').fill('e2e UI Created Check');

			// Type defaults to row_count — fill min_rows
			await page.locator('#hc-min-rows').fill('1');

			// Submit
			const saveBtn = page.getByRole('button', { name: 'Save Check' });
			await expect(saveBtn).toBeEnabled({ timeout: 5_000 });
			await saveBtn.click();

			// Check should appear in the list
			await expect(page.getByText('e2e UI Created Check')).toBeVisible({ timeout: 8_000 });
		} finally {
			await deleteHealthCheckViaUI(page, 'e2e UI Created Check');
			await deleteDatasourceViaUI(page, 'e2e-hc-create-ds');
		}
	});
});

test.describe('Monitoring – Builds tab', () => {
	test('Builds tab shows empty state when no runs exist', async ({ page }) => {
		// Set up route mock before navigation to ensure the first request is intercepted
		await page.route('**/api/v1/engine-runs**', (route) => {
			if (route.request().method() === 'GET') {
				return route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify([])
				});
			}
			return route.continue();
		});

		await page.goto('/monitoring?tab=builds');
		await expect(page.getByRole('tab', { name: 'Builds' })).toHaveAttribute(
			'aria-selected',
			'true'
		);
		const panel = page.locator('#panel-builds');
		await expect(panel).toBeVisible({ timeout: 5_000 });
		await expect(panel.getByText('No engine runs yet.')).toBeVisible({ timeout: 15_000 });
	});

	test('Builds search filters by text', async ({ page, request }) => {
		test.setTimeout(60_000);
		await createDatasource(request, 'e2e-filter-ds');
		try {
			await page.goto('/monitoring?tab=builds');
			const panel = page.locator('#panel-builds');
			await expect(panel.getByText('e2e-filter-ds').first()).toBeVisible({ timeout: 20_000 });

			await page.getByLabel(/Search builds, schedules, or health checks/i).fill('ZZZNOMATCH');
			await expect(panel.getByText('e2e-filter-ds')).not.toBeVisible({ timeout: 5_000 });

			await page.getByLabel(/Search builds, schedules, or health checks/i).fill('e2e-filter-ds');
			await expect(panel.getByText('e2e-filter-ds').first()).toBeVisible({ timeout: 5_000 });
		} finally {
			await deleteDatasourceViaUI(page, 'e2e-filter-ds');
		}
	});

	test('Builds tab shows datasource creation run', async ({ page, request }) => {
		test.setTimeout(60_000);
		await createDatasource(request, 'e2e-build-ds');
		try {
			await page.goto('/monitoring?tab=builds');
			const panel = page.locator('#panel-builds');
			await expect(panel).toBeVisible();
			await expect(panel.getByText('e2e-build-ds').first()).toBeVisible({ timeout: 20_000 });
			const cells = panel.locator('td');
			await expect(cells.getByText('Success').first()).toBeVisible({ timeout: 5_000 });
		} finally {
			await deleteDatasourceViaUI(page, 'e2e-build-ds');
		}
	});

	test('clicking a build row expands to show detail panel', async ({ page, request }) => {
		test.setTimeout(60_000);
		await createDatasource(request, 'e2e-expand-ds');
		try {
			await page.goto('/monitoring?tab=builds');
			const panel = page.locator('#panel-builds');
			await expect(panel.getByText('e2e-expand-ds').first()).toBeVisible({ timeout: 20_000 });

			const buildRow = panel.locator('tr[data-build-row]', { hasText: 'e2e-expand-ds' }).first();
			await buildRow.click();

			const detailRow = panel.locator('tr[data-build-detail]').first();
			await expect(detailRow).toBeVisible({ timeout: 5_000 });
			await expect(detailRow.getByText('Request Config')).toBeVisible();
			await expect(detailRow.getByText('Result')).toBeVisible();
			await screenshot(page, 'monitoring', 'build-row-expanded');
		} finally {
			await deleteDatasourceViaUI(page, 'e2e-expand-ds');
		}
	});

	test('build detail shows Request Payload JSON', async ({ page, request }) => {
		test.setTimeout(60_000);
		await createDatasource(request, 'e2e-payload-ds');
		try {
			await page.goto('/monitoring?tab=builds');
			const panel = page.locator('#panel-builds');
			await expect(panel.getByText('e2e-payload-ds').first()).toBeVisible({ timeout: 20_000 });

			const buildRow = panel.locator('tr[data-build-row]', { hasText: 'e2e-payload-ds' }).first();
			await buildRow.click();

			const detailRow = panel.locator('tr[data-build-detail]').first();
			await expect(detailRow).toBeVisible({ timeout: 5_000 });
			await expect(detailRow.getByText('Request Payload')).toBeVisible();
			await expect(detailRow.getByText('Run ID:')).toBeVisible();
		} finally {
			await deleteDatasourceViaUI(page, 'e2e-payload-ds');
		}
	});

	test('build detail Result tab shows result metadata', async ({ page, request }) => {
		test.setTimeout(60_000);
		await createDatasource(request, 'e2e-result-ds');
		try {
			await page.goto('/monitoring?tab=builds');
			const panel = page.locator('#panel-builds');
			await expect(panel.getByText('e2e-result-ds').first()).toBeVisible({ timeout: 20_000 });

			const buildRow = panel.locator('tr[data-build-row]', { hasText: 'e2e-result-ds' }).first();
			await buildRow.click();

			const detailRow = panel.locator('tr[data-build-detail]').first();
			await expect(detailRow).toBeVisible({ timeout: 5_000 });

			await detailRow.getByRole('button', { name: 'Result' }).click();
			await expect(
				detailRow.getByText('Result Metadata').or(detailRow.getByText('No result data available'))
			).toBeVisible({ timeout: 5_000 });
		} finally {
			await deleteDatasourceViaUI(page, 'e2e-result-ds');
		}
	});

	test('clicking an expanded build row collapses it', async ({ page, request }) => {
		test.setTimeout(60_000);
		await createDatasource(request, 'e2e-collapse-ds');
		try {
			await page.goto('/monitoring?tab=builds');
			const panel = page.locator('#panel-builds');
			await expect(panel.getByText('e2e-collapse-ds').first()).toBeVisible({ timeout: 20_000 });

			const buildRow = panel.locator('tr[data-build-row]', { hasText: 'e2e-collapse-ds' }).first();
			await buildRow.click();
			const detailRow = panel.locator('tr[data-build-detail]').first();
			await expect(detailRow).toBeVisible({ timeout: 5_000 });

			// Click again to collapse
			await buildRow.click();
			await expect(detailRow).not.toBeVisible({ timeout: 5_000 });
		} finally {
			await deleteDatasourceViaUI(page, 'e2e-collapse-ds');
		}
	});
});
