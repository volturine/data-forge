import { expect, type Page } from '@playwright/test';
import { waitForCurrentAnalysisEditor } from './analysis.js';
import {
	gotoAuthedRoute,
	gotoMonitoringTab,
	gotoNewAnalysis,
	waitForDatasourceList,
	waitForLayoutReady,
	waitForUdfList
} from './readiness.js';

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
		timeout: 5_000
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
	await expect(createButton).toBeEnabled({ timeout: 5_000 });
	await createButton.click();
	// Cookie is set on the register response; hard-load home for a settled session.
	await expect(page.getByText(/Account created\./i)).toBeVisible({ timeout: 15_000 });
	await page.goto('/', { waitUntil: 'networkidle' });
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
	await gotoAuthedRoute(page, '/datasources/new');
	const fileInput = page.locator('#file-input');
	await expect(fileInput).toBeVisible({ timeout: 5_000 });
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
	await expect(uploadBtn).toBeEnabled({ timeout: 5_000 });
	// Wait for any finished upload response (not only 200). No short timeout:
	// upload runs through the compute runtime and can exceed 15s under parallel
	// CI load; the Playwright test timeout bounds the wait. Non-OK statuses
	// fail immediately with the response body.
	const uploadResponsePromise = page.waitForResponse(
		(response) =>
			response.url().includes('/api/v1/datasource/upload') &&
			!response.url().includes('/bulk') &&
			response.request().method() === 'POST' &&
			response.status() !== 0
	);
	await uploadBtn.click();
	const uploadResponse = await uploadResponsePromise;
	if (!uploadResponse.ok()) {
		const body = await uploadResponse.text().catch(() => '');
		throw new Error(
			`Datasource upload failed for ${name}: HTTP ${uploadResponse.status()} ${body.slice(0, 300)}`
		);
	}
	await expect(
		page,
		`Upload did not redirect to the created datasource list for ${name}`
	).toHaveURL((url) => url.pathname === '/datasources' && url.searchParams.has('id'), {
		timeout: 15_000
	});
	const currentUrl = new URL(page.url());
	const datasourceId = currentUrl.searchParams.get('id');
	if (!datasourceId) {
		throw new Error(`Could not extract browser-visible datasource id after upload for ${name}`);
	}
	await waitForDatasourceList(page, 5_000);
	const row = page.locator(`[data-ds-row="${name}"]`);
	await expect(row).toBeVisible({ timeout: 5_000 });
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
	return waitForCurrentAnalysisEditor(page);
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
	return waitForCurrentAnalysisEditor(page);
}

export async function createUdfViaUi(page: Page, name: string): Promise<string> {
	await gotoAuthedRoute(page, '/udfs/new');
	await page.locator('#udf-name').fill(name);
	await page.locator('#udf-description').fill(`Test UDF: ${name}`);
	await page.locator('#udf-tags').fill('test');
	const [response] = await Promise.all([
		page.waitForResponse(
			(resp) =>
				resp.url().includes('/api/v1/udf') &&
				resp.request().method() === 'POST' &&
				resp.status() !== 0
		),
		page.getByTestId('udf-save-button').click()
	]);
	if (!response.ok()) {
		throw new Error(`UDF create failed: HTTP ${response.status()}`);
	}
	const payload = (await response.json()) as { id: string };
	await expect(page).toHaveURL(new RegExp(`/udfs/${payload.id}$`), { timeout: 5_000 });
	return payload.id;
}

export async function createScheduleViaUi(
	page: Page,
	datasourceId: string,
	cron = '0 9 * * *'
): Promise<string> {
	await gotoMonitoringTab(page, 'schedules');
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
			(resp) =>
				resp.url().includes('/api/v1/schedules') &&
				resp.request().method() === 'POST' &&
				resp.status() !== 0
		),
		page.getByRole('button', { name: 'Create Schedule' }).click()
	]);
	if (!response.ok()) {
		throw new Error(`Schedule create failed: HTTP ${response.status()}`);
	}
	const payload = (await response.json()) as { id: string };
	return payload.id;
}

export async function createHealthCheckViaUi(
	page: Page,
	datasourceId: string,
	name: string
): Promise<string> {
	await gotoMonitoringTab(page, 'health');
	await page.getByRole('button', { name: /New Check/i }).click();
	const select = page.locator('#hc-target');
	await expect(select).toBeVisible({ timeout: 5_000 });
	await select.selectOption(datasourceId);
	await page.locator('#hc-name').fill(name);
	await page.locator('#hc-min-rows').fill('1');
	const [response] = await Promise.all([
		page.waitForResponse(
			(resp) =>
				resp.url().includes('/api/v1/healthchecks') &&
				resp.request().method() === 'POST' &&
				resp.status() !== 0
		),
		page.getByRole('button', { name: 'Save Check' }).click()
	]);
	if (!response.ok()) {
		throw new Error(`Health check create failed: HTTP ${response.status()}`);
	}
	const payload = (await response.json()) as { id: string };
	return payload.id;
}

export async function waitForUdfVisible(page: Page, name: string): Promise<void> {
	await page.goto('/udfs');
	await waitForUdfList(page);
	await expect(page.locator(`[data-udf-card="${name}"]`)).toBeVisible({ timeout: 5_000 });
}

export async function shutdownEngineViaUi(
	page: Page,
	analysisId: string,
	options?: { timeoutMs?: number }
): Promise<void> {
	const timeoutMs = options?.timeoutMs ?? 5_000;
	await page.goto('/', { waitUntil: 'domcontentloaded' });
	await waitForLayoutReady(page, timeoutMs);

	const engineButton = page.getByRole('button', { name: 'Engine Monitor' });
	await expect(engineButton).toBeVisible({ timeout: timeoutMs });
	await engineButton.click();

	const popup = page.locator('[data-engines-popup="true"]');
	await expect(popup).toBeVisible({ timeout: timeoutMs });

	const identityKey = `analysis_interactive:${analysisId}`;
	const row = popup.locator(`[data-engine-row="${identityKey}"]`);
	const shutdownButton = popup.locator(`[data-engine-shutdown="${identityKey}"]`);
	const started = Date.now();
	while (Date.now() - started < timeoutMs) {
		if (await row.isVisible().catch(() => false)) {
			await expect(shutdownButton).toBeEnabled({ timeout: 1_000 });
			await shutdownButton.click();
			await expect(row).toBeHidden({
				timeout: Math.max(timeoutMs - (Date.now() - started), 1_000)
			});
			await page.keyboard.press('Escape').catch(() => undefined);
			return;
		}
		await page.waitForTimeout(250);
	}

	await page.keyboard.press('Escape').catch(() => undefined);
}
