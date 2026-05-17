import { expect, type Page } from '@playwright/test';
import { gotoNewAnalysis, waitForLayoutReady, waitForUdfList } from './readiness.js';

export const E2E_PASSWORD = 'E2eTestPw12345';

const SAMPLE_CSV = 'id,name,age,city\n1,Alice,30,London\n2,Bob,25,Paris\n3,Charlie,35,Berlin\n';
const DATE_CSV =
	'id,name,event_date,amount\n1,Alice,2024-01-15,100\n2,Bob,2024-03-22,250\n3,Charlie,2024-06-10,75\n';

function generateLargeCsv(rows: number): string {
	const names = ['Alice', 'Bob', 'Charlie', 'Diana', 'Eve', 'Frank', 'Grace', 'Hank'];
	const cities = ['London', 'Paris', 'Berlin', 'Tokyo', 'Sydney', 'Oslo', 'Rome', 'Madrid'];
	const lines = ['id,name,age,city'];
	for (let index = 1; index <= rows; index += 1) {
		lines.push(
			`${index},${names[index % names.length]},${20 + (index % 50)},${cities[index % cities.length]}`
		);
	}
	return `${lines.join('\n')}\n`;
}

export async function registerViaUi(page: Page, email: string, name: string): Promise<void> {
	await page.goto('/register');
	await expect(page.getByRole('heading', { name: 'Create account' })).toBeVisible({
		timeout: 15_000
	});
	const nameInput = page.locator('#name');
	const emailInput = page.locator('#email');
	const passwordInput = page.locator('#password');
	const confirmInput = page.locator('#confirm');
	await nameInput.fill(name);
	await emailInput.fill(email);
	await passwordInput.fill(E2E_PASSWORD);
	await confirmInput.fill(E2E_PASSWORD);
	await expect(nameInput).toHaveValue(name);
	await expect(emailInput).toHaveValue(email);
	await expect(passwordInput).toHaveValue(E2E_PASSWORD);
	await expect(confirmInput).toHaveValue(E2E_PASSWORD);
	const createButton = page.getByRole('button', { name: 'Create account', exact: true });
	await expect(createButton).toBeEnabled({ timeout: 15_000 });
	await createButton.click();
	const continueLink = page.getByRole('link', { name: /Continue/i });
	await Promise.race([
		continueLink.waitFor({ state: 'visible', timeout: 15_000 }),
		page.getByLabel('Main navigation').waitFor({ state: 'visible', timeout: 15_000 }),
		page.getByText(/Account created\./i).waitFor({ state: 'visible', timeout: 15_000 })
	]).catch(() => undefined);
	if (await continueLink.isVisible().catch(() => false)) {
		await continueLink.click();
	} else {
		await page.goto('/', { waitUntil: 'domcontentloaded' });
	}
	await page.getByLabel('Main navigation').waitFor({ state: 'visible', timeout: 15_000 });
}

export async function uploadDatasourceViaUi(
	page: Page,
	name: string,
	options?: {
		description?: string;
		rows?: number;
		csv?: string;
	}
): Promise<{ id: string }> {
	await page.goto('/datasources/new');
	await waitForLayoutReady(page);
	const fileInput = page.locator('#file-input');
	await fileInput.setInputFiles({
		name: `${name}.csv`,
		mimeType: 'text/csv',
		buffer: Buffer.from(
			options?.csv ?? (options?.rows ? generateLargeCsv(options.rows) : SAMPLE_CSV)
		)
	});
	if (options?.description) {
		await page.locator('#file-description').fill(options.description);
	}
	const uploadBtn = page.getByRole('button', { name: 'Upload', exact: true });
	await expect(uploadBtn).toBeEnabled({ timeout: 10_000 });
	await uploadBtn.click();
	await expect(page).toHaveURL((url) => url.pathname === '/datasources', { timeout: 30_000 });
	const row = page.locator(`[data-ds-row="${name}"]`);
	await expect(row).toBeVisible({ timeout: 30_000 });
	await row.click();
	await expect(page).toHaveURL(/id=/, { timeout: 15_000 });
	const datasourceId = new URL(page.url()).searchParams.get('id');
	if (!datasourceId) {
		throw new Error(`Could not extract datasource id after uploading ${name}`);
	}
	return { id: datasourceId };
}

export async function uploadDatasourceWithDatesViaUi(
	page: Page,
	name: string
): Promise<{ id: string }> {
	return uploadDatasourceViaUi(page, name, { csv: DATE_CSV });
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
	await page.locator(`[data-picker-option="${datasourceName}"]`).click();
	await page.getByRole('heading', { name: /Select Data Sources/i }).click();
	await page.getByRole('button', { name: /Next/i }).click();
	await expect(page.getByRole('heading', { name: /Choose Template/i })).toBeVisible();
	await page.getByRole('button', { name: /Next/i }).click();
	await expect(page.getByRole('heading', { name: /Configure Outputs/i })).toBeVisible();
	await page.getByRole('button', { name: /Next/i }).click();
	await expect(page.getByRole('heading', { name: /Review/i })).toBeVisible();
	await page.getByRole('button', { name: /Create Analysis/i }).click();
	await expect(page).toHaveURL(
		(url) => url.pathname.startsWith('/analysis/') && url.pathname !== '/analysis/new',
		{ timeout: 20_000 }
	);
	const match = page.url().match(/\/analysis\/([^/?#]+)/);
	if (!match || match[1] === 'new') {
		throw new Error(`Could not extract analysis id from URL: ${page.url()}`);
	}
	return match[1];
}

export async function importAnalysisViaUi(
	page: Page,
	options: {
		name: string;
		description?: string;
		pipeline: Record<string, unknown>;
		datasourceRemap?: Record<string, string>;
	}
): Promise<string> {
	await gotoNewAnalysis(page);
	await page.getByRole('button', { name: 'Import JSON' }).click();
	await page.locator('#name').fill(options.name);
	if (options.description) {
		await page.locator('#description').fill(options.description);
	}
	await page.getByRole('button', { name: /Next/i }).click();
	await expect(page.getByRole('heading', { name: /Import Pipeline Definition/i })).toBeVisible();
	await page.locator('input[type="file"]').setInputFiles({
		name: `${options.name}.json`,
		mimeType: 'application/json',
		buffer: Buffer.from(JSON.stringify(options.pipeline, null, 2))
	});
	if (options.datasourceRemap) {
		for (const [missingId, datasourceId] of Object.entries(options.datasourceRemap)) {
			const remapSelect = page
				.locator('label')
				.filter({ hasText: `Remap ${missingId}` })
				.locator('select');
			await remapSelect.selectOption(datasourceId);
		}
	}
	await page.getByRole('button', { name: /Next/i }).click();
	await expect(page.getByRole('heading', { name: /Review Import/i })).toBeVisible();
	await page.getByRole('button', { name: /Create Analysis/i }).click();
	await expect(page).toHaveURL(
		(url) => url.pathname.startsWith('/analysis/') && url.pathname !== '/analysis/new',
		{ timeout: 30_000 }
	);
	const match = page.url().match(/\/analysis\/([^/?#]+)/);
	if (!match || match[1] === 'new') {
		throw new Error(`Could not extract imported analysis id from URL: ${page.url()}`);
	}
	return match[1];
}

export async function createUdfViaUi(page: Page, name: string): Promise<string> {
	await page.goto('/udfs/new');
	await waitForLayoutReady(page);
	await page.locator('#udf-name').fill(name);
	await page.locator('#udf-description').fill(`Test UDF: ${name}`);
	await page.locator('#udf-tags').fill('test');
	const [response] = await Promise.all([
		page.waitForResponse(
			(resp) => resp.url().includes('/api/v1/udf') && resp.request().method() === 'POST'
		),
		page.getByTestId('udf-save-button').click()
	]);
	const payload = (await response.json()) as { id: string };
	await expect(page).toHaveURL(new RegExp(`/udfs/${payload.id}$`), { timeout: 15_000 });
	return payload.id;
}

export async function createScheduleViaUi(
	page: Page,
	datasourceId: string,
	cron = '0 9 * * *'
): Promise<string> {
	await page.goto('/monitoring?tab=schedules');
	await waitForLayoutReady(page);
	await page.getByRole('button', { name: /New Schedule/i }).click();
	const select = page.locator('#schedule-datasource');
	await expect(select).toBeVisible({ timeout: 5_000 });
	await select.selectOption(datasourceId);
	if (cron !== '0 * * * *') {
		const cronInput = page.locator('input[name="cron"]');
		if (await cronInput.isVisible().catch(() => false)) {
			await cronInput.fill(cron);
		}
	}
	const [response] = await Promise.all([
		page.waitForResponse(
			(resp) => resp.url().includes('/api/v1/schedules') && resp.request().method() === 'POST'
		),
		page.getByRole('button', { name: 'Create Schedule' }).click()
	]);
	const payload = (await response.json()) as { id: string };
	return payload.id;
}

export async function createHealthCheckViaUi(
	page: Page,
	datasourceId: string,
	name: string
): Promise<string> {
	await page.goto('/monitoring?tab=health');
	await waitForLayoutReady(page);
	await page.getByRole('button', { name: /New Check/i }).click();
	const select = page.locator('#hc-target');
	await expect(select).toBeVisible({ timeout: 5_000 });
	await select.selectOption(datasourceId);
	await page.locator('#hc-name').fill(name);
	await page.locator('#hc-min-rows').fill('1');
	const [response] = await Promise.all([
		page.waitForResponse(
			(resp) => resp.url().includes('/api/v1/healthchecks') && resp.request().method() === 'POST'
		),
		page.getByRole('button', { name: 'Save Check' }).click()
	]);
	const payload = (await response.json()) as { id: string };
	return payload.id;
}

export async function waitForUdfVisible(page: Page, name: string): Promise<void> {
	await page.goto('/udfs');
	await waitForUdfList(page);
	await expect(page.locator(`[data-udf-card="${name}"]`)).toBeVisible({ timeout: 10_000 });
}
