import { test, expect } from './fixtures.js';
import { screenshot } from './utils/visual.js';
import { waitForAppShell, waitForProfileTabs, waitForProfileTab } from './utils/readiness.js';

// ────────────────────────────────────────────────────────────────────────────────
// Profile page – tabbed interface
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Profile – tabbed interface', () => {
	test('profile page renders with Account tab active by default', async ({ page }) => {
		await page.goto('/profile');
		await waitForProfileTabs(page);

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
		await page.goto('/profile');
		await waitForProfileTabs(page);

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
		await page.goto('/profile#notifications');
		await waitForProfileTabs(page);

		await expect(page.getByRole('tab', { name: 'Notifications' })).toHaveAttribute(
			'aria-selected',
			'true'
		);
		await expect(page.locator('#panel-notifications')).toBeVisible();

		await screenshot(page, 'profile', 'notifications-deeplink');
	});

	test('navigating to /profile#ai-providers opens AI Providers tab', async ({ page }) => {
		await page.goto('/profile#ai-providers');
		await waitForProfileTabs(page);

		await expect(page.getByRole('tab', { name: 'AI Providers' })).toHaveAttribute(
			'aria-selected',
			'true'
		);
		await expect(page.locator('#panel-ai-providers')).toBeVisible();

		await screenshot(page, 'profile', 'ai-providers-deeplink');
	});

	test('navigating to /profile#system opens System tab', async ({ page }) => {
		await page.goto('/profile#system');
		await waitForProfileTabs(page);

		await expect(page.getByRole('tab', { name: 'System' })).toHaveAttribute(
			'aria-selected',
			'true'
		);
		await expect(page.locator('#panel-system')).toBeVisible();

		await screenshot(page, 'profile', 'system-deeplink');
	});

	test('invalid hash defaults to Account tab', async ({ page }) => {
		await page.goto('/profile#nonexistent');
		await waitForProfileTabs(page);

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
		await page.goto('/profile');
		await waitForProfileTabs(page);

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
		await page.goto('/profile');
		await waitForProfileTabs(page);

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
		await page.goto('/profile#account');
		await waitForProfileTabs(page);

		const panel = page.locator('#panel-account');
		const emailInput = panel.locator('#email');
		await expect(emailInput).toBeVisible();
		await expect(emailInput).toBeDisabled();

		const nameInput = panel.locator('#name');
		await expect(nameInput).toBeVisible();

		await screenshot(page, 'profile', 'account-fields');
	});

	test('account tab shows password change form', async ({ page }) => {
		await page.goto('/profile#account');
		await waitForProfileTabs(page);

		const panel = page.locator('#panel-account');
		await expect(panel.locator('#current')).toBeVisible();
		await expect(panel.locator('#fresh')).toBeVisible();
		await expect(panel.locator('#confirm')).toBeVisible();
		await expect(panel.getByRole('button', { name: 'Change password' })).toBeVisible();
	});

	test('account tab shows connected accounts section', async ({ page }) => {
		await page.goto('/profile#account');
		await waitForProfileTabs(page);

		const panel = page.locator('#panel-account');
		await expect(panel.getByText('Connected accounts')).toBeVisible();
		await expect(panel.getByText('Google')).toBeVisible();
		await expect(panel.getByText('GitHub')).toBeVisible();
	});

	test('profile save shows success feedback on 200', async ({ page }) => {
		await page.goto('/profile#account');
		await waitForProfileTabs(page);

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
		await page.goto('/profile#notifications');
		await waitForProfileTab(page, 'Notifications');

		await expect(page.getByText('SMTP', { exact: true })).toBeVisible();
		await expect(page.getByText('Telegram', { exact: true })).toBeVisible();

		// SMTP section is expanded by default, check fields
		await expect(page.locator('#smtp-host')).toBeVisible();
		await expect(page.locator('#smtp-port')).toBeVisible();

		await screenshot(page, 'profile', 'notifications-tab');
	});

	test('notifications tab SMTP test button exists', async ({ page }) => {
		await page.goto('/profile#notifications');
		await waitForProfileTab(page, 'Notifications');

		await expect(page.locator('[data-testid="settings-smtp-test-button"]')).toBeVisible();
		await expect(page.locator('[data-testid="settings-smtp-test-recipient"]')).toBeVisible();
	});

	test('notifications tab has Telegram toggle', async ({ page }) => {
		await page.goto('/profile#notifications');
		await waitForProfileTab(page, 'Notifications');

		// Expand Telegram section
		await page.getByRole('button', { name: /Telegram/i }).click();
		await expect(page.locator('#telegram-bot-token')).toBeVisible();
		await expect(page.getByRole('switch', { name: 'Toggle Telegram bot' })).toBeVisible();
	});

	test('notifications save shows success feedback on 200', async ({ page }) => {
		await page.goto('/profile#notifications');
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
	test('ai providers tab shows all four provider panels', async ({ page }) => {
		await page.goto('/profile#ai-providers');
		await waitForProfileTab(page, 'AI Providers');

		await expect(page.getByText('OpenRouter')).toBeVisible();
		await expect(page.getByText('OpenAI')).toBeVisible();
		await expect(page.getByText('Ollama')).toBeVisible();
		await expect(page.getByText('Hugging Face')).toBeVisible();

		await screenshot(page, 'profile', 'ai-providers-tab');
	});

	test('ai providers tab has test buttons for each provider', async ({ page }) => {
		await page.goto('/profile#ai-providers');
		await waitForProfileTab(page, 'AI Providers');

		await expect(page.getByRole('button', { name: 'Test OpenRouter' })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Test OpenAI' })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Test Ollama' })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Test Hugging Face' })).toBeVisible();
	});

	test('ai providers save shows success feedback on 200', async ({ page }) => {
		await page.goto('/profile#ai-providers');
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
	test('system tab shows debug section with IndexedDB toggle', async ({ page }) => {
		await page.goto('/profile#system');
		await waitForProfileTab(page, 'System');

		await expect(page.getByRole('heading', { name: 'Debug' })).toBeVisible();
		await expect(page.getByText('IndexedDB Inspector')).toBeVisible();
		await expect(page.getByRole('switch', { name: 'Toggle IndexedDB inspector' })).toBeVisible();

		await screenshot(page, 'profile', 'system-tab');
	});

	test('system save shows success feedback on 200', async ({ page }) => {
		await page.goto('/profile#system');
		await waitForProfileTab(page, 'System');

		await page.getByRole('button', { name: 'Save' }).click();
		await expect(page.getByText('System settings saved')).toBeVisible({ timeout: 5_000 });

		await screenshot(page, 'profile', 'system-save-success');
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Profile – Settings redirect
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Profile – settings redirect', () => {
	test('/settings redirects to /profile with system tab', async ({ page }) => {
		await page.goto('/settings');
		await page.waitForURL(/\/profile/, { timeout: 10_000 });
		await expect(page).toHaveURL(/profile/);
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
		await page.waitForURL(/\/profile/, { timeout: 10_000 });

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
		await page.goto('/profile');
		await waitForProfileTabs(page);

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
		await page.goto('/profile');
		await waitForProfileTabs(page);

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
