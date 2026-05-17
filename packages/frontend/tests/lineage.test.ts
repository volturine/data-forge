import { test, expect } from './fixtures.js';
import { createDatasource, createAnalysis } from './utils/api.js';
import { waitForLineageToolbar } from './utils/readiness.js';
import { deleteAnalysisViaUI, deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { uid } from './utils/uid.js';
import { screenshot } from './utils/visual.js';

/**
 * E2E tests for the /lineage page — data lineage graph and sidebar.
 */
test.describe('Lineage – page structure', () => {
	test('renders Data Lineage heading', async ({ page }) => {
		await page.goto('/lineage');
		await expect(page.getByRole('heading', { name: 'Data Lineage' })).toBeVisible();
	});

	test('shows datasource and branch selectors', async ({ page }) => {
		await page.goto('/lineage');
		await waitForLineageToolbar(page);
		await expect(page.getByLabel('Output datasource')).toBeVisible();
		await expect(page.getByLabel('Branch')).toBeVisible();
	});

	test('shows layout toolbar buttons', async ({ page }) => {
		await page.goto('/lineage');
		await waitForLineageToolbar(page);
		await expect(page.locator('button[title="Horizontal tree layout"]')).toBeVisible();
		await expect(page.locator('button[title="Vertical tree layout"]')).toBeVisible();
		await expect(page.locator('button[title="Grid layout"]')).toBeVisible();
	});

	test('shows zoom controls', async ({ page }) => {
		await page.goto('/lineage');
		await waitForLineageToolbar(page);
		await expect(page.locator('button[title="Zoom in"]')).toBeVisible();
		await expect(page.locator('button[title="Zoom out"]')).toBeVisible();
		await expect(page.locator('button[title="Reset view"]')).toBeVisible();
	});

	test('sidebar shows "Select a node" prompt by default', async ({ page }) => {
		await page.goto('/lineage');
		await expect(page.getByText('Select a node')).toBeVisible();
		await expect(page.getByText('Click a node to view details and schedules.')).toBeVisible();
		await screenshot(page, 'lineage', 'default-state');
	});

	test('branch selector is disabled when no datasource is selected', async ({ page }) => {
		await page.goto('/lineage');
		await waitForLineageToolbar(page);
		await expect(page.getByLabel('Branch')).toBeDisabled();
	});
});

test.describe('Lineage – layout switching', () => {
	test('clicking Vertical layout button switches to vertical mode', async ({ page }) => {
		await page.goto('/lineage');
		await waitForLineageToolbar(page);
		const verticalBtn = page.locator('button[title="Vertical tree layout"]');
		await verticalBtn.click();
		await expect(page.getByText('Vertical')).toBeVisible();
	});

	test('clicking Grid layout button switches to grid mode', async ({ page }) => {
		await page.goto('/lineage');
		await waitForLineageToolbar(page);
		const gridBtn = page.locator('button[title="Grid layout"]');
		await gridBtn.click();
		await expect(page.getByText('Grid')).toBeVisible();
	});

	test('clicking Horizontal layout button restores horizontal mode', async ({ page }) => {
		await page.goto('/lineage');
		await waitForLineageToolbar(page);
		await page.locator('button[title="Grid layout"]').click();
		await page.locator('button[title="Horizontal tree layout"]').click();
		await expect(page.getByText('Horizontal')).toBeVisible();
	});
});

test.describe('Lineage – graph interaction', () => {
	test('zoom percentage is displayed', async ({ page }) => {
		await page.goto('/lineage');
		await waitForLineageToolbar(page);
		// The zoom label renders as "{zoomPercent}%" – match the specific pattern
		await expect(page.getByText(/^\d+%$/)).toBeVisible();
	});

	test('lineage graph loads without error state', async ({ page }) => {
		await page.goto('/lineage');
		await waitForLineageToolbar(page);
		// Wait for the loading state to clear first, then verify no error
		await expect(page.getByText('Loading lineage...')).not.toBeVisible({ timeout: 15_000 });
		await expect(page.getByText('Failed to load lineage.')).not.toBeVisible();
	});
});

test.describe('Lineage – with datasource data', () => {
	test('lineage graph renders nodes when datasources exist', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsName = `e2e-lineage-ds-${uid()}`;
		const aName = `E2E Lineage ${uid()}`;
		const dsId = await createDatasource(request, dsName);
		await createAnalysis(request, aName, dsId);
		try {
			await page.goto('/lineage');
			// The lineage graph area should not show the error state
			await expect(page.getByText('Failed to load lineage.')).not.toBeVisible();
			// The graph container should be present and not loading
			await expect(page.getByText('Loading lineage...')).not.toBeVisible({ timeout: 15_000 });
			await screenshot(page, 'lineage', 'with-data');
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('dragging the canvas pans visible lineage nodes', async ({ page, request }) => {
		test.setTimeout(60_000);
		const dsName = `e2e-lineage-pan-ds-${uid()}`;
		const aName = `E2E Lineage Pan ${uid()}`;
		const dsId = await createDatasource(request, dsName);
		await createAnalysis(request, aName, dsId);

		try {
			await page.goto('/lineage');
			await waitForLineageToolbar(page);
			const graph = page.getByTestId('lineage-canvas');
			await expect(graph).toBeVisible({ timeout: 15_000 });

			const node = page.getByRole('button', { name: `source ${dsName}` });
			await expect(node).toBeVisible({ timeout: 15_000 });

			const before = await node.boundingBox();
			const graphBox = await graph.boundingBox();
			expect(before).not.toBeNull();
			expect(graphBox).not.toBeNull();
			if (!before || !graphBox) {
				throw new Error('Expected lineage node and graph canvas bounding boxes');
			}

			await page.mouse.move(graphBox.x + 24, graphBox.y + 24);
			await page.mouse.down();
			await page.mouse.move(graphBox.x + 180, graphBox.y + 120, { steps: 12 });
			await page.mouse.up();

			const after = await node.boundingBox();
			expect(after).not.toBeNull();
			if (!after) {
				throw new Error('Expected lineage node bounding box after panning');
			}

			expect(after.x).toBeGreaterThan(before.x + 60);
			expect(after.y).toBeGreaterThan(before.y + 40);
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});
});
