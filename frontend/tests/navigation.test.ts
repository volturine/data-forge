import { test, expect } from '@playwright/test';
import { screenshot } from './utils/visual.js';

/**
 * Smoke tests: every top-level route renders without a JS crash,
 * and primary navigation links work.
 */
test.describe('Navigation – page load smoke tests', () => {
	test('home page renders Analyses heading', async ({ page }) => {
		await page.goto('/');
		await expect(page.getByRole('heading', { name: 'Analyses' })).toBeVisible();
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
		await page.getByRole('button', { name: 'Settings' }).click();

		const dialog = page.getByRole('dialog');
		await expect(dialog).toBeVisible({ timeout: 5_000 });
		await expect(dialog.getByRole('heading', { name: 'Settings' })).toBeVisible();

		// Verify all three sections render
		await expect(dialog.getByText('SMTP', { exact: true })).toBeVisible();
		await expect(dialog.getByText('Telegram', { exact: true })).toBeVisible();
		await expect(dialog.getByText('Debug', { exact: true })).toBeVisible();

		// Verify SMTP form fields are present
		await expect(dialog.locator('#smtp-host')).toBeVisible();
		await expect(dialog.locator('#smtp-port')).toBeVisible();

		await screenshot(page, 'navigation', 'settings-popup-open');
	});

	test('settings popup closes via close button', async ({ page }) => {
		await page.goto('/');
		await page.getByRole('button', { name: 'Settings' }).click();

		const dialog = page.getByRole('dialog');
		await expect(dialog.getByRole('heading', { name: 'Settings' })).toBeVisible({
			timeout: 5_000
		});

		await dialog.getByRole('button', { name: /Close settings/i }).click();
		await expect(dialog).not.toBeVisible({ timeout: 3_000 });
	});

	test('settings popup closes via Escape key', async ({ page }) => {
		await page.goto('/');
		await page.getByRole('button', { name: 'Settings' }).click();

		const dialog = page.getByRole('dialog');
		await expect(dialog).toBeVisible({ timeout: 5_000 });

		await page.keyboard.press('Escape');
		await expect(dialog).not.toBeVisible({ timeout: 3_000 });
	});

	test('settings popup shows IndexedDB toggle in Debug section', async ({ page }) => {
		await page.goto('/');
		await page.getByRole('button', { name: 'Settings' }).click();

		const dialog = page.getByRole('dialog');
		await expect(dialog).toBeVisible({ timeout: 5_000 });

		// Debug section has the IndexedDB Inspector toggle
		await expect(dialog.getByText('IndexedDB Inspector')).toBeVisible();
		await expect(dialog.getByRole('switch', { name: /Toggle IndexedDB/i })).toBeVisible();
	});

	test('settings popup shows Telegram bot toggle', async ({ page }) => {
		await page.goto('/');
		await page.getByRole('button', { name: 'Settings' }).click();

		const dialog = page.getByRole('dialog');
		await expect(dialog).toBeVisible({ timeout: 5_000 });

		await expect(dialog.getByRole('switch', { name: /Toggle Telegram bot/i })).toBeVisible();
	});

	test('settings save shows success feedback on 200', async ({ page }) => {
		await page.route('**/api/v1/settings', (route) => {
			if (route.request().method() === 'PUT') {
				return route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify({
						smtp_host: '',
						smtp_port: 587,
						smtp_user: '',
						smtp_password: '',
						telegram_bot_token: '',
						telegram_bot_enabled: false,
						public_idb_debug: false
					})
				});
			}
			return route.continue();
		});

		await page.goto('/');
		await page.getByRole('button', { name: 'Settings' }).click();

		const dialog = page.getByRole('dialog');
		await expect(dialog).toBeVisible({ timeout: 5_000 });

		const saveBtn = dialog.getByRole('button', { name: 'Save' });
		await expect(saveBtn).toBeEnabled({ timeout: 5_000 });
		await saveBtn.click();
		await expect(dialog.getByText('Settings saved')).toBeVisible({ timeout: 5_000 });

		await screenshot(page, 'navigation', 'settings-save-success');
	});

	test('settings save shows error feedback on failure', async ({ page }) => {
		await page.route('**/api/v1/settings', (route) => {
			if (route.request().method() === 'PUT') {
				return route.fulfill({
					status: 500,
					contentType: 'application/json',
					body: JSON.stringify({ detail: 'Database connection failed' })
				});
			}
			return route.continue();
		});

		await page.goto('/');
		await page.getByRole('button', { name: 'Settings' }).click();

		const dialog = page.getByRole('dialog');
		await expect(dialog).toBeVisible({ timeout: 5_000 });

		await dialog.getByRole('button', { name: 'Save' }).click();

		// The component displays err.message from the API error
		// Just verify that *some* error feedback appears (red banner with XCircle)
		const errorBanner = dialog.locator('text=/error|fail/i').first();
		await expect(errorBanner).toBeVisible({ timeout: 5_000 });

		await screenshot(page, 'navigation', 'settings-save-error');
	});

	test('SMTP test shows success feedback on 200', async ({ page }) => {
		await page.route('**/api/v1/settings/test-smtp', (route) => {
			if (route.request().method() === 'POST') {
				return route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify({ success: true, message: 'Test email sent successfully' })
				});
			}
			return route.continue();
		});

		await page.goto('/');
		await page.getByRole('button', { name: 'Settings' }).click();

		const dialog = page.getByRole('dialog');
		await expect(dialog).toBeVisible({ timeout: 5_000 });

		await dialog.locator('#smtp-test-to').fill('test@example.com');
		await dialog.getByRole('button', { name: 'Test' }).click();

		await expect(dialog.getByText('Test email sent successfully')).toBeVisible({ timeout: 5_000 });
		await screenshot(page, 'navigation', 'settings-smtp-test-success');
	});

	test('SMTP test shows error feedback on failure', async ({ page }) => {
		await page.route('**/api/v1/settings/test-smtp', (route) => {
			if (route.request().method() === 'POST') {
				return route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify({ success: false, message: 'Connection refused' })
				});
			}
			return route.continue();
		});

		await page.goto('/');
		await page.getByRole('button', { name: 'Settings' }).click();

		const dialog = page.getByRole('dialog');
		await expect(dialog).toBeVisible({ timeout: 5_000 });

		await dialog.locator('#smtp-test-to').fill('test@example.com');
		await dialog.getByRole('button', { name: 'Test' }).click();

		await expect(dialog.getByText('Connection refused')).toBeVisible({ timeout: 5_000 });
	});

	test('SMTP test button is disabled without recipient', async ({ page }) => {
		await page.goto('/');
		await page.getByRole('button', { name: 'Settings' }).click();

		const dialog = page.getByRole('dialog');
		await expect(dialog).toBeVisible({ timeout: 5_000 });

		const testBtn = dialog.getByRole('button', { name: 'Test' });
		await expect(testBtn).toBeDisabled();
	});

	test('Telegram bot toggle updates aria-checked state', async ({ page }) => {
		await page.goto('/');
		await page.getByRole('button', { name: 'Settings' }).click();

		const dialog = page.getByRole('dialog');
		await expect(dialog).toBeVisible({ timeout: 5_000 });

		const toggle = dialog.getByRole('switch', { name: /Toggle Telegram bot/i });
		const initial = await toggle.getAttribute('aria-checked');

		await toggle.click();
		const toggled = initial === 'true' ? 'false' : 'true';
		await expect(toggle).toHaveAttribute('aria-checked', toggled);
	});

	test('settings load failure does not crash the popup', async ({ page }) => {
		await page.route('**/api/v1/settings', (route) => {
			if (route.request().method() === 'GET') {
				return route.fulfill({
					status: 500,
					contentType: 'application/json',
					body: JSON.stringify({ detail: 'Internal server error' })
				});
			}
			return route.continue();
		});

		await page.goto('/');
		await page.getByRole('button', { name: 'Settings' }).click();

		const dialog = page.getByRole('dialog');
		await expect(dialog).toBeVisible({ timeout: 5_000 });
		await expect(dialog.getByRole('heading', { name: 'Settings' })).toBeVisible();

		// Loading state should clear even on failure — form fields should still render
		await expect(dialog.locator('#smtp-host')).toBeVisible({ timeout: 5_000 });
	});
});

test.describe('Navigation – error state regression', () => {
	test('datasources page handles API failure gracefully', async ({ page }) => {
		// Intercept the datasource list API to simulate a server error
		await page.route('**/api/v1/datasource', (route) => {
			if (route.request().method() === 'GET') {
				return route.fulfill({ status: 500, body: 'Internal Server Error' });
			}
			return route.continue();
		});

		await page.goto('/datasources');

		// Page should still render the heading without crashing
		await expect(page.getByRole('heading', { name: 'Data Sources' })).toBeVisible({
			timeout: 10_000
		});

		// The error callout should be visible
		await expect(page.getByText(/Error:/i)).toBeVisible({ timeout: 10_000 });

		// The datasource list should not show any items
		await expect(page.locator('[data-ds-row]')).toHaveCount(0, { timeout: 5_000 });
	});

	test('monitoring page handles API failure without crash', async ({ page }) => {
		// Intercept all monitoring-related APIs to simulate failure
		await page.route('**/api/v1/engine-runs**', (route) =>
			route.fulfill({ status: 500, body: 'Internal Server Error' })
		);

		await page.goto('/monitoring');

		// Page structure should still render
		await expect(page.getByRole('heading', { name: 'Monitoring' })).toBeVisible({
			timeout: 10_000
		});
		await expect(page.getByRole('tab', { name: 'Builds' })).toBeVisible();
		await expect(page.getByRole('tab', { name: 'Schedules' })).toBeVisible();
		await expect(page.getByRole('tab', { name: 'Health Checks' })).toBeVisible();

		// The builds panel should show error or empty state — not silently succeed
		// Scope to visible, non-select text to avoid matching <option> values like "Failed"
		const panel = page.locator('#panel-builds');
		await expect(
			panel
				.locator(':not(select):not(option)')
				.getByText(/error|No engine runs/i)
				.first()
		).toBeVisible({
			timeout: 10_000
		});
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Chat panel – minimal smoke tests
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Navigation – chat panel smoke', () => {
	test('chat trigger opens panel and close button dismisses it', async ({ page }) => {
		await page.goto('/');

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

		await page.getByRole('button', { name: 'AI Assistant' }).click();
		const panel = page.locator('#chat-panel');
		await expect(panel).toBeVisible({ timeout: 5_000 });

		await page.keyboard.press('Escape');
		await expect(panel).not.toBeVisible({ timeout: 3_000 });
	});

	test('chat panel toggle: second click closes the panel', async ({ page }) => {
		await page.goto('/');

		const trigger = page.getByRole('button', { name: 'AI Assistant' });
		await trigger.click();
		const panel = page.locator('#chat-panel');
		await expect(panel).toBeVisible({ timeout: 5_000 });

		// Click trigger again to close
		await trigger.click();
		await expect(panel).not.toBeVisible({ timeout: 3_000 });
	});
});
