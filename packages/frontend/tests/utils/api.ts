import type { APIRequestContext, Browser, Page } from '@playwright/test';
import { expect } from '@playwright/test';
import {
	createHealthCheckViaUi,
	createScheduleViaUi,
	createUdfViaUi,
	importAnalysisViaUi,
	shutdownEngineViaUi,
	uploadDatasourceViaUi,
	uploadDatasourceWithDatesViaUi,
	E2E_PASSWORD
} from './user-flows.js';
import { deleteDatasourceViaUI } from './ui-cleanup.js';
import { waitForLayoutReady } from './readiness.js';
import { switchNamespace } from './namespace.js';

export const E2E_RUN_STAMP =
	process.env.E2E_RUN_STAMP || `${Date.now().toString(36)}-${process.pid}`;

export { E2E_PASSWORD };

/** Playwright storage state held in memory for the worker lifetime. */
export type E2EStorageState = {
	cookies: Array<{
		name: string;
		value: string;
		domain: string;
		path: string;
		expires: number;
		httpOnly: boolean;
		secure: boolean;
		sameSite: 'Strict' | 'Lax' | 'None';
	}>;
	origins: Array<{
		origin: string;
		localStorage: Array<{ name: string; value: string }>;
	}>;
};

export interface WorkerAuth {
	workerIndex: number;
	sessionState: E2EStorageState;
}

export interface E2ERequest extends APIRequestContext {
	browser: Browser;
	/**
	 * In-memory Playwright storage state for newContext().
	 * Named sessionState (not storageState) to avoid clashing with
	 * APIRequestContext.storageState().
	 */
	sessionState: E2EStorageState;
	workerIndex: number;
	baseURL: string;
}

const datasourceRegistry = new Map<string, { name: string; namespace?: string }>();
const analysisRegistry = new Map<string, { name: string }>();
const udfRegistry = new Map<string, { name: string }>();

async function withAuthedPage<T>(request: E2ERequest, fn: (page: Page) => Promise<T>): Promise<T> {
	const context = await request.browser.newContext({
		baseURL: request.baseURL,
		// Clone so Playwright cannot mutate the worker-owned session snapshot.
		storageState: structuredClone(request.sessionState)
	});
	const page = await context.newPage();
	try {
		return await fn(page);
	} finally {
		await page.close().catch(() => undefined);
		await context.close().catch(() => undefined);
	}
}

function buildOutput(filename: string) {
	return {
		result_id: crypto.randomUUID(),
		datasource_type: 'iceberg',
		format: 'parquet',
		filename,
		build_mode: 'full',
		iceberg: {
			namespace: 'outputs',
			table_name: filename,
			branch: 'master'
		}
	};
}

export async function createDatasource(
	request: E2ERequest,
	name: string,
	namespace?: string,
	description?: string
): Promise<string> {
	return withAuthedPage(request, async (page) => {
		if (namespace) {
			await page.goto('/');
			await waitForLayoutReady(page);
			await switchNamespace(page, namespace);
		}
		const { id } = await uploadDatasourceViaUi(page, name, { description });
		datasourceRegistry.set(id, { name, namespace });
		return id;
	});
}

export async function createLargeDatasource(
	request: E2ERequest,
	name: string,
	rows: number
): Promise<string> {
	return withAuthedPage(request, async (page) => {
		const { id } = await uploadDatasourceViaUi(page, name, { rows });
		datasourceRegistry.set(id, { name });
		return id;
	});
}

export async function createDatasourceWithDates(
	request: E2ERequest,
	name: string
): Promise<string> {
	return withAuthedPage(request, async (page) => {
		const { id } = await uploadDatasourceWithDatesViaUi(page, name);
		datasourceRegistry.set(id, { name });
		return id;
	});
}

export async function deleteDatasource(
	request: E2ERequest,
	id: string,
	namespace?: string
): Promise<void> {
	const entry = datasourceRegistry.get(id);
	if (!entry) return;
	await withAuthedPage(request, async (page) => {
		if (namespace) {
			await page.goto('/');
			await waitForLayoutReady(page);
			await switchNamespace(page, namespace);
		}
		await deleteDatasourceViaUI(page, entry.name);
	});
}

export async function deleteAnalysisByApi(page: Page, analysisId: string): Promise<number> {
	const endpoint = `/api/v1/analysis/${analysisId}`;
	const current = await page.request.get(endpoint, { timeout: 5_000 });
	if (current.status() === 404) return 404;
	if (!current.ok()) throw new Error(`Cleanup GET ${endpoint} returned HTTP ${current.status()}`);
	const revision = current.headers()['x-analysis-version'];
	if (!revision) throw new Error(`Cleanup GET ${endpoint} did not return X-Analysis-Version`);
	const response = await page.request.delete(endpoint, {
		timeout: 5_000,
		headers: { 'If-Match': revision }
	});
	return response.status();
}

export async function createAnalysis(
	request: E2ERequest,
	name: string,
	datasourceId: string
): Promise<string> {
	const datasourceRef = `source-${crypto.randomUUID()}`;
	const viewId = crypto.randomUUID();
	return createImportedAnalysis(
		request,
		name,
		{
			tabs: [
				{
					id: crypto.randomUUID(),
					name: 'Source 1',
					parent_id: null,
					datasource: {
						id: datasourceRef,
						analysis_tab_id: null,
						config: { branch: 'master' }
					},
					output: buildOutput('source_1'),
					steps: [{ id: viewId, type: 'view', config: {}, depends_on: [], is_applied: true }]
				}
			]
		},
		{ [datasourceRef]: datasourceId }
	);
}

export async function createImportedAnalysis(
	request: E2ERequest,
	name: string,
	pipeline: Record<string, unknown>,
	datasourceRemap?: Record<string, string>,
	description?: string
): Promise<string> {
	return withAuthedPage(request, async (page) => {
		const id = await importAnalysisViaUi(page, { name, description, pipeline, datasourceRemap });
		analysisRegistry.set(id, { name });
		await page.goto('/', { waitUntil: 'domcontentloaded' }).catch(() => undefined);
		return id;
	});
}

export async function createMultiStepAnalysis(
	request: E2ERequest,
	name: string,
	datasourceId: string
): Promise<string> {
	const sourceRef = `source-${crypto.randomUUID()}`;
	const viewId = crypto.randomUUID();
	const filterId = crypto.randomUUID();
	const sortId = crypto.randomUUID();
	return createImportedAnalysis(
		request,
		name,
		{
			tabs: [
				{
					id: crypto.randomUUID(),
					name: 'Source 1',
					parent_id: null,
					datasource: {
						id: sourceRef,
						analysis_tab_id: null,
						config: { branch: 'master' }
					},
					output: buildOutput('source_1'),
					steps: [
						{ id: viewId, type: 'view', config: {}, depends_on: [], is_applied: true },
						{
							id: filterId,
							type: 'filter',
							config: {
								conditions: [
									{ column: 'age', operator: '>', value: 10, value_type: 'number', dtype: 'Int64' }
								],
								logic: 'AND'
							},
							depends_on: [viewId],
							is_applied: true
						},
						{
							id: sortId,
							type: 'sort',
							config: { columns: ['name'], descending: [false] },
							depends_on: [filterId],
							is_applied: true
						}
					]
				}
			]
		},
		{ [sourceRef]: datasourceId }
	);
}

export async function createLongRunningAnalysis(
	request: E2ERequest,
	name: string,
	datasourceId: string
): Promise<string> {
	const sourceRef = `source-${crypto.randomUUID()}`;
	const viewId = crypto.randomUUID();
	const sleepStepOneId = crypto.randomUUID();
	const sleepStepTwoId = crypto.randomUUID();
	const sortId = crypto.randomUUID();
	return createImportedAnalysis(
		request,
		name,
		{
			tabs: [
				{
					id: crypto.randomUUID(),
					name: 'Source 1',
					parent_id: null,
					datasource: { id: sourceRef, analysis_tab_id: null, config: { branch: 'master' } },
					output: buildOutput('source_1'),
					steps: [
						{ id: viewId, type: 'view', config: {}, depends_on: [], is_applied: true },
						{
							id: sleepStepOneId,
							type: 'with_columns',
							config: {
								expressions: [
									{
										name: 'slow_name',
										type: 'udf',
										args: ['name'],
										code: 'def udf(value):\n' + '    sleep(0.05)\n' + '    return value\n'
									}
								]
							},
							depends_on: [viewId],
							is_applied: true
						},
						{
							id: sleepStepTwoId,
							type: 'with_columns',
							config: {
								expressions: [
									{
										name: 'slow_city',
										type: 'udf',
										args: ['city'],
										code: 'def udf(value):\n' + '    sleep(0.05)\n' + '    return value\n'
									}
								]
							},
							depends_on: [sleepStepOneId],
							is_applied: true
						},
						{
							id: sortId,
							type: 'sort',
							config: { columns: ['age'], descending: [true] },
							depends_on: [sleepStepTwoId],
							is_applied: true
						}
					]
				}
			]
		},
		{ [sourceRef]: datasourceId }
	);
}

export async function createUdf(request: E2ERequest, name: string): Promise<string> {
	return withAuthedPage(request, async (page) => {
		const id = await createUdfViaUi(page, name);
		udfRegistry.set(id, { name });
		return id;
	});
}

export async function createSchedule(
	request: E2ERequest,
	datasourceId: string,
	cron = '0 9 * * *'
): Promise<string> {
	return withAuthedPage(request, async (page) => createScheduleViaUi(page, datasourceId, cron));
}

export async function createHealthCheck(
	request: E2ERequest,
	datasourceId: string,
	name: string
): Promise<string> {
	return withAuthedPage(request, async (page) => createHealthCheckViaUi(page, datasourceId, name));
}

export async function waitForNoRuntimeBuild(
	request: E2ERequest,
	analysisId: string,
	timeoutMs = 5_000
): Promise<void> {
	await withAuthedPage(request, async (page) => {
		const started = Date.now();
		await page.goto(`/monitoring?tab=builds&analysis_id=${analysisId}`);
		await waitForLayoutReady(page);
		const panel = page.locator('#panel-builds');
		await expect(panel).toBeVisible({ timeout: 5_000 });
		while (Date.now() - started < timeoutMs) {
			const running = panel.locator(
				`[data-build-analysis-id="${analysisId}"][data-build-status="running"]`
			);
			const terminal = panel.locator(
				`[data-build-analysis-id="${analysisId}"][data-build-status="completed"], ` +
					`[data-build-analysis-id="${analysisId}"][data-build-status="failed"], ` +
					`[data-build-analysis-id="${analysisId}"][data-build-status="cancelled"]`
			);
			if (
				!(await running
					.first()
					.isVisible()
					.catch(() => false)) &&
				(await terminal.count()) > 0
			) {
				return;
			}
			await page
				.getByRole('button', { name: /Refresh History/i })
				.click()
				.catch(() => undefined);
			await page.waitForTimeout(1_000);
		}
		throw new Error(`Timed out waiting for active build to finish for analysis ${analysisId}`);
	});
}

export async function spawnEngine(_request: E2ERequest, _analysisId: string): Promise<void> {
	// No-op in pure UI e2e: engines are started through visible user actions.
}

export async function waitForNoEngineJob(
	_request: E2ERequest,
	_analysisId: string,
	_timeoutMs = 5_000
): Promise<void> {
	// No-op in pure UI e2e: engine lifecycle is observed via visible build status.
}

export function findAnalysisIdByName(name: string): string | null {
	for (const [id, entry] of analysisRegistry.entries()) {
		if (entry.name === name) return id;
	}
	return null;
}

export async function shutdownEngine(
	request: E2ERequest,
	analysisId: string,
	options?: { waitForIdleMs?: number }
): Promise<void> {
	await waitForNoRuntimeBuild(request, analysisId, options?.waitForIdleMs ?? 5_000).catch(() => {});
	await withAuthedPage(request, async (page) => {
		await shutdownEngineViaUi(page, analysisId, { timeoutMs: options?.waitForIdleMs ?? 5_000 });
	});
}

export function nameForDatasourceId(datasourceId: string): string | undefined {
	return datasourceRegistry.get(datasourceId)?.name;
}

export function nameForAnalysisId(analysisId: string): string | undefined {
	return analysisRegistry.get(analysisId)?.name;
}

export function nameForUdfId(udfId: string): string | undefined {
	return udfRegistry.get(udfId)?.name;
}
