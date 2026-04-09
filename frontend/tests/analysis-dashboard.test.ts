import { test, expect } from '@playwright/test';
import {
	createDatasource,
	createAnalysisWithDashboard,
	createAnalysisWithChartDashboard
} from './utils/api.js';
import { deleteAnalysisViaUI, deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { uid } from './utils/uid.js';
import { screenshot } from './utils/visual.js';
import { waitForLayoutReady } from './utils/readiness.js';
import { gotoAnalysisEditor } from './utils/analysis.js';

test.describe('Dashboard – builder mode', () => {
	test('switches to dashboard builder and shows builder UI', async ({ page, request }) => {
		test.setTimeout(60_000);
		const suffix = uid();
		const dsName = `e2e-dash-builder-ds-${suffix}`;
		const aName = `E2E Dash Builder ${suffix}`;
		const dsId = await createDatasource(request, dsName);
		const { analysisId } = await createAnalysisWithDashboard(request, aName, dsId);
		try {
			await gotoAnalysisEditor(page, analysisId);
			await page.locator('[data-testid="editor-mode-dashboards"]').click();
			await expect(page.locator('[data-testid="dashboard-builder"]')).toBeVisible({
				timeout: 10_000
			});
			await expect(page.getByRole('heading', { name: 'Variables' })).toBeVisible();
			await expect(page.getByRole('heading', { name: 'Dashboards' })).toBeVisible();
			await screenshot(page, 'analysis/dashboard', 'builder-mode');
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('adds a dashboard and widgets via builder', async ({ page, request }) => {
		test.setTimeout(60_000);
		const suffix = uid();
		const dsName = `e2e-dash-add-ds-${suffix}`;
		const aName = `E2E Dash Add ${suffix}`;
		const dsId = await createDatasource(request, dsName);
		const { analysisId } = await createAnalysisWithDashboard(request, aName, dsId);
		try {
			await gotoAnalysisEditor(page, analysisId);
			await page.locator('[data-testid="editor-mode-dashboards"]').click();
			await expect(page.locator('[data-testid="dashboard-builder"]')).toBeVisible({
				timeout: 10_000
			});

			const existingWidgets = await page.locator('[data-testid="widget-card"]').count();

			await page.locator('[data-testid="add-widget-dataset"]').click();
			await expect(page.locator('[data-testid="widget-card"]')).toHaveCount(existingWidgets + 1, {
				timeout: 5_000
			});

			const lastCard = page.locator('[data-testid="widget-card"]').last();
			await expect(lastCard).toHaveAttribute('data-widget-type', 'dataset_preview');

			await screenshot(page, 'analysis/dashboard', 'builder-add-widget');
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('add variable button creates a new variable card', async ({ page, request }) => {
		test.setTimeout(60_000);
		const suffix = uid();
		const dsName = `e2e-dash-var-ds-${suffix}`;
		const aName = `E2E Dash Var ${suffix}`;
		const dsId = await createDatasource(request, dsName);
		const { analysisId } = await createAnalysisWithDashboard(request, aName, dsId);
		try {
			await gotoAnalysisEditor(page, analysisId);
			await page.locator('[data-testid="editor-mode-dashboards"]').click();
			await expect(page.locator('[data-testid="dashboard-builder"]')).toBeVisible({
				timeout: 10_000
			});

			await page.locator('[data-testid="add-variable"]').click();
			const variableSection = page
				.locator('[data-testid="dashboard-builder"] section')
				.filter({ hasText: 'Variables' });
			const labelInput = variableSection.locator('input').first();
			await expect(labelInput).toHaveValue('Variable 1', { timeout: 5_000 });

			await screenshot(page, 'analysis/dashboard', 'builder-add-variable');
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('resize gesture updates widget dimensions', async ({ page, request }) => {
		test.setTimeout(60_000);
		const suffix = uid();
		const dsName = `e2e-dash-resize-ds-${suffix}`;
		const aName = `E2E Dash Resize ${suffix}`;
		const dsId = await createDatasource(request, dsName);
		const { analysisId } = await createAnalysisWithDashboard(request, aName, dsId);
		try {
			await gotoAnalysisEditor(page, analysisId);
			await page.locator('[data-testid="editor-mode-dashboards"]').click();
			await expect(page.locator('[data-testid="dashboard-builder"]')).toBeVisible({
				timeout: 10_000
			});

			const moveHandle = page.getByRole('button', { name: /^Move Dataset Preview$/ });
			await expect(moveHandle).toBeVisible({ timeout: 5_000 });

			await expect(moveHandle).toContainText('12x3');

			const resizeHandle = page.getByRole('button', { name: /^Resize Dataset Preview$/ });
			await expect(resizeHandle).toBeVisible();
			const box = await resizeHandle.boundingBox();
			expect(box).toBeTruthy();

			const cx = box!.x + box!.width / 2;
			const cy = box!.y + box!.height / 2;

			await page.mouse.move(cx, cy);
			await page.mouse.down();
			const steps = 5;
			for (let step = 1; step <= steps; step++) {
				await page.mouse.move(cx, cy + (72 * step) / steps, { steps: 1 });
			}
			await page.mouse.up();

			await expect(moveHandle).not.toContainText('12x3', { timeout: 5_000 });

			await screenshot(page, 'analysis/dashboard', 'builder-resize');
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});
});

test.describe('Dashboard – runtime', () => {
	test('loads runtime page with dashboard title and widgets', async ({ page, request }) => {
		test.setTimeout(90_000);
		const suffix = uid();
		const dsName = `e2e-dash-runtime-ds-${suffix}`;
		const aName = `E2E Dash Runtime ${suffix}`;
		const dsId = await createDatasource(request, dsName);
		const { analysisId, dashboardId } = await createAnalysisWithDashboard(request, aName, dsId);
		try {
			await page.goto(`/analysis/${analysisId}/dashboards/${dashboardId}`);
			await waitForLayoutReady(page);

			await expect(page.locator('[data-testid="dashboard-runtime"]')).toBeVisible({
				timeout: 15_000
			});
			await expect(page.getByRole('heading', { name: 'Test Dashboard' })).toBeVisible({
				timeout: 15_000
			});

			await expect(page.getByRole('button', { name: 'Refresh' })).toBeVisible();

			const widgets = page.locator('[data-testid="runtime-widget"]');
			await expect(widgets).toHaveCount(3, { timeout: 20_000 });

			await screenshot(page, 'analysis/dashboard', 'runtime-loaded');
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('dataset widget renders data table after refresh', async ({ page, request }) => {
		test.setTimeout(90_000);
		const suffix = uid();
		const dsName = `e2e-dash-dataset-ds-${suffix}`;
		const aName = `E2E Dash Dataset ${suffix}`;
		const dsId = await createDatasource(request, dsName);
		const { analysisId, dashboardId } = await createAnalysisWithDashboard(request, aName, dsId);
		try {
			await page.goto(`/analysis/${analysisId}/dashboards/${dashboardId}`);
			await waitForLayoutReady(page);
			await expect(page.locator('[data-testid="dashboard-runtime"]')).toBeVisible({
				timeout: 15_000
			});

			const datasetWidget = page.locator(
				'[data-testid="runtime-widget"][data-widget-type="dataset_preview"]'
			);
			await expect(datasetWidget).toBeVisible({ timeout: 20_000 });

			const table = datasetWidget.locator('table');
			await expect(table).toBeVisible({ timeout: 20_000 });

			const headerCells = table.locator('thead th');
			await expect(headerCells.first()).toBeVisible({ timeout: 10_000 });

			await screenshot(page, 'analysis/dashboard', 'runtime-dataset');
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('dataset search filters visible rows', async ({ page, request }) => {
		test.setTimeout(90_000);
		const suffix = uid();
		const dsName = `e2e-dash-search-ds-${suffix}`;
		const aName = `E2E Dash Search ${suffix}`;
		const dsId = await createDatasource(request, dsName);
		const { analysisId, dashboardId } = await createAnalysisWithDashboard(request, aName, dsId);
		try {
			await page.goto(`/analysis/${analysisId}/dashboards/${dashboardId}`);
			await waitForLayoutReady(page);

			const datasetWidget = page.locator(
				'[data-testid="runtime-widget"][data-widget-type="dataset_preview"]'
			);
			await expect(datasetWidget).toBeVisible({ timeout: 20_000 });

			const table = datasetWidget.locator('table');
			await expect(table).toBeVisible({ timeout: 20_000 });

			const searchInput = datasetWidget.getByPlaceholder('Search current page');
			await expect(searchInput).toBeVisible({ timeout: 10_000 });

			const rowsBefore = await table.locator('tbody tr').count();
			expect(rowsBefore).toBeGreaterThan(0);

			await searchInput.fill('Alice');
			await expect(table.locator('tbody tr').first()).toContainText(/alice/i, { timeout: 5_000 });

			const rowsAfter = await table.locator('tbody tr').count();
			expect(rowsAfter).toBeLessThanOrEqual(rowsBefore);
			expect(rowsAfter).toBeGreaterThan(0);

			await searchInput.fill('ZZZNOMATCH');
			await expect(table.locator('tbody tr')).toHaveCount(0, { timeout: 5_000 });

			await screenshot(page, 'analysis/dashboard', 'runtime-search');
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('metric widget displays a computed value', async ({ page, request }) => {
		test.setTimeout(90_000);
		const suffix = uid();
		const dsName = `e2e-dash-metric-ds-${suffix}`;
		const aName = `E2E Dash Metric ${suffix}`;
		const dsId = await createDatasource(request, dsName);
		const { analysisId, dashboardId } = await createAnalysisWithDashboard(request, aName, dsId);
		try {
			await page.goto(`/analysis/${analysisId}/dashboards/${dashboardId}`);
			await waitForLayoutReady(page);

			const metricWidget = page.locator(
				'[data-testid="runtime-widget"][data-widget-type="metric_kpi"]'
			);
			await expect(metricWidget).toBeVisible({ timeout: 20_000 });

			await expect(metricWidget.getByText('Total Rows')).toBeVisible({ timeout: 15_000 });

			const value = metricWidget.locator('strong');
			await expect(value).toBeVisible({ timeout: 15_000 });
			const valueText = await value.textContent();
			expect(valueText).toBeTruthy();
			expect(Number(valueText)).toBeGreaterThan(0);

			await screenshot(page, 'analysis/dashboard', 'runtime-metric');
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('header widget renders heading text', async ({ page, request }) => {
		test.setTimeout(90_000);
		const suffix = uid();
		const dsName = `e2e-dash-header-ds-${suffix}`;
		const aName = `E2E Dash Header ${suffix}`;
		const dsId = await createDatasource(request, dsName);
		const { analysisId, dashboardId } = await createAnalysisWithDashboard(request, aName, dsId);
		try {
			await page.goto(`/analysis/${analysisId}/dashboards/${dashboardId}`);
			await waitForLayoutReady(page);

			const headerWidget = page.locator(
				'[data-testid="runtime-widget"][data-widget-type="text_header"]'
			);
			await expect(headerWidget).toBeVisible({ timeout: 20_000 });

			await expect(headerWidget.getByRole('heading', { name: 'Summary' })).toBeVisible({
				timeout: 15_000
			});

			await screenshot(page, 'analysis/dashboard', 'runtime-header');
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('refresh button re-fetches widget data', async ({ page, request }) => {
		test.setTimeout(90_000);
		const suffix = uid();
		const dsName = `e2e-dash-refresh-ds-${suffix}`;
		const aName = `E2E Dash Refresh ${suffix}`;
		const dsId = await createDatasource(request, dsName);
		const { analysisId, dashboardId } = await createAnalysisWithDashboard(request, aName, dsId);
		try {
			await page.goto(`/analysis/${analysisId}/dashboards/${dashboardId}`);
			await waitForLayoutReady(page);

			const datasetWidget = page.locator(
				'[data-testid="runtime-widget"][data-widget-type="dataset_preview"]'
			);
			await expect(datasetWidget.locator('table')).toBeVisible({ timeout: 20_000 });

			const refreshBtn = page.getByRole('button', { name: 'Refresh' });
			const responsePromise = page.waitForResponse(
				(resp) => resp.url().includes('/run') && resp.status() === 200
			);
			await refreshBtn.click();
			await responsePromise;

			await expect(datasetWidget.locator('table')).toBeVisible({ timeout: 10_000 });

			await screenshot(page, 'analysis/dashboard', 'runtime-after-refresh');
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('chart selection filters sibling dataset widget', async ({ page, request }) => {
		test.setTimeout(120_000);
		const suffix = uid();
		const dsName = `e2e-dash-chartsel-ds-${suffix}`;
		const aName = `E2E Dash ChartSel ${suffix}`;
		const dsId = await createDatasource(request, dsName);
		const { analysisId, dashboardId } = await createAnalysisWithChartDashboard(
			request,
			aName,
			dsId
		);
		try {
			await page.goto(`/analysis/${analysisId}/dashboards/${dashboardId}`);
			await waitForLayoutReady(page);
			await expect(page.locator('[data-testid="dashboard-runtime"]')).toBeVisible({
				timeout: 15_000
			});

			const chartWidget = page.locator('[data-testid="runtime-widget"][data-widget-type="chart"]');
			await expect(chartWidget).toBeVisible({ timeout: 20_000 });

			const datasetWidget = page.locator(
				'[data-testid="runtime-widget"][data-widget-type="dataset_preview"]'
			);
			const table = datasetWidget.locator('table');
			await expect(table).toBeVisible({ timeout: 20_000 });

			const rowsBefore = await table.locator('tbody tr').count();
			expect(rowsBefore).toBeGreaterThan(0);

			// Targets a chart bar via its aria-label (city name from test fixture data)
			const bar = chartWidget.getByRole('button', { name: 'London' });
			await expect(bar).toBeVisible({ timeout: 15_000 });

			const runResponsePromise = page.waitForResponse(
				(resp) => resp.url().includes('/run') && resp.status() === 200
			);
			await bar.click();

			const filterBar = page.locator('[data-testid="selection-filter-bar"]');
			await expect(filterBar).toBeVisible({ timeout: 10_000 });
			await expect(filterBar).toContainText('London', { timeout: 5_000 });

			await runResponsePromise;

			await expect(async () => {
				const rowsAfter = await table.locator('tbody tr').count();
				expect(rowsAfter).toBeLessThan(rowsBefore);
				expect(rowsAfter).toBeGreaterThan(0);
			}).toPass({ timeout: 10_000 });

			const clearBtn = page.getByRole('button', { name: 'Clear all' });
			await expect(clearBtn).toBeVisible({ timeout: 5_000 });

			const clearRunResponse = page.waitForResponse(
				(resp) => resp.url().includes('/run') && resp.status() === 200
			);
			await clearBtn.click();
			await clearRunResponse;

			await expect(filterBar).not.toBeVisible({ timeout: 10_000 });

			await expect(async () => {
				const rowsRestored = await table.locator('tbody tr').count();
				expect(rowsRestored).toBe(rowsBefore);
			}).toPass({ timeout: 10_000 });

			await screenshot(page, 'analysis/dashboard', 'runtime-chart-selection');
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});
});
