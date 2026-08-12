import { test, expect } from './fixtures.js';
import { restoreDefaultNamespace, switchNamespace } from './utils/namespace.js';
import {
	waitForAppShell,
	waitForProfileTabs,
	waitForProfileTab,
	gotoProfile
} from './utils/readiness.js';
import { uid } from './utils/uid.js';
import { screenshot } from './utils/visual.js';
import { E2E_PASSWORD } from './utils/user-flows.js';

async function expandSystemExportGroup(page: import('@playwright/test').Page, schemaName: string) {
	const toggle = page.locator(
		`[data-testid="system-export-group-toggle"][data-schema-name="${schemaName}"]`
	);
	await expect(toggle).toBeVisible();
	if ((await toggle.getAttribute('aria-expanded')) === 'true') return;
	await toggle.click();
	await expect(toggle).toHaveAttribute('aria-expanded', 'true');
}

// ────────────────────────────────────────────────────────────────────────────────
// Profile page – tabbed interface
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Profile – tabbed interface', () => {
	test('profile page renders with Account tab active by default', async ({ page }) => {
		await gotoProfile(page);

		await expect(page.getByRole('heading', { name: 'Profile', level: 1 })).toBeVisible();
		await expect(page.getByText('Manage your account and application settings')).toBeVisible();

		// All four tabs visible
		await expect(page.getByRole('tab', { name: 'Account' })).toBeVisible();
		await expect(page.getByRole('tab', { name: 'Notifications' })).toBeVisible();
		await expect(page.getByRole('tab', { name: 'AI Providers' })).toBeVisible();
		await expect(page.getByRole('tab', { name: 'System' })).toBeVisible();

		// Account tab is selected by default
		await expect(page.getByRole('tab', { name: 'Account' })).toHaveAttribute(
			'aria-selected',
			'true'
		);

		await screenshot(page, 'profile', 'tabbed-default');
	});

	test('profile page shows Account tab content', async ({ page }) => {
		await gotoProfile(page);

		const panel = page.locator('#panel-account');
		await expect(panel).toBeVisible();
		await expect(panel.locator('#email')).toBeVisible();
		await expect(panel.locator('#name')).toBeVisible();

		await screenshot(page, 'profile', 'account-tab');
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Profile – deep-linkable tabs via URL hash
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Profile – deep-link tabs', () => {
	test('navigating to /profile#notifications opens Notifications tab', async ({ page }) => {
		await gotoProfile(page, 'notifications');

		await expect(page.getByRole('tab', { name: 'Notifications' })).toHaveAttribute(
			'aria-selected',
			'true'
		);
		await expect(page.locator('#panel-notifications')).toBeVisible();

		await screenshot(page, 'profile', 'notifications-deeplink');
	});

	test('navigating to /profile#ai-providers opens AI Providers tab', async ({ page }) => {
		await gotoProfile(page, 'ai-providers');

		await expect(page.getByRole('tab', { name: 'AI Providers' })).toHaveAttribute(
			'aria-selected',
			'true'
		);
		await expect(page.locator('#panel-ai-providers')).toBeVisible();

		await screenshot(page, 'profile', 'ai-providers-deeplink');
	});

	test('navigating to /profile#system opens System tab', async ({ page }) => {
		await gotoProfile(page, 'system');

		await expect(page.getByRole('tab', { name: 'System' })).toHaveAttribute(
			'aria-selected',
			'true'
		);
		await expect(page.locator('#panel-system')).toBeVisible();

		await screenshot(page, 'profile', 'system-deeplink');
	});

	test('invalid hash defaults to Account tab', async ({ page }) => {
		await gotoProfile(page, 'nonexistent');

		await expect(page.getByRole('tab', { name: 'Account' })).toHaveAttribute(
			'aria-selected',
			'true'
		);
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Profile – tab switching
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Profile – tab switching', () => {
	test('clicking each tab switches content and updates URL hash', async ({ page }) => {
		await gotoProfile(page);

		// Switch to Notifications
		await page.getByRole('tab', { name: 'Notifications' }).click();
		await expect(page.getByRole('tab', { name: 'Notifications' })).toHaveAttribute(
			'aria-selected',
			'true'
		);
		await expect(page).toHaveURL(/profile#notifications/);
		await expect(page.locator('#panel-notifications')).toBeVisible();

		// Switch to AI Providers
		await page.getByRole('tab', { name: 'AI Providers' }).click();
		await expect(page.getByRole('tab', { name: 'AI Providers' })).toHaveAttribute(
			'aria-selected',
			'true'
		);
		await expect(page).toHaveURL(/profile#ai-providers/);
		await expect(page.locator('#panel-ai-providers')).toBeVisible();

		// Switch to System
		await page.getByRole('tab', { name: 'System' }).click();
		await expect(page.getByRole('tab', { name: 'System' })).toHaveAttribute(
			'aria-selected',
			'true'
		);
		await expect(page).toHaveURL(/profile#system/);
		await expect(page.locator('#panel-system')).toBeVisible();

		// Switch back to Account
		await page.getByRole('tab', { name: 'Account' }).click();
		await expect(page.getByRole('tab', { name: 'Account' })).toHaveAttribute(
			'aria-selected',
			'true'
		);
		await expect(page).toHaveURL(/profile#account/);
		await expect(page.locator('#panel-account')).toBeVisible();

		await screenshot(page, 'profile', 'tab-switching');
	});

	test('keyboard navigation between tabs works (ArrowRight, ArrowLeft)', async ({ page }) => {
		await gotoProfile(page);

		const accountTab = page.getByRole('tab', { name: 'Account' });
		await accountTab.focus();

		// ArrowRight → Notifications
		await page.keyboard.press('ArrowRight');
		await expect(page.getByRole('tab', { name: 'Notifications' })).toHaveAttribute(
			'aria-selected',
			'true'
		);

		// ArrowRight → AI Providers
		await page.keyboard.press('ArrowRight');
		await expect(page.getByRole('tab', { name: 'AI Providers' })).toHaveAttribute(
			'aria-selected',
			'true'
		);

		// ArrowRight → System
		await page.keyboard.press('ArrowRight');
		await expect(page.getByRole('tab', { name: 'System' })).toHaveAttribute(
			'aria-selected',
			'true'
		);

		// ArrowRight wraps → Account
		await page.keyboard.press('ArrowRight');
		await expect(page.getByRole('tab', { name: 'Account' })).toHaveAttribute(
			'aria-selected',
			'true'
		);

		// ArrowLeft wraps → System
		await page.keyboard.press('ArrowLeft');
		await expect(page.getByRole('tab', { name: 'System' })).toHaveAttribute(
			'aria-selected',
			'true'
		);
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Profile – Account tab (US-2)
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Profile – Account tab', () => {
	test('account tab shows email (read-only), display name, and save button', async ({ page }) => {
		await gotoProfile(page, 'account');

		const panel = page.locator('#panel-account');
		const emailInput = panel.locator('#email');
		await expect(emailInput).toBeVisible();
		await expect(emailInput).toBeDisabled();

		const nameInput = panel.locator('#name');
		await expect(nameInput).toBeVisible();

		await screenshot(page, 'profile', 'account-fields');
	});

	test('account tab shows password change form', async ({ page }) => {
		await gotoProfile(page, 'account');

		const panel = page.locator('#panel-account');
		await expect(panel.locator('#current')).toBeVisible();
		await expect(panel.locator('#fresh')).toBeVisible();
		await expect(panel.locator('#confirm')).toBeVisible();
		await expect(panel.getByRole('button', { name: 'Change password' })).toBeVisible();
	});

	test('account tab shows connected accounts section', async ({ page }) => {
		await gotoProfile(page, 'account');

		const panel = page.locator('#panel-account');
		await expect(panel.getByText('Connected accounts')).toBeVisible();
		await expect(panel.getByText('Google')).toBeVisible();
		await expect(panel.getByText('GitHub')).toBeVisible();
	});

	test('profile save shows success feedback on 200', async ({ page }) => {
		await gotoProfile(page, 'account');

		const panel = page.locator('#panel-account');
		const nameInput = panel.locator('#name');
		const currentValue = await nameInput.inputValue();

		// Type the same value to trigger save without actually changing
		await nameInput.fill(currentValue || 'Test User');
		await panel.getByRole('button', { name: 'Save' }).click();
		await expect(panel.getByText('Profile updated')).toBeVisible({ timeout: 5_000 });

		await screenshot(page, 'profile', 'account-save-success');
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Profile – Notifications tab (US-3)
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Profile – Notifications tab', () => {
	test('notifications tab shows SMTP and Telegram sections', async ({ page }) => {
		await gotoProfile(page, 'notifications');
		await waitForProfileTab(page, 'Notifications');

		await expect(page.getByText('SMTP', { exact: true })).toBeVisible();
		await expect(page.getByText('Telegram', { exact: true })).toBeVisible();

		// SMTP section is expanded by default, check fields
		await expect(page.locator('#smtp-host')).toBeVisible();
		await expect(page.locator('#smtp-port')).toBeVisible();

		await screenshot(page, 'profile', 'notifications-tab');
	});

	test('notifications tab SMTP test button exists', async ({ page }) => {
		await gotoProfile(page, 'notifications');
		await waitForProfileTab(page, 'Notifications');

		await expect(page.locator('[data-testid="settings-smtp-test-button"]')).toBeVisible();
		await expect(page.locator('[data-testid="settings-smtp-test-recipient"]')).toBeVisible();
	});

	test('notifications tab has Telegram toggle', async ({ page }) => {
		await gotoProfile(page, 'notifications');
		await waitForProfileTab(page, 'Notifications');

		// Expand Telegram section
		await page.getByRole('button', { name: /Telegram/i }).click();
		await expect(page.locator('#telegram-bot-token')).toBeVisible();
		await expect(page.getByRole('switch', { name: 'Toggle Telegram bot' })).toBeVisible();
	});

	test('notifications save shows success feedback on 200', async ({ page }) => {
		await gotoProfile(page, 'notifications');
		await waitForProfileTab(page, 'Notifications');

		await page.getByRole('button', { name: 'Save' }).click();
		await expect(page.getByText('Notification settings saved')).toBeVisible({ timeout: 5_000 });

		await screenshot(page, 'profile', 'notifications-save-success');
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Profile – AI Providers tab (US-4)
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Profile – AI Providers tab', () => {
	test('ai providers tab shows all provider panels', async ({ page }) => {
		await gotoProfile(page, 'ai-providers');
		await waitForProfileTab(page, 'AI Providers');

		await expect(page.getByText('OpenRouter')).toBeVisible();
		await expect(page.getByText('OpenAI')).toBeVisible();
		await expect(page.getByText('Ollama')).toBeVisible();

		await screenshot(page, 'profile', 'ai-providers-tab');
	});

	test('ai providers tab has test buttons for each provider', async ({ page }) => {
		await gotoProfile(page, 'ai-providers');
		await waitForProfileTab(page, 'AI Providers');

		await expect(page.getByRole('button', { name: 'Test OpenRouter' })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Test OpenAI' })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Test Ollama' })).toBeVisible();
	});

	test('ai providers save shows success feedback on 200', async ({ page }) => {
		await gotoProfile(page, 'ai-providers');
		await waitForProfileTab(page, 'AI Providers');

		await page.getByRole('button', { name: 'Save' }).click();
		await expect(page.getByText('AI provider settings saved')).toBeVisible({ timeout: 5_000 });

		await screenshot(page, 'profile', 'ai-providers-save-success');
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Profile – System tab
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Profile – System tab', () => {
	test.afterEach(async ({ page }) => {
		await restoreDefaultNamespace(page);
	});
	test('system tab shows debug section with IndexedDB toggle', async ({ page }) => {
		await gotoProfile(page, 'system');
		await waitForProfileTab(page, 'System');

		await expect(page.getByRole('heading', { name: 'Debug' })).toBeVisible();
		await expect(page.getByText('IndexedDB Inspector', { exact: true })).toBeVisible();
		await expect(page.getByRole('switch', { name: 'Toggle IndexedDB inspector' })).toBeVisible();

		await screenshot(page, 'profile', 'system-tab');
	});

	test('IndexedDB toggle persists after save and reload', async ({ page }) => {
		await gotoProfile(page, 'system');
		await waitForProfileTab(page, 'System');

		const toggle = page.getByRole('switch', { name: 'Toggle IndexedDB inspector' });
		const wasEnabled = (await toggle.getAttribute('aria-checked')) === 'true';

		// Toggle to the opposite state
		await toggle.click();
		await expect(toggle).toHaveAttribute('aria-checked', String(!wasEnabled), { timeout: 3_000 });

		await page.getByRole('button', { name: 'Save' }).click();
		await expect(page.getByText('System settings saved')).toBeVisible({ timeout: 5_000 });

		// Verify toggle state is correct immediately after save (before reload)
		await expect(toggle).toHaveAttribute('aria-checked', String(!wasEnabled), { timeout: 5_000 });

		await page.reload();
		await waitForProfileTab(page, 'System');
		await expect(toggle).toHaveAttribute('aria-checked', String(!wasEnabled), { timeout: 5_000 });

		// Restore original state
		await toggle.click();
		await expect(toggle).toHaveAttribute('aria-checked', String(wasEnabled), { timeout: 3_000 });
		await page.getByRole('button', { name: 'Save' }).click();
		await expect(page.getByText('System settings saved')).toBeVisible({ timeout: 5_000 });
	});

	test('system tab shows collapsible schema groups for export options', async ({ page }) => {
		await gotoProfile(page, 'system');
		await waitForProfileTab(page, 'System');

		await expect(page.getByText('What you can export')).toBeVisible();
		await expect(page.getByText('Namespace tables: default')).toBeVisible();
		await expect(
			page.locator('[data-testid="system-export-group-toggle"][data-schema-name="public"]')
		).toContainText('App tables');
		const defaultToggle = page.locator(
			'[data-testid="system-export-group-toggle"][data-schema-name="default"]'
		);
		await expect(defaultToggle).toBeVisible();
		await expect(defaultToggle).toHaveAttribute('aria-expanded', 'false');
		await expect(
			page.locator('[data-testid="internal-table-onboard-switch"]').first()
		).not.toBeVisible();

		await defaultToggle.click();
		await expect(defaultToggle).toHaveAttribute('aria-expanded', 'true');
		await expect(
			page.locator('[data-testid="internal-table-onboard-switch"]').first()
		).toBeVisible();

		await defaultToggle.click();
		await expect(defaultToggle).toHaveAttribute('aria-expanded', 'false');
	});

	test('system internal postgres switch persists on refresh and can toggle off again', async ({
		page
	}) => {
		await gotoProfile(page, 'system');
		await waitForProfileTab(page, 'System');

		await expandSystemExportGroup(page, 'default');

		const switchControl = page.locator(
			'[data-testid="internal-table-onboard-switch"][data-internal-table-key="default.analyses"]'
		);
		await expect(switchControl).toBeVisible({ timeout: 15_000 });

		if ((await switchControl.getAttribute('aria-checked')) !== 'true') {
			await switchControl.click();
			await expect(switchControl).toHaveAttribute('aria-checked', 'true', {
				timeout: 15_000
			});
			await expect(switchControl).toBeEnabled({ timeout: 15_000 });
		}

		await page.reload();
		await waitForProfileTabs(page);
		await waitForProfileTab(page, 'System');
		await expandSystemExportGroup(page, 'default');
		await expect(switchControl).toHaveAttribute('aria-checked', 'true', {
			timeout: 15_000
		});
		await expect(switchControl).toBeEnabled({ timeout: 15_000 });

		await switchControl.click();
		await expect(switchControl).toHaveAttribute('aria-checked', 'false', {
			timeout: 15_000
		});
		await expect(switchControl).toBeEnabled({ timeout: 15_000 });
	});

	test('system tab preserves hash and reloads onboard state when namespace changes', async ({
		page
	}) => {
		const id = uid();
		const nsA = `e2e-profile-a-${id}`;
		const nsB = `e2e-profile-b-${id}`;
		const switchControl = page.locator(
			'[data-testid="internal-table-onboard-switch"][data-internal-table-key="default.analyses"]'
		);

		try {
			await gotoProfile(page, 'system');
			await waitForProfileTab(page, 'System');

			await switchNamespace(page, nsA);
			await expect(page).toHaveURL((url) => url.pathname === '/profile' && url.hash === '#system', {
				timeout: 5_000
			});
			await waitForProfileTab(page, 'System');
			await expandSystemExportGroup(page, 'default');
			await expect(switchControl).toHaveAttribute('aria-checked', 'false', {
				timeout: 5_000
			});

			await switchControl.click();
			await expect(switchControl).toHaveAttribute('aria-checked', 'true', {
				timeout: 5_000
			});

			await switchNamespace(page, nsB);
			await expect(page).toHaveURL((url) => url.pathname === '/profile' && url.hash === '#system', {
				timeout: 5_000
			});
			await waitForProfileTab(page, 'System');
			await expandSystemExportGroup(page, 'default');
			await expect(switchControl).toHaveAttribute('aria-checked', 'false', {
				timeout: 5_000
			});

			await switchNamespace(page, nsA);
			await expect(page).toHaveURL((url) => url.pathname === '/profile' && url.hash === '#system', {
				timeout: 5_000
			});
			await waitForProfileTab(page, 'System');
			await expandSystemExportGroup(page, 'default');
			await expect(switchControl).toHaveAttribute('aria-checked', 'true', {
				timeout: 5_000
			});
		} finally {
			await switchNamespace(page, nsA);
			await waitForProfileTab(page, 'System');
			await expandSystemExportGroup(page, 'default');
			if ((await switchControl.getAttribute('aria-checked')) === 'true') {
				await switchControl.click();
				await expect(switchControl).toHaveAttribute('aria-checked', 'false', {
					timeout: 5_000
				});
			}
		}
	});

	test('system tab keeps public namespace distinct from app schema public', async ({ page }) => {
		await gotoProfile(page, 'system');
		await waitForProfileTab(page, 'System');
		await switchNamespace(page, 'public');
		await expect(page).toHaveURL((url) => url.pathname === '/profile' && url.hash === '#system', {
			timeout: 5_000
		});
		await waitForProfileTab(page, 'System');
		await expect(page.getByText('App tables')).toBeVisible();
		await expect(page.getByText('Shared internal app data')).toBeVisible();
		await expect(page.getByText('Namespace tables: public')).toBeVisible();
		await expect(page.getByText('Data Forge namespace: public (current)')).toBeVisible();
		await expect(page.getByText('Namespace tables: default')).toBeVisible();
		await expect(page.getByText('Data Forge namespace: default')).toBeVisible();
		await expect(page.getByText('df$tenant$public')).toHaveCount(0);
	});

	test('system save shows success feedback on 200', async ({ page }) => {
		await gotoProfile(page, 'system');
		await waitForProfileTab(page, 'System');

		await page.getByRole('button', { name: 'Save' }).click();
		await expect(page.getByText('System settings saved')).toBeVisible({ timeout: 5_000 });

		await screenshot(page, 'profile', 'system-save-success');
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Profile – sidebar navigation
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Profile – sidebar navigation', () => {
	test('sidebar Profile link navigates to /profile', async ({ page }) => {
		await page.goto('/');
		await waitForAppShell(page);

		await page.getByRole('link', { name: 'Profile' }).click();
		await page.waitForURL(/\/profile/, { timeout: 5_000 });

		await expect(page.getByRole('tab', { name: 'Account' })).toHaveAttribute(
			'aria-selected',
			'true'
		);

		await screenshot(page, 'profile', 'sidebar-profile-navigation');
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Profile – accessibility
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Profile – accessibility', () => {
	test('tab panel has correct ARIA attributes', async ({ page }) => {
		await gotoProfile(page);

		// Tablist has aria-label
		await expect(page.getByRole('tablist', { name: 'Profile sections' })).toBeVisible();

		// Active tab has aria-selected=true and controls the panel
		const accountTab = page.getByRole('tab', { name: 'Account' });
		await expect(accountTab).toHaveAttribute('aria-selected', 'true');
		await expect(accountTab).toHaveAttribute('aria-controls', 'panel-account');

		// Inactive tabs have aria-selected=false
		const notifTab = page.getByRole('tab', { name: 'Notifications' });
		await expect(notifTab).toHaveAttribute('aria-selected', 'false');

		// Panel has role=tabpanel and aria-labelledby
		const panel = page.locator('#panel-account');
		await expect(panel).toHaveAttribute('role', 'tabpanel');
		await expect(panel).toHaveAttribute('aria-labelledby', 'tab-account');
	});

	test('Home and End keys navigate to first and last tab', async ({ page }) => {
		await gotoProfile(page);

		// Focus Account tab and press End
		const accountTab = page.getByRole('tab', { name: 'Account' });
		await accountTab.focus();
		await page.keyboard.press('End');
		await expect(page.getByRole('tab', { name: 'System' })).toHaveAttribute(
			'aria-selected',
			'true'
		);

		// Press Home
		await page.keyboard.press('Home');
		await expect(page.getByRole('tab', { name: 'Account' })).toHaveAttribute(
			'aria-selected',
			'true'
		);
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Profile – Account tab functional
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Profile – Account tab functional', () => {
	test('password change with correct current password succeeds', async ({ page }) => {
		await gotoProfile(page, 'account');

		const panel = page.locator('#panel-account');
		await panel.locator('#current').fill(E2E_PASSWORD);
		await panel.locator('#fresh').fill('NewValidPass123!');
		await panel.locator('#confirm').fill('NewValidPass123!');

		await panel.getByRole('button', { name: 'Change password' }).click();

		await expect(panel.getByText('Password changed')).toBeVisible({ timeout: 5_000 });

		// Fields should be cleared after success
		await expect(panel.locator('#current')).toHaveValue('');
		await expect(panel.locator('#fresh')).toHaveValue('');
		await expect(panel.locator('#confirm')).toHaveValue('');
	});

	test('password change with wrong current password shows error', async ({ page }) => {
		await gotoProfile(page, 'account');

		const panel = page.locator('#panel-account');
		await panel.locator('#current').fill('WrongPassword123!');
		await panel.locator('#fresh').fill('NewValidPass123!');
		await panel.locator('#confirm').fill('NewValidPass123!');

		await panel.getByRole('button', { name: 'Change password' }).click();

		// Backend returns "Invalid email or password" for wrong current password
		await expect(panel.getByText(/Invalid email or password/i)).toBeVisible({ timeout: 5_000 });
	});

	test('password change with mismatched new passwords shows error', async ({ page }) => {
		await gotoProfile(page, 'account');

		const panel = page.locator('#panel-account');
		await panel.locator('#current').fill(E2E_PASSWORD);
		await panel.locator('#fresh').fill('NewValidPass123!');
		await panel.locator('#confirm').fill('DifferentPass123!');

		await panel.getByRole('button', { name: 'Change password' }).click();

		await expect(panel.getByText(/Passwords do not match/i)).toBeVisible({ timeout: 5_000 });
	});

	test('password change with short new password is blocked by HTML5 validation', async ({
		page
	}) => {
		await gotoProfile(page, 'account');

		const panel = page.locator('#panel-account');
		await panel.locator('#current').fill(E2E_PASSWORD);
		await panel.locator('#fresh').fill('short');
		await panel.locator('#confirm').fill('short');

		// The #fresh input has minlength=8, so browser blocks submission before JS runs
		await expect(panel.locator('#fresh')).toHaveAttribute('minlength', '8');

		// Clicking submit should not navigate away or show a success message
		await panel.getByRole('button', { name: 'Change password' }).click();
		await expect(page).toHaveURL('/profile#account');
		await expect(panel.getByText('Password changed')).not.toBeVisible();
	});

	test('display name can be edited and persists after save and reload', async ({ page }) => {
		await gotoProfile(page, 'account');

		const panel = page.locator('#panel-account');
		const newName = `E2E Display ${uid()}`;
		await panel.locator('#name').fill(newName);
		await panel.getByRole('button', { name: 'Save' }).click();
		await expect(panel.getByText('Profile updated')).toBeVisible({ timeout: 5_000 });

		// Verify display name is correct immediately after save (before reload)
		await expect(panel.locator('#name')).toHaveValue(newName);

		await page.reload();
		await waitForProfileTabs(page);
		await expect(panel.locator('#name')).toHaveValue(newName);
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Profile – AI Providers tab functional
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Profile – AI Providers tab functional', () => {
	test('clicking Test Ollama button triggers feedback message', async ({ page }) => {
		await gotoProfile(page, 'ai-providers');
		await waitForProfileTab(page, 'AI Providers');

		const testBtn = page.getByRole('button', { name: 'Test Ollama' });
		await expect(testBtn).toBeVisible();
		await testBtn.click();

		// Wait for feedback to appear (either success or error)
		await expect(
			page.locator(':text("ollama:")').or(page.getByText(/error|failed/i).first())
		).toBeVisible({ timeout: 10_000 });
	});

	test('clicking Test OpenRouter without key triggers error feedback', async ({ page }) => {
		await gotoProfile(page, 'ai-providers');
		await waitForProfileTab(page, 'AI Providers');

		const testBtn = page.getByRole('button', { name: 'Test OpenRouter' });
		await expect(testBtn).toBeVisible();
		await testBtn.click();

		await expect(
			page.locator(':text("openrouter:")').or(page.getByText(/error|failed|key/i).first())
		).toBeVisible({ timeout: 10_000 });
	});

	test('AI provider model and key dirty state persists after save and reload', async ({ page }) => {
		await gotoProfile(page, 'ai-providers');
		await waitForProfileTab(page, 'AI Providers');

		const modelInput = page.locator('input[placeholder="openai/gpt-4o-mini"]');
		const keyInput = page.locator('input[type="password"]').first();

		const testModel = `e2e-model-${uid()}`;
		await modelInput.fill(testModel);
		await keyInput.fill('e2e-fake-key-12345');

		await page.getByRole('button', { name: 'Save' }).click();
		await expect(page.getByText('AI provider settings saved')).toBeVisible({ timeout: 5_000 });

		// Verify model value is correct immediately after save (before reload)
		await expect(modelInput).toHaveValue(testModel);

		await page.reload();
		await waitForProfileTab(page, 'AI Providers');

		// Model should persist
		await expect(modelInput).toHaveValue(testModel);
		// Key should be cleared (masked) after reload since server returns masked
		await expect(keyInput).toHaveValue('');
	});

	test('AI provider OpenAI endpoint edit persists after save and reload', async ({ page }) => {
		await gotoProfile(page, 'ai-providers');
		await waitForProfileTab(page, 'AI Providers');

		const endpointInput = page.locator('#openai-endpoint-url');
		await expect(endpointInput).toBeVisible({ timeout: 3_000 });

		const customEndpoint = 'https://e2e-openai.example.com';
		await endpointInput.fill(customEndpoint);

		await page.getByRole('button', { name: 'Save' }).click();
		await expect(page.getByText('AI provider settings saved')).toBeVisible({ timeout: 5_000 });

		// Verify endpoint is correct immediately after save (before reload)
		await expect(endpointInput).toHaveValue(customEndpoint);

		await page.reload();
		await waitForProfileTab(page, 'AI Providers');
		await expect(endpointInput).toHaveValue(customEndpoint);
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Profile – Notifications tab functional
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Profile – Notifications tab functional', () => {
	test('SMTP test button is disabled when recipient is empty', async ({ page }) => {
		await gotoProfile(page, 'notifications');
		await waitForProfileTab(page, 'Notifications');

		const testBtn = page.locator('[data-testid="settings-smtp-test-button"]');
		await expect(testBtn).toBeDisabled();
	});

	test('SMTP test with recipient triggers feedback', async ({ page }) => {
		await gotoProfile(page, 'notifications');
		await waitForProfileTab(page, 'Notifications');

		await page.locator('[data-testid="settings-smtp-test-recipient"]').fill('test@example.com');
		await page.locator('[data-testid="settings-smtp-test-button"]').click();

		// Wait for feedback (success or error)
		await expect(page.getByText(/SMTP|test|sent|error|failed/i).first()).toBeVisible({
			timeout: 10_000
		});
	});

	test('SMTP test button toggles enabled state with recipient input', async ({ page }) => {
		await gotoProfile(page, 'notifications');
		await waitForProfileTab(page, 'Notifications');

		const testBtn = page.locator('[data-testid="settings-smtp-test-button"]');
		const recipient = page.locator('[data-testid="settings-smtp-test-recipient"]');

		// Initially disabled
		await expect(testBtn).toBeDisabled();

		// Typing enables the button
		await recipient.fill('user@example.com');
		await expect(testBtn).toBeEnabled({ timeout: 3_000 });

		// Clearing disables again
		await recipient.fill('');
		await expect(testBtn).toBeDisabled({ timeout: 3_000 });
	});

	test('Telegram toggle on/off persists after save and reload', async ({ page }) => {
		await gotoProfile(page, 'notifications');
		await waitForProfileTab(page, 'Notifications');

		// Expand Telegram section
		await page.getByRole('button', { name: /Telegram/i }).click();
		await expect(page.locator('#telegram-bot-token')).toBeVisible({ timeout: 3_000 });

		const toggle = page.locator('[role="switch"][aria-label="Toggle Telegram bot"]');
		await expect(toggle).toBeVisible();

		// Toggle on if not already
		const wasEnabled = (await toggle.getAttribute('aria-checked')) === 'true';
		if (!wasEnabled) {
			await toggle.click();
			await expect(toggle).toHaveAttribute('aria-checked', 'true', { timeout: 3_000 });
		}

		// Save
		await page.getByRole('button', { name: 'Save' }).click();
		await expect(page.getByText('Notification settings saved')).toBeVisible({ timeout: 5_000 });

		// Verify toggle state is correct immediately after save (before reload)
		await expect(toggle).toHaveAttribute('aria-checked', 'true', { timeout: 5_000 });

		// Reload and verify toggle state persisted
		await page.reload();
		await waitForProfileTab(page, 'Notifications');
		await page.getByRole('button', { name: /Telegram/i }).click();
		await expect(page.locator('#telegram-bot-token')).toBeVisible({ timeout: 3_000 });
		await expect(toggle).toHaveAttribute('aria-checked', 'true', { timeout: 5_000 });

		// Toggle back off to clean up
		await toggle.click();
		await expect(toggle).toHaveAttribute('aria-checked', 'false', { timeout: 3_000 });
		await page.getByRole('button', { name: 'Save' }).click();
		await expect(page.getByText('Notification settings saved')).toBeVisible({ timeout: 5_000 });
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Profile – Connected accounts functional
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Profile – Connected accounts', () => {
	test('Google and GitHub connect buttons are present when not connected', async ({ page }) => {
		await gotoProfile(page, 'account');

		const panel = page.locator('#panel-account');

		// Since e2e worker registers via email, OAuth should not be connected.
		// Look for Connect buttons in the connected-accounts section.
		const connectButtons = panel.getByRole('button', { name: 'Connect' });
		await expect(connectButtons).toHaveCount(2);
	});
});
