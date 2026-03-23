import { test, expect } from '@playwright/test';
import { createDatasource, deleteDatasource } from './utils/api.js';

const SAMPLE_CSV = 'id,name,age\n1,Alice,30\n2,Bob,25\n';

/**
 * E2E tests for datasources – mirrors test_datasource.py / test_datasource_extended.py.
 */
test.describe('Datasources – list & management', () => {
	test('shows empty state when no datasources exist', async ({ page, request }) => {
		const resp = await request.get('http://localhost:8000/api/v1/datasource');
		const datasources = (await resp.json()) as unknown[];
		test.skip(datasources.length > 0, 'Datasources already exist – skipping empty-state check');

		await page.goto('/datasources');
		await expect(page.getByText(/No data sources yet/i)).toBeVisible();
	});

	test('lists datasource after API create', async ({ page, request }) => {
		const dsId = await createDatasource(request, 'e2e-visible-ds');
		try {
			await page.goto('/datasources');
			await expect(page.getByText('e2e-visible-ds')).toBeVisible();
		} finally {
			await deleteDatasource(request, dsId);
		}
	});

	test('shows Import and Analysis badges', async ({ page, request }) => {
		const dsId = await createDatasource(request, 'e2e-badge-ds');
		try {
			await page.goto('/datasources');
			// Wait for the datasource list to render before checking badges
			await expect(page.getByText('e2e-badge-ds')).toBeVisible();
			// uploaded files have "Import" badge
			await expect(page.getByText('Import').first()).toBeVisible();
		} finally {
			await deleteDatasource(request, dsId);
		}
	});

	test('search input filters datasource list', async ({ page, request }) => {
		const dsId = await createDatasource(request, 'e2e-search-alpha-ds');
		try {
			await page.goto('/datasources');
			await expect(page.getByText('e2e-search-alpha-ds')).toBeVisible();

			await page.getByPlaceholder(/Search datasources/i).fill('ZZZNOMATCH');
			await expect(page.getByText('e2e-search-alpha-ds')).not.toBeVisible();
			await expect(page.getByText(/No datasources match/i)).toBeVisible();
		} finally {
			await deleteDatasource(request, dsId);
		}
	});

	test('clicking a datasource clears the "No datasource selected" placeholder', async ({
		page,
		request
	}) => {
		const dsId = await createDatasource(request, 'e2e-select-ds');
		try {
			await page.goto('/datasources');
			await expect(page.getByText(/No datasource selected/i)).toBeVisible();

			await page.getByText('e2e-select-ds').click();
			await expect(page.getByText(/No datasource selected/i)).not.toBeVisible();
		} finally {
			await deleteDatasource(request, dsId);
		}
	});

	test('multiple datasources are all listed', async ({ page, request }) => {
		const id1 = await createDatasource(request, 'e2e-multi-ds-a');
		const id2 = await createDatasource(request, 'e2e-multi-ds-b');
		try {
			await page.goto('/datasources');
			await expect(page.getByText('e2e-multi-ds-a')).toBeVisible();
			await expect(page.getByText('e2e-multi-ds-b')).toBeVisible();
		} finally {
			await deleteDatasource(request, id1);
			await deleteDatasource(request, id2);
		}
	});

	test('delete button removes datasource from list', async ({ page, request }) => {
		const dsId = await createDatasource(request, 'e2e-delete-ds');
		try {
			await page.goto('/datasources');
			await expect(page.getByText('e2e-delete-ds')).toBeVisible();

			// The delete button has title="Delete" and is next to the datasource name
			const row = page.locator('button', { hasText: 'e2e-delete-ds' }).locator('..');
			const deleteBtn = row.locator('button[title="Delete"]');
			await deleteBtn.click();

			await expect(page.getByText('e2e-delete-ds')).not.toBeVisible({ timeout: 8_000 });
		} finally {
			await deleteDatasource(request, dsId).catch(() => undefined);
		}
	});

	test('Show/Hide hidden datasources toggle is visible', async ({ page }) => {
		await page.goto('/datasources');
		// EyeOff/Eye button to toggle hidden datasources
		await expect(page.locator('button[title*="datasources"]')).toBeVisible();
	});
});

test.describe('Datasources – upload page', () => {
	test('upload page has "File Upload" and "External DB" tabs', async ({ page }) => {
		await page.goto('/datasources/new');
		await expect(page.getByRole('button', { name: 'File Upload' })).toBeVisible();
		await expect(page.getByRole('button', { name: 'External DB' })).toBeVisible();
	});

	test('upload page shows a file input', async ({ page }) => {
		await page.goto('/datasources/new');
		await expect(page.locator('input[type="file"]')).toBeAttached();
	});

	test('External DB tab shows connection string field', async ({ page }) => {
		await page.goto('/datasources/new');
		await page.getByRole('button', { name: 'External DB' }).click();
		// Connection string input has id="connection-string"
		await expect(page.locator('#connection-string')).toBeVisible({ timeout: 8_000 });
	});

	test('CSV upload creates datasource', async ({ page, request }) => {
		test.setTimeout(60_000);
		await page.goto('/datasources/new');

		// Use setInputFiles directly on the file input
		const fileInput = page.locator('#file-input');
		await fileInput.setInputFiles({
			name: 'e2e-upload.csv',
			mimeType: 'text/csv',
			buffer: Buffer.from(SAMPLE_CSV)
		});

		// After file selection, the Upload button should become enabled (exact match avoids 'File Upload' tab)
		const uploadBtn = page.getByRole('button', { name: 'Upload', exact: true });
		await expect(uploadBtn).toBeEnabled({ timeout: 10_000 });
		await uploadBtn.click();

		// Should navigate away from /datasources/new on success
		await page.waitForURL((url) => !url.pathname.endsWith('/new'), { timeout: 30_000 });

		// Cleanup
		const resp = await request.get('http://localhost:8000/api/v1/datasource');
		const datasources = (await resp.json()) as Array<{ id: string; name: string }>;
		const created = datasources.find((d) => d.name.includes('e2e-upload'));
		if (created) await deleteDatasource(request, created.id);
	});
});

test.describe('Datasources – detail view', () => {
	let dsId = '';

	test.beforeAll(async ({ request }) => {
		dsId = await createDatasource(request, 'e2e-detail-view-ds');
	});

	test.afterAll(async ({ request }) => {
		await deleteDatasource(request, dsId);
	});

	test('selecting datasource shows its config panel', async ({ page }) => {
		await page.goto('/datasources');
		await page.getByText('e2e-detail-view-ds').click();
		// Right pane shows either "Time Travel" (iceberg SnapshotPicker label) or
		// "Time travel is available for Iceberg datasources." (non-iceberg fallback)
		await expect(page.getByText(/Time travel/i).first()).toBeVisible({ timeout: 8_000 });
	});

	test('datasource URL includes id query param after selection', async ({ page }) => {
		await page.goto('/datasources');
		await page.getByText('e2e-detail-view-ds').click();
		await expect(page).toHaveURL(new RegExp(`id=${dsId}`), { timeout: 5_000 });
	});
});
