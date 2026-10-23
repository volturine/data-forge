import {
	E2E_SHARED_NAMESPACE_A,
	E2E_SHARED_NAMESPACE_B,
	E2E_SHARED_NAMESPACE_DATASOURCE,
	expect,
	test
} from './fixtures.js';
import { nameForAnalysisId } from './utils/api.js';
import { gotoAnalysisEditor } from './utils/analysis.js';
import { screenshot } from './utils/visual.js';
import {
	gotoMonitoringTab,
	readyTimeoutMs,
	waitForAppShell,
	waitForDatasourceList
} from './utils/readiness.js';
import {
	DEFAULT_NAMESPACE,
	switchNamespace,
	expectNamespace,
	restoreDefaultNamespace
} from './utils/namespace.js';
import { createAnalysisViaUi } from './utils/user-flows.js';
import { deleteAnalysisViaUI } from './utils/ui-cleanup.js';
import { uid } from './utils/uid.js';

/**
 * E2E tests for namespace data isolation.
 * Verifies that datasources created in one namespace are invisible from another,
 * and reappear when switching back.
 */
test.describe('Namespace – data isolation', () => {
	test.afterEach(async ({ page }) => {
		await restoreDefaultNamespace(page);
	});

	test('creates a namespace through the large picker and preserves it after reload', async ({
		page
	}) => {
		const namespace = `e2e-picker-${uid()}`;
		await page.goto('/datasources');
		await waitForAppShell(page);
		const trigger = page.getByRole('button', { name: 'Select namespace' });
		await trigger.click();
		const dialog = page.locator('[role="dialog"][aria-labelledby="namespace-picker-title"]');
		await expect(dialog.getByRole('textbox', { name: 'Search namespaces' })).toBeFocused();
		await dialog.getByRole('button', { name: 'New namespace' }).click();
		const name = dialog.getByRole('textbox', { name: 'Name', exact: true });
		await expect(name).toBeFocused();
		const create = dialog.getByRole('button', { name: 'Create namespace' });
		await name.fill('Invalid_Name');
		await expect(dialog.getByRole('alert')).toContainText('lowercase letters');
		await expect(create).toBeDisabled();
		await name.fill(namespace);
		await expect(dialog.getByText(`S3 bucket (root): ${namespace}`, { exact: true })).toBeVisible({
			timeout: readyTimeoutMs()
		});
		await expect(create).toBeEnabled();
		await screenshot(page, 'namespace', 'namespace-creation-dialog');
		await create.click();
		await expect(dialog).not.toBeVisible({ timeout: readyTimeoutMs() });
		await expectNamespace(page, namespace);
		await expect(page).toHaveURL('/datasources');
		await expect(trigger).toBeFocused();

		await page.reload();
		await waitForAppShell(page);
		await expectNamespace(page, namespace);
		await trigger.click();
		await dialog.getByRole('textbox', { name: 'Search namespaces' }).fill(namespace);
		await expect(dialog.locator(`[data-namespace-option="${namespace}"]`)).toHaveAttribute(
			'aria-pressed',
			'true'
		);
		await page.keyboard.press('Escape');
	});

	test('datasource in namespace A is invisible from namespace B', async ({ page }) => {
		const nsA = E2E_SHARED_NAMESPACE_A;
		const nsB = E2E_SHARED_NAMESPACE_B;
		const dsName = E2E_SHARED_NAMESPACE_DATASOURCE;

		try {
			await page.goto('/');
			await waitForAppShell(page);
			await switchNamespace(page, nsA);
			await page.goto('/datasources');

			// 1. Datasource should be visible in nsA
			await expect(page).toHaveURL(/datasources/, { timeout: 5_000 });
			await waitForDatasourceList(page);
			await expect(page.locator(`[data-ds-row="${dsName}"]`)).toBeVisible({ timeout: 5_000 });
			await screenshot(page, 'namespace', 'ds-visible-in-ns-a');

			// 2. Switch to nsB while on /datasources – stays on page, ds hidden
			await switchNamespace(page, nsB);
			await expect(page).toHaveURL(/datasources/, { timeout: 5_000 });
			await waitForDatasourceList(page);
			await expect(page.locator(`[data-ds-row="${dsName}"]`)).not.toBeVisible({ timeout: 5_000 });
			await screenshot(page, 'namespace', 'ds-not-visible-in-ns-b');

			// 3. Switch back to nsA – datasource reappears (still on /datasources)
			await switchNamespace(page, nsA);
			await expect(page).toHaveURL(/datasources/, { timeout: 5_000 });
			await waitForDatasourceList(page);
			await expect(page.locator(`[data-ds-row="${dsName}"]`)).toBeVisible({ timeout: 5_000 });
			await screenshot(page, 'namespace', 'ds-visible-again-in-ns-a');
		} finally {
			await switchNamespace(page, nsA);
		}
	});

	test('namespace switches keep the route, clear stale selection, and send no stale preview requests', async ({
		page,
		sharedDatasource
	}) => {
		// Namespace provisioning and analysis creation make this journey heavy, so
		// it runs in one slow test; each former test is a step with its own setup.
		test.slow();
		const nsA = E2E_SHARED_NAMESPACE_A;
		const nsB = E2E_SHARED_NAMESPACE_B;
		const dsName = E2E_SHARED_NAMESPACE_DATASOURCE;

		await test.step('switching namespace preserves current route', async () => {
			// Start on /datasources
			await page.goto('/datasources');
			await waitForAppShell(page);

			await switchNamespace(page, nsA);
			await expect(page).toHaveURL(/datasources/, { timeout: 5_000 });
			await expectNamespace(page, nsA);

			// Switch namespace while on /datasources — should stay on /datasources
			await switchNamespace(page, nsB);
			await expect(page).toHaveURL(/datasources/, { timeout: 5_000 });
			await expectNamespace(page, nsB);
			await screenshot(page, 'namespace', 'route-preserved-datasources');

			// Navigate to /monitoring?tab=schedules and switch again
			await gotoMonitoringTab(page, 'schedules');
			await expect(page.getByRole('button', { name: /New Schedule/i })).toBeVisible({
				timeout: 5_000
			});

			await switchNamespace(page, nsA);
			await expect(page).toHaveURL(
				(url) => url.pathname === '/monitoring' && url.searchParams.get('tab') === 'schedules',
				{
					timeout: 5_000
				}
			);
			await expectNamespace(page, nsA);
			await screenshot(page, 'namespace', 'route-preserved-monitoring');

			await switchNamespace(page, DEFAULT_NAMESPACE);
			const analysisId = await createAnalysisViaUi(page, sharedDatasource.name);
			const analysisName = nameForAnalysisId(analysisId);
			if (!analysisName) throw new Error(`Analysis ${analysisId} was not registered for cleanup`);

			try {
				await gotoAnalysisEditor(page, analysisId);
				await switchNamespace(page, nsB);
				await expect(page).toHaveURL(`/analysis/${analysisId}`, { timeout: 5_000 });
				await expectNamespace(page, nsB);
				await screenshot(page, 'namespace', 'route-preserved-analysis');
			} finally {
				await switchNamespace(page, DEFAULT_NAMESPACE);
				await deleteAnalysisViaUI(page, analysisName, {
					id: analysisId,
					namespace: DEFAULT_NAMESPACE
				});
			}
		});

		await test.step('namespace switch clears stale datasource selection', async () => {
			await page.goto('/');
			await waitForAppShell(page);
			await switchNamespace(page, nsA);
			await page.goto('/datasources');

			// 1. Select a datasource in nsA so the URL has ?id=
			await page.goto('/datasources');
			await waitForDatasourceList(page);
			await page.locator(`[data-ds-row="${dsName}"]`).click();
			await expect(page).toHaveURL(/id=/, { timeout: 5_000 });

			// 2. Switch to nsB — selection must clear, no crash
			await switchNamespace(page, nsB);
			await expect(page).toHaveURL(/datasources/, { timeout: 5_000 });
			await expect(page).not.toHaveURL(/id=/, { timeout: 5_000 });
			await waitForDatasourceList(page);
			await expect(page.getByText(/No datasource selected/i)).toBeVisible({ timeout: 5_000 });
			await screenshot(page, 'namespace', 'stale-selection-cleared');
		});

		await test.step('namespace switch with open preview sends no stale compute requests', async () => {
			try {
				await page.goto('/');
				await waitForAppShell(page);
				await switchNamespace(page, nsA);
				await page.goto('/datasources');
				await waitForDatasourceList(page);
				await page.locator(`[data-ds-row="${dsName}"]`).click();
				const previewState = page
					.locator('[data-preview-ready="true"]')
					.or(page.getByText('Loading').first());
				await expect(previewState).toBeVisible({ timeout: 5_000 });

				const staleRequests: string[] = [];
				await page.route('**/api/v1/compute/preview', (route) => {
					const ns = route.request().headers()['x-namespace'] ?? '';
					staleRequests.push(ns);
					return route.continue();
				});

				// The default namespace is already provisioned. This scenario tests
				// leaving an active preview, not a second expensive namespace bootstrap.
				await switchNamespace(page, DEFAULT_NAMESPACE);
				await expect(page).toHaveURL(/datasources/, { timeout: 5_000 });
				await expect(page).not.toHaveURL(/id=/, { timeout: 5_000 });
				await waitForDatasourceList(page);

				const wrongNs = staleRequests.filter((ns) => ns === nsA);
				expect(wrongNs).toHaveLength(0);

				await screenshot(page, 'namespace', 'no-stale-preview-requests');
			} finally {
				await switchNamespace(page, nsA);
			}
		});
	});
});
