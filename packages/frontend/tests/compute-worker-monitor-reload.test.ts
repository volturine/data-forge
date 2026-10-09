import { test, expect } from './fixtures.js';
import { createAnalysis, createCsvDatasource } from './utils/api.js';
import { gotoAnalysisEditor } from './utils/analysis.js';
import {
	closeComputeWorkersPopup,
	deleteAnalysisViaUI,
	deleteDatasourceViaUI,
	openComputeWorkersPopup
} from './utils/ui-cleanup.js';
import { waitForInlinePreviewReady, waitForLayoutReady } from './utils/readiness.js';
import { switchNamespace } from './utils/namespace.js';
import { uid } from './utils/uid.js';

test('the compute worker monitor keeps its snapshot after an analysis page reload', async ({
	page,
	request
}) => {
	const suffix = uid();
	const namespace = `e2e-compute-worker-reload-${suffix}`;
	const datasourceName = `E2E Compute Worker Reload Source ${suffix}`;
	const analysisName = `E2E Compute Worker Reload ${suffix}`;
	let datasourceId: string | null = null;
	let analysisId: string | null = null;

	try {
		datasourceId = await createCsvDatasource(
			request,
			datasourceName,
			'id,name\n1,Alice\n2,Bob\n',
			namespace
		);
		analysisId = await createAnalysis(request, analysisName, datasourceId, namespace);
		await page.goto('/', { waitUntil: 'domcontentloaded' });
		await waitForLayoutReady(page);
		await switchNamespace(page, namespace);
		await gotoAnalysisEditor(page, analysisId);
		await waitForInlinePreviewReady(page);

		const popupBefore = await openComputeWorkersPopup(page);
		const rowsBefore = await popupBefore.locator('[data-compute-worker-row]').evaluateAll((rows) =>
			rows
				.map((row) => row.getAttribute('data-compute-worker-row'))
				.filter(Boolean)
				.sort()
		);
		const badgeBefore = page.getByTestId('compute-worker-monitor-count');
		const countBefore = Number(await badgeBefore.textContent());

		expect(countBefore).toBeGreaterThan(0);
		expect(countBefore).toBe(rowsBefore.length);
		expect(rowsBefore).toContain(`analysis_interactive:${analysisId}`);
		await closeComputeWorkersPopup(page);

		await page.getByRole('link', { name: 'Analyses', exact: true }).click();
		await expect(page).toHaveURL('/');
		await waitForLayoutReady(page);
		await expect(page.getByRole('heading', { name: 'Analyses', exact: true })).toBeVisible();

		await page.reload();
		await waitForLayoutReady(page);
		await expect(page.getByRole('heading', { name: 'Analyses', exact: true })).toBeVisible();

		const badgeAfter = page.getByTestId('compute-worker-monitor-count');
		await expect(badgeAfter).toHaveText(String(countBefore));

		const popupAfter = await openComputeWorkersPopup(page);
		const rowsAfter = await popupAfter.locator('[data-compute-worker-row]').evaluateAll((rows) =>
			rows
				.map((row) => row.getAttribute('data-compute-worker-row'))
				.filter(Boolean)
				.sort()
		);

		expect(rowsAfter).toEqual(rowsBefore);
	} finally {
		await closeComputeWorkersPopup(page).catch(() => undefined);
		if (analysisId) {
			await deleteAnalysisViaUI(page, analysisName, { id: analysisId, namespace });
		}
		if (datasourceId) {
			await deleteDatasourceViaUI(page, datasourceName, { id: datasourceId, namespace });
		}
	}
});
