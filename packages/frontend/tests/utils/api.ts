import path from 'node:path';
import type { APIRequestContext, Browser, Page } from '@playwright/test';
import { expect } from '@playwright/test';
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

const apiOrigin =
	process.env.PLAYWRIGHT_API_ORIGIN || `http://localhost:${process.env.PORT || '8000'}`;
export const API_BASE = `${apiOrigin}/api/v1`;
export const AUTH_DIR = path.resolve('tests/.artifacts/auth');
export const META_FILE = path.join(AUTH_DIR, 'meta.json');
export const E2E_RUN_STAMP =
	process.env.E2E_RUN_STAMP || `${Date.now().toString(36)}-${process.pid}`;

export { E2E_PASSWORD };

export interface E2ERequest {
	browser: Browser;
	authFile: string;
	workerIndex: number;
	baseURL: string;
}

const datasourceRegistry = new Map<string, { name: string; namespace?: string }>();
const analysisRegistry = new Map<string, { name: string }>();
const udfRegistry = new Map<string, { name: string }>();

export function workerAuthFile(workerIndex: number): string {
	return path.join(AUTH_DIR, `state-${E2E_RUN_STAMP}-w${workerIndex}.json`);
}

function asE2ERequest(request: APIRequestContext): E2ERequest {
	return request as unknown as E2ERequest;
}

async function withAuthedPage<T>(
	request: APIRequestContext,
	fn: (page: Page) => Promise<T>
): Promise<T> {
	const setup = asE2ERequest(request);
	const context = await setup.browser.newContext({
		baseURL: setup.baseURL,
		storageState: setup.authFile
	});
	const page = await context.newPage();
	try {
		return await fn(page);
	} finally {
		await context.close();
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
	request: APIRequestContext,
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
	request: APIRequestContext,
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
	request: APIRequestContext,
	name: string
): Promise<string> {
	return withAuthedPage(request, async (page) => {
		const { id } = await uploadDatasourceWithDatesViaUi(page, name);
		datasourceRegistry.set(id, { name });
		return id;
	});
}

export async function deleteDatasource(
	request: APIRequestContext,
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

export async function createAnalysis(
	request: APIRequestContext,
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
	request: APIRequestContext,
	name: string,
	pipeline: Record<string, unknown>,
	datasourceRemap?: Record<string, string>,
	description?: string
): Promise<string> {
	return withAuthedPage(request, async (page) => {
		const id = await importAnalysisViaUi(page, { name, description, pipeline, datasourceRemap });
		analysisRegistry.set(id, { name });
		return id;
	});
}

export async function createMultiStepAnalysis(
	request: APIRequestContext,
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
	request: APIRequestContext,
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

export async function createUdf(request: APIRequestContext, name: string): Promise<string> {
	return withAuthedPage(request, async (page) => {
		const id = await createUdfViaUi(page, name);
		udfRegistry.set(id, { name });
		return id;
	});
}

export async function createSchedule(
	request: APIRequestContext,
	datasourceId: string,
	cron = '0 9 * * *'
): Promise<string> {
	return withAuthedPage(request, async (page) => createScheduleViaUi(page, datasourceId, cron));
}

export async function createHealthCheck(
	request: APIRequestContext,
	datasourceId: string,
	name: string
): Promise<string> {
	return withAuthedPage(request, async (page) => createHealthCheckViaUi(page, datasourceId, name));
}

export async function waitForNoActiveBuild(
	request: APIRequestContext,
	analysisId: string,
	timeoutMs = 60_000
): Promise<void> {
	await withAuthedPage(request, async (page) => {
		const started = Date.now();
		await page.goto(`/monitoring?tab=builds&analysis_id=${analysisId}`);
		await waitForLayoutReady(page);
		const panel = page.locator('#panel-builds');
		await expect(panel).toBeVisible({ timeout: 15_000 });
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

export async function spawnEngine(_request: APIRequestContext, _analysisId: string): Promise<void> {
	// No-op in pure UI e2e: engines are started through visible user actions.
}

export async function waitForNoEngineJob(
	_request: APIRequestContext,
	_analysisId: string,
	_timeoutMs = 30_000
): Promise<void> {
	// No-op in pure UI e2e: engine lifecycle is observed via visible build status.
}

export async function shutdownEngine(
	request: APIRequestContext,
	analysisId: string,
	options?: { waitForIdleMs?: number }
): Promise<void> {
	await waitForNoActiveBuild(request, analysisId, options?.waitForIdleMs ?? 5_000).catch(() => {});
}

export async function registerUser(_email: string, _displayName: string): Promise<string> {
	throw new Error('registerUser should not be used in pure UI e2e helpers');
}

export async function deleteAccount(_token: string): Promise<'error'> {
	throw new Error('deleteAccount should not be used in pure UI e2e helpers');
}

export function buildStorageState(_sessionToken: string | undefined): never {
	throw new Error('buildStorageState should not be used in pure UI e2e helpers');
}

export async function shutdownEngineByToken(_token: string, _analysisId: string): Promise<void> {
	// No-op in pure UI e2e.
}

export async function waitForNoEngineJobByToken(
	_token: string,
	_analysisId: string
): Promise<void> {
	// No-op in pure UI e2e.
}

export async function loginAs(_email: string): Promise<never> {
	throw new Error('loginAs should not be used in pure UI e2e helpers');
}

export async function registerWorker(_workerIndex: number): Promise<never> {
	throw new Error('registerWorker should not be used in pure UI e2e helpers');
}

export async function ensureWorkerClean(_workerIndex: number): Promise<void> {
	// No-op in pure UI e2e.
}

export function readStoredSessionToken(_authFile: string): string | undefined {
	return undefined;
}

export function readMeta(): { authRequired: boolean; stamp: string } {
	return { authRequired: true, stamp: Date.now().toString(36) };
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
