import { test, expect } from '@playwright/test';
import { createDatasource, createLargeDatasource } from './utils/api.js';
import { deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { screenshot } from './utils/visual.js';

/**
 * E2E tests for datasources – mirrors test_datasource.py / test_datasource_extended.py.
 */
test.describe('Datasources – list & management', () => {
	test('shows empty state when no datasources exist', async ({ page }) => {
		await page.route('**/api/v1/datasource', (route) => {
			if (route.request().method() === 'GET') {
				return route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify([])
				});
			}
			return route.continue();
		});

		await page.goto('/datasources');
		await expect(page.getByText(/No data sources yet/i)).toBeVisible();
	});

	test('lists datasource after API create', async ({ page, request }) => {
		await createDatasource(request, 'e2e-visible-ds');
		try {
			await page.goto('/datasources');
			await expect(page.getByText('e2e-visible-ds')).toBeVisible();
			await screenshot(page, 'datasources', 'list-with-datasource');
		} finally {
			await deleteDatasourceViaUI(page, 'e2e-visible-ds');
		}
	});

	test('shows Import and Analysis badges', async ({ page, request }) => {
		await createDatasource(request, 'e2e-badge-ds');
		try {
			await page.goto('/datasources');
			await expect(page.getByText('e2e-badge-ds').first()).toBeVisible();
			// uploaded files have "Import" badge
			await expect(page.getByText('Import').first()).toBeVisible();
		} finally {
			await deleteDatasourceViaUI(page, 'e2e-badge-ds');
		}
	});

	test('search input filters datasource list', async ({ page, request }) => {
		await createDatasource(request, 'e2e-search-alpha-ds');
		try {
			await page.goto('/datasources');
			await expect(page.getByText('e2e-search-alpha-ds')).toBeVisible();

			await page.getByPlaceholder(/Search datasources/i).fill('ZZZNOMATCH');
			await expect(page.getByText('e2e-search-alpha-ds')).not.toBeVisible();
			await expect(page.getByText(/No datasources match/i)).toBeVisible();
		} finally {
			await deleteDatasourceViaUI(page, 'e2e-search-alpha-ds');
		}
	});

	test('clicking a datasource clears the "No datasource selected" placeholder', async ({
		page,
		request
	}) => {
		await createDatasource(request, 'e2e-select-ds');
		try {
			await page.goto('/datasources');
			await expect(page.getByText(/No datasource selected/i)).toBeVisible();

			await page.getByText('e2e-select-ds').click();
			await expect(page.getByText(/No datasource selected/i)).not.toBeVisible();
		} finally {
			await deleteDatasourceViaUI(page, 'e2e-select-ds');
		}
	});

	test('multiple datasources are all listed', async ({ page, request }) => {
		await createDatasource(request, 'e2e-multi-ds-a');
		await createDatasource(request, 'e2e-multi-ds-b');
		try {
			await page.goto('/datasources');
			await expect(page.getByText('e2e-multi-ds-a')).toBeVisible();
			await expect(page.getByText('e2e-multi-ds-b')).toBeVisible();
		} finally {
			await deleteDatasourceViaUI(page, 'e2e-multi-ds-a');
			await deleteDatasourceViaUI(page, 'e2e-multi-ds-b');
		}
	});

	test('delete button removes datasource from list', async ({ page, request }) => {
		await createDatasource(request, 'e2e-delete-ds');
		await page.goto('/datasources');
		await expect(page.getByText('e2e-delete-ds').first()).toBeVisible();

		// The delete button has title="Delete" inside the datasource row container
		const row = page.locator('[data-ds-row="e2e-delete-ds"]');
		const deleteBtn = row.locator('button[title="Delete"]');
		await deleteBtn.click();

		// Confirm in the dialog
		const dialog = page.getByRole('dialog');
		await expect(dialog.getByRole('heading', { name: /Delete Datasource/i })).toBeVisible();
		await dialog.getByRole('button', { name: /^Delete$/ }).click();

		await expect(page.getByText('e2e-delete-ds')).not.toBeVisible({ timeout: 8_000 });
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
		await screenshot(page, 'datasources', 'upload-page');
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

	test('CSV upload creates datasource', async ({ page }) => {
		test.setTimeout(60_000);
		await page.goto('/datasources/new');
		await page.waitForLoadState('networkidle');

		// Use setInputFiles directly on the file input
		const fileInput = page.locator('#file-input');
		await fileInput.setInputFiles({
			name: 'e2e-upload.csv',
			mimeType: 'text/csv',
			buffer: Buffer.from('id,name,age,city\n1,Alice,30,London\n2,Bob,25,Paris\n')
		});

		// After file selection, the Upload button should become enabled (exact match avoids 'File Upload' tab)
		const uploadBtn = page.getByRole('button', { name: 'Upload', exact: true });
		await expect(uploadBtn).toBeEnabled({ timeout: 10_000 });
		await uploadBtn.click();

		// Should navigate away from /datasources/new on success
		await page.waitForURL((url) => !url.pathname.endsWith('/new'), { timeout: 30_000 });

		// Cleanup via UI
		await deleteDatasourceViaUI(page, 'e2e-upload');
	});
});

test.describe('Datasources – detail view', () => {
	test.beforeEach(async ({ request }) => {
		await createDatasource(request, 'e2e-detail-view-ds');
	});

	test.afterEach(async ({ page }) => {
		await deleteDatasourceViaUI(page, 'e2e-detail-view-ds');
	});

	test('selecting datasource shows General tab with source information', async ({ page }) => {
		await page.goto('/datasources');
		await page.getByText('e2e-detail-view-ds').click();

		const config = page.locator('[data-ds-config]');
		await expect(config).toBeVisible({ timeout: 8_000 });

		const generalTab = config.getByRole('tab', { name: 'General' });
		await expect(generalTab).toHaveAttribute('aria-selected', 'true');

		await expect(config.getByText('Source Information')).toBeVisible();
		await expect(config.getByText('Imported')).toBeVisible();
		await expect(config.getByText('Datasource ID')).toBeVisible();

		await screenshot(page, 'datasources', 'detail-config-panel');
	});

	test('Schema tab shows actual column names from CSV', async ({ page }) => {
		await page.goto('/datasources');
		await page.getByText('e2e-detail-view-ds').click();

		const config = page.locator('[data-ds-config]');
		await expect(config).toBeVisible({ timeout: 8_000 });

		await config.getByRole('tab', { name: 'Schema' }).click();

		await expect(config.locator('[data-schema-column="id"]')).toBeVisible({ timeout: 10_000 });
		await expect(config.locator('[data-schema-column="name"]')).toBeVisible();
		await expect(config.locator('[data-schema-column="age"]')).toBeVisible();
		await expect(config.locator('[data-schema-column="city"]')).toBeVisible();
	});

	test('General tab shows row count from actual data', async ({ page }) => {
		await page.goto('/datasources');
		await page.getByText('e2e-detail-view-ds').click();

		const config = page.locator('[data-ds-config]');
		await expect(config).toBeVisible({ timeout: 8_000 });

		await expect(config.getByText('Rows')).toBeVisible({ timeout: 10_000 });
		await expect(config.getByText('3', { exact: true })).toBeVisible({ timeout: 5_000 });
	});

	test('datasource URL includes id query param after selection', async ({ page }) => {
		await page.goto('/datasources');
		await page.getByText('e2e-detail-view-ds').click();
		await expect(page).toHaveURL(/id=/, { timeout: 5_000 });
	});

	test('right pane shows preview table with column headers and data', async ({ page }) => {
		test.setTimeout(45_000);
		await page.goto('/datasources');
		await page.getByText('e2e-detail-view-ds').click();

		// Preview loads in the right pane (DatasourcePreview), not in a config tab
		await expect(page.locator('[data-preview-ready="true"]')).toBeVisible({ timeout: 15_000 });

		// Verify actual column headers from the CSV are rendered
		await expect(page.locator('[data-column-id="id"]')).toBeVisible({ timeout: 5_000 });
		await expect(page.locator('[data-column-id="name"]')).toBeVisible();
		await expect(page.locator('[data-column-id="age"]')).toBeVisible();
		await expect(page.locator('[data-column-id="city"]')).toBeVisible();

		// Verify actual data values from the CSV
		await expect(page.getByText('Alice', { exact: true }).first()).toBeVisible();
		await expect(page.getByText('London', { exact: true }).first()).toBeVisible();
		await expect(page.getByText('Berlin', { exact: true }).first()).toBeVisible();
	});
});

test.describe('Datasources – preview pagination', () => {
	test.setTimeout(60_000);

	test('pagination navigates between pages', async ({ page, request }) => {
		const dsId = await createLargeDatasource(request, 'e2e-pagination-ds', 150);
		try {
			await page.goto(`/datasources?id=${dsId}`);
			await expect(page.locator('[data-preview-ready="true"]')).toBeVisible({ timeout: 15_000 });

			const pageLabel = page.locator('[data-testid="pagination-page"]');
			await expect(pageLabel).toHaveText('Page 1');

			const nextBtn = page.locator('[data-testid="pagination-next"]');
			const prevBtn = page.locator('[data-testid="pagination-prev"]');

			// Prev should be disabled on page 1
			await expect(prevBtn).toBeDisabled();
			// Next should be enabled (150 rows > 100 row limit)
			await expect(nextBtn).toBeEnabled();

			await nextBtn.click();
			await expect(page.locator('[data-preview-ready="true"]')).toBeVisible({ timeout: 15_000 });
			await expect(pageLabel).toHaveText('Page 2');
			await expect(prevBtn).toBeEnabled();

			await screenshot(page, 'datasources', 'preview-pagination-page2');

			await prevBtn.click();
			await expect(page.locator('[data-preview-ready="true"]')).toBeVisible({ timeout: 15_000 });
			await expect(pageLabel).toHaveText('Page 1');
			await expect(prevBtn).toBeDisabled();
		} finally {
			await deleteDatasourceViaUI(page, 'e2e-pagination-ds');
		}
	});
});

test.describe('Datasources – column stats panel', () => {
	test.setTimeout(60_000);

	test('column stats panel opens, shows content, and closes', async ({ page, request }) => {
		await createDatasource(request, 'e2e-stats-ds');
		try {
			await page.goto('/datasources');
			await page.getByText('e2e-stats-ds').click();
			await expect(page.locator('[data-preview-ready="true"]')).toBeVisible({ timeout: 15_000 });

			// Open column menu for "age" column
			const ageHeader = page.locator('[data-column-id="age"]');
			await ageHeader.locator('button[aria-label="Column options"]').click();
			await page.getByText('Column stats').click();

			// Column stats panel should appear
			const panel = page.locator('[data-testid="column-stats-panel"]');
			await expect(panel).toBeVisible({ timeout: 10_000 });

			// Panel should show "Column Stats" heading and the column name
			await expect(panel.getByText('Column Stats')).toBeVisible();
			await expect(panel.getByText('age')).toBeVisible();

			// Panel should show stats content (Overview section with Rows)
			await expect(panel.getByText('Overview')).toBeVisible({ timeout: 10_000 });
			await expect(panel.getByText('Rows')).toBeVisible();

			await screenshot(page, 'datasources', 'column-stats-panel-open');

			// Close the panel
			await page.locator('[data-testid="column-stats-close"]').click();
			await expect(panel).not.toBeVisible();
		} finally {
			await deleteDatasourceViaUI(page, 'e2e-stats-ds');
		}
	});
});

test.describe('Datasources – preview error state', () => {
	test.setTimeout(45_000);

	test('shows error UI when preview API fails', async ({ page, request }) => {
		await createDatasource(request, 'e2e-error-ds');
		try {
			// Intercept the compute preview API to return a 500 error
			await page.route('**/api/v1/compute/preview', (route) =>
				route.fulfill({
					status: 500,
					contentType: 'application/json',
					body: JSON.stringify({ detail: 'Simulated preview failure' })
				})
			);

			await page.goto('/datasources');
			await page.getByText('e2e-error-ds').click();

			// The error state should be visible
			const errorEl = page.locator('[data-testid="preview-error"]');
			await expect(errorEl).toBeVisible({ timeout: 15_000 });
			await expect(errorEl.getByText('Failed')).toBeVisible();

			await screenshot(page, 'datasources', 'preview-error-state');
		} finally {
			await page.unrouteAll({ behavior: 'ignoreErrors' });
			await deleteDatasourceViaUI(page, 'e2e-error-ds');
		}
	});
});

test.describe('Datasources – config tab interactions', () => {
	test.setTimeout(45_000);

	test('Runs tab shows datasource_create run for fresh datasource', async ({ page, request }) => {
		await createDatasource(request, 'e2e-runs-tab-ds');
		try {
			await page.goto('/datasources');
			await page.getByText('e2e-runs-tab-ds').click();

			const config = page.locator('[data-ds-config]');
			await expect(config).toBeVisible({ timeout: 8_000 });

			await config.getByRole('tab', { name: 'Runs' }).click();
			// Creating a datasource via API upload triggers a datasource_create engine run
			await expect(config.getByText('Create', { exact: true })).toBeVisible({ timeout: 10_000 });

			await screenshot(page, 'datasources', 'runs-tab-with-create-run');
		} finally {
			await deleteDatasourceViaUI(page, 'e2e-runs-tab-ds');
		}
	});

	test('rename datasource shows Save button and persists', async ({ page, request }) => {
		await createDatasource(request, 'e2e-rename-ds');
		try {
			await page.goto('/datasources');
			await page.getByText('e2e-rename-ds').click();

			const config = page.locator('[data-ds-config]');
			await expect(config).toBeVisible({ timeout: 8_000 });

			const nameInput = config.locator('input[type="text"]').first();
			await nameInput.fill('e2e-renamed-ds');

			await expect(config.getByRole('button', { name: 'Save Changes' })).toBeVisible({
				timeout: 5_000
			});
			await config.getByRole('button', { name: 'Save Changes' }).click();

			// After save, reload page and verify renamed datasource appears
			await page.reload();
			await expect(page.getByText('e2e-renamed-ds')).toBeVisible({ timeout: 10_000 });
		} finally {
			await deleteDatasourceViaUI(page, 'e2e-renamed-ds');
		}
	});
});
