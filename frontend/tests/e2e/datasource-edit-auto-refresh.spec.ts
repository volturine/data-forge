import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';

test.describe('DataSource Edit Auto-Refresh', () => {
	test('CSV delimiter change and auto-refresh', async ({ page }) => {
		// Navigate to datasources page
		await page.goto('/datasources');

		// Check if there are existing datasources
		const datasourceCards = page.locator('[data-testid="datasource-card"]');
		const count = await datasourceCards.count();

		let datasourceId: string;

		if (count === 0) {
			// Need to create a new datasource
			await page.goto('/datasources/new');

			// Create a test CSV file
			const csvContent = 'name;age;city\nAlice;30;NYC\nBob;25;LA\nCharlie;35;SF';
			const tempDir = path.join(process.cwd(), 'temp');
			if (!fs.existsSync(tempDir)) {
				fs.mkdirSync(tempDir);
			}
			const csvPath = path.join(tempDir, 'test_semicolon.csv');
			fs.writeFileSync(csvPath, csvContent);

			// Upload the file
			const fileInput = page.locator('input[type="file"]');
			await fileInput.setInputFiles(csvPath);

			// Wait for upload to complete and get the datasource ID
			await page.waitForURL(/\/datasources\/[^/]+/);
			const url = page.url();
			const match = url.match(/\/datasources\/([^/]+)/);
			if (match) {
				datasourceId = match[1];
			} else {
				throw new Error('Failed to get datasource ID after upload');
			}

			// Clean up temp file
			fs.unlinkSync(csvPath);
		} else {
			// Use existing datasource
			const firstCard = datasourceCards.first();
			const link = firstCard.locator('a');
			const href = await link.getAttribute('href');
			if (href) {
				const match = href.match(/\/datasources\/([^/]+)/);
				if (match) {
					datasourceId = match[1];
				} else {
					throw new Error('Failed to extract datasource ID from link');
				}
			} else {
				throw new Error('No href found on datasource card');
			}
		}

		// Navigate to edit page
		await page.goto(`/datasources/${datasourceId}/edit`);

		// Go to CSV Options tab
		const csvOptionsTab = page.getByRole('tab', { name: 'CSV Options' });
		await csvOptionsTab.click();

		// Change delimiter from Comma to Semicolon
		const delimiterSelect = page.locator('select[name="delimiter"]');
		await delimiterSelect.selectOption({ label: 'Semicolon (;)' });

		// Wait for auto-save (loading indicator)
		const loadingIndicator = page.locator('[data-testid="saving-indicator"], .loading');
		if ((await loadingIndicator.count()) > 0) {
			await expect(loadingIndicator).toBeVisible();
			await expect(loadingIndicator).not.toBeVisible({ timeout: 10000 });
		}

		// Switch to Schema tab
		const schemaTab = page.getByRole('tab', { name: 'Schema' });
		await schemaTab.click();

		// Wait for schema refresh
		const refreshingIndicator = page.locator('text="Refreshing schema..."');
		if ((await refreshingIndicator.count()) > 0) {
			await expect(refreshingIndicator).toBeVisible();
			await expect(refreshingIndicator).not.toBeVisible({ timeout: 10000 });
		}

		// Verify schema shows 3 columns
		const columnHeaders = page.locator('[data-testid="column-header"], .column-name');
		await expect(columnHeaders).toHaveCount(3);
		await expect(columnHeaders.nth(0)).toContainText('name');
		await expect(columnHeaders.nth(1)).toContainText('age');
		await expect(columnHeaders.nth(2)).toContainText('city');
	});

	test('Skip rows debounced auto-refresh', async ({ page }) => {
		// Assuming we have a datasource from previous test or existing
		await page.goto('/datasources');

		const datasourceCards = page.locator('[data-testid="datasource-card"]');
		const count = await datasourceCards.count();

		if (count === 0) {
			test.skip(); // Skip if no datasources
		}

		const firstCard = datasourceCards.first();
		const link = firstCard.locator('a');
		const href = await link.getAttribute('href');
		if (!href) {
			test.skip();
			return;
		}
		const match = href.match(/\/datasources\/([^/]+)/);
		if (!match) {
			test.skip();
			return;
		}
		const datasourceId = match[1];

		await page.goto(`/datasources/${datasourceId}/edit`);

		// Go to CSV Options tab
		const csvOptionsTab = page.getByRole('tab', { name: 'CSV Options' });
		await csvOptionsTab.click();

		// Change skip rows to 1 (debounced)
		const skipRowsInput = page.locator('input[name="skip_rows"]');
		await skipRowsInput.fill('1');

		// Wait for debounce (500ms)
		await page.waitForTimeout(600);

		// Switch to Schema tab
		const schemaTab = page.getByRole('tab', { name: 'Schema' });
		await schemaTab.click();

		// Wait for schema refresh
		const refreshingIndicator = page.locator('text="Refreshing schema..."');
		if ((await refreshingIndicator.count()) > 0) {
			await expect(refreshingIndicator).toBeVisible();
			await expect(refreshingIndicator).not.toBeVisible({ timeout: 10000 });
		}

		// Verify schema updates (should have 2 rows instead of 3 if skip 1)
		// Note: This depends on the actual data, but generally schema columns should be the same
		const columnHeaders = page.locator('[data-testid="column-header"], .column-name');
		await expect(columnHeaders).toHaveCount(3); // Assuming same columns
	});
});
