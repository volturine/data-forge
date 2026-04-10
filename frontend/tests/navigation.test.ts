import { test, expect } from './fixtures.js';
import { screenshot } from './utils/visual.js';
import { waitForAppShell, waitForSettingsForm } from './utils/readiness.js';

/**
 * Smoke tests: every top-level route renders without a JS crash,
 * and primary navigation links work.
 */
test.describe('Navigation – page load smoke tests', () => {
	test('home page renders Analyses heading', async ({ page }) => {
		await page.goto('/');
		await expect(page.getByRole('heading', { name: 'Analyses', level: 1 })).toBeVisible();
		await expect(page.getByRole('link', { name: /New Analysis/i })).toBeVisible();
		await screenshot(page, 'navigation', 'home-page');
	});

	test('datasources page renders Data Sources heading', async ({ page }) => {
		await page.goto('/datasources');
		await expect(page.getByRole('heading', { name: 'Data Sources' })).toBeVisible();
		await screenshot(page, 'navigation', 'datasources-page');
	});

	test('UDF library page renders UDF Library heading', async ({ page }) => {
		await page.goto('/udfs');
		await expect(page.getByRole('heading', { name: 'UDF Library' })).toBeVisible();
	});

	test('monitoring page renders Monitoring heading', async ({ page }) => {
		await page.goto('/monitoring');
		await expect(page.getByRole('heading', { name: 'Monitoring' })).toBeVisible({
			timeout: 10_000
		});
		await expect(page.getByRole('tab', { name: 'Builds' })).toBeVisible({ timeout: 10_000 });
		await screenshot(page, 'navigation', 'monitoring-page');
	});

	test('new analysis page renders wizard', async ({ page }) => {
		await page.goto('/analysis/new');
		await expect(page.getByRole('heading', { name: 'New Analysis' })).toBeVisible();
		await screenshot(page, 'navigation', 'new-analysis-wizard');
	});

	test('new datasource page loads', async ({ page }) => {
		await page.goto('/datasources/new');
		await expect(page).toHaveURL(/datasources\/new/);
	});

	test('new UDF page loads', async ({ page }) => {
		await page.goto('/udfs/new');
		await expect(page).toHaveURL(/udfs\/new/);
	});

	// ── header nav links ──────────────────────────────────────────────────────

	test('clicking Analyses nav link goes to /', async ({ page }) => {
		await page.goto('/datasources');
		// Nav link in header – look for it by href
		await page.locator('a[href="/"]').first().click();
		await expect(page).toHaveURL('/');
	});

	test('"New Analysis" link navigates to /analysis/new', async ({ page }) => {
		await page.goto('/');
		const link = page.getByRole('link', { name: /New Analysis/i });
		await expect(link).toBeVisible();
		await link.click();
		await expect(page).toHaveURL(/analysis\/new/, { timeout: 15_000 });
	});

	test('datasources "Add" link navigates to /datasources/new', async ({ page }) => {
		await page.goto('/datasources');
		// The "Add" link is the primary CTA in the datasource left panel header
		await page.getByRole('link', { name: /^Add$/ }).click();
		await expect(page).toHaveURL(/datasources\/new/, { timeout: 10_000 });
	});

	test('UDFs "New UDF" button navigates to /udfs/new', async ({ page }) => {
		await page.goto('/udfs');
		const newUdfBtn = page.getByRole('button', { name: /New UDF/i });
		await expect(newUdfBtn).toBeVisible();
		await newUdfBtn.click();
		await expect(page).toHaveURL(/udfs\/new/);
	});
});

test.describe('Navigation – settings popup', () => {
	test('settings popup opens and shows SMTP, Telegram, Debug sections', async ({ page }) => {
		await page.goto('/');
		await waitForAppShell(page);
		await page.getByRole('button', { name: 'Settings' }).click();

		const dialog = page.getByRole('dialog');
		await expect(dialog).toBeVisible({ timeout: 5_000 });
		await expect(dialog.getByRole('heading', { name: 'Settings' })).toBeVisible();
		await waitForSettingsForm(dialog);

		// Sections are collapsed by default; assert toggles first, then expand SMTP
		// before checking its contents.
		await expect(dialog.getByText('SMTP', { exact: true })).toBeVisible();
		await expect(dialog.getByText('Telegram', { exact: true })).toBeVisible();
		await expect(dialog.getByText('Debug', { exact: true })).toBeVisible();

		await dialog.getByRole('button', { name: 'SMTP' }).click();
		await expect(dialog.locator('#smtp-host')).toBeVisible();
		await expect(dialog.locator('#smtp-port')).toBeVisible();

		await screenshot(page, 'navigation', 'settings-popup-open');
	});

	test('settings save shows success feedback on 200', async ({ page }) => {
		await page.goto('/');
		await waitForAppShell(page);
		await page.getByRole('button', { name: 'Settings' }).click();

		const dialog = page.getByRole('dialog');
		await waitForSettingsForm(dialog);

		const saveBtn = dialog.getByRole('button', { name: 'Save' });
		await expect(saveBtn).toBeEnabled({ timeout: 5_000 });
		await saveBtn.click();
		await expect(dialog.getByText('Settings saved')).toBeVisible({ timeout: 5_000 });

		await screenshot(page, 'navigation', 'settings-save-success');
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Chat panel – minimal smoke tests
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Navigation – chat panel smoke', () => {
	test('chat trigger opens panel and close button dismisses it', async ({ page }) => {
		await page.goto('/');
		await waitForAppShell(page);

		const trigger = page.getByRole('button', { name: 'AI Assistant' });
		await expect(trigger).toBeVisible();
		await trigger.click();

		const panel = page.locator('#chat-panel');
		await expect(panel).toBeVisible({ timeout: 5_000 });

		await screenshot(page, 'navigation', 'chat-panel-open');

		// Close via the close button
		await panel.getByRole('button', { name: 'Close chat' }).click();
		await expect(panel).not.toBeVisible({ timeout: 3_000 });
	});

	test('chat panel closes via Escape key', async ({ page }) => {
		await page.goto('/');
		await waitForAppShell(page);

		await page.getByRole('button', { name: 'AI Assistant' }).click();
		const panel = page.locator('#chat-panel');
		await expect(panel).toBeVisible({ timeout: 5_000 });

		await page.keyboard.press('Escape');
		await expect(panel).not.toBeVisible({ timeout: 3_000 });
	});

	test('chat panel toggle: second click closes the panel', async ({ page }) => {
		await page.goto('/');
		await waitForAppShell(page);

		const trigger = page.getByRole('button', { name: 'AI Assistant' });
		await trigger.click();
		const panel = page.locator('#chat-panel');
		await expect(panel).toBeVisible({ timeout: 5_000 });

		// Click trigger again to close
		await trigger.click();
		await expect(panel).not.toBeVisible({ timeout: 3_000 });
	});
});
