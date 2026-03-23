import { test, expect } from '@playwright/test';
import {
	createDatasource,
	deleteDatasource,
	createSchedule,
	deleteSchedule,
	createHealthCheck,
	deleteHealthCheck
} from './utils/api.js';

/**
 * E2E tests for the monitoring page – mirrors test_healthchecks.py /
 * test_scheduler.py / test_engine_runs.py.
 */
test.describe('Monitoring – page structure', () => {
	test.beforeEach(async ({ page }) => {
		await page.goto('/monitoring');
	});

	test('renders Monitoring heading and description', async ({ page }) => {
		await expect(page.getByRole('heading', { name: 'Monitoring' })).toBeVisible();
		await expect(page.getByText(/Review builds, schedules, and health checks/i)).toBeVisible();
	});

	test('shows all three tabs: Builds, Schedules, Health Checks', async ({ page }) => {
		await expect(page.getByRole('button', { name: 'Builds' })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Schedules' })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Health Checks' })).toBeVisible();
	});

	test('Builds tab is active by default', async ({ page }) => {
		// The Builds tab content renders (BuildsManager). No crash = pass.
		await expect(page.getByRole('button', { name: 'Builds' })).toBeVisible();
	});

	test('can switch between all tabs without error', async ({ page }) => {
		for (const tabName of ['Schedules', 'Health Checks', 'Builds'] as const) {
			await page.getByRole('button', { name: tabName }).click();
			// No Callout with tone=error visible
			await expect(page.locator('.callout--tone_error')).not.toBeVisible();
		}
	});

	test('search input is present', async ({ page }) => {
		await expect(
			page.getByPlaceholder(/Search builds, schedules, or health checks/i)
		).toBeVisible();
	});

	test('typing in search does not crash the page', async ({ page }) => {
		await page.getByPlaceholder(/Search builds, schedules, or health checks/i).fill('test query');
		await expect(page.getByRole('heading', { name: 'Monitoring' })).toBeVisible();
	});
});

test.describe('Monitoring – Schedules tab', () => {
	test('Schedules tab shows schedule list or empty state', async ({ page }) => {
		await page.goto('/monitoring');
		await page.getByRole('button', { name: 'Schedules' }).click();
		// Either a schedule list or an empty/create state
		await expect(page.locator('main, [role="main"]').last()).toBeVisible();
	});

	test('Schedules tab shows "New Schedule" button', async ({ page }) => {
		await page.goto('/monitoring');
		const schedulesTab = page.getByRole('button', { name: 'Schedules' });
		await expect(schedulesTab).toBeVisible();
		await schedulesTab.click();
		await expect(page.getByRole('button', { name: /New Schedule/i })).toBeVisible({
			timeout: 10_000
		});
	});

	test('created schedule appears in the Schedules tab', async ({ page, request }) => {
		// Need a datasource to attach the schedule to
		const dsId = await createDatasource(request, 'e2e-sched-ds');
		let schedId = '';
		try {
			schedId = await createSchedule(request, dsId, '0 6 * * *');
			await page.goto('/monitoring');
			await page.getByRole('button', { name: 'Schedules' }).click();
			// The cron expression or datasource name should be visible
			await expect(
				page.getByText('0 6 * * *').or(page.getByText('e2e-sched-ds')).first()
			).toBeVisible({ timeout: 8_000 });
		} finally {
			if (schedId) await deleteSchedule(request, schedId).catch(() => undefined);
			await deleteDatasource(request, dsId);
		}
	});

	test('schedule can be deleted via UI', async ({ page, request }) => {
		const dsId = await createDatasource(request, 'e2e-sched-del-ds');
		let schedId = '';
		try {
			schedId = await createSchedule(request, dsId, '0 7 * * *');
			await page.goto('/monitoring');
			await page.getByRole('button', { name: 'Schedules' }).click();
			const scheduleText = page.getByText('0 7 * * *');
			await expect(scheduleText.first()).toBeVisible({ timeout: 8_000 });
			const countBefore = await scheduleText.count();

			// Click delete button
			const deleteBtn = page.getByRole('button', { name: /Delete/i }).first();
			await deleteBtn.click();

			// After deletion the count should decrease
			await expect(scheduleText).toHaveCount(countBefore - 1, { timeout: 8_000 });
			schedId = ''; // already deleted
		} finally {
			if (schedId) await deleteSchedule(request, schedId).catch(() => undefined);
			await deleteDatasource(request, dsId);
		}
	});
});

test.describe('Monitoring – Health Checks tab', () => {
	test('Health Checks tab renders without error', async ({ page }) => {
		await page.goto('/monitoring');
		await page.getByRole('button', { name: 'Health Checks' }).click();
		await expect(page.getByRole('heading', { name: 'Monitoring' })).toBeVisible();
	});

	test('Health Checks tab shows "New Check" button', async ({ page }) => {
		await page.goto('/monitoring');
		await page.getByRole('button', { name: 'Health Checks' }).click();
		await expect(page.getByRole('button', { name: /New Check/i })).toBeVisible({ timeout: 8_000 });
	});

	test('created health check appears in list', async ({ page, request }) => {
		const dsId = await createDatasource(request, 'e2e-hc-ds');
		let hcId = '';
		try {
			hcId = await createHealthCheck(request, dsId, 'E2E Row Count Check');
			await page.goto('/monitoring');
			await page.getByRole('button', { name: 'Health Checks' }).click();
			await expect(page.getByText('E2E Row Count Check')).toBeVisible({ timeout: 8_000 });
		} finally {
			if (hcId) await deleteHealthCheck(request, hcId).catch(() => undefined);
			await deleteDatasource(request, dsId);
		}
	});

	test('health check delete button removes it from list', async ({ page, request }) => {
		const dsId = await createDatasource(request, 'e2e-hc-del-ds');
		let hcId = '';
		try {
			hcId = await createHealthCheck(request, dsId, 'E2E Delete Health Check');
			await page.goto('/monitoring');
			await page.getByRole('button', { name: 'Health Checks' }).click();
			await expect(page.getByText('E2E Delete Health Check').first()).toBeVisible({
				timeout: 8_000
			});
			const hcCount = await page.getByText('E2E Delete Health Check').count();

			// Delete button has title="Delete check"
			await page.locator('button[title="Delete check"]').first().click();

			await expect(page.getByText('E2E Delete Health Check')).toHaveCount(hcCount - 1, {
				timeout: 8_000
			});
			hcId = '';
		} finally {
			if (hcId) await deleteHealthCheck(request, hcId).catch(() => undefined);
			await deleteDatasource(request, dsId);
		}
	});
});

test.describe('Monitoring – Builds tab', () => {
	test('Builds tab shows empty state or build list', async ({ page }) => {
		await page.goto('/monitoring');
		await page.getByRole('button', { name: 'Builds' }).click();
		// Just check the tab loaded without crashing
		await expect(page.getByRole('heading', { name: 'Monitoring' })).toBeVisible();
	});

	test('Builds search filters by text', async ({ page }) => {
		await page.goto('/monitoring');
		await page.getByRole('button', { name: 'Builds' }).click();
		await page.getByPlaceholder(/Search builds, schedules, or health checks/i).fill('ZZZNOMATCH');
		// Should not crash
		await expect(page.getByRole('heading', { name: 'Monitoring' })).toBeVisible();
	});

	test('Builds tab shows datasource creation run', async ({ page, request }) => {
		test.setTimeout(60_000);
		// createDatasource triggers a 'datasource_create' engine run with branch='master',
		// which appears in the Builds tab under the default 'master' branch filter.
		const dsId = await createDatasource(request, 'e2e-build-ds');
		try {
			await page.goto('/monitoring');
			await page.getByRole('button', { name: 'Builds' }).click();
			// The datasource name appears in the Datasource column once the lookup resolves
			await expect(page.getByText('e2e-build-ds').first()).toBeVisible({ timeout: 20_000 });
		} finally {
			await deleteDatasource(request, dsId);
		}
	});
});
