import { readFileSync } from 'fs';
import { test, expect } from './fixtures.js';
import { createUdf } from './utils/api.js';
import { waitForLayoutReady, waitForUdfList, gotoUdfEditor } from './utils/readiness.js';
import { uid } from './utils/uid.js';
import { deleteUdfViaUI } from './utils/ui-cleanup.js';
import { screenshot } from './utils/visual.js';

/**
 * E2E tests for UDFs – mirrors test_udf.py.
 */
test.describe('UDFs – list & management', () => {
	test('seeded default UDFs are visible on first load', async ({ page }) => {
		await page.goto('/udfs');
		await waitForUdfList(page);

		await expect(page.locator('[data-udf-card="Ratio"]')).toBeVisible();
		await expect(page.locator('[data-udf-card="Coalesce"]')).toBeVisible();
		await expect(page.locator('[data-udf-card="Normalize"]')).toBeVisible();
	});

	test('lists UDF after API create', async ({ page, request }) => {
		const udf = `e2e_list_${uid()}`;
		await createUdf(request, udf);
		try {
			await page.goto('/udfs');
			await waitForUdfList(page);
			await expect(page.locator(`[data-udf-card="${udf}"]`)).toBeVisible();
			await screenshot(page, 'udfs', 'list-with-udf');
		} finally {
			await deleteUdfViaUI(page, udf);
		}
	});

	test('UDF description is shown in the list', async ({ page, request }) => {
		const udf = `e2e_desc_${uid()}`;
		await createUdf(request, udf);
		try {
			await page.goto('/udfs');
			await waitForUdfList(page);
			await expect(page.getByText(`Test UDF: ${udf}`)).toBeVisible();
		} finally {
			await deleteUdfViaUI(page, udf);
		}
	});

	test('UDF tags are shown in the list', async ({ page, request }) => {
		const udf = `e2e_tags_${uid()}`;
		await createUdf(request, udf);
		try {
			await page.goto('/udfs');
			await waitForUdfList(page);
			// Tag chips are <span> elements inside the UDF row
			await expect(
				page.locator(`[data-udf-card="${udf}"]`).getByText('test', { exact: true })
			).toBeVisible();
		} finally {
			await deleteUdfViaUI(page, udf);
		}
	});

	test('search input filters UDF list', async ({ page, request }) => {
		const udf = `e2e_search_${uid()}`;
		await createUdf(request, udf);
		try {
			await page.goto('/udfs');
			await waitForUdfList(page);
			await expect(page.locator(`[data-udf-card="${udf}"]`)).toBeVisible();

			await page.getByPlaceholder(/Search UDFs/i).fill('ZZZNOMATCH');
			// UDF list filtered server-side – item should disappear
			await expect(page.locator(`[data-udf-card="${udf}"]`)).not.toBeVisible();
		} finally {
			await deleteUdfViaUI(page, udf);
		}
	});

	test('Delete button with inline confirm removes UDF', async ({ page, request }) => {
		const udf = `e2e_delete_${uid()}`;
		await createUdf(request, udf);
		await page.goto('/udfs');
		await waitForUdfList(page);
		await expect(page.locator(`[data-udf-card="${udf}"]`)).toBeVisible();

		// Row container
		const row = page.locator(`[data-udf-card="${udf}"]`);
		await row.getByRole('button', { name: /^Delete$/i }).click();
		// Inline confirm/cancel appears
		await row.getByRole('button', { name: /Confirm/i }).click();

		await expect(page.locator(`[data-udf-card="${udf}"]`)).not.toBeVisible({
			timeout: 8_000
		});
	});

	test('Delete cancel keeps UDF in list', async ({ page, request }) => {
		const udf = `e2e_cancel_${uid()}`;
		await createUdf(request, udf);
		try {
			await page.goto('/udfs');
			await waitForUdfList(page);
			const row = page.locator(`[data-udf-card="${udf}"]`);
			await row.getByRole('button', { name: /^Delete$/i }).click();
			await row.getByRole('button', { name: /Cancel/i }).click();
			await expect(page.locator(`[data-udf-card="${udf}"]`)).toBeVisible();
		} finally {
			await deleteUdfViaUI(page, udf);
		}
	});

	test('Clone button creates a copy of the UDF', async ({ page, request }) => {
		test.setTimeout(60_000);
		const udf = `e2e_clone_${uid()}`;
		await createUdf(request, udf);
		try {
			await page.goto('/udfs');
			await waitForUdfList(page);
			await expect(page.locator(`[data-udf-card="${udf}"]`)).toBeVisible();

			const row = page.locator(`[data-udf-card="${udf}"]`);
			await row.getByRole('button', { name: /Clone/i }).click();

			// Clone gets the name "${udf} (copy)"
			const cloneName = `${udf} (copy)`;
			await expect(page.locator(`[data-udf-card="${cloneName}"]`)).toBeVisible({
				timeout: 8_000
			});
		} finally {
			// Delete clone first (has " (copy)" suffix), then original
			await deleteUdfViaUI(page, `${udf} (copy)`);
			await deleteUdfViaUI(page, udf);
		}
	});

	test('Edit button navigates to UDF editor page', async ({ page, request }) => {
		const udf = `e2e_edit_${uid()}`;
		const udfId = await createUdf(request, udf);
		try {
			await page.goto('/udfs');
			await waitForUdfList(page);
			const row = page.locator(`[data-udf-card="${udf}"]`);
			await row.getByRole('button', { name: /Edit/i }).click();
			await expect(page).toHaveURL(new RegExp(`/udfs/${udfId}`), { timeout: 10_000 });
		} finally {
			await deleteUdfViaUI(page, udf);
		}
	});
});

test.describe('UDFs – export & import', () => {
	test('Export button triggers a JSON file download', async ({ page, request }) => {
		const udf = `e2e_export_${uid()}`;
		await createUdf(request, udf);
		try {
			await page.goto('/udfs');
			await waitForUdfList(page);
			// Wait for UDF list to load before exporting
			await expect(page.locator(`[data-udf-card="${udf}"]`)).toBeVisible();

			const [download] = await Promise.all([
				page.waitForEvent('download'),
				page.getByRole('button', { name: /Export/i }).click()
			]);

			expect(download.suggestedFilename()).toBe('udfs.json');
		} finally {
			await deleteUdfViaUI(page, udf);
		}
	});

	test('Import button opens the import dialog', async ({ page }) => {
		await page.goto('/udfs');
		const importBtn = page.getByRole('button', { name: /Import/i });
		await expect(importBtn).toBeVisible();
		await importBtn.click();
		await expect(page.getByRole('dialog')).toBeVisible();
		await expect(page.getByRole('heading', { name: /Import UDFs/i })).toBeVisible();
	});

	test('Import dialog Cancel closes it', async ({ page }) => {
		await page.goto('/udfs');
		const importBtn = page.getByRole('button', { name: /Import/i });
		await expect(importBtn).toBeVisible();
		await importBtn.click();
		const dialog = page.getByRole('dialog');
		await expect(dialog).toBeVisible();
		const dialogHeading = dialog.getByRole('heading', { name: /Import UDFs/i });
		await expect(dialogHeading).toBeVisible();
		await dialog.getByRole('button', { name: /Cancel/i }).click();
		await expect(dialogHeading).not.toBeVisible();
	});

	test('Import dialog: invalid JSON shows error', async ({ page }) => {
		await page.goto('/udfs');
		const importBtn = page.getByRole('button', { name: /Import/i });
		await expect(importBtn).toBeVisible();
		await importBtn.click();
		const dialog = page.getByRole('dialog');
		await expect(dialog).toBeVisible();
		await page.locator('#udf-import-json').fill('not-valid-json');
		await dialog.getByRole('button', { name: /^Import$/i }).click();
		await expect(page.getByText(/Invalid JSON/i)).toBeVisible();
	});

	test('Import dialog: missing udfs array shows error', async ({ page }) => {
		await page.goto('/udfs');
		const importBtn = page.getByRole('button', { name: /Import/i });
		await expect(importBtn).toBeVisible();
		await importBtn.click();
		const dialog = page.getByRole('dialog');
		await expect(dialog).toBeVisible();
		await expect(dialog.getByRole('heading', { name: /Import UDFs/i })).toBeVisible();
		await page.locator('#udf-import-json').fill('{"other": []}');
		await dialog.getByRole('button', { name: /^Import$/i }).click();
		await expect(page.getByText(/udfs array/i)).toBeVisible();
	});

	test('valid import roundtrip: export then import', async ({ page, request }) => {
		test.setTimeout(60_000);
		const udf = `e2e_roundtrip_${uid()}`;
		await createUdf(request, udf);
		try {
			await page.goto('/udfs');

			// Export
			const [download] = await Promise.all([
				page.waitForEvent('download'),
				page.getByRole('button', { name: /Export/i }).click()
			]);
			const exportedJson = await download.path().then((p) => {
				if (!p) throw new Error('No download path');
				return readFileSync(p, 'utf8');
			});

			// Delete the UDF via UI first
			await deleteUdfViaUI(page, udf);
			await page.goto('/udfs');
			await waitForUdfList(page);
			await expect(page.locator(`[data-udf-card="${udf}"]`)).toHaveCount(0);

			// Import the exported UDF back via the UI import dialog
			const importBtn = page.getByRole('button', { name: /Import/i });
			await importBtn.click();
			const importDialog = page.getByRole('dialog');
			await expect(importDialog).toBeVisible();
			await page.locator('#udf-import-json').fill(exportedJson);
			await importDialog.getByRole('button', { name: /^Import$/i }).click();
			await expect(importDialog.getByRole('heading', { name: /Import UDFs/i })).not.toBeVisible({
				timeout: 10_000
			});

			await expect(page.locator(`[data-udf-card="${udf}"]`)).toBeVisible({ timeout: 10_000 });
		} finally {
			await deleteUdfViaUI(page, udf);
		}
	});
});

test.describe('UDFs – editor page', () => {
	test('new UDF editor has name field', async ({ page }) => {
		await page.goto('/udfs/new');
		await expect(page.locator('#udf-name')).toBeVisible({ timeout: 8_000 });
	});

	test('new UDF editor has code editor', async ({ page }) => {
		await page.goto('/udfs/new');
		await expect(page.locator('.cm-editor')).toBeVisible({ timeout: 8_000 });
		await screenshot(page, 'udfs', 'editor-page');
	});

	test('new UDF editor has Save button', async ({ page }) => {
		await page.goto('/udfs/new');
		await waitForLayoutReady(page);
		await expect(page.getByRole('button', { name: /Save/i })).toBeVisible({ timeout: 8_000 });
	});

	test('existing UDF editor shows UDF content', async ({ page, request }) => {
		const udf = `e2e_editor_${uid()}`;
		const udfId = await createUdf(request, udf);
		try {
			await gotoUdfEditor(page, udfId);
			const nameInput = page.locator('#udf-name');
			await expect(nameInput).toHaveValue(new RegExp(udf));
		} finally {
			await deleteUdfViaUI(page, udf);
		}
	});
});

test.describe('UDFs – editor functional flows', () => {
	test('create UDF via editor and verify it appears in list', async ({ page }) => {
		test.setTimeout(60_000);
		const udf = `e2e_create_flow_${uid()}`;
		try {
			await page.goto('/udfs/new');
			await expect(page.locator('#udf-name')).toBeVisible({ timeout: 8_000 });

			await page.locator('#udf-name').fill(udf);
			await page.locator('#udf-description').fill('Created via editor E2E test');
			await page.locator('#udf-tags').fill('e2e, create');

			const saveBtn = page.locator('[data-testid="udf-save-button"]');
			await expect(saveBtn).toBeEnabled();
			await saveBtn.click();

			// After create, editor redirects to /udfs/<id>
			await expect(page).toHaveURL(/\/udfs\/[0-9a-f-]+$/, { timeout: 15_000 });
			await screenshot(page, 'udfs', 'editor-after-create');

			// Navigate to list and verify the UDF appears
			await page.goto('/udfs');
			await waitForUdfList(page);
			await expect(page.locator(`[data-udf-card="${udf}"]`)).toBeVisible({ timeout: 10_000 });
		} finally {
			await deleteUdfViaUI(page, udf);
		}
	});

	test('edit existing UDF and save changes', async ({ page, request }) => {
		test.setTimeout(60_000);
		const udf = `e2e_edit_flow_${uid()}`;
		const udfId = await createUdf(request, udf);
		try {
			await gotoUdfEditor(page, udfId);
			const nameInput = page.locator('#udf-name');
			await expect(nameInput).toHaveValue(udf);

			// Modify the description
			await page.locator('#udf-description').fill('Updated description from E2E');

			const saveBtn = page.locator('[data-testid="udf-save-button"]');
			await saveBtn.click();

			// Reload and verify the changes persisted
			await page.reload();
			await expect(page.locator('#udf-description')).toHaveValue('Updated description from E2E', {
				timeout: 10_000
			});
			await screenshot(page, 'udfs', 'editor-after-edit');
		} finally {
			await deleteUdfViaUI(page, udf);
		}
	});

	test('Save button is disabled when name is empty', async ({ page }) => {
		await page.goto('/udfs/new');
		await expect(page.locator('[data-testid="udf-save-button"]')).toBeVisible({ timeout: 8_000 });

		// Name starts empty — Save should be disabled
		const nameInput = page.locator('#udf-name');
		await expect(nameInput).toHaveValue('');
		await expect(page.locator('[data-testid="udf-save-button"]')).toBeDisabled();

		// Fill a name — Save should become enabled
		await nameInput.fill('e2e_validation_test');
		await expect(page.locator('[data-testid="udf-save-button"]')).toBeEnabled();

		// Clear the name — Save should be disabled again
		await nameInput.fill('');
		await expect(page.locator('[data-testid="udf-save-button"]')).toBeDisabled();
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// UDF error-state regression tests
// ────────────────────────────────────────────────────────────────────────────────

test.describe('UDFs – error states', () => {
	const BAD_ID = '00000000-0000-0000-0000-000000000000';

	test('load error displays error state for bad UDF ID', async ({ page }) => {
		await page.goto(`/udfs/${BAD_ID}`);

		await expect(page.locator('[data-testid="udf-load-error"]')).toBeVisible({ timeout: 15_000 });
		await expect(page.getByText('Failed to load UDF.')).toBeVisible();

		await screenshot(page, 'udfs', 'load-error-state');
	});

	test('load error does not crash navigation', async ({ page }) => {
		await page.goto(`/udfs/${BAD_ID}`);
		await expect(page.locator('[data-testid="udf-load-error"]')).toBeVisible({ timeout: 15_000 });

		await page.locator('a[href="/udfs"]').click();
		await expect(page).toHaveURL('/udfs');
		await expect(page.getByRole('heading', { name: 'UDF Library' })).toBeVisible();
	});
});
