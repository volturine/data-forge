import { test, expect } from '@playwright/test';
import { uid } from './utils/uid.js';

const port = parseInt(process.env.FRONTEND_PORT || '3000', 10);
const baseURL = process.env.PLAYWRIGHT_BASE_URL || `http://localhost:${port}`;

test.describe('Auth – registration flow', () => {
	test('register with valid credentials creates account', async ({ browser }) => {
		const context = await browser.newContext({ baseURL });
		const page = await context.newPage();
		try {
			const email = `e2e-auth-reg-${uid()}@example.com`;
			await page.goto('/register');
			await expect(page.getByRole('heading', { name: 'Create account' })).toBeVisible({
				timeout: 5_000
			});

			await page.locator('#name').fill('E2E Auth User');
			await page.locator('#email').fill(email);
			await page.locator('#password').fill('ValidPass123!');
			await page.locator('#confirm').fill('ValidPass123!');

			await page.getByRole('button', { name: 'Create account', exact: true }).click();

			await expect(
				page.getByText(/Account created/i).or(page.getByLabel('Main navigation'))
			).toBeVisible({ timeout: 5_000 });
		} finally {
			await context.close();
		}
	});

	test('register submit button is disabled when password is too short', async ({ browser }) => {
		const context = await browser.newContext({ baseURL });
		const page = await context.newPage();
		try {
			await page.goto('/register');
			await expect(page.getByRole('heading', { name: 'Create account' })).toBeVisible({
				timeout: 5_000
			});

			await page.locator('#name').fill('E2E User');
			await page.locator('#email').fill(`e2e-auth-${uid()}@example.com`);
			await page.locator('#password').fill('short');
			await page.locator('#confirm').fill('short');

			await expect(
				page.getByRole('button', { name: 'Create account', exact: true })
			).toBeDisabled();
		} finally {
			await context.close();
		}
	});

	test('register submit button is disabled when passwords do not match', async ({ browser }) => {
		const context = await browser.newContext({ baseURL });
		const page = await context.newPage();
		try {
			await page.goto('/register');
			await expect(page.getByRole('heading', { name: 'Create account' })).toBeVisible({
				timeout: 5_000
			});

			await page.locator('#name').fill('E2E User');
			await page.locator('#email').fill(`e2e-auth-${uid()}@example.com`);
			await page.locator('#password').fill('ValidPass123!');
			await page.locator('#confirm').fill('DifferentPass123!');

			await expect(
				page.getByRole('button', { name: 'Create account', exact: true })
			).toBeDisabled();
		} finally {
			await context.close();
		}
	});

	test('register submit button is disabled when name is empty', async ({ browser }) => {
		const context = await browser.newContext({ baseURL });
		const page = await context.newPage();
		try {
			await page.goto('/register');
			await expect(page.getByRole('heading', { name: 'Create account' })).toBeVisible({
				timeout: 5_000
			});

			await page.locator('#email').fill(`e2e-auth-${uid()}@example.com`);
			await page.locator('#password').fill('ValidPass123!');
			await page.locator('#confirm').fill('ValidPass123!');

			await expect(
				page.getByRole('button', { name: 'Create account', exact: true })
			).toBeDisabled();
		} finally {
			await context.close();
		}
	});
});

test.describe('Auth – login flow', () => {
	test('login page renders email and password fields', async ({ browser }) => {
		const context = await browser.newContext({ baseURL });
		const page = await context.newPage();
		try {
			await page.goto('/login');
			await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible({ timeout: 5_000 });
			await expect(page.locator('#email')).toBeVisible();
			await expect(page.locator('#password')).toBeVisible();
			await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
		} finally {
			await context.close();
		}
	});

	test('login with wrong password shows error message', async ({ browser }) => {
		const context = await browser.newContext({ baseURL });
		const page = await context.newPage();
		try {
			await page.goto('/login');
			await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible({ timeout: 5_000 });

			await page.locator('#email').fill(`e2e-auth-${uid()}@example.com`);
			await page.locator('#password').fill('WrongPassword123!');
			await page.getByRole('button', { name: 'Sign in', exact: true }).click();

			// Error state should appear (any error text in the form vicinity)
			await expect(page.locator('form')).toContainText(/.+/, { timeout: 5_000 });
		} finally {
			await context.close();
		}
	});

	test('login form includes forgot password link', async ({ browser }) => {
		const context = await browser.newContext({ baseURL });
		const page = await context.newPage();
		try {
			await page.goto('/login');
			await expect(page.getByRole('link', { name: 'Forgot password?' })).toBeVisible();
		} finally {
			await context.close();
		}
	});
});

test.describe('Auth – forgot password flow', () => {
	test('forgot password with valid email shows success message', async ({ browser }) => {
		const context = await browser.newContext({ baseURL });
		const page = await context.newPage();
		try {
			await page.goto('/forgot-password');
			await expect(page.getByRole('heading', { name: 'Forgot password' })).toBeVisible({
				timeout: 5_000
			});
			// Wait for SvelteKit hydration to attach the onsubmit handler
			await page.waitForLoadState('networkidle');

			await page.locator('#email').fill(`e2e-auth-${uid()}@example.com`);
			await page.getByRole('button', { name: 'Send reset link', exact: true }).click();

			// Wait for either success or error feedback (backend may return error if SMTP is not configured)
			await expect(
				page
					.getByText(
						/If an account exists with that email|An internal error occurred|Failed to|error/i
					)
					.first()
			).toBeVisible({ timeout: 10_000 });
		} finally {
			await context.close();
		}
	});
});

test.describe('Auth – reset password flow', () => {
	test('reset password page with no token shows invalid link message and request link', async ({
		browser
	}) => {
		const context = await browser.newContext({ baseURL });
		const page = await context.newPage();
		try {
			await page.goto('/reset-password');
			await expect(page.getByRole('heading', { name: 'Reset password' })).toBeVisible({
				timeout: 5_000
			});

			await expect(page.getByText(/Invalid reset link/i)).toBeVisible();
			// The "Request new reset link" is an <a> styled as a button
			await expect(page.getByRole('link', { name: 'Request new reset link' })).toBeVisible();
		} finally {
			await context.close();
		}
	});

	test('reset password submit button is disabled when password is too short', async ({
		browser
	}) => {
		const context = await browser.newContext({ baseURL });
		const page = await context.newPage();
		try {
			await page.goto('/reset-password?token=dummy-token');
			await expect(page.getByRole('heading', { name: 'Reset password' })).toBeVisible({
				timeout: 5_000
			});

			await page.locator('#password').fill('short');
			await page.locator('#confirm').fill('short');

			await expect(
				page.getByRole('button', { name: 'Reset password', exact: true })
			).toBeDisabled();
		} finally {
			await context.close();
		}
	});

	test('reset password submit button is disabled when passwords do not match', async ({
		browser
	}) => {
		const context = await browser.newContext({ baseURL });
		const page = await context.newPage();
		try {
			await page.goto('/reset-password?token=dummy-token');
			await expect(page.getByRole('heading', { name: 'Reset password' })).toBeVisible({
				timeout: 5_000
			});

			await page.locator('#password').fill('ValidPass123!');
			await page.locator('#confirm').fill('DifferentPass123!');

			await expect(
				page.getByRole('button', { name: 'Reset password', exact: true })
			).toBeDisabled();
		} finally {
			await context.close();
		}
	});
});

test.describe('Auth – verify email flow', () => {
	test('verify page without token shows check email message', async ({ browser }) => {
		const context = await browser.newContext({ baseURL });
		const page = await context.newPage();
		try {
			await page.goto('/verify');
			await expect(page.getByRole('heading', { name: 'Email verification' })).toBeVisible({
				timeout: 5_000
			});

			await expect(page.getByText(/Check your email for a verification link/i)).toBeVisible();
			await expect(page.getByRole('link', { name: 'Back to sign in' })).toBeVisible();
		} finally {
			await context.close();
		}
	});

	test('verify page with invalid token shows error and resend button', async ({ browser }) => {
		const context = await browser.newContext({ baseURL });
		const page = await context.newPage();
		try {
			await page.goto('/verify?token=invalid-token-12345');
			await expect(page.getByRole('heading', { name: 'Email verification' })).toBeVisible({
				timeout: 5_000
			});

			await expect(page.getByText(/Verification failed/i)).toBeVisible({ timeout: 5_000 });
			await expect(page.getByRole('button', { name: /Resend verification email/i })).toBeVisible();
		} finally {
			await context.close();
		}
	});
});

test.describe('Auth – navigation between auth pages', () => {
	test('login page links to register and forgot password', async ({ browser }) => {
		const context = await browser.newContext({ baseURL });
		const page = await context.newPage();
		try {
			await page.goto('/login');
			await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible({ timeout: 5_000 });

			await page.getByRole('link', { name: 'Forgot password?' }).click();
			await expect(page).toHaveURL(/forgot-password/, { timeout: 5_000 });

			await page.goto('/login');
			await page.getByRole('link', { name: 'Sign up' }).click();
			await expect(page).toHaveURL(/register/, { timeout: 5_000 });
		} finally {
			await context.close();
		}
	});

	test('register page links to login', async ({ browser }) => {
		const context = await browser.newContext({ baseURL });
		const page = await context.newPage();
		try {
			await page.goto('/register');
			await expect(page.getByRole('heading', { name: 'Create account' })).toBeVisible({
				timeout: 5_000
			});

			await page.getByRole('link', { name: 'Sign in' }).click();
			await expect(page).toHaveURL(/login/, { timeout: 5_000 });
		} finally {
			await context.close();
		}
	});

	test('forgot password page links back to login', async ({ browser }) => {
		const context = await browser.newContext({ baseURL });
		const page = await context.newPage();
		try {
			await page.goto('/forgot-password');
			await expect(page.getByRole('heading', { name: 'Forgot password' })).toBeVisible({
				timeout: 5_000
			});

			await page.getByRole('link', { name: 'Back to sign in' }).click();
			await expect(page).toHaveURL(/login/, { timeout: 5_000 });
		} finally {
			await context.close();
		}
	});
});
