import { test, expect } from './fixtures.js';
import { createCsvDatasource, createDatasource } from './utils/api.js';
import type { Page } from '@playwright/test';
import { deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { uploadDatasourceViaUi } from './utils/user-flows.js';
import { uid } from './utils/uid.js';
import { screenshot } from './utils/visual.js';
import {
	gotoDatasourcesPage,
	selectDatasourceAndWaitForConfig,
	openSchemaTabAndWait,
	waitForLayoutReady,
	waitForDatasourcePreviewReady,
	readyTimeoutMs
} from './utils/readiness.js';
import { dialogByHeading } from './utils/locators.js';

/**
 * E2E tests for datasources – mirrors test_datasource.py / test_datasource_extended.py.
 */
test.describe('Datasources – list & management', () => {
	const sharedDescription = 'Primary customer dataset for retention analysis and reporting.';

	test('list shows datasource description preview', async ({ page, sharedDatasource }) => {
		await gotoDatasourcesPage(page);
		const row = page.locator(`[data-ds-row="${sharedDatasource.name}"]`);
		await expect(row).toBeVisible();
		await expect(row.getByText(sharedDescription)).toBeVisible();
	});

	test('lists datasource after API create', async ({ page, sharedDatasource }) => {
		await gotoDatasourcesPage(page);
		await expect(page.locator(`[data-ds-row="${sharedDatasource.name}"]`)).toBeVisible();
		await screenshot(page, 'datasources', 'list-with-datasource');
	});

	test('shows Import and Analysis badges', async ({ page, sharedDatasource }) => {
		await gotoDatasourcesPage(page);
		const row = page.locator(`[data-ds-row="${sharedDatasource.name}"]`);
		await expect(row).toBeVisible();
		// uploaded files have "Import" badge
		await expect(row.getByText('Import', { exact: true })).toBeVisible();
	});

	test('search input filters datasource list', async ({ page, sharedDatasource }) => {
		await gotoDatasourcesPage(page);
		const row = page.locator(`[data-ds-row="${sharedDatasource.name}"]`);
		await expect(row).toBeVisible();

		await page.getByPlaceholder(/Search datasources/i).fill('ZZZNOMATCH');
		await expect(row).not.toBeVisible();
		await expect(page.getByText(/No datasources match/i)).toBeVisible();
	});

	test('clicking a datasource clears the "No datasource selected" placeholder', async ({
		page,
		sharedDatasource
	}) => {
		await gotoDatasourcesPage(page);
		await expect(page.getByText(/No datasource selected/i)).toBeVisible();

		await page.locator(`[data-ds-row="${sharedDatasource.name}"]`).click();
		await expect(page.getByText(/No datasource selected/i)).not.toBeVisible();
	});

	test('multiple datasources are all listed', async ({
		page,
		sharedDatasource,
		sharedAuxDatasource
	}) => {
		// The shard already owns two independent immutable datasets. Reuse them
		// here; this test verifies list behavior, not the upload pipeline.
		await gotoDatasourcesPage(page);
		await expect(page.locator(`[data-ds-row="${sharedDatasource.name}"]`)).toBeVisible();
		await expect(page.locator(`[data-ds-row="${sharedAuxDatasource.name}"]`)).toBeVisible();
	});

	test('delete button removes datasource from list', async ({ page }) => {
		const ds = `e2e-delete-${uid()}`;
		const { id } = await uploadDatasourceViaUi(page, ds);
		try {
			await waitForDatasourcePreviewReady(page);

			// The delete button has title="Delete" inside the datasource row container.
			const row = page.locator(`[data-ds-row="${ds}"]`);
			const deleteBtn = row.locator('button[title="Delete"]');
			await deleteBtn.click();

			// Confirm in the dialog
			const dialog = dialogByHeading(page, /Delete Datasource/i);
			await expect(dialog).toBeVisible();
			await dialog.getByRole('button', { name: /^Delete$/ }).click();

			await expect(row).not.toBeVisible({ timeout: 5_000 });
		} finally {
			await deleteDatasourceViaUI(page, ds, { id }).catch(() => undefined);
		}
	});

	test('Show/Hide hidden datasources toggle shows and hides auto-generated datasources', async ({
		page
	}) => {
		await gotoDatasourcesPage(page);

		const showBtn = page.locator('button[title="Show auto-generated datasources"]');
		await expect(showBtn).toBeVisible();

		await showBtn.click();
		await expect(page.locator('button[title="Hide auto-generated datasources"]')).toBeVisible();

		await page.locator('button[title="Hide auto-generated datasources"]').click();
		await expect(page.locator('button[title="Show auto-generated datasources"]')).toBeVisible();
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
		await waitForLayoutReady(page);
		await expect(page.getByRole('button', { name: 'File Upload' })).toBeVisible();
		await expect(page.getByRole('button', { name: 'External DB' })).toBeVisible();
		await screenshot(page, 'datasources', 'upload-page');
	});

	test('upload page shows a file input', async ({ page }) => {
		await page.goto('/datasources/new');
		await waitForLayoutReady(page);
		await expect(page.locator('input[type="file"]')).toBeAttached();
	});

	test('External DB tab shows connection string field', async ({ page }) => {
		await page.goto('/datasources/new');
		await page.getByRole('button', { name: 'External DB' }).click();
		// Connection string input has id="connection-string"
		await expect(page.locator('#connection-string')).toBeVisible({ timeout: 5_000 });
	});

	test('CSV upload creates datasource', async ({ page }) => {
		const dsName = `e2e-upload-${Date.now()}`;
		const { id } = await uploadDatasourceViaUi(page, dsName);
		await expect(page.locator(`[data-ds-id="${id}"]`)).toBeVisible({ timeout: readyTimeoutMs() });
		await deleteDatasourceViaUI(page, dsName, { id });
	});
});

test.describe('Datasources – detail view', () => {
	test('selecting datasource shows General tab with source information', async ({
		page,
		sharedDatasource
	}) => {
		await gotoDatasourcesPage(page);
		await page.locator(`[data-ds-row="${sharedDatasource.name}"]`).click();

		const config = page.locator('[data-ds-config]');
		await expect(config).toBeVisible({ timeout: 5_000 });

		const generalTab = config.getByRole('tab', { name: 'General' });
		await expect(generalTab).toHaveAttribute('aria-selected', 'true');

		await expect(config.getByText('Source Information')).toBeVisible();
		await expect(config.getByText('Imported')).toBeVisible();
		await expect(config.getByText('Datasource ID')).toBeVisible();

		await screenshot(page, 'datasources', 'detail-config-panel');
	});

	test('general tab allows editing and clearing the datasource description', async ({
		page,
		request
	}) => {
		const ds = `e2e-detail-description-${uid()}`;
		const dsId = await createDatasource(request, ds);
		try {
			await gotoDatasourcesPage(page);
			await selectDatasourceAndWaitForConfig(page, ds);

			const config = page.locator('[data-ds-config]');
			const descriptionField = config.locator('textarea[id^="datasource-description-"]');
			await expect(descriptionField).toHaveValue('');

			await descriptionField.fill('Initial dataset guidance for weekly commercial reporting.');
			await config.getByRole('button', { name: /Save Changes/i }).click();
			await expect(config.getByText('Changes saved successfully!')).toBeVisible();
			await expect(descriptionField).toHaveValue(
				'Initial dataset guidance for weekly commercial reporting.'
			);

			await descriptionField.fill('');
			await config.getByRole('button', { name: /Save Changes/i }).click();
			await expect(config.getByText('Changes saved successfully!')).toBeVisible();
			await expect(descriptionField).toHaveValue('');
		} finally {
			await deleteDatasourceViaUI(page, ds, { id: dsId }).catch(() => undefined);
		}
	});

	test('Schema tab shows actual column names from CSV', async ({ page, sharedDatasource }) => {
		await gotoDatasourcesPage(page);
		await selectDatasourceAndWaitForConfig(page, sharedDatasource.name);
		await openSchemaTabAndWait(page);

		const config = page.locator('[data-ds-config]');
		await expect(config.locator('[data-schema-column="id"]')).toBeVisible({ timeout: 5_000 });
		await expect(config.locator('[data-schema-column="name"]')).toBeVisible();
		await expect(config.locator('[data-schema-column="age"]')).toBeVisible();
		await expect(config.locator('[data-schema-column="city"]')).toBeVisible();
	});

	test('Schema tab allows editing and viewing column descriptions', async ({ page, request }) => {
		const ds = `e2e-detail-schema-${uid()}`;
		const dsId = await createDatasource(request, ds);
		try {
			await gotoDatasourcesPage(page);
			await selectDatasourceAndWaitForConfig(page, ds);
			await openSchemaTabAndWait(page);

			const config = page.locator('[data-ds-config]');
			const editButton = config.getByRole('button', { name: 'Edit description for city' });
			await editButton.click();
			await config.locator('textarea').fill('Primary city label used for regional rollups');
			await config.getByRole('button', { name: 'Save' }).click();
			await expect(editButton).toBeVisible({ timeout: 5_000 });

			await expect(config.locator('[data-schema-description="city"]')).toContainText(
				'Primary city label used for regional rollups'
			);

			await config.locator('[data-schema-column="city"]').click();
			const panel = page.getByTestId('column-stats-panel');
			await expect(panel).toContainText('Description');
			await expect(panel).toContainText('Primary city label used for regional rollups');
		} finally {
			await deleteDatasourceViaUI(page, ds, { id: dsId }).catch(() => undefined);
		}
	});

	test('General tab shows row count from actual data', async ({ page, sharedDatasource }) => {
		await gotoDatasourcesPage(page);
		await page.locator(`[data-ds-row="${sharedDatasource.name}"]`).click();

		const config = page.locator('[data-ds-config]');
		await expect(config).toBeVisible({ timeout: 5_000 });

		await expect(config.getByText('Rows')).toBeVisible({ timeout: 5_000 });
		await expect(page.getByTestId('datasource-row-count')).toHaveText('3', { timeout: 5_000 });
	});

	test('datasource URL includes id query param after selection', async ({
		page,
		sharedDatasource
	}) => {
		await gotoDatasourcesPage(page);
		await page.locator(`[data-ds-row="${sharedDatasource.name}"]`).click();
		await expect(page).toHaveURL(/id=/, { timeout: 5_000 });
	});

	test('right pane shows preview table with column headers and data', async ({
		page,
		sharedDatasource
	}) => {
		await gotoDatasourcesPage(page);
		await page.locator(`[data-ds-row="${sharedDatasource.name}"]`).click();

		// Preview loads in the right pane (DatasourcePreview), not in a config tab
		await waitForDatasourcePreviewReady(page);

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
	test('pagination navigates between pages', async ({ page, sharedPaginationDatasource }) => {
		await gotoDatasourcesPage(page);
		await page.locator(`[data-ds-row="${sharedPaginationDatasource.name}"]`).click();
		await waitForDatasourcePreviewReady(page);

		const pageLabel = page.locator('[data-testid="pagination-page"]');
		await expect(pageLabel).toHaveText('Page 1');

		const nextBtn = page.locator('[data-testid="pagination-next"]');
		const prevBtn = page.locator('[data-testid="pagination-prev"]');

		// Prev should be disabled on page 1
		await expect(prevBtn).toBeDisabled();
		// Next should be enabled (150 rows > 100 row limit)
		await expect(nextBtn).toBeEnabled();

		await nextBtn.click();
		await waitForDatasourcePreviewReady(page);
		await expect(pageLabel).toHaveText('Page 2');
		await expect(prevBtn).toBeEnabled();

		await screenshot(page, 'datasources', 'preview-pagination-page2');

		await prevBtn.click();
		await waitForDatasourcePreviewReady(page);
		await expect(pageLabel).toHaveText('Page 1');
		await expect(prevBtn).toBeDisabled();
	});
});

test.describe('Datasources – column stats panel', () => {
	test('column stats panel opens, shows content, and closes', async ({
		page,
		sharedDatasource
	}) => {
		await page.goto(`/datasources?id=${sharedDatasource.id}`);
		await waitForDatasourcePreviewReady(page);

		const ageHeader = page.locator('[data-column-id="age"]');
		await ageHeader.locator('button[aria-label="Column options"]').click();
		await page.getByText('Column stats').click();

		const panel = page.locator('[data-testid="column-stats-panel"]');
		await expect(panel).toBeVisible({ timeout: 5_000 });
		await expect(panel.getByText('Column Stats')).toBeVisible();
		await expect(panel.getByText('age')).toBeVisible();
		// Stats are computed by an on-demand engine; under parallel workers the
		// first compute can take well over the default five seconds.
		await expect(panel.getByText('Overview')).toBeVisible({ timeout: 15_000 });
		await expect(panel.getByText('Rows')).toBeVisible();

		await screenshot(page, 'datasources', 'column-stats-panel-open');

		await page.locator('[data-testid="column-stats-close"]').click();
		await expect(panel).not.toBeVisible();
	});
});

test.describe('Datasources – config tab interactions', () => {
	test('Runs tab shows onboarding build for imported datasource', async ({
		page,
		sharedDatasource
	}) => {
		await gotoDatasourcesPage(page);
		await page.locator(`[data-ds-row="${sharedDatasource.name}"]`).click();

		const config = page.locator('[data-ds-config]');
		await expect(config).toBeVisible({ timeout: 5_000 });

		await config.getByRole('tab', { name: 'Runs' }).click();
		await expect(config.getByText('No runs associated with this datasource.')).toHaveCount(0);
		// The shard reuses one immutable datasource, so other tests may have
		// created additional build rows. Assert on any matching row instead of
		// requiring the text locator to be unique.
		await expect(config.getByText('Build').first()).toBeVisible({ timeout: 5_000 });

		await screenshot(page, 'datasources', 'runs-tab-onboarding-build');
	});

	test('rename datasource shows Save button and persists', async ({ page, request }) => {
		const id = uid();
		const ds = `e2e-rename-${id}`;
		const renamed = `e2e-renamed-${id}`;
		await createDatasource(request, ds);
		try {
			await gotoDatasourcesPage(page);
			await page.locator(`[data-ds-row="${ds}"]`).click();

			const config = page.locator('[data-ds-config]');
			await expect(config).toBeVisible({ timeout: 5_000 });

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

			// Verify the new name is visible immediately after save (before reload)
			await expect(nameInput).toHaveValue(renamed, { timeout: 5_000 });

			// After save, reload page and verify renamed datasource appears
			await page.reload();
			await expect(page.locator(`[data-ds-row="${renamed}"]`)).toBeVisible({ timeout: 5_000 });
		} finally {
			await deleteDatasourceViaUI(page, renamed);
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Datasources – deeper tab interactions
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Datasources – Runs tab functional', () => {
	test('Runs tab toggles show/hide previews', async ({ page, sharedDatasource }) => {
		await gotoDatasourcesPage(page);
		await page.locator(`[data-ds-row="${sharedDatasource.name}"]`).click();

		const config = page.locator('[data-ds-config]');
		await expect(config).toBeVisible({ timeout: 5_000 });

		await config.getByRole('tab', { name: 'Runs' }).click();

		// The show/hide previews toggle button should be visible
		const toggleBtn = config.getByRole('button', { name: /Show previews|Hide previews/i });
		await expect(toggleBtn).toBeVisible({ timeout: 5_000 });

		// Click to show previews (if not already showing)
		const textBefore = await toggleBtn.textContent();
		if (textBefore?.includes('Show')) {
			await toggleBtn.click();
			await expect(toggleBtn).toContainText(/Hide previews/i, { timeout: 3_000 });
		} else {
			await toggleBtn.click();
			await expect(toggleBtn).toContainText(/Show previews/i, { timeout: 3_000 });
		}
	});
});

test.describe('Datasources – Health Checks tab functional', () => {
	test('Health Checks tab shows New Check button', async ({ page, sharedDatasource }) => {
		await gotoDatasourcesPage(page);
		await page.locator(`[data-ds-row="${sharedDatasource.name}"]`).click();

		const config = page.locator('[data-ds-config]');
		await expect(config).toBeVisible({ timeout: 5_000 });

		await config.getByRole('tab', { name: 'Health Checks' }).click();
		await expect(config.getByRole('button', { name: 'Add', exact: true })).toBeVisible({
			timeout: 5_000
		});
	});
});

test.describe('Datasources – CSV config tab functional', () => {
	test('changing CSV delimiter persists after save and reload', async ({ page, request }) => {
		const ds = `e2e-csv-config-${uid()}`;
		await createDatasource(request, ds);
		try {
			await gotoDatasourcesPage(page);
			await selectDatasourceAndWaitForConfig(page, ds);

			const config = page.locator('[data-ds-config]');

			// Click CSV tab
			await config.getByRole('tab', { name: 'CSV' }).click();
			await expect(config.getByText('CSV Options')).toBeVisible({ timeout: 5_000 });

			// Change delimiter to semicolon
			const delimiterSelect = config.locator('select[id^="csv-delimiter-"]');
			await expect(delimiterSelect).toBeVisible();
			await delimiterSelect.selectOption(';');

			// Save changes
			await config.getByRole('button', { name: 'Save Changes' }).click();
			await expect(config.getByText('Changes saved successfully!')).toBeVisible({
				timeout: 5_000
			});

			// Verify delimiter is still semicolon immediately after save (before reload)
			await expect(delimiterSelect).toHaveValue(';', { timeout: 5_000 });

			// Reload and verify delimiter persisted
			await gotoDatasourcesPage(page);
			await selectDatasourceAndWaitForConfig(page, ds);
			await config.getByRole('tab', { name: 'CSV' }).click();
			await expect(delimiterSelect).toHaveValue(';', { timeout: 5_000 });
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});

	test('CSV header checkbox can be toggled and persists', async ({ page, request }) => {
		const ds = `e2e-csv-header-${uid()}`;
		await createDatasource(request, ds);
		try {
			await gotoDatasourcesPage(page);
			await selectDatasourceAndWaitForConfig(page, ds);

			const config = page.locator('[data-ds-config]');

			await config.getByRole('tab', { name: 'CSV' }).click();
			await expect(config.getByText('CSV Options')).toBeVisible({ timeout: 5_000 });

			const headerCheckbox = config.locator('input[id^="csv-header-"]');
			const wasChecked = await headerCheckbox.isChecked();

			await headerCheckbox.click();
			await expect(headerCheckbox).toBeChecked({ checked: !wasChecked });

			await config.getByRole('button', { name: 'Save Changes' }).click();
			await expect(config.getByText('Changes saved successfully!')).toBeVisible({
				timeout: 5_000
			});

			// Verify checkbox state is correct immediately after save (before reload)
			await expect(headerCheckbox).toBeChecked({ checked: !wasChecked, timeout: 5_000 });

			// Reload and verify
			await gotoDatasourcesPage(page);
			await selectDatasourceAndWaitForConfig(page, ds);
			await config.getByRole('tab', { name: 'CSV' }).click();
			await expect(headerCheckbox).toBeChecked({ checked: !wasChecked, timeout: 5_000 });
		} finally {
			await deleteDatasourceViaUI(page, ds);
		}
	});
});

test.describe('Datasources – schema refresh', () => {
	async function holdSharedDatasourceIngest(
		page: import('@playwright/test').Page,
		datasourceId: string
	) {
		let release!: () => void;
		const released = new Promise<void>((resolve) => {
			release = resolve;
		});
		const routePattern = `**/api/v1/datasource/${datasourceId}/ingest`;
		await page.route(routePattern, async (route) => {
			await released;
			await route.fulfill({ status: 200, contentType: 'application/json', json: {} });
		});
		return { release, routePattern };
	}

	test('clicking refresh schema shows loading state', async ({ page, sharedDatasource }) => {
		const ingest = await holdSharedDatasourceIngest(page, sharedDatasource.id);
		try {
			await gotoDatasourcesPage(page);
			await page.locator(`[data-ds-row="${sharedDatasource.name}"]`).click();

			const config = page.locator('[data-ds-config]');
			await expect(config).toBeVisible({ timeout: 5_000 });

			// The refresh button is in the General tab
			const refreshBtn = config.getByRole('button', {
				name: /Refresh schema|Re-ingest from source/i
			});
			await expect(refreshBtn).toBeVisible({ timeout: 5_000 });

			await refreshBtn.click();

			// After clicking, button should show loading text
			await expect(config.getByRole('button', { name: /Refreshing|Re-ingesting/i })).toBeVisible({
				timeout: 3_000
			});

			// This is a UI loading-state test. Hold the mutating request so the
			// immutable shared fixture is never re-ingested by an unrelated test.
			ingest.release();
			await expect(refreshBtn).toBeVisible({ timeout: readyTimeoutMs() });
		} finally {
			ingest.release();
			await page.unroute(ingest.routePattern);
		}
	});

	test('refresh schema button returns to idle after loading', async ({
		page,
		sharedDatasource
	}) => {
		const ingest = await holdSharedDatasourceIngest(page, sharedDatasource.id);
		try {
			await gotoDatasourcesPage(page);
			await selectDatasourceAndWaitForConfig(page, sharedDatasource.name);

			const config = page.locator('[data-ds-config]');
			const refreshBtn = config.getByRole('button', {
				name: /Refresh schema|Re-ingest from source/i
			});
			await expect(refreshBtn).toBeVisible({ timeout: 5_000 });
			await refreshBtn.click();

			// Loading state appears
			await expect(config.getByRole('button', { name: /Refreshing|Re-ingesting/i })).toBeVisible({
				timeout: 5_000
			});

			// Complete the intercepted request only after the busy state was observed.
			ingest.release();
			await expect(refreshBtn).toBeVisible({ timeout: readyTimeoutMs() });
		} finally {
			ingest.release();
			await page.unroute(ingest.routePattern);
		}
	});

	test('re-ingest from source completes successfully and keeps preview table operational', async ({
		page,
		request
	}) => {
		const ds = `e2e-reingest-${uid()}`;
		const dsId = await createDatasource(request, ds);
		try {
			await gotoDatasourcesPage(page);
			await selectDatasourceAndWaitForConfig(page, ds);

			await waitForDatasourcePreviewReady(page);
			const preview = page.getByTestId('datasource-preview');
			await expect(preview.locator('table')).toBeVisible({ timeout: readyTimeoutMs() });

			const config = page.locator('[data-ds-config]');
			const reingestBtn = config.getByRole('button', {
				name: /Re-ingest from source|Refresh schema/i
			});
			await expect(reingestBtn).toBeVisible({ timeout: 5_000 });
			await reingestBtn.click();

			// Wait for re-ingest button to finish loading
			await expect(
				config.getByRole('button', { name: /Refreshing|Re-ingesting/i })
			).not.toBeVisible({
				timeout: readyTimeoutMs()
			});

			// Check that preview error is not visible and preview table is operational with data rows
			await expect(preview.getByTestId('preview-error')).not.toBeVisible();
			await waitForDatasourcePreviewReady(page);
			await expect(preview.locator('table')).toBeVisible({ timeout: readyTimeoutMs() });
			await expect(preview.locator('tbody tr').first()).toBeVisible({ timeout: readyTimeoutMs() });
		} finally {
			await deleteDatasourceViaUI(page, ds, { id: dsId }).catch(() => undefined);
		}
	});
});

test.describe('Datasources – error states', () => {
	test('bad datasource ID shows empty state without crashing shell', async ({ page }) => {
		await page.goto('/datasources?id=00000000-0000-0000-0000-000000000000');
		await waitForLayoutReady(page);

		// Shell should still be intact
		await expect(page.getByLabel('Main navigation')).toBeVisible({ timeout: 5_000 });

		// The right pane shows "No datasource selected" for an unknown ID
		await expect(page.getByText(/No datasource selected/i)).toBeVisible({ timeout: 5_000 });
	});
});

test.describe('Datasources – preview table interactions', () => {
	test('column options dropdown opens on click', async ({ page, sharedDatasource }) => {
		await gotoDatasourcesPage(page);
		await page.locator(`[data-ds-row="${sharedDatasource.name}"]`).click();

		const config = page.locator('[data-ds-config]');
		await expect(config).toBeVisible({ timeout: 5_000 });
		await waitForDatasourcePreviewReady(page);

		const colOptionsBtn = page.getByRole('button', { name: 'Column options' }).first();
		await colOptionsBtn.click({ force: true });

		// The dropdown should show sort options (rendered in the preview table, outside data-ds-config)
		await expect(page.getByText('Sort A-Z')).toBeVisible({ timeout: 3_000 });
		await expect(page.getByText('Sort Z-A')).toBeVisible({ timeout: 3_000 });
	});

	test('column search filters visible columns', async ({ page, sharedDatasource }) => {
		await gotoDatasourcesPage(page);
		await page.locator(`[data-ds-row="${sharedDatasource.name}"]`).click();

		const config = page.locator('[data-ds-config]');
		await expect(config).toBeVisible({ timeout: 5_000 });
		await waitForDatasourcePreviewReady(page);

		const searchInput = page.locator('#dt-col-search');
		await expect(searchInput).toBeVisible();
		await searchInput.fill('ZZZNOMATCH');

		// All column option buttons should be hidden since no columns match
		await expect(page.getByRole('button', { name: 'Column options' })).toHaveCount(0);

		await searchInput.fill('');
		await expect(page.getByRole('button', { name: 'Column options' }).first()).toBeVisible();
	});

	test('column sort A-Z actually reorders preview rows', async ({ page, sharedDatasource }) => {
		await gotoDatasourcesPage(page);
		await page.locator(`[data-ds-row="${sharedDatasource.name}"]`).click();
		await waitForDatasourcePreviewReady(page);

		// Get the first data row text before sorting
		const firstRow = page.locator('tbody tr').first();
		await expect(firstRow).toBeVisible();
		const beforeText = await firstRow.textContent();

		// Click column options for "city" (4th column in sample CSV)
		const cityColBtn = page
			.locator('th')
			.filter({ hasText: /city/i })
			.getByRole('button', { name: 'Column options' });
		await cityColBtn.click({ force: true });

		// Click Sort A-Z
		await page.getByText('Sort A-Z').click();

		// After sorting by city A-Z, Berlin should be first
		await expect(page.locator('tbody tr').first()).toContainText('Berlin', {
			timeout: 5_000
		});

		// Clear sort should restore original order
		await cityColBtn.click({ force: true });
		await page.getByText('Clear sort').click();
		await expect(page.locator('tbody tr').first()).toHaveText(beforeText ?? '', {
			timeout: 5_000
		});
	});

	test('copy cell value button appears on hover and is clickable', async ({
		page,
		sharedDatasource
	}) => {
		await gotoDatasourcesPage(page);
		await page.locator(`[data-ds-row="${sharedDatasource.name}"]`).click();
		await waitForDatasourcePreviewReady(page);

		// Hover over the first data cell (Alice in the name column)
		const firstCell = page.locator('tbody tr').first().locator('td').nth(1);
		await firstCell.hover();

		// The copy button should appear on hover
		const copyBtn = page.getByRole('button', { name: 'Copy cell value' }).first();
		await expect(copyBtn).toBeVisible({ timeout: 3_000 });

		// Click copy — should not throw and button should remain visible while hovering
		await copyBtn.click();
		await expect(copyBtn).toBeVisible({ timeout: 3_000 });
	});
});

test.describe('Datasources – build comparison', () => {
	test('Compare builds button toggles comparison panel', async ({ page, sharedDatasource }) => {
		await gotoDatasourcesPage(page);
		await page.locator(`[data-ds-row="${sharedDatasource.name}"]`).click();

		const config = page.locator('[data-ds-config]');
		await expect(config).toBeVisible({ timeout: 5_000 });

		// The comparison button should be visible for iceberg datasources
		const compareBtn = page.getByRole('button', { name: 'Compare builds' });
		await expect(compareBtn).toBeVisible({ timeout: 5_000 });

		await compareBtn.click();
		await expect(page.getByRole('button', { name: 'Hide comparison' })).toBeVisible({
			timeout: 3_000
		});
		await expect(page.getByText('Select builds')).toBeVisible({ timeout: 3_000 });

		// Toggle back off
		await page.getByRole('button', { name: 'Hide comparison' }).click();
		await expect(page.getByRole('button', { name: 'Compare builds' })).toBeVisible({
			timeout: 3_000
		});
	});
});

test.describe('Datasources – re-ingest freshness & time travel', () => {
	// Five data rows with a header. Re-ingests flip `skip_rows` (same column
	// type, different row count) so each generation is distinguishable by its
	// preview data without hitting Iceberg's incompatible-type path.
	const REINGEST_CSV = 'value\n1\n2\n3\n4\n5\n';

	async function readLastUpdated(page: Page, dsId: string): Promise<number> {
		const response = await page.context().request.get(`/api/v1/datasource/${dsId}`);
		expect(response.ok()).toBeTruthy();
		const body = (await response.json()) as { last_data_update: string | null };
		return body.last_data_update ? new Date(body.last_data_update).getTime() : 0;
	}

	test('re-ingest advances the Last updated stamp instead of staying stale', async ({
		page,
		request
	}) => {
		const ds = `e2e-last-updated-${uid()}`;
		const dsId = await createCsvDatasource(request, ds, REINGEST_CSV);
		try {
			await gotoDatasourcesPage(page);
			await selectDatasourceAndWaitForConfig(page, ds);
			await waitForDatasourcePreviewReady(page);

			const config = page.locator('[data-ds-config]');
			const beforeMs = await readLastUpdated(page, dsId);
			expect(beforeMs).toBeGreaterThan(0);
			// The publish response carries the freshness stamp: "Never" must
			// not appear for a freshly imported, ingested datasource.
			await expect(config.getByText('Never', { exact: true })).toHaveCount(0);
			const displayedTimestamp = config.locator('time').first();
			await expect(displayedTimestamp).toBeVisible();
			const displayedBefore = await displayedTimestamp.getAttribute('datetime');
			expect(displayedBefore).not.toBeNull();
			expect(Date.parse(displayedBefore ?? '')).toBe(beforeMs);
			const listRow = page.locator(`[data-ds-row="${ds}"]`);
			await expect(listRow.getByText('Last updated', { exact: true })).toBeVisible();
			const listTimestamp = listRow.locator('time').first();
			await expect(listTimestamp).toBeVisible();
			expect(Date.parse((await listTimestamp.getAttribute('datetime')) ?? '')).toBe(beforeMs);

			await config.getByRole('button', { name: /Re-ingest from source/i }).click();
			await expect(config.getByRole('button', { name: /Re-ingesting/i })).not.toBeVisible({
				timeout: readyTimeoutMs()
			});
			await waitForDatasourcePreviewReady(page);

			await expect(config.getByText('Never', { exact: true })).toHaveCount(0);
			// The stamp must actually advance with the new ingest.
			await expect
				.poll(() => readLastUpdated(page, dsId), { timeout: readyTimeoutMs() })
				.toBeGreaterThan(beforeMs);
			await expect
				.poll(async () => Date.parse((await displayedTimestamp.getAttribute('datetime')) ?? ''), {
					timeout: readyTimeoutMs()
				})
				.toBeGreaterThan(beforeMs);
			await expect
				.poll(async () => Date.parse((await listTimestamp.getAttribute('datetime')) ?? ''), {
					timeout: readyTimeoutMs()
				})
				.toBeGreaterThan(beforeMs);
		} finally {
			await deleteDatasourceViaUI(page, ds, { id: dsId }).catch(() => undefined);
		}
	});

	test('time travel lists every ingest and switching snapshots changes the preview data', async ({
		page,
		request
	}) => {
		const ds = `e2e-time-travel-${uid()}`;
		const dsId = await createCsvDatasource(request, ds, REINGEST_CSV);
		try {
			await gotoDatasourcesPage(page);
			await selectDatasourceAndWaitForConfig(page, ds);
			await waitForDatasourcePreviewReady(page);
			const preview = page.locator('[data-testid="datasource-preview"]');
			// Latest generation: skip_rows=0 → five rows.
			await expect(preview.locator('tbody tr')).toHaveCount(5, { timeout: readyTimeoutMs() });

			const config = page.locator('[data-ds-config]');
			const beforeMs = await readLastUpdated(page, dsId);
			expect(beforeMs).toBeGreaterThan(0);

			// Change parsing options and save: the panel re-ingests, producing
			// a second ingest generation (skip_rows=1 → four rows).
			await config.getByRole('tab', { name: 'CSV' }).click();
			await config.locator('input[id^="csv-skip-rows-"]').fill('1');
			await config.getByRole('button', { name: 'Save Changes' }).click();
			await expect
				.poll(() => readLastUpdated(page, dsId), { timeout: readyTimeoutMs() })
				.toBeGreaterThan(beforeMs);
			await waitForDatasourcePreviewReady(page);
			await expect(preview.locator('tbody tr')).toHaveCount(4, { timeout: readyTimeoutMs() });

			// The time travel picker must list BOTH ingest generations.
			const timeTravelButton = page.getByRole('button', { name: /Time Travel/i });
			await expect(timeTravelButton).toBeVisible();
			await timeTravelButton.click();
			const popover = page.getByTestId('time-travel-popover');
			await expect(popover.getByTestId('time-travel-selected')).toContainText('Latest');
			await expect(popover.getByText('Select a day to view snapshots.')).toBeVisible();
			const ingestionDay = popover.locator(
				'[data-testid="time-travel-day"][data-snapshot-count="2"]'
			);
			await expect(ingestionDay).toHaveCount(1, { timeout: readyTimeoutMs() });
			await ingestionDay.click();
			const items = popover.getByTestId('time-travel-snapshot-item');
			await expect(items).toHaveCount(2, { timeout: readyTimeoutMs() });

			// Selecting the older ingestion must send its exact Iceberg snapshot
			// to compute and load that generation's data.
			const olderSnapshot = items.last();
			const olderSnapshotId = await olderSnapshot.getAttribute('data-snapshot-id');
			expect(olderSnapshotId).toBeTruthy();
			const previewRequest = page.waitForRequest(
				(request) =>
					request.url().includes('/api/v1/compute/preview') && request.method() === 'POST',
				{ timeout: readyTimeoutMs() }
			);
			await olderSnapshot.getByRole('button').first().click();
			const selectedPreviewRequest = await previewRequest;
			const previewPayload = selectedPreviewRequest.postDataJSON() as {
				analysis_pipeline: {
					tabs: Array<{ datasource: { config: { snapshot_id?: string } } }>;
				};
			};
			expect(previewPayload.analysis_pipeline.tabs[0]?.datasource.config.snapshot_id).toBe(
				olderSnapshotId
			);
			await expect(popover.getByTestId('time-travel-selected')).toContainText('#');
			await expect(popover.getByTestId('time-travel-selected')).not.toContainText('Latest');
			await page.getByRole('button', { name: /Time Travel/i }).click();
			await waitForDatasourcePreviewReady(page);
			await expect(preview.locator('tbody tr')).toHaveCount(5, { timeout: readyTimeoutMs() });

			// Returning to latest restores the newest generation.
			await page.getByRole('button', { name: /Time Travel/i }).click();
			await popover.getByTestId('time-travel-latest').click();
			await page.getByRole('button', { name: /Time Travel/i }).click();
			await waitForDatasourcePreviewReady(page);
			await expect(preview.locator('tbody tr')).toHaveCount(4, { timeout: readyTimeoutMs() });
		} finally {
			await deleteDatasourceViaUI(page, ds, { id: dsId }).catch(() => undefined);
		}
	});
});
