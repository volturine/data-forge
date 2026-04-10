import { expect, type Page } from '@playwright/test';
import { E2E_PASSWORD } from './api.js';
import { gotoNewAnalysis, waitForDatasourceList, waitForLayoutReady } from './readiness.js';

const SAMPLE_CSV = 'id,name,age,city\n1,Alice,30,London\n2,Bob,25,Paris\n3,Charlie,35,Berlin\n';

export async function registerViaUi(page: Page, email: string, name: string): Promise<void> {
	await page.goto('/register');
	await expect(page.getByRole('heading', { name: 'Create account' })).toBeVisible({
		timeout: 15_000
	});
	await page.locator('#name').fill(name);
	await page.locator('#email').fill(email);
	await page.locator('#password').fill(E2E_PASSWORD);
	await page.locator('#confirm').fill(E2E_PASSWORD);
	await page.getByRole('button', { name: 'Create account' }).click();
	await expect(
		page.getByText(
			'Account created. Check your email for a verification link to activate your account.'
		)
	).toBeVisible({
		timeout: 15_000
	});
}

export async function uploadDatasourceViaUi(page: Page, name: string): Promise<void> {
	await page.goto('/datasources/new');
	await waitForLayoutReady(page);
	const fileInput = page.locator('#file-input');
	await fileInput.setInputFiles({
		name: `${name}.csv`,
		mimeType: 'text/csv',
		buffer: Buffer.from(SAMPLE_CSV)
	});
	await page.getByRole('button', { name: 'Upload', exact: true }).click();
	await expect(page).toHaveURL((url) => !url.pathname.endsWith('/new'), { timeout: 30_000 });
	await page.goto('/datasources');
	await waitForDatasourceList(page);
	await expect(page.locator(`[data-ds-row="${name}"]`)).toBeVisible({ timeout: 15_000 });
}

export async function createAnalysisViaUi(
	page: Page,
	analysisName: string,
	datasourceName: string
): Promise<string> {
	await gotoNewAnalysis(page);
	await page.locator('#name').fill(analysisName);
	await page.getByRole('button', { name: /Next/i }).click();
	await expect(page.getByRole('heading', { name: /Select Data Sources/i })).toBeVisible();
	await page.getByPlaceholder('Search datasources...').click();
	await page.locator('[role="option"]', { hasText: datasourceName }).first().click();
	await page.getByRole('heading', { name: /Select Data Sources/i }).click();
	await page.getByRole('button', { name: /Next/i }).click();
	await expect(page.getByRole('heading', { name: /Review/i })).toBeVisible();
	await page.getByRole('button', { name: /Create Analysis/i }).click();
	await expect(page).toHaveURL(
		(url) => url.pathname.startsWith('/analysis/') && url.pathname !== '/analysis/new',
		{
			timeout: 20_000
		}
	);
	const match = page.url().match(/\/analysis\/([^/?#]+)/);
	if (!match || match[1] === 'new') {
		throw new Error(`Could not extract analysis id from URL: ${page.url()}`);
	}
	return match[1];
}
