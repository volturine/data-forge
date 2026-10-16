import { test, expect } from './fixtures.js';
import { createImportedAnalysis } from './utils/api.js';
import { gotoAnalysisEditor, waitForEditorReload } from './utils/analysis.js';
import { deleteAnalysisViaUI } from './utils/ui-cleanup.js';
import { readyTimeoutMs } from './utils/readiness.js';
import { uid } from './utils/uid.js';

test.describe('Target preview reuse', () => {
	test('adding a downstream view preserves the upstream view preview', async ({
		page,
		request,
		sharedDatasource
	}, testInfo) => {
		const name = `E2E Preview Reuse ${uid()}`;
		const tabId = crypto.randomUUID();
		const resultId = crypto.randomUUID();
		const datasourceRef = `source-${crypto.randomUUID()}`;
		const importedUpstreamViewId = crypto.randomUUID();
		const filterId = crypto.randomUUID();
		const previewTargetRequests: Array<{ targetStepId: string; cacheEnabled?: boolean }> = [];

		const onRequest = (incoming: import('@playwright/test').Request) => {
			if (incoming.method() !== 'POST') return;
			const url = new URL(incoming.url());
			if (!url.pathname.endsWith('/api/v1/compute/preview')) return;
			let body: {
				target_step_id?: string;
				analysis_pipeline?: {
					tabs?: Array<{ steps?: Array<{ id: string; config?: Record<string, unknown> }> }>;
				};
			};
			try {
				body = incoming.postDataJSON() as typeof body;
			} catch {
				return;
			}
			const targetStepId = body.target_step_id;
			if (!targetStepId) return;
			const targetStep = body.analysis_pipeline?.tabs
				?.flatMap((tab) => tab.steps ?? [])
				.find((step) => step.id === targetStepId);
			const cacheEnabled = targetStep?.config?.cacheEnabled;
			previewTargetRequests.push({
				targetStepId,
				...(typeof cacheEnabled === 'boolean' ? { cacheEnabled } : {})
			});
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
				.poll(
					() =>
						previewTargetRequests.filter((request) => request.targetStepId === upstreamViewId)
							.length,
					{ timeout: readyTimeoutMs() }
				)
				.toBeGreaterThan(0);
			const initialUpstreamRequestCount = previewTargetRequests.filter(
				(request) => request.targetStepId === upstreamViewId
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
			if (!downstreamViewId) throw new Error('New downstream view was not rendered');
			const downstreamTable = page.locator(
				`[data-step-id="${downstreamViewId}"] [data-testid="inline-data-table"]`
			);
			await expect(downstreamTable).toHaveAttribute('data-preview-ready', 'true', {
				timeout: readyTimeoutMs()
			});
			await expect(downstreamTable.locator('tbody tr')).toHaveCount(2);
			const downstreamNode = page.locator(`[data-step-id="${downstreamViewId}"]`);
			await downstreamNode.locator('[data-action="edit"]').click();
			const configPanel = page.locator('[data-step-config="view"]');
			await expect(configPanel).toBeVisible();
			const cacheCheckbox = configPanel.getByTestId('view-cache-enabled-checkbox');
			await expect(cacheCheckbox).toBeChecked();
			await configPanel.screenshot({
				path: testInfo.outputPath('preview-cache-enabled.png')
			});
			const downstreamRequestCount = () =>
				previewTargetRequests.filter((request) => request.targetStepId === downstreamViewId).length;
			const initialDownstreamRequestCount = downstreamRequestCount();
			expect(
				previewTargetRequests.filter((request) => request.targetStepId === downstreamViewId).at(-1)
					?.cacheEnabled
			).toBe(true);

			await cacheCheckbox.uncheck();
			const applyButton = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyButton).toBeEnabled();
			await applyButton.click();
			await expect(applyButton).toBeDisabled({ timeout: 5_000 });
			await expect
				.poll(downstreamRequestCount, { timeout: readyTimeoutMs() })
				.toBeGreaterThan(initialDownstreamRequestCount);
			await expect(downstreamTable).toHaveAttribute('data-preview-ready', 'true', {
				timeout: readyTimeoutMs()
			});
			expect(
				previewTargetRequests.filter((request) => request.targetStepId === downstreamViewId).at(-1)
					?.cacheEnabled
			).toBe(false);
			await expect(downstreamTable.locator('tbody tr')).toHaveCount(2);
			await configPanel.screenshot({
				path: testInfo.outputPath('preview-cache-disabled.png')
			});

			const firstOffRequestCount = downstreamRequestCount();
			await cacheCheckbox.check();
			await expect(applyButton).toBeEnabled();
			await applyButton.click();
			await expect(applyButton).toBeDisabled({ timeout: 5_000 });
			await expect
				.poll(downstreamRequestCount, { timeout: readyTimeoutMs() })
				.toBeGreaterThan(firstOffRequestCount);
			await expect(downstreamTable).toHaveAttribute('data-preview-ready', 'true', {
				timeout: readyTimeoutMs()
			});
			expect(
				previewTargetRequests.filter((request) => request.targetStepId === downstreamViewId).at(-1)
					?.cacheEnabled
			).toBe(true);
			await expect(downstreamTable.locator('tbody tr')).toHaveCount(2);

			const firstOnRequestCount = downstreamRequestCount();
			await cacheCheckbox.uncheck();
			await expect(applyButton).toBeEnabled();
			await applyButton.click();
			await expect(applyButton).toBeDisabled({ timeout: 5_000 });
			await expect
				.poll(downstreamRequestCount, { timeout: readyTimeoutMs() })
				.toBeGreaterThan(firstOnRequestCount);
			await expect(downstreamTable).toHaveAttribute('data-preview-ready', 'true', {
				timeout: readyTimeoutMs()
			});
			expect(
				previewTargetRequests.filter((request) => request.targetStepId === downstreamViewId).at(-1)
					?.cacheEnabled
			).toBe(false);
			await expect(downstreamTable.locator('tbody tr')).toHaveCount(2);

			expect(previewTargetRequests.map((request) => request.targetStepId)).toContain(
				downstreamViewId
			);
			expect(
				previewTargetRequests.filter((request) => request.targetStepId === upstreamViewId)
			).toHaveLength(initialUpstreamRequestCount);
			await expect(upstreamTable).toHaveAttribute(
				'data-preview-reuse-marker',
				'mounted-before-edit'
			);
			await expect(upstreamTable.locator('tbody tr')).toHaveCount(3);

			await page.getByRole('button', { name: 'Save' }).click();
			await expect(page.getByRole('button', { name: 'Saved' })).toBeVisible({ timeout: 15_000 });
			await page.reload();
			await waitForEditorReload(page);
			await expect(upstreamTable).toHaveAttribute('data-preview-ready', 'true', {
				timeout: readyTimeoutMs()
			});
			await expect(downstreamTable).toHaveAttribute('data-preview-ready', 'true', {
				timeout: readyTimeoutMs()
			});
			await expect(downstreamTable.locator('tbody tr')).toHaveCount(2);
			await downstreamNode.locator('[data-action="edit"]').click();
			await expect(configPanel).toBeVisible();
			await expect(cacheCheckbox).not.toBeChecked();
			const postReloadDownstreamRequestCount = downstreamRequestCount();
			const postReloadUpstreamRequestCount = previewTargetRequests.filter(
				(request) => request.targetStepId === upstreamViewId
			).length;
			await upstreamTable.evaluate((element) => {
				element.setAttribute('data-preview-reuse-marker', 'mounted-after-reload');
			});

			await cacheCheckbox.check();
			await expect(applyButton).toBeEnabled();
			await applyButton.click();
			await expect(applyButton).toBeDisabled({ timeout: 5_000 });
			await expect
				.poll(downstreamRequestCount, { timeout: readyTimeoutMs() })
				.toBeGreaterThan(postReloadDownstreamRequestCount);
			await expect(downstreamTable).toHaveAttribute('data-preview-ready', 'true', {
				timeout: readyTimeoutMs()
			});
			expect(
				previewTargetRequests.filter((request) => request.targetStepId === downstreamViewId).at(-1)
					?.cacheEnabled
			).toBe(true);
			await expect(downstreamTable.locator('tbody tr')).toHaveCount(2);
			expect(
				previewTargetRequests.filter((request) => request.targetStepId === upstreamViewId)
			).toHaveLength(postReloadUpstreamRequestCount);
			await expect(upstreamTable).toHaveAttribute(
				'data-preview-reuse-marker',
				'mounted-after-reload'
			);
			await expect(upstreamTable.locator('tbody tr')).toHaveCount(3);

			await page.getByRole('button', { name: 'Save' }).click();
			await expect(page.getByRole('button', { name: 'Saved' })).toBeVisible({ timeout: 15_000 });
		} finally {
			page.off('request', onRequest);
			await deleteAnalysisViaUI(page, name, { id: createdAnalysisId });
		}
	});
});
