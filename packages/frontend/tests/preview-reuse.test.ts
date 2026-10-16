import { test, expect } from './fixtures.js';
import { createImportedAnalysis } from './utils/api.js';
import { gotoAnalysisEditor } from './utils/analysis.js';
import { deleteAnalysisViaUI } from './utils/ui-cleanup.js';
import { readyTimeoutMs } from './utils/readiness.js';
import { uid } from './utils/uid.js';

test.describe('Target preview reuse', () => {
	test('adding a downstream view preserves the upstream view preview', async ({
		page,
		request,
		sharedDatasource
	}) => {
		const name = `E2E Preview Reuse ${uid()}`;
		const tabId = crypto.randomUUID();
		const resultId = crypto.randomUUID();
		const datasourceRef = `source-${crypto.randomUUID()}`;
		const importedUpstreamViewId = crypto.randomUUID();
		const filterId = crypto.randomUUID();
		const previewTargetRequests: string[] = [];

		const onRequest = (incoming: import('@playwright/test').Request) => {
			if (incoming.method() !== 'POST') return;
			const url = new URL(incoming.url());
			if (!url.pathname.endsWith('/api/v1/compute/preview')) return;
			let targetStepId: string | undefined;
			try {
				targetStepId = (incoming.postDataJSON() as { target_step_id?: string }).target_step_id;
			} catch {
				return;
			}
			if (!targetStepId) return;
			previewTargetRequests.push(targetStepId);
		};
		page.on('request', onRequest);

		const createdAnalysisId = await createImportedAnalysis(
			request,
			name,
			{
				tabs: [
					{
						id: tabId,
						name: 'Source 1',
						parent_id: null,
						datasource: {
							id: datasourceRef,
							analysis_tab_id: null,
							config: { branch: 'master' }
						},
						output: {
							result_id: resultId,
							datasource_type: 'iceberg',
							format: 'parquet',
							filename: 'source_1',
							build_mode: 'full',
							iceberg: {
								namespace: 'outputs',
								table_name: 'source_1',
								branch: 'master'
							}
						},
						steps: [
							{
								id: importedUpstreamViewId,
								type: 'view',
								config: {},
								depends_on: [],
								is_applied: true
							},
							{
								id: filterId,
								type: 'filter',
								config: {
									conditions: [{ column: 'age', operator: '>', value: '25', value_type: 'number' }],
									logic: 'AND'
								},
								depends_on: [importedUpstreamViewId],
								is_applied: true
							}
						]
					}
				]
			},
			{ [datasourceRef]: sharedDatasource.id }
		);

		try {
			await gotoAnalysisEditor(page, createdAnalysisId);
			const upstreamViewId = await page
				.locator('[data-step-type="view"]')
				.first()
				.getAttribute('data-step-id');
			expect(upstreamViewId).toBeTruthy();
			if (!upstreamViewId) throw new Error('Imported upstream view was not rendered');
			const upstreamTable = page.locator(
				`[data-step-id="${upstreamViewId}"] [data-testid="inline-data-table"]`
			);
			await expect(upstreamTable).toHaveAttribute('data-preview-ready', 'true', {
				timeout: readyTimeoutMs()
			});
			await expect(upstreamTable.locator('tbody tr')).toHaveCount(3);
			await expect
				.poll(() => previewTargetRequests.filter((target) => target === upstreamViewId).length, {
					timeout: readyTimeoutMs()
				})
				.toBeGreaterThan(0);
			const initialUpstreamRequestCount = previewTargetRequests.filter(
				(target) => target === upstreamViewId
			).length;
			await upstreamTable.evaluate((element) => {
				element.setAttribute('data-preview-reuse-marker', 'mounted-before-edit');
			});

			await page.locator('button[data-step="view"]').click();
			await expect(page.locator('[data-step-type="view"]')).toHaveCount(2, { timeout: 5_000 });
			const downstreamViewId = await page
				.locator('[data-step-type="view"]')
				.last()
				.getAttribute('data-step-id');
			expect(downstreamViewId).toBeTruthy();
			const downstreamTable = page.locator(
				`[data-step-id="${downstreamViewId}"] [data-testid="inline-data-table"]`
			);
			await expect(downstreamTable).toHaveAttribute('data-preview-ready', 'true', {
				timeout: readyTimeoutMs()
			});
			await expect(downstreamTable.locator('tbody tr')).toHaveCount(2);

			expect(previewTargetRequests).toContain(downstreamViewId);
			expect(previewTargetRequests.filter((target) => target === upstreamViewId)).toHaveLength(
				initialUpstreamRequestCount
			);
			await expect(upstreamTable).toHaveAttribute(
				'data-preview-reuse-marker',
				'mounted-before-edit'
			);
			await expect(upstreamTable.locator('tbody tr')).toHaveCount(3);
		} finally {
			page.off('request', onRequest);
			await deleteAnalysisViaUI(page, name, { id: createdAnalysisId });
		}
	});
});
