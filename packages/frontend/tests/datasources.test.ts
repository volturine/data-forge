import { test, expect } from './fixtures.js';
import { createDatasource, createLargeDatasource } from './utils/api.js';
import { deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { uid } from './utils/uid.js';
import { screenshot } from './utils/visual.js';
import {
	selectDatasourceAndWaitForConfig,
	openSchemaTabAndWait,
	waitForDatasourceList,
	waitForLayoutReady
} from './utils/readiness.js';
import { dialogByHeading } from './utils/locators.js';

/**
 * E2E tests for datasources – mirrors test_datasource.py / test_datasource_extended.py.
 */
test.describe('Datasources – list & management', () => {
	test('list shows datasource description preview', async ({ page, request }) => {
		const ds = `e2e-description-list-${uid()}`;
		const description = 'Primary customer dataset for retention analysis and reporting.';
		await createDatasource(request, ds, undefined, description);
		try {
			await page.goto('/datasources');
			const row = page.locator(`[data-ds-row="${ds}"]`);
			await expect(row).toBeVisible();
			await expect(row.getByText(description)).toBeVisible();
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('lists datasource after API create', async ({ page, request }) => {
		const ds = `e2e-visible-${uid()}`;
		await createDatasource(request, ds);
		try {
			await page.goto('/datasources');
			await expect(page.locator(`[data-ds-row="${ds}"]`)).toBeVisible();
			await screenshot(page, 'datasources', 'list-with-datasource');
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('shows Import and Analysis badges', async ({ page, request }) => {
		const ds = `e2e-badge-${uid()}`;
		await createDatasource(request, ds);
		try {
			await page.goto('/datasources');
			const row = page.locator(`[data-ds-row="${ds}"]`);
			await expect(row).toBeVisible();
			// uploaded files have "Import" badge
			await expect(row.getByText('Import', { exact: true })).toBeVisible();
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('search input filters datasource list', async ({ page, request }) => {
		const ds = `e2e-search-${uid()}`;
		await createDatasource(request, ds);
		try {
			await page.goto('/datasources');
			const row = page.locator(`[data-ds-row="${ds}"]`);
			await expect(row).toBeVisible();

			await page.getByPlaceholder(/Search datasources/i).fill('ZZZNOMATCH');
			await expect(row).not.toBeVisible();
			await expect(page.getByText(/No datasources match/i)).toBeVisible();
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('clicking a datasource clears the "No datasource selected" placeholder', async ({
		page,
		request
	}) => {
		const ds = `e2e-select-${uid()}`;
		await createDatasource(request, ds);
		try {
			await page.goto('/datasources');
			await expect(page.getByText(/No datasource selected/i)).toBeVisible();

			await page.locator(`[data-ds-row="${ds}"]`).click();
			await expect(page.getByText(/No datasource selected/i)).not.toBeVisible();
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('multiple datasources are all listed', async ({ page, request }) => {
		test.setTimeout(60_000);
		const id = uid();
		const dsA = `e2e-multi-a-${id}`;
		const dsB = `e2e-multi-b-${id}`;
		await createDatasource(request, dsA);
		await createDatasource(request, dsB);
		try {
			await page.goto('/datasources');
			await expect(page.locator(`[data-ds-row="${dsA}"]`)).toBeVisible();
			await expect(page.locator(`[data-ds-row="${dsB}"]`)).toBeVisible();
		} finally {
			await deleteDatasourceViaUI(page, dsA);
			await deleteDatasourceViaUI(page, dsB);
		}
	});

	test('delete button removes datasource from list', async ({ page, request }) => {
		const ds = `e2e-delete-${uid()}`;
		await createDatasource(request, ds);
		await page.goto('/datasources');
		await expect(page.locator(`[data-ds-row="${ds}"]`)).toBeVisible();

		// The delete button has title="Delete" inside the datasource row container
		const row = page.locator(`[data-ds-row="${ds}"]`);
		const deleteBtn = row.locator('button[title="Delete"]');
		await deleteBtn.click();

		// Confirm in the dialog
		const dialog = dialogByHeading(page, /Delete Datasource/i);
		await expect(dialog).toBeVisible();
		await dialog.getByRole('button', { name: /^Delete$/ }).click();

		await expect(row).not.toBeVisible({ timeout: 8_000 });
	});

	test('Show/Hide hidden datasources toggle is visible', async ({ page }) => {
		await page.goto('/datasources');
		// EyeOff/Eye button to toggle hidden datasources
		await expect(page.locator('button[title*="datasources"]')).toBeVisible();
	});
});

test.describe('Datasources – upload page', () => {
	test('upload page shows description fields for file and database flows', async ({ page }) => {
		await page.goto('/datasources/new');
		await waitForLayoutReady(page);
		await page.locator('#file-input').setInputFiles({
			name: 'upload-description.csv',
			mimeType: 'text/csv',
			buffer: Buffer.from('id,name\n1,Alice\n')
		});
		await expect(page.locator('#file-description')).toBeVisible();
		await page.getByRole('button', { name: 'External DB' }).click();
		await expect(page.locator('#db-description')).toBeVisible();
	});

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
		const dsName = `e2e-upload-${Date.now()}`;
		await page.goto('/datasources/new');

		const fileInput = page.locator('#file-input');
		await fileInput.setInputFiles({
			name: `${dsName}.csv`,
			mimeType: 'text/csv',
			buffer: Buffer.from('id,name,age,city\n1,Alice,30,London\n2,Bob,25,Paris\n')
		});

		const uploadBtn = page.getByRole('button', { name: 'Upload', exact: true });
		await expect(uploadBtn).toBeEnabled({ timeout: 10_000 });
		await uploadBtn.click();

		// Wait for navigation away from /new, then verify the datasource exists in the list
		await expect(page).toHaveURL((url) => !url.pathname.endsWith('/new'), { timeout: 30_000 });
		await page.goto('/datasources');
		await expect(page.locator(`[data-ds-row="${dsName}"]`)).toBeVisible({ timeout: 15_000 });

		await deleteDatasourceViaUI(page, dsName);
	});
});

test.describe('Datasources – detail view', () => {
	let ds: string;

	test.beforeEach(async ({ request }) => {
		ds = `e2e-detail-view-${uid()}`;
		await createDatasource(request, ds);
	});

	test.afterEach(async ({ page }) => {
		await deleteDatasourceViaUI(page, ds);
	});

	test('selecting datasource shows General tab with source information', async ({ page }) => {
		await page.goto('/datasources');
		await page.locator(`[data-ds-row="${ds}"]`).click();

		const config = page.locator('[data-ds-config]');
		await expect(config).toBeVisible({ timeout: 8_000 });

		const generalTab = config.getByRole('tab', { name: 'General' });
		await expect(generalTab).toHaveAttribute('aria-selected', 'true');

		await expect(config.getByText('Source Information')).toBeVisible();
		await expect(config.getByText('Imported')).toBeVisible();
		await expect(config.getByText('Datasource ID')).toBeVisible();

		await screenshot(page, 'datasources', 'detail-config-panel');
	});

	test('general tab allows editing and clearing the datasource description', async ({ page }) => {
		await page.goto('/datasources');
		await selectDatasourceAndWaitForConfig(page, ds);

		const config = page.locator('[data-ds-config]');
		const descriptionField = config.locator('textarea[id^="datasource-description-"]');
		await expect(config.getByText('No description added yet.')).toBeVisible();

		await descriptionField.fill('Initial dataset guidance for weekly commercial reporting.');
		await config.getByRole('button', { name: /Save Changes/i }).click();
		await expect(config.getByText('Changes saved successfully!')).toBeVisible();
		await expect(descriptionField).toHaveValue(
			'Initial dataset guidance for weekly commercial reporting.'
		);

		await descriptionField.fill('');
		await config.getByRole('button', { name: /Save Changes/i }).click();
		await expect(config.getByText('Changes saved successfully!')).toBeVisible();
		await expect(config.getByText('No description added yet.')).toBeVisible();
	});

	test('Schema tab shows actual column names from CSV', async ({ page }) => {
		await page.goto('/datasources');
		await selectDatasourceAndWaitForConfig(page, ds);
		await openSchemaTabAndWait(page);

		const config = page.locator('[data-ds-config]');
		await expect(config.locator('[data-schema-column="id"]')).toBeVisible({ timeout: 10_000 });
		await expect(config.locator('[data-schema-column="name"]')).toBeVisible();
		await expect(config.locator('[data-schema-column="age"]')).toBeVisible();
		await expect(config.locator('[data-schema-column="city"]')).toBeVisible();
	});

	test('Schema tab allows editing and viewing column descriptions', async ({ page }) => {
		await page.goto('/datasources');
		await selectDatasourceAndWaitForConfig(page, ds);
		await openSchemaTabAndWait(page);

		const config = page.locator('[data-ds-config]');
		const editButton = config.getByRole('button', { name: 'Edit description for city' });
		await editButton.click();
		await config.locator('textarea').fill('Primary city label used for regional rollups');
		await config.getByRole('button', { name: 'Save' }).click();
		await expect(editButton).toBeVisible({ timeout: 10_000 });

		await expect(config.locator('[data-schema-description="city"]')).toContainText(
			'Primary city label used for regional rollups'
		);

		await config.locator('[data-schema-column="city"]').click();
		const panel = page.getByTestId('column-stats-panel');
		await expect(panel).toContainText('Description');
		await expect(panel).toContainText('Primary city label used for regional rollups');
	});

	test('General tab shows row count from actual data', async ({ page }) => {
		await page.goto('/datasources');
		await page.locator(`[data-ds-row="${ds}"]`).click();

		const config = page.locator('[data-ds-config]');
		await expect(config).toBeVisible({ timeout: 8_000 });

		await expect(config.getByText('Rows')).toBeVisible({ timeout: 10_000 });
		await expect(page.getByTestId('datasource-row-count')).toHaveText('3', { timeout: 5_000 });
	});

	test('datasource URL includes id query param after selection', async ({ page }) => {
		await page.goto('/datasources');
		await page.locator(`[data-ds-row="${ds}"]`).click();
		await expect(page).toHaveURL(/id=/, { timeout: 5_000 });
	});

	test('right pane shows preview table with column headers and data', async ({ page }) => {
		test.setTimeout(45_000);
		await page.goto('/datasources');
		await page.locator(`[data-ds-row="${ds}"]`).click();

		// Preview loads in the right pane (DatasourcePreview), not in a config tab
		await expect(page.locator('[data-preview-ready="true"]')).toBeVisible({ timeout: 30_000 });

		// Verify actual column headers from the CSV are rendered
		await expect(page.locator('[data-column-id="id"]')).toBeVisible({ timeout: 5_000 });
		await expect(page.locator('[data-column-id="name"]')).toBeVisible();
		await expect(page.locator('[data-column-id="age"]')).toBeVisible();
		await expect(page.locator('[data-column-id="city"]')).toBeVisible();

		// Verify actual data values from the CSV
		const preview = page.locator('[data-preview-ready="true"]');
		await expect(preview.getByText('Alice', { exact: true })).toBeVisible();
		await expect(preview.getByText('London', { exact: true })).toBeVisible();
		await expect(preview.getByText('Berlin', { exact: true })).toBeVisible();
	});
});

test.describe('Datasources – preview pagination', () => {
	test.setTimeout(60_000);

	test('pagination navigates between pages', async ({ page, request }) => {
		const ds = `e2e-pagination-${uid()}`;
		await createLargeDatasource(request, ds, 150);
		try {
			await page.goto('/datasources');
			await waitForDatasourceList(page);
			await page.locator(`[data-ds-row="${ds}"]`).click();
			await expect(page.locator('[data-preview-ready="true"]')).toBeVisible({ timeout: 30_000 });

			const pageLabel = page.locator('[data-testid="pagination-page"]');
			await expect(pageLabel).toHaveText('Page 1');

			const nextBtn = page.locator('[data-testid="pagination-next"]');
			const prevBtn = page.locator('[data-testid="pagination-prev"]');

			// Prev should be disabled on page 1
			await expect(prevBtn).toBeDisabled();
			// Next should be enabled (150 rows > 100 row limit)
			await expect(nextBtn).toBeEnabled();

			await nextBtn.click();
			await expect(page.locator('[data-preview-ready="true"]')).toBeVisible({ timeout: 30_000 });
			await expect(pageLabel).toHaveText('Page 2');
			await expect(prevBtn).toBeEnabled();

			await screenshot(page, 'datasources', 'preview-pagination-page2');

			await prevBtn.click();
			await expect(page.locator('[data-preview-ready="true"]')).toBeVisible({ timeout: 30_000 });
			await expect(pageLabel).toHaveText('Page 1');
			await expect(prevBtn).toBeDisabled();
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});
});

test.describe('Datasources – column stats panel', () => {
	test.setTimeout(60_000);

	test('column stats panel opens, shows content, and closes', async ({ page, request }) => {
		const ds = `e2e-stats-${uid()}`;
		await createDatasource(request, ds);
		try {
			await page.goto('/datasources');
			await page.locator(`[data-ds-row="${ds}"]`).click();
			await expect(page.locator('[data-preview-ready="true"]')).toBeVisible({ timeout: 30_000 });

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
			await deleteDatasourceViaUI(page, ds);
		}
	});
});

test.describe('Datasources – config tab interactions', () => {
	test.setTimeout(45_000);

	test('Runs tab shows empty state for fresh datasource', async ({ page, request }) => {
		const ds = `e2e-runs-tab-${uid()}`;
		await createDatasource(request, ds);
		try {
			await page.goto('/datasources');
			await page.locator(`[data-ds-row="${ds}"]`).click();

			const config = page.locator('[data-ds-config]');
			await expect(config).toBeVisible({ timeout: 8_000 });

			await config.getByRole('tab', { name: 'Runs' }).click();
			await expect(config.getByText('No runs associated with this datasource.')).toBeVisible({
				timeout: 15_000
			});

			await screenshot(page, 'datasources', 'runs-tab-empty-state');
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('rename datasource shows Save button and persists', async ({ page, request }) => {
		const id = uid();
		const ds = `e2e-rename-${id}`;
		const renamed = `e2e-renamed-${id}`;
		await createDatasource(request, ds);
		try {
			await page.goto('/datasources');
			await page.locator(`[data-ds-row="${ds}"]`).click();

			const config = page.locator('[data-ds-config]');
			await expect(config).toBeVisible({ timeout: 8_000 });

			const nameInput = config.locator('[id^="datasource-name-"]');
			await nameInput.fill(renamed);

			await expect(config.getByRole('button', { name: 'Save Changes' })).toBeVisible({
				timeout: 5_000
			});

			// Wait for save API call to complete before reloading
			const [saveResponse] = await Promise.all([
				page.waitForResponse(
					(resp) => resp.url().includes('/api/v1/datasource/') && resp.request().method() === 'PUT'
				),
				config.getByRole('button', { name: 'Save Changes' }).click()
			]);
			expect(saveResponse.ok()).toBeTruthy();

			// After save, reload page and verify renamed datasource appears
			await page.reload();
			await expect(page.locator(`[data-ds-row="${renamed}"]`)).toBeVisible({ timeout: 10_000 });
		} finally {
			await deleteDatasourceViaUI(page, renamed);
		}
	});
});
