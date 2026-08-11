import {
	expect,
	type APIRequestContext,
	type Browser,
	type BrowserContext,
	type Page
} from '@playwright/test';
import {
	createHealthCheckViaUi,
	createScheduleViaUi,
	createUdfViaUi,
	importAnalysisViaUi,
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
	 * In-memory Playwright storage state.
	 * Named sessionState (not storageState) to avoid clashing with
	 * APIRequestContext.storageState().
	 */
	sessionState: E2EStorageState;
	/** Worker-scoped context reused for setup helpers — never open a new context per call. */
	helperContext: BrowserContext;
	workerIndex: number;
	baseURL: string;
}

const datasourceRegistry = new Map<string, { name: string; namespace?: string }>();
const analysisRegistry = new Map<string, { name: string }>();
const udfRegistry = new Map<string, { name: string }>();

/**
 * Default app namespace used by helpers unless a test passes another.
 * Read from the visible sidebar namespace control (not /api/v1/config).
 * Memoized per worker after first shell load.
 */
let helperDefaultNamespace: string | undefined;

async function resolveHelperDefaultNamespace(page: Page): Promise<string> {
	if (!helperDefaultNamespace) {
		await page.goto('/');
		await waitForLayoutReady(page);
		const label = page.getByRole('button', { name: 'Select namespace' });
		await expect(label).toBeVisible({ timeout: 5_000 });
		const text = (await label.innerText()).trim();
		helperDefaultNamespace = text || 'default';
	}
	return helperDefaultNamespace;
}

/**
 * Run setup work on the worker's long-lived helper context.
 * One page at a time: workers run tests serially, so no lock is required.
 */
async function withAuthedPage<T>(request: E2ERequest, fn: (page: Page) => Promise<T>): Promise<T> {
	if (!request.helperContext) {
		throw new Error(`withAuthedPage requires helperContext (worker ${request.workerIndex})`);
	}
	const page = await request.helperContext.newPage();
	try {
		return await fn(page);
	} finally {
		await page.close();
	}
}

/**
 * Shared helper context reuses IndexedDB across calls. Always pin namespace
 * before mutating data so a prior namespaced helper call cannot leak into
 * the next. Pins to the app's configured default namespace when the caller
 * does not require a specific one.
 */
async function prepareHelperNamespace(page: Page, namespace?: string): Promise<void> {
	const target = namespace ?? (await resolveHelperDefaultNamespace(page));
	await page.goto('/');
	await waitForLayoutReady(page);
	const sidebar = page.locator('aside[aria-label="Main navigation"]');
	const active = sidebar.getByText(target, { exact: true });
	if (await active.isVisible().catch(() => false)) return;
	await switchNamespace(page, target);
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
		const target = namespace ?? (await resolveHelperDefaultNamespace(page));
		await prepareHelperNamespace(page, target);
		const { id } = await uploadDatasourceViaUi(page, name, { description });
		datasourceRegistry.set(id, { name, namespace: target });
		return id;
	});
}

export async function createLargeDatasource(
	request: E2ERequest,
	name: string,
	rows: number
): Promise<string> {
	return withAuthedPage(request, async (page) => {
		const target = await resolveHelperDefaultNamespace(page);
		await prepareHelperNamespace(page, target);
		const { id } = await uploadDatasourceViaUi(page, name, { rows });
		datasourceRegistry.set(id, { name, namespace: target });
		return id;
	});
}

export async function createDatasourceWithDates(
	request: E2ERequest,
	name: string
): Promise<string> {
	return withAuthedPage(request, async (page) => {
		const target = await resolveHelperDefaultNamespace(page);
		await prepareHelperNamespace(page, target);
		const { id } = await uploadDatasourceWithDatesViaUi(page, name);
		datasourceRegistry.set(id, { name, namespace: target });
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
		await prepareHelperNamespace(page, namespace ?? entry.namespace);
		await deleteDatasourceViaUI(page, entry.name);
	});
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
		await prepareHelperNamespace(page);
		// importAnalysisViaUi registers the analysis for cleanup / engine shutdown.
		return importAnalysisViaUi(page, { name, description, pipeline, datasourceRemap });
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
		await prepareHelperNamespace(page);
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
	return withAuthedPage(request, async (page) => {
		await prepareHelperNamespace(page);
		return createScheduleViaUi(page, datasourceId, cron);
	});
}

export async function createHealthCheck(
	request: E2ERequest,
	datasourceId: string,
	name: string
): Promise<string> {
	return withAuthedPage(request, async (page) => {
		await prepareHelperNamespace(page);
		return createHealthCheckViaUi(page, datasourceId, name);
	});
}

export async function spawnEngine(_request: E2ERequest, _analysisId: string): Promise<void> {
	// Engines are started through visible user actions / analysis prewarm.
}

export async function waitForNoEngineJob(
	_request: E2ERequest,
	_analysisId: string,
	_timeoutMs = 5_000
): Promise<void> {
	// Observe engine lifecycle via the Engines popup / visible build status.
}

export function registerAnalysis(id: string, name: string): void {
	analysisRegistry.set(id, { name });
}

export function findAnalysisIdByName(name: string): string | null {
	for (const [id, entry] of analysisRegistry.entries()) {
		if (entry.name === name) return id;
	}
	return null;
}

export function unregisterAnalysis(analysisId: string): void {
	analysisRegistry.delete(analysisId);
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
