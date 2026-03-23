import { readFileSync } from 'fs';
import { test, expect } from '@playwright/test';
import { createUdf, deleteUdf } from './utils/api.js';

/**
 * E2E tests for UDFs – mirrors test_udf.py.
 */
test.describe('UDFs – list & management', () => {
	test('shows empty state when no UDFs exist', async ({ page, request }) => {
		const resp = await request.get('http://localhost:8000/api/v1/udf');
		const udfs = (await resp.json()) as unknown[];
		test.skip(udfs.length > 0, 'UDFs already exist – skipping empty-state check');

		await page.goto('/udfs');
		await expect(page.getByText(/No UDFs yet/i)).toBeVisible();
	});

	test('lists UDF after API create', async ({ page, request }) => {
		const udfId = await createUdf(request, 'e2e_list_udf');
		try {
			await page.goto('/udfs');
			await expect(page.locator('h3', { hasText: 'e2e_list_udf' })).toBeVisible();
		} finally {
			await deleteUdf(request, udfId);
		}
	});

	test('UDF description is shown in the list', async ({ page, request }) => {
		const udfId = await createUdf(request, 'e2e_desc_udf');
		try {
			await page.goto('/udfs');
			await expect(page.getByText('Test UDF: e2e_desc_udf')).toBeVisible();
		} finally {
			await deleteUdf(request, udfId);
		}
	});

	test('UDF tags are shown in the list', async ({ page, request }) => {
		const udfId = await createUdf(request, 'e2e_tags_udf');
		try {
			await page.goto('/udfs');
			// Tag chips are <span> elements inside the UDF row
			await expect(page.locator('span', { hasText: 'test' }).first()).toBeVisible();
		} finally {
			await deleteUdf(request, udfId);
		}
	});

	test('search input filters UDF list', async ({ page, request }) => {
		const udfId = await createUdf(request, 'e2e_search_udf');
		try {
			await page.goto('/udfs');
			await expect(page.locator('h3', { hasText: 'e2e_search_udf' })).toBeVisible();

			await page.getByPlaceholder(/Search UDFs/i).fill('ZZZNOMATCH');
			// UDF list filtered server-side – item should disappear
			await expect(page.locator('h3', { hasText: 'e2e_search_udf' })).not.toBeVisible();
		} finally {
			await deleteUdf(request, udfId);
		}
	});

	test('Delete button with inline confirm removes UDF', async ({ page, request }) => {
		const udfId = await createUdf(request, 'e2e_delete_udf');
		try {
			await page.goto('/udfs');
			await expect(page.locator('h3', { hasText: 'e2e_delete_udf' })).toBeVisible();

			// Row container
			const row = page.locator('h3', { hasText: 'e2e_delete_udf' }).locator('../../..');
			await row.getByRole('button', { name: /^Delete$/i }).click();
			// Inline confirm/cancel appears
			await row.getByRole('button', { name: /Confirm/i }).click();

			await expect(page.locator('h3', { hasText: 'e2e_delete_udf' })).not.toBeVisible({
				timeout: 8_000
			});
		} finally {
			await deleteUdf(request, udfId).catch(() => undefined);
		}
	});

	test('Delete cancel keeps UDF in list', async ({ page, request }) => {
		const udfId = await createUdf(request, 'e2e_cancel_delete_udf');
		try {
			await page.goto('/udfs');
			const row = page.locator('h3', { hasText: 'e2e_cancel_delete_udf' }).locator('../../..');
			await row.getByRole('button', { name: /^Delete$/i }).click();
			await row.getByRole('button', { name: /Cancel/i }).click();
			await expect(page.locator('h3', { hasText: 'e2e_cancel_delete_udf' })).toBeVisible();
		} finally {
			await deleteUdf(request, udfId);
		}
	});

	test('Clone button creates a copy of the UDF', async ({ page, request }) => {
		await createUdf(request, 'e2e_clone_udf');
		try {
			await page.goto('/udfs');
			await expect(page.locator('h3', { hasText: 'e2e_clone_udf' })).toBeVisible();

			const row = page.locator('h3', { hasText: 'e2e_clone_udf' }).locator('../../..');
			await row.getByRole('button', { name: /Clone/i }).click();

			// A second UDF with same name or "Copy" suffix appears
			await expect(page.locator('h3', { hasText: 'e2e_clone_udf' }).nth(1)).toBeVisible({
				timeout: 8_000
			});
		} finally {
			const resp = await request.get('http://localhost:8000/api/v1/udf?q=e2e_clone_udf');
			const udfs = (await resp.json()) as Array<{ id: string }>;
			for (const udf of udfs) await deleteUdf(request, udf.id);
		}
	});

	test('Edit button navigates to UDF editor page', async ({ page, request }) => {
		const udfId = await createUdf(request, 'e2e_edit_udf');
		try {
			await page.goto('/udfs');
			const row = page.locator('h3', { hasText: 'e2e_edit_udf' }).locator('../../..');
			await row.getByRole('button', { name: /Edit/i }).click();
			await page.waitForURL(new RegExp(`/udfs/${udfId}`), { timeout: 10_000 });
		} finally {
			await deleteUdf(request, udfId);
		}
	});
});

test.describe('UDFs – export & import', () => {
	test('Export button triggers a JSON file download', async ({ page, request }) => {
		const udfId = await createUdf(request, 'e2e_export_udf');
		try {
			await page.goto('/udfs');

			const [download] = await Promise.all([
				page.waitForEvent('download'),
				page.getByRole('button', { name: /Export/i }).click()
			]);

			expect(download.suggestedFilename()).toBe('udfs.json');
		} finally {
			await deleteUdf(request, udfId);
		}
	});

	test('Import button opens the import dialog', async ({ page }) => {
		await page.goto('/udfs');
		await page.getByRole('button', { name: /Import/i }).click();
		await expect(page.getByRole('heading', { name: /Import UDFs/i })).toBeVisible();
	});

	test('Import dialog Cancel closes it', async ({ page }) => {
		await page.goto('/udfs');
		const importBtn = page.getByRole('button', { name: /Import/i });
		await expect(importBtn).toBeVisible();
		await importBtn.click();
		const dialogHeading = page.getByRole('heading', { name: /Import UDFs/i });
		await expect(dialogHeading).toBeVisible();
		// Cancel button is in the dialog footer
		const cancelBtn = page.getByRole('button', { name: /Cancel/i });
		await expect(cancelBtn).toBeVisible();
		await cancelBtn.click();
		await expect(dialogHeading).not.toBeVisible();
	});

	test('Import dialog: invalid JSON shows error', async ({ page }) => {
		await page.goto('/udfs');
		await page.getByRole('button', { name: /Import/i }).click();
		await page.getByLabel(/Import JSON/i).fill('not-valid-json');
		// Click the primary Import button inside the dialog (last one = dialog's CTA)
		await page
			.getByRole('button', { name: /^Import$/i })
			.last()
			.click();
		await expect(page.getByText(/Invalid JSON/i)).toBeVisible();
	});

	test('Import dialog: missing udfs array shows error', async ({ page }) => {
		await page.goto('/udfs');
		await page.getByRole('button', { name: /Import/i }).click();
		await page.getByLabel(/Import JSON/i).fill('{"other": []}');
		await page
			.getByRole('button', { name: /^Import$/i })
			.last()
			.click();
		await expect(page.getByText(/udfs array/i)).toBeVisible();
	});

	test('valid import roundtrip: export then import', async ({ page, request }) => {
		test.setTimeout(60_000);
		const udfId = await createUdf(request, 'e2e_roundtrip_udf');
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

			// Delete the UDF first
			await deleteUdf(request, udfId);
			await page.reload();
			await expect(page.locator('h3', { hasText: 'e2e_roundtrip_udf' })).toHaveCount(0);

			// Import it back directly via API – only import the specific UDF (not the full export)
			const importPayload = JSON.parse(exportedJson) as {
				udfs: Array<{ name: string; [key: string]: unknown }>;
			};
			const ourUdf = importPayload.udfs.find((u) => u.name === 'e2e_roundtrip_udf');
			if (!ourUdf) throw new Error('e2e_roundtrip_udf not found in export JSON');

			const importResp = await request.post('http://localhost:8000/api/v1/udf/import', {
				data: { udfs: [ourUdf], overwrite: false }
			});
			if (!importResp.ok()) {
				throw new Error(`Import failed: ${importResp.status()} ${await importResp.text()}`);
			}

			// Reload to pick up the freshly imported UDF
			await page.reload();
			await expect(page.locator('h3', { hasText: 'e2e_roundtrip_udf' }).first()).toBeVisible({
				timeout: 10_000
			});
		} finally {
			try {
				const resp = await request.get('http://localhost:8000/api/v1/udf?q=e2e_roundtrip_udf');
				const udfs = (await resp.json()) as Array<{ id: string }>;
				for (const udf of udfs) await deleteUdf(request, udf.id).catch(() => undefined);
			} catch {
				// Cleanup best-effort — backend may be temporarily unavailable
			}
		}
	});
});

test.describe('UDFs – editor page', () => {
	test('new UDF editor has name field', async ({ page }) => {
		await page.goto('/udfs/new');
		await expect(page.getByLabel(/Name/i).first()).toBeVisible({ timeout: 8_000 });
	});

	test('new UDF editor has code editor', async ({ page }) => {
		await page.goto('/udfs/new');
		// CodeMirror editor or a textarea for the Python code
		await expect(page.locator('.cm-editor').or(page.locator('textarea')).first()).toBeVisible({
			timeout: 8_000
		});
	});

	test('new UDF editor has Save button', async ({ page }) => {
		await page.goto('/udfs/new');
		await expect(page.getByRole('button', { name: /Save/i })).toBeVisible({ timeout: 8_000 });
	});

	test('existing UDF editor shows UDF content', async ({ page, request }) => {
		const udfId = await createUdf(request, 'e2e_editor_content_udf');
		try {
			await page.goto(`/udfs/${udfId}`);
			// The name input (#udf-name) is populated with the UDF name
			const nameInput = page.locator('#udf-name');
			await expect(nameInput).toBeVisible({ timeout: 10_000 });
			await expect(nameInput).toHaveValue(/e2e_editor_content_udf/);
		} finally {
			await deleteUdf(request, udfId);
		}
	});
});
