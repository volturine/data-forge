import { test, expect } from './fixtures.js';
import { createAnalysis } from './utils/api.js';
import { waitForLineageToolbar } from './utils/readiness.js';
import { deleteAnalysisViaUI } from './utils/ui-cleanup.js';
import { uid } from './utils/uid.js';
import { screenshot } from './utils/visual.js';

/**
 * E2E tests for the /lineage page — data lineage graph and sidebar.
 */
test.describe('Lineage – page structure', () => {
	// These are one unchanged page contract, not six separate bootstrap journeys.
	test('renders the heading, selectors, layout controls and default sidebar without errors', async ({
		page
	}) => {
		await page.goto('/lineage');
		await waitForLineageToolbar(page);
		await expect(page.getByRole('heading', { name: 'Data Lineage' })).toBeVisible();
		await expect(page.getByLabel('Output datasource')).toBeVisible();
		await expect(page.getByLabel('Branch')).toBeVisible();
		await expect(page.getByLabel('Branch')).toBeDisabled();
		await expect(page.locator('button[title="Horizontal tree layout"]')).toBeVisible();
		await expect(page.locator('button[title="Vertical tree layout"]')).toBeVisible();
		await expect(page.locator('button[title="Grid layout"]')).toBeVisible();
		await expect(page.locator('button[title="Zoom in"]')).toBeVisible();
		await expect(page.locator('button[title="Zoom out"]')).toBeVisible();
		await expect(page.locator('button[title="Reset view"]')).toBeVisible();
		// Exact match excludes Svelte Flow's visually hidden accessibility hint.
		await expect(page.getByText('Select a node', { exact: true })).toBeVisible();
		await expect(page.getByText('Click a node to view details and schedules.')).toBeVisible();
		await expect(page.getByText('Loading lineage...')).not.toBeVisible({ timeout: 5_000 });
		await expect(page.getByText('Failed to load lineage.')).not.toBeVisible();
		await screenshot(page, 'lineage', 'default-state');
	});
});

test.describe('Lineage – layout switching', () => {
	test('recovers from a worker failure and switches layouts in one journey', async ({
		page,
		sharedDatasource
	}) => {
		await page.route('**/elk-worker.min.*.js', (route) => route.abort(), { times: 1 });
		await page.goto('/lineage');
		await waitForLineageToolbar(page);
		const fallback = page.getByText(
			'Layered layout failed; showing grid. Choose horizontal or vertical to retry.'
		);
		await expect(fallback).toBeVisible();
		await expect(
			page.getByRole('button', { name: `source ${sharedDatasource.name}` })
		).toBeVisible();
		await page.locator('button[title="Vertical tree layout"]').click();
		await expect(page.getByRole('button', { name: 'Vertical', exact: true })).toBeVisible();
		await expect(fallback).not.toBeVisible();
		await page.locator('button[title="Grid layout"]').click();
		await expect(page.getByRole('button', { name: 'Grid', exact: true })).toBeVisible();
		await page.locator('button[title="Horizontal tree layout"]').click();
		await expect(page.getByRole('button', { name: 'Horizontal', exact: true })).toBeVisible();
	});
});

test.describe('Lineage – graph interaction', () => {
	test('zoom in and out changes zoom percentage', async ({ page }) => {
		await page.goto('/lineage');
		await waitForLineageToolbar(page);
		await expect(page.getByText('Loading lineage...')).not.toBeVisible({ timeout: 5_000 });

		const zoomLabel = page.getByText(/^\d+%$/);
		await expect(zoomLabel).toBeVisible();
		const before = await zoomLabel.textContent();

		await page.locator('button[title="Zoom in"]').click();
		await expect(zoomLabel).not.toHaveText(before ?? '', { timeout: 5_000 });
		const afterIn = await zoomLabel.textContent();

		await page.locator('button[title="Zoom out"]').click();
		await expect(zoomLabel).not.toHaveText(afterIn ?? '', { timeout: 5_000 });
	});
});

test.describe('Lineage – with datasource data', () => {
	test('lineage graph renders nodes when datasources exist', async ({
		page,
		request,
		sharedDatasource
	}) => {
		const aName = `E2E Lineage ${uid()}`;
		await createAnalysis(request, aName, sharedDatasource.id);
		try {
			const workerResponse = page.waitForResponse((response) =>
				/\/elk-worker\.min\.[^/]+\.js$/.test(new URL(response.url()).pathname)
			);
			await page.goto('/lineage');
			expect((await workerResponse).ok()).toBe(true);
			await waitForLineageToolbar(page);
			// The lineage graph area should not show the error state
			await expect(page.getByText('Failed to load lineage.')).not.toBeVisible();
			// The graph container should be present and not loading
			await expect(page.getByText('Loading lineage...')).not.toBeVisible({ timeout: 5_000 });
			await expect(page.getByTestId('lineage-canvas').locator('.svelte-flow')).toBeVisible();
			await expect(page.getByRole('link', { name: 'Svelte Flow attribution' })).toHaveCount(0);
			await screenshot(page, 'lineage', 'with-data');
		} finally {
			await deleteAnalysisViaUI(page, aName);
		}
	});

	test('clicking a lineage node opens node details in sidebar', async ({
		page,
		request,
		sharedDatasource
	}) => {
		const dsName = sharedDatasource.name;
		const aName = `E2E Lineage Node ${uid()}`;
		await createAnalysis(request, aName, sharedDatasource.id);
		try {
			await page.goto('/lineage');
			await waitForLineageToolbar(page);

			await expect(page.getByText('Loading lineage...')).not.toBeVisible({ timeout: 5_000 });

			const node = page.getByRole('button', { name: `source ${dsName}` });
			await expect(node).toBeVisible({ timeout: 5_000 });
			await expect(node.getByTestId('lineage-node-name')).toHaveText(dsName);
			await expect(node.getByTestId('lineage-node-kind-icon')).toHaveAttribute(
				'data-kind-icon',
				'source'
			);
			await expect(node.getByText('Source', { exact: true })).toHaveCount(0);

			const analysisNode = page.getByRole('button', { name: `analysis ${aName}` });
			await expect(analysisNode).toBeVisible({ timeout: 5_000 });
			await expect(analysisNode.getByTestId('lineage-node-name')).toHaveText(aName);
			await expect(analysisNode.getByTestId('lineage-node-kind-icon')).toHaveAttribute(
				'data-kind-icon',
				'analysis'
			);
			await expect(analysisNode.getByText('Analysis', { exact: true })).toHaveCount(0);

			const graph = page.getByTestId('lineage-canvas');
			const nodeBox = await node.boundingBox();
			const minimapBox = await graph.locator('.svelte-flow__minimap').boundingBox();
			const graphBox = await graph.boundingBox();
			if (!nodeBox || !minimapBox || !graphBox) {
				throw new Error('Expected lineage node, minimap, and canvas bounding boxes');
			}
			const centerX = nodeBox.x + nodeBox.width / 2;
			const centerY = nodeBox.y + nodeBox.height / 2;
			if (
				centerX >= minimapBox.x &&
				centerX <= minimapBox.x + minimapBox.width &&
				centerY >= minimapBox.y &&
				centerY <= minimapBox.y + minimapBox.height
			) {
				// Pan the node out from under the interactive minimap before clicking it.
				await page.mouse.move(graphBox.x + 24, graphBox.y + 24);
				await page.mouse.down();
				await page.mouse.move(graphBox.x + 24 + minimapBox.width + 32, graphBox.y + 24, {
					steps: 12
				});
				await page.mouse.up();
			}
			await node.click();

			// Sidebar should show node details instead of the default prompt
			await expect(page.getByText('Select a node', { exact: true })).not.toBeVisible({
				timeout: 3_000
			});
			// The sidebar heading contains the node label (scoped to sidebar to avoid matching the node itself)
			await expect(page.locator('aside').getByText(dsName)).toBeVisible({ timeout: 3_000 });
		} finally {
			await deleteAnalysisViaUI(page, aName);
		}
	});

	test('dragging the canvas pans visible lineage nodes', async ({
		page,
		request,
		sharedDatasource
	}) => {
		const dsName = sharedDatasource.name;
		const aName = `E2E Lineage Pan ${uid()}`;
		await createAnalysis(request, aName, sharedDatasource.id);

		try {
			await page.goto('/lineage');
			await waitForLineageToolbar(page);
			const graph = page.getByTestId('lineage-canvas');
			await expect(graph).toBeVisible({ timeout: 5_000 });

			const node = page.getByRole('button', { name: `source ${dsName}` });
			await expect(node).toBeVisible({ timeout: 5_000 });

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
		}
	});
});
