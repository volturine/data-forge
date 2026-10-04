import type { Request } from '@playwright/test';
import { test, expect } from './fixtures.js';
import { createAnalysisWithTabs, type E2ERequest } from './utils/api.js';
import { gotoAnalysesGallery, readyTimeoutMs } from './utils/readiness.js';
import { waitForCurrentAnalysisEditor } from './utils/analysis.js';
import { deleteAnalysisViaUI } from './utils/ui-cleanup.js';
import { uid } from './utils/uid.js';

async function createPreviewAnalysis(request: E2ERequest, name: string, datasourceId: string) {
	const view = {
		id: crypto.randomUUID(),
		type: 'view',
		config: { rowLimit: 2 },
		depends_on: [],
		is_applied: true
	};
	const chart = {
		id: crypto.randomUUID(),
		type: 'chart',
		config: { chart_type: 'bar', x_column: 'city', y_column: 'value', aggregation: 'sum' },
		depends_on: [view.id],
		is_applied: true
	};
	const disabledView = {
		...view,
		id: crypto.randomUUID(),
		depends_on: [chart.id],
		is_applied: false
	};
	const disabledChart = {
		...chart,
		id: crypto.randomUUID(),
		depends_on: [chart.id],
		is_applied: false
	};
	const unconfiguredChart = {
		...chart,
		id: crypto.randomUUID(),
		config: { chart_type: 'bar', x_column: '' },
		depends_on: [chart.id]
	};
	const otherView = { ...view, id: crypto.randomUUID() };
	const tabs = [
		{
			id: crypto.randomUUID(),
			name: 'Active previews',
			steps: [view, chart, disabledView, disabledChart, unconfiguredChart]
		},
		{ id: crypto.randomUUID(), name: 'Other tab', steps: [otherView] }
	].map((tab) => {
		const outputId = crypto.randomUUID();
		return {
			...tab,
			parent_id: null,
			datasource: { id: datasourceId, analysis_tab_id: null, config: { branch: 'master' } },
			output: {
				result_id: outputId,
				format: 'parquet',
				filename: 'audit',
				build_mode: 'full',
				iceberg: {
					namespace: 'outputs',
					table_name: `audit_${outputId.replaceAll('-', '_')}`,
					branch: 'master'
				}
			}
		};
	});
	const id = await createAnalysisWithTabs(request, name, tabs);
	return { id, name, tabs, view, chart, otherView };
}

type NetworkCall = {
	phase: string;
	method: string;
	path: string;
	body: Record<string, unknown> | null;
	status: number | null;
	failure: string | null;
};

test('analysis navigation only computes active previews and reuses completed commands', async ({
	page,
	request,
	sharedChartDatasource
}, testInfo) => {
	testInfo.setTimeout(180_000);
	const suffix = uid();
	const first = await createPreviewAnalysis(
		request,
		`Network First ${suffix}`,
		sharedChartDatasource.id
	);
	const second = await createPreviewAnalysis(
		request,
		`Network Second ${suffix}`,
		sharedChartDatasource.id
	);
	const calls: NetworkCall[] = [];
	const byRequest = new Map<Request, NetworkCall>();
	let phase = 'gallery';
	page.on('request', (networkRequest) => {
		const path = new URL(networkRequest.url()).pathname;
		if (!path.startsWith('/api/') || path === '/api/v1/logs/client') return;
		const call: NetworkCall = {
			phase,
			method: networkRequest.method(),
			path,
			body: networkRequest.postDataJSON(),
			status: null,
			failure: null
		};
		calls.push(call);
		byRequest.set(networkRequest, call);
	});
	page.on('response', (response) => {
		const call = byRequest.get(response.request());
		if (call) call.status = response.status();
	});
	page.on('requestfailed', (networkRequest) => {
		const call = byRequest.get(networkRequest);
		if (call) call.failure = networkRequest.failure()?.errorText ?? 'failed';
	});
	const previews = () => calls.filter((call) => call.path === '/api/v1/compute/preview');

	async function settle() {
		await expect
			.poll(() => calls.filter((call) => call.status === null && call.failure === null).length, {
				timeout: readyTimeoutMs()
			})
			.toBe(0);
		await page.evaluate(
			() =>
				new Promise<void>((resolve) =>
					requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
				)
		);
	}

	async function openAnalysis(analysis: typeof first, nextPhase: string) {
		phase = nextPhase;
		await page
			.getByRole('group', { name: 'Favorite analyses' })
			.getByRole('link', { name: analysis.name, exact: true })
			.click();
		await expect(page).toHaveURL(`/analysis/${analysis.id}`, { timeout: readyTimeoutMs() });
		expect(await waitForCurrentAnalysisEditor(page)).toBe(analysis.id);
		await expect(
			page.locator(`[data-step-id="${analysis.view.id}"] [data-preview-ready="true"]`)
		).toBeVisible({ timeout: readyTimeoutMs() });
		await expect(
			page.locator(`[data-step-id="${analysis.chart.id}"] [data-preview-ready="true"]`)
		).toBeVisible({ timeout: readyTimeoutMs() });
		await settle();
	}

	try {
		await gotoAnalysesGallery(page);
		const expand = page.getByRole('button', { name: 'Expand sidebar' });
		if (await expand.isVisible()) await expand.click();
		for (const analysis of [first, second]) {
			const card = page.locator(`[data-analysis-card="${analysis.name}"]`);
			const prefetched = page.waitForResponse(
				(response) =>
					new URL(response.url()).pathname === `/api/v1/analysis/${analysis.id}` &&
					response.request().method() === 'GET'
			);
			await card.hover();
			expect((await prefetched).status()).toBe(200);
			const favorite = page.waitForResponse(
				(response) =>
					new URL(response.url()).pathname === `/api/v1/analysis/${analysis.id}/favorite`
			);
			await card.getByRole('button', { name: 'Add analysis to favorites' }).click();
			expect((await favorite).status()).toBe(200);
		}
		await settle();
		await openAnalysis(first, 'first-open');
		expect(
			previews()
				.map((call) => call.body?.target_step_id)
				.sort()
		).toEqual([first.view.id, first.chart.id].sort());
		await openAnalysis(second, 'second-open');
		expect(
			previews()
				.filter((call) => call.phase === 'second-open')
				.map((call) => call.body?.target_step_id)
				.sort()
		).toEqual([second.view.id, second.chart.id].sort());
		await openAnalysis(first, 'cached-return');
		expect(previews().filter((call) => call.phase === 'cached-return')).toEqual([]);

		phase = 'other-tab';
		await page.getByTestId(`tab-button-${first.tabs[1].id}`).click();
		await expect(
			page.locator(`[data-step-id="${first.otherView.id}"] [data-preview-ready="true"]`)
		).toBeVisible({ timeout: readyTimeoutMs() });
		await settle();
		expect(
			previews()
				.filter((call) => call.phase === 'other-tab')
				.map((call) => call.body?.target_step_id)
		).toEqual([first.otherView.id]);
		phase = 'cached-tab';
		await page.getByTestId(`tab-button-${first.tabs[0].id}`).click();
		await expect(
			page.locator(`[data-step-id="${first.view.id}"] [data-preview-ready="true"]`)
		).toBeVisible({ timeout: readyTimeoutMs() });
		await settle();
		expect(previews().filter((call) => call.phase === 'cached-tab')).toEqual([]);

		phase = 'next-page';
		const table = page.locator(`[data-step-id="${first.view.id}"]`);
		await table.getByRole('button', { name: 'Next', exact: true }).click();
		await expect(table.getByText('Page 2', { exact: true })).toBeVisible();
		await expect(table.locator('[data-preview-ready="true"]')).toBeVisible({
			timeout: readyTimeoutMs()
		});
		await settle();
		expect(
			previews()
				.filter((call) => call.phase === 'next-page')
				.map((call) => [call.body?.target_step_id, call.body?.page])
		).toEqual([[first.view.id, 2]]);
		phase = 'previous-page';
		await table.getByRole('button', { name: 'Prev', exact: true }).click();
		await expect(table.getByText('Page 1', { exact: true })).toBeVisible();
		await settle();
		expect(previews().filter((call) => call.phase === 'previous-page')).toEqual([]);

		for (const call of previews()) {
			const analysis = call.body?.analysis_id === first.id ? first : second;
			expect(call.body?.analysis_id).toBe(analysis.id);
			expect((call.body?.analysis_pipeline as { analysis_id: string }).analysis_id).toBe(
				analysis.id
			);
			const tab = analysis.tabs.find((candidate) => candidate.id === call.body?.tab_id);
			expect(
				tab?.steps.some((step) => step.id === call.body?.target_step_id && step.is_applied)
			).toBe(true);
		}
		expect(new Set(previews().map((call) => JSON.stringify(call.body))).size).toBe(
			previews().length
		);
		expect(
			calls.filter((call) => call.failure || (call.status !== null && call.status >= 400))
		).toEqual([]);
		expect(calls.filter((call) => call.path === '/api/v1/compute/defaults')).toHaveLength(1);
		expect(
			calls.filter((call) => call.path === `/api/v1/datasource/${sharedChartDatasource.id}`)
		).toEqual([]);
		expect(
			calls.filter(
				(call) =>
					call.path === '/api/v1/compute/row-count' || call.path === '/api/v1/compute/schema'
			)
		).toEqual([]);
	} finally {
		await testInfo.attach('analysis-navigation-network.json', {
			body: JSON.stringify(calls, null, 2),
			contentType: 'application/json'
		});
		await deleteAnalysisViaUI(page, first.name, { id: first.id }).catch(() => undefined);
		await deleteAnalysisViaUI(page, second.name, { id: second.id }).catch(() => undefined);
	}
});
