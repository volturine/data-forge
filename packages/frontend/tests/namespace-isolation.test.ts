import { test, expect } from './fixtures.js';
import { uploadDatasourceViaUi } from './utils/user-flows.js';
import { deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { uid } from './utils/uid.js';
import { screenshot } from './utils/visual.js';
import { waitForAppShell, waitForDatasourceList } from './utils/readiness.js';
import { switchNamespace, expectNamespace } from './utils/namespace.js';

/**
 * E2E tests for namespace data isolation.
 * Verifies that datasources created in one namespace are invisible from another,
 * and reappear when switching back.
 */
test.describe('Namespace – data isolation', () => {
	test('datasource in namespace A is invisible from namespace B', async ({ page }) => {
		test.setTimeout(90_000);

		const id = uid();
		const nsA = `e2e-ns-a-${id}`;
		const nsB = `e2e-ns-b-${id}`;
		const dsName = `e2e-iso-${id}`;

		try {
			await page.goto('/');
			await waitForAppShell(page);
			await switchNamespace(page, nsA);
			await uploadDatasourceViaUi(page, dsName);

			// 1. Datasource should be visible in nsA
			await expect(page).toHaveURL(/datasources/, { timeout: 10_000 });
			await waitForDatasourceList(page);
			await expect(page.locator(`[data-ds-row="${dsName}"]`)).toBeVisible({ timeout: 10_000 });
			await screenshot(page, 'namespace', 'ds-visible-in-ns-a');

			// 2. Switch to nsB while on /datasources – stays on page, ds hidden
			await switchNamespace(page, nsB);
			await expect(page).toHaveURL(/datasources/, { timeout: 10_000 });
			await waitForDatasourceList(page);
			await expect(page.locator(`[data-ds-row="${dsName}"]`)).not.toBeVisible({ timeout: 5_000 });
			await screenshot(page, 'namespace', 'ds-not-visible-in-ns-b');

			// 3. Switch back to nsA – datasource reappears (still on /datasources)
			await switchNamespace(page, nsA);
			await expect(page).toHaveURL(/datasources/, { timeout: 10_000 });
			await waitForDatasourceList(page);
			await expect(page.locator(`[data-ds-row="${dsName}"]`)).toBeVisible({ timeout: 10_000 });

			// 4. Verify preview still works after round-trip
			await page.locator(`[data-ds-row="${dsName}"]`).click();
			const preview = page.locator('[data-preview-ready="true"]');
			await expect(preview).toBeVisible({ timeout: 30_000 });
			await expect(page.locator('[data-column-id="name"]')).toBeVisible({ timeout: 5_000 });
			await expect(preview.getByText('Alice', { exact: true })).toBeVisible();
			await screenshot(page, 'namespace', 'ds-preview-after-roundtrip');
		} finally {
			await switchNamespace(page, nsA);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('selected namespace persists across page refresh', async ({ page }) => {
		test.setTimeout(30_000);
		const ns = `e2e-persist-${uid()}`;

		await page.goto('/');
		await waitForAppShell(page);

		await switchNamespace(page, ns);
		await expectNamespace(page, ns);

		await page.reload({ waitUntil: 'networkidle' });
		await waitForAppShell(page);

		await expectNamespace(page, ns);
		await screenshot(page, 'namespace', 'persistence-after-refresh');
	});

	test('switching namespace preserves current route', async ({ page }) => {
		test.setTimeout(60_000);

		const id = uid();
		const nsA = `e2e-route-a-${id}`;
		const nsB = `e2e-route-b-${id}`;

		// Start on /datasources
		await page.goto('/datasources');
		await waitForAppShell(page);

		await switchNamespace(page, nsA);
		await expect(page).toHaveURL(/datasources/, { timeout: 10_000 });
		await expectNamespace(page, nsA);

		// Switch namespace while on /datasources — should stay on /datasources
		await switchNamespace(page, nsB);
		await expect(page).toHaveURL(/datasources/, { timeout: 10_000 });
		await expectNamespace(page, nsB);
		await screenshot(page, 'namespace', 'route-preserved-datasources');

		// Navigate to /monitoring and switch again
		await page.goto('/monitoring');
		await expect(page.getByRole('heading', { name: 'Monitoring' })).toBeVisible({
			timeout: 10_000
		});

		await switchNamespace(page, nsA);
		await expect(page).toHaveURL(/monitoring/, { timeout: 10_000 });
		await expectNamespace(page, nsA);
		await screenshot(page, 'namespace', 'route-preserved-monitoring');

		// Navigate to /udfs and switch again
		await page.goto('/udfs');
		await expect(page.getByRole('heading', { name: 'UDF Library' })).toBeVisible({
			timeout: 10_000
		});

		await switchNamespace(page, nsB);
		await expect(page).toHaveURL(/udfs/, { timeout: 10_000 });
		await expectNamespace(page, nsB);
		await screenshot(page, 'namespace', 'route-preserved-udfs');
	});

	test('namespace switch clears stale datasource selection', async ({ page }) => {
		test.setTimeout(90_000);

		const id = uid();
		const nsA = `e2e-stale-a-${id}`;
		const nsB = `e2e-stale-b-${id}`;
		const dsName = `e2e-stale-ds-${id}`;

		try {
			await page.goto('/');
			await waitForAppShell(page);
			await switchNamespace(page, nsA);
			await uploadDatasourceViaUi(page, dsName);

			// 1. Select a datasource in nsA so the URL has ?id=
			await page.goto('/datasources');
			await waitForDatasourceList(page);
			await page.locator(`[data-ds-row="${dsName}"]`).click();
			await expect(page).toHaveURL(/id=/, { timeout: 5_000 });
			await expect(page.locator('[data-preview-ready="true"]')).toBeVisible({ timeout: 30_000 });

			// 2. Switch to nsB — selection must clear, no crash
			await switchNamespace(page, nsB);
			await expect(page).toHaveURL(/datasources/, { timeout: 10_000 });
			await expect(page).not.toHaveURL(/id=/, { timeout: 5_000 });
			await waitForDatasourceList(page);
			await expect(page.getByText(/No datasource selected/i)).toBeVisible({ timeout: 5_000 });
			await screenshot(page, 'namespace', 'stale-selection-cleared');
		} finally {
			await switchNamespace(page, nsA);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('namespace switch with open preview sends no stale compute requests', async ({ page }) => {
		test.setTimeout(90_000);

		const id = uid();
		const nsA = `e2e-race-a-${id}`;
		const nsB = `e2e-race-b-${id}`;
		const dsName = `e2e-race-ds-${id}`;

		try {
			await page.goto('/');
			await waitForAppShell(page);
			await switchNamespace(page, nsA);
			await uploadDatasourceViaUi(page, dsName);
			await page.goto('/datasources');
			await waitForDatasourceList(page);
			await page.locator(`[data-ds-row="${dsName}"]`).click();
			await expect(page.locator('[data-preview-ready="true"]')).toBeVisible({ timeout: 30_000 });

			// Capture all compute/preview requests fired after namespace switch starts
			const staleRequests: string[] = [];
			await page.route('**/api/v1/compute/preview', (route) => {
				const ns = route.request().headers()['x-namespace'] ?? '';
				staleRequests.push(ns);
				return route.continue();
			});

			await switchNamespace(page, nsB);
			await expect(page).toHaveURL(/datasources/, { timeout: 10_000 });
			await expect(page).not.toHaveURL(/id=/, { timeout: 5_000 });
			await waitForDatasourceList(page);

			// No preview requests should have been sent with the old namespace
			const wrongNs = staleRequests.filter((ns) => ns === nsA);
			expect(wrongNs).toHaveLength(0);

			await screenshot(page, 'namespace', 'no-stale-preview-requests');
		} finally {
			await switchNamespace(page, nsA);
			await deleteDatasourceViaUI(page, dsName);
		}
	});
});
