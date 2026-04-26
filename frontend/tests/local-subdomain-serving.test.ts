import { test, expect } from './fixtures.js';
import { buildStorageState, deleteAccount, registerUser } from './utils/api.js';
import { waitForAppShell } from './utils/readiness.js';

test.describe('Local subdomain serving', () => {
	test('app boots on dataforge.localhost and credentialed backend fetches succeed', async ({
		browser
	}) => {
		const frontendPort = process.env.FRONTEND_PORT || '3000';
		const backendPort = process.env.BACKEND_PORT || process.env.PORT || '8000';
		const subdomainHost = process.env.PLAYWRIGHT_SUBDOMAIN_HOST || 'dataforge.localhost';
		const frontendOrigin = `http://${subdomainHost}:${frontendPort}`;
		const apiOrigin = `http://${subdomainHost}:${backendPort}`;
		const email = `e2e-subdomain-${Date.now().toString(36)}@example.com`;
		const token = await registerUser(email, 'Subdomain User');

		const context = await browser.newContext({
			baseURL: frontendOrigin,
			storageState: buildStorageState(token, {
				apiOrigin,
				cookieDomain: subdomainHost,
				frontendOrigin
			})
		});
		const page = await context.newPage();

		try {
			await page.goto('/');
			await waitForAppShell(page);
			await expect(page.getByRole('heading', { name: 'Analyses', level: 1 })).toBeVisible();
			expect(new URL(page.url()).origin).toBe(frontendOrigin);

			const me = await page.evaluate(async (origin) => {
				const response = await fetch(`${origin}/api/v1/auth/me`, {
					credentials: 'include',
					headers: { Accept: 'application/json' },
					mode: 'cors'
				});

				return {
					body: (await response.json()) as { email?: string },
					ok: response.ok,
					status: response.status
				};
			}, apiOrigin);

			expect(me.ok).toBe(true);
			expect(me.status).toBe(200);
			expect(me.body.email).toBe(email);
		} finally {
			await page.close().catch(() => {});
			await context.close().catch(() => {});
			await deleteAccount(token).catch(() => {});
		}
	});
});
