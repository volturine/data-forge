import fs from 'node:fs';
import path from 'node:path';
import type { APIRequestContext, BrowserContextOptions } from '@playwright/test';

// Hybrid Playwright seed helpers.
// These bypass the UI and should be treated as explicit state setup, not user-driven coverage.

const apiPort = process.env.BACKEND_PORT || process.env.PORT || '8000';
const apiOrigin = process.env.PLAYWRIGHT_API_ORIGIN || `http://localhost:${apiPort}`;
export const API_BASE = `${apiOrigin}/api/v1`;
const DATASOURCE_READY_TIMEOUT_MS = 20_000;
const DATASOURCE_READY_DELAY_MS = 500;

export const AUTH_DIR = path.resolve('tests/.auth');
export const META_FILE = path.join(AUTH_DIR, 'meta.json');

export const E2E_PASSWORD = 'E2eTestPw12345';

export function workerEmail(workerIndex: number): string {
	return `e2e-worker-${workerIndex}@example.com`;
}

export function workerDisplayName(workerIndex: number): string {
	return `E2E Worker ${workerIndex}`;
}

export function workerAuthFile(workerIndex: number): string {
	return path.join(AUTH_DIR, `state-w${workerIndex}.json`);
}

// ── Auth helpers ──────────────────────────────────────────────────────────────

export type DeleteOutcome = 'deleted' | 'unauthenticated' | 'forbidden' | 'error';
export type LoginResult =
	| { status: 'ok'; token: string }
	| { status: 'invalid_credentials' }
	| { status: 'error'; code: number };

export function parseSessionToken(response: Response): string | undefined {
	const raw = response.headers.getSetCookie?.();
	const entries = raw ?? [response.headers.get('set-cookie') ?? ''];
	for (const entry of entries) {
		const match = entry.match(/session_token=([^;]+)/);
		if (match) return match[1];
	}
	return undefined;
}

export async function deleteAccount(token: string): Promise<DeleteOutcome> {
	const resp = await fetch(`${API_BASE}/auth/account`, {
		method: 'DELETE',
		headers: { Cookie: `session_token=${token}` }
	});
	if (resp.status === 200) return 'deleted';
	if (resp.status === 401) return 'unauthenticated';
	if (resp.status === 403) return 'forbidden';
	return 'error';
}

export async function loginAs(email: string): Promise<LoginResult> {
	const resp = await fetch(`${API_BASE}/auth/login`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ email, password: E2E_PASSWORD })
	});
	if (resp.ok) {
		const token = parseSessionToken(resp);
		if (!token) return { status: 'error', code: resp.status };
		return { status: 'ok', token };
	}
	if (resp.status === 401) return { status: 'invalid_credentials' };
	return { status: 'error', code: resp.status };
}

export async function registerWorker(workerIndex: number): Promise<string> {
	const register = async (): Promise<Response> =>
		fetch(`${API_BASE}/auth/register`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				email: workerEmail(workerIndex),
				password: E2E_PASSWORD,
				display_name: workerDisplayName(workerIndex)
			})
		});

	let resp = await register();
	if (resp.status === 409) {
		await ensureWorkerClean(workerIndex);
		resp = await register();
	}

	if (resp.status === 409) {
		const login = await loginAs(workerEmail(workerIndex));
		if (login.status === 'ok') {
			return login.token;
		}
	}

	if (!resp.ok) {
		throw new Error(`Worker ${workerIndex} register failed: ${resp.status} ${await resp.text()}`);
	}
	const token = parseSessionToken(resp);
	if (!token) {
		throw new Error(`Worker ${workerIndex} register succeeded but no session_token received`);
	}
	return token;
}

export async function registerUser(email: string, displayName: string): Promise<string> {
	const resp = await fetch(`${API_BASE}/auth/register`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			email,
			password: E2E_PASSWORD,
			display_name: displayName
		})
	});

	if (resp.status === 409) {
		const login = await loginAs(email);
		if (login.status === 'ok') {
			return login.token;
		}
	}

	if (!resp.ok) {
		throw new Error(`registerUser failed for ${email}: ${resp.status} ${await resp.text()}`);
	}

	const token = parseSessionToken(resp);
	if (!token) {
		throw new Error(`registerUser succeeded for ${email} but no session_token received`);
	}
	return token;
}

export async function ensureWorkerClean(workerIndex: number): Promise<void> {
	const email = workerEmail(workerIndex);
	const result = await loginAs(email);
	if (result.status === 'invalid_credentials') return;
	if (result.status === 'error') {
		throw new Error(`[worker ${workerIndex}] login probe failed with status ${result.code}`);
	}

	const outcome = await deleteAccount(result.token);
	if (outcome === 'deleted') return;
	if (outcome === 'forbidden') {
		throw new Error(`[worker ${workerIndex}] cannot delete protected account`);
	}
	throw new Error(`[worker ${workerIndex}] delete returned '${outcome}'`);
}

export function readStoredSessionToken(authFile: string): string | undefined {
	try {
		const raw = fs.readFileSync(authFile, 'utf-8');
		const state = JSON.parse(raw) as { cookies?: Array<{ name: string; value: string }> };
		return state.cookies?.find((c) => c.name === 'session_token')?.value;
	} catch {
		return undefined;
	}
}

const frontendPort = process.env.FRONTEND_PORT || '3000';
const frontendOrigin = process.env.PLAYWRIGHT_FRONTEND_ORIGIN || `http://localhost:${frontendPort}`;
const apiStorageOrigin = new URL(API_BASE).origin;
const cookieDomain = process.env.PLAYWRIGHT_COOKIE_DOMAIN || 'localhost';

export function buildStorageState(
	sessionToken: string | undefined
): NonNullable<BrowserContextOptions['storageState']> {
	return {
		cookies: sessionToken
			? [
					{
						name: 'session_token',
						value: sessionToken,
						domain: cookieDomain,
						path: '/',
						expires: -1,
						httpOnly: true,
						secure: false,
						sameSite: 'Lax'
					}
				]
			: [],
		origins: [
			{ origin: apiStorageOrigin, localStorage: [] },
			{ origin: frontendOrigin, localStorage: [] }
		]
	} satisfies NonNullable<BrowserContextOptions['storageState']>;
}

export interface RunMeta {
	authRequired: boolean;
	stamp: string;
}

export function readMeta(): RunMeta {
	try {
		fs.mkdirSync(AUTH_DIR, { recursive: true });
		const raw = fs.readFileSync(META_FILE, 'utf-8');
		return JSON.parse(raw) as RunMeta;
	} catch {
		return { authRequired: true, stamp: Date.now().toString(36) };
	}
}

async function waitForDatasourceVisible(
	request: APIRequestContext,
	id: string,
	namespace?: string,
	timeoutMs = DATASOURCE_READY_TIMEOUT_MS
): Promise<void> {
	const headers: Record<string, string> = {};
	if (namespace) headers['X-Namespace'] = namespace;
	const startedAt = Date.now();
	let lastError = '';

	while (Date.now() - startedAt < timeoutMs) {
		const response = await request.get(`${API_BASE}/datasource?include_hidden=true`, { headers });
		if (response.ok()) {
			const datasources = (await response.json()) as Array<{ id: string }>;
			if (datasources.some((datasource) => datasource.id === id)) return;
			lastError = `datasource ${id} not visible in list yet`;
		} else {
			lastError = `list datasources failed: ${response.status()} ${await response.text()}`;
		}
		await delay(DATASOURCE_READY_DELAY_MS);
	}

	throw new Error(`Timed out waiting for datasource visibility: ${lastError}`);
}

// ── Datasource ────────────────────────────────────────────────────────────────

const SAMPLE_CSV = 'id,name,age,city\n1,Alice,30,London\n2,Bob,25,Paris\n3,Charlie,35,Berlin\n';

function generateLargeCsv(rows: number): string {
	const names = ['Alice', 'Bob', 'Charlie', 'Diana', 'Eve', 'Frank', 'Grace', 'Hank'];
	const cities = ['London', 'Paris', 'Berlin', 'Tokyo', 'Sydney', 'Oslo', 'Rome', 'Madrid'];
	const lines = ['id,name,age,city'];
	for (let i = 1; i <= rows; i++) {
		lines.push(`${i},${names[i % names.length]},${20 + (i % 50)},${cities[i % cities.length]}`);
	}
	return lines.join('\n') + '\n';
}

const DATE_CSV =
	'id,name,event_date,amount\n1,Alice,2024-01-15,100\n2,Bob,2024-03-22,250\n3,Charlie,2024-06-10,75\n';

export async function createDatasourceWithDates(
	request: APIRequestContext,
	name: string
): Promise<string> {
	const response = await request.post(`${API_BASE}/datasource/upload`, {
		multipart: {
			file: {
				name: `${name}.csv`,
				mimeType: 'text/csv',
				buffer: Buffer.from(DATE_CSV)
			},
			name
		}
	});
	if (!response.ok()) {
		throw new Error(
			`createDatasourceWithDates failed: ${response.status()} ${await response.text()}`
		);
	}
	return ((await response.json()) as { id: string }).id;
}

export async function createDatasource(
	request: APIRequestContext,
	name: string,
	namespace?: string,
	description?: string
): Promise<string> {
	const headers: Record<string, string> = {};
	if (namespace) headers['X-Namespace'] = namespace;
	const multipart: Record<string, string | { name: string; mimeType: string; buffer: Buffer }> = {
		file: {
			name: `${name}.csv`,
			mimeType: 'text/csv',
			buffer: Buffer.from(SAMPLE_CSV)
		},
		name
	};
	if (description !== undefined) {
		multipart.description = description;
	}
	const response = await request.post(`${API_BASE}/datasource/upload`, {
		headers,
		multipart
	});
	if (!response.ok()) {
		throw new Error(`createDatasource failed: ${response.status()} ${await response.text()}`);
	}
	const id = ((await response.json()) as { id: string }).id;
	await waitForDatasourceVisible(request, id, namespace);
	return id;
}

export async function createLargeDatasource(
	request: APIRequestContext,
	name: string,
	rows: number
): Promise<string> {
	const csv = generateLargeCsv(rows);
	const response = await request.post(`${API_BASE}/datasource/upload`, {
		multipart: {
			file: {
				name: `${name}.csv`,
				mimeType: 'text/csv',
				buffer: Buffer.from(csv)
			},
			name
		}
	});
	if (!response.ok()) {
		throw new Error(`createLargeDatasource failed: ${response.status()} ${await response.text()}`);
	}
	const id = ((await response.json()) as { id: string }).id;
	await waitForDatasourceVisible(request, id);
	return id;
}

export async function deleteDatasource(
	request: APIRequestContext,
	id: string,
	namespace?: string
): Promise<void> {
	const headers: Record<string, string> = {};
	if (namespace) headers['X-Namespace'] = namespace;
	const response = await request.delete(`${API_BASE}/datasource/${id}`, { headers });
	if (!response.ok() && response.status() !== 404) {
		throw new Error(`deleteDatasource failed: ${response.status()} ${await response.text()}`);
	}
}

// ── Analysis ──────────────────────────────────────────────────────────────────

export async function createAnalysis(
	request: APIRequestContext,
	name: string,
	datasourceId: string
): Promise<string> {
	const resultId = crypto.randomUUID();

	const response = await request.post(`${API_BASE}/analysis`, {
		data: {
			name,
			description: null,
			tabs: [
				{
					id: crypto.randomUUID(),
					name: 'Source 1',
					parent_id: null,
					datasource: {
						id: datasourceId,
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
							id: crypto.randomUUID(),
							type: 'view',
							config: {},
							depends_on: [],
							is_applied: true
						}
					]
				}
			]
		}
	});
	if (!response.ok()) {
		throw new Error(`createAnalysis failed: ${response.status()} ${await response.text()}`);
	}
	return ((await response.json()) as { id: string }).id;
}

export async function spawnEngine(
	request: APIRequestContext,
	analysisId: string,
	resourceConfig?: Record<string, unknown>
): Promise<void> {
	const response = await request.post(`${API_BASE}/compute/engine/spawn/${analysisId}`, {
		data: resourceConfig ? { resource_config: resourceConfig } : undefined
	});
	if (!response.ok()) {
		throw new Error(`spawnEngine failed: ${response.status()} ${await response.text()}`);
	}
}

interface ActiveBuildListResponse {
	builds: Array<{
		analysis_id: string;
		status: 'running' | 'completed' | 'failed' | 'cancelled';
	}>;
	total: number;
}

interface EngineStatusResponse {
	current_job_id: string | null;
}

interface ShutdownEngineOptions {
	waitForIdleMs?: number;
	ignoreActiveJob?: boolean;
}

const SHUTDOWN_RETRY_DELAY_MS = 500;
const DEFAULT_SHUTDOWN_WAIT_MS = 30_000;

function delay(ms: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function waitForNoActiveBuild(
	request: APIRequestContext,
	analysisId: string,
	timeoutMs = 60_000
): Promise<void> {
	const startedAt = Date.now();
	let lastError = '';

	while (Date.now() - startedAt < timeoutMs) {
		const response = await request.get(`${API_BASE}/compute/builds/active`);
		if (response.ok()) {
			const payload = (await response.json()) as ActiveBuildListResponse;
			const active = payload.builds.some(
				(build) => build.analysis_id === analysisId && build.status === 'running'
			);
			if (!active) return;
			lastError = `active build still running for analysis ${analysisId}`;
		} else {
			lastError = `list active builds failed: ${response.status()} ${await response.text()}`;
		}
		await delay(500);
	}

	throw new Error(`Timed out waiting for active build to finish: ${lastError}`);
}

export async function waitForNoEngineJob(
	request: APIRequestContext,
	analysisId: string,
	timeoutMs = DEFAULT_SHUTDOWN_WAIT_MS
): Promise<void> {
	const startedAt = Date.now();
	let lastError = '';

	while (Date.now() - startedAt < timeoutMs) {
		const response = await request.post(`${API_BASE}/compute/engine/keepalive/${analysisId}`);
		if (response.status() === 404) return;
		if (response.ok()) {
			const status = (await response.json()) as EngineStatusResponse;
			if (!status.current_job_id) return;
			lastError = `engine job ${status.current_job_id} still active for analysis ${analysisId}`;
		} else {
			lastError = `engine keepalive failed: ${response.status()} ${await response.text()}`;
		}
		await delay(SHUTDOWN_RETRY_DELAY_MS);
	}

	throw new Error(`Timed out waiting for engine job to finish: ${lastError}`);
}

async function waitForNoEngineJobByToken(
	token: string,
	analysisId: string,
	timeoutMs = DEFAULT_SHUTDOWN_WAIT_MS
): Promise<void> {
	const startedAt = Date.now();
	let lastError = '';

	while (Date.now() - startedAt < timeoutMs) {
		const response = await fetch(`${API_BASE}/compute/engine/keepalive/${analysisId}`, {
			method: 'POST',
			headers: { Cookie: `session_token=${token}` }
		});
		if (response.status === 404) return;
		if (response.ok) {
			const status = (await response.json()) as EngineStatusResponse;
			if (!status.current_job_id) return;
			lastError = `engine job ${status.current_job_id} still active for analysis ${analysisId}`;
		} else {
			lastError = `engine keepalive failed: ${response.status} ${await response.text()}`;
		}
		await delay(SHUTDOWN_RETRY_DELAY_MS);
	}

	throw new Error(`Timed out waiting for engine job to finish: ${lastError}`);
}

export async function shutdownEngine(
	request: APIRequestContext,
	analysisId: string,
	options: ShutdownEngineOptions = {}
): Promise<void> {
	const deadline = Date.now() + (options.waitForIdleMs ?? DEFAULT_SHUTDOWN_WAIT_MS);
	while (true) {
		const response = await request.delete(`${API_BASE}/compute/engine/${analysisId}`);
		if (response.ok() || response.status() === 404) return;
		if (response.status() === 409) {
			const detail = await response.text();
			const remainingMs = deadline - Date.now();
			if (remainingMs <= 0) {
				if (options.ignoreActiveJob) return;
				throw new Error(`shutdownEngine failed: ${response.status()} ${detail}`);
			}
			try {
				await waitForNoEngineJob(request, analysisId, remainingMs);
			} catch (error) {
				if (options.ignoreActiveJob) return;
				throw error;
			}
			continue;
		}
		throw new Error(`shutdownEngine failed: ${response.status()} ${await response.text()}`);
	}
}

export async function shutdownEngineByToken(
	token: string,
	analysisId: string,
	options: ShutdownEngineOptions = {}
): Promise<void> {
	const deadline = Date.now() + (options.waitForIdleMs ?? DEFAULT_SHUTDOWN_WAIT_MS);
	while (true) {
		const resp = await fetch(`${API_BASE}/compute/engine/${analysisId}`, {
			method: 'DELETE',
			headers: { Cookie: `session_token=${token}` }
		});
		if (resp.ok || resp.status === 404) return;
		if (resp.status === 409) {
			const detail = await resp.text();
			const remainingMs = deadline - Date.now();
			if (remainingMs <= 0) {
				if (options.ignoreActiveJob) return;
				throw new Error(`shutdownEngineByToken failed: ${resp.status} ${detail}`);
			}
			try {
				await waitForNoEngineJobByToken(token, analysisId, remainingMs);
			} catch (error) {
				if (options.ignoreActiveJob) return;
				throw error;
			}
			continue;
		}
		throw new Error(`shutdownEngineByToken failed: ${resp.status} ${await resp.text()}`);
	}
}

export async function createMultiStepAnalysis(
	request: APIRequestContext,
	name: string,
	datasourceId: string
): Promise<string> {
	const resultId = crypto.randomUUID();
	const viewId = crypto.randomUUID();
	const filterId = crypto.randomUUID();
	const sortId = crypto.randomUUID();

	const response = await request.post(`${API_BASE}/analysis`, {
		data: {
			name,
			description: null,
			tabs: [
				{
					id: crypto.randomUUID(),
					name: 'Source 1',
					parent_id: null,
					datasource: {
						id: datasourceId,
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
							id: viewId,
							type: 'view',
							config: {},
							depends_on: [],
							is_applied: true
						},
						{
							id: filterId,
							type: 'filter',
							config: {
								conditions: [
									{
										column: 'age',
										operator: '>',
										value: 10,
										value_type: 'number',
										dtype: 'Int64'
									}
								],
								logic: 'AND'
							},
							depends_on: [viewId],
							is_applied: true
						},
						{
							id: sortId,
							type: 'sort',
							config: {
								columns: ['name'],
								descending: [false]
							},
							depends_on: [filterId],
							is_applied: true
						}
					]
				}
			]
		}
	});
	if (!response.ok()) {
		throw new Error(
			`createMultiStepAnalysis failed: ${response.status()} ${await response.text()}`
		);
	}
	return ((await response.json()) as { id: string }).id;
}

export async function createLongRunningAnalysis(
	request: APIRequestContext,
	name: string,
	datasourceId: string
): Promise<string> {
	const resultId = crypto.randomUUID();
	const tabId = crypto.randomUUID();
	const viewId = crypto.randomUUID();
	const joinId = crypto.randomUUID();
	const sortId = crypto.randomUUID();
	const withColumnsId = crypto.randomUUID();
	const deduplicateId = crypto.randomUUID();
	const groupById = crypto.randomUUID();
	const pivotId = crypto.randomUUID();

	const steps: Array<Record<string, unknown>> = [
		{
			id: viewId,
			type: 'view',
			config: {},
			depends_on: [],
			is_applied: true
		},
		{
			id: joinId,
			type: 'join',
			config: {
				how: 'inner',
				right_source: datasourceId,
				join_columns: [
					{
						id: crypto.randomUUID(),
						left_column: 'city',
						right_column: 'city'
					}
				],
				right_columns: ['age', 'id'],
				suffix: '_right'
			},
			depends_on: [viewId],
			is_applied: true
		},
		{
			id: sortId,
			type: 'sort',
			config: {
				columns: ['name'],
				descending: [false]
			},
			depends_on: [joinId],
			is_applied: true
		},
		{
			id: withColumnsId,
			type: 'with_columns',
			config: {
				expressions: [
					{
						name: 'city_name',
						type: 'udf',
						args: ['city', 'name'],
						code:
							'def udf(column_city, column_name):\n' +
							'    total = 0\n' +
							'    for i in range(50):\n' +
							'        total += i\n' +
							'    return column_city + "-" + column_name + str(total)\n'
					}
				]
			},
			depends_on: [sortId],
			is_applied: true
		},
		{
			id: deduplicateId,
			type: 'deduplicate',
			config: {
				columns: ['city_name'],
				keep: 'first'
			},
			depends_on: [withColumnsId],
			is_applied: true
		},
		{
			id: groupById,
			type: 'groupby',
			config: {
				group_columns: ['city'],
				aggregations: [
					{
						column: 'age',
						function: 'mean',
						alias: 'avg_age'
					}
				]
			},
			depends_on: [deduplicateId],
			is_applied: true
		},
		{
			id: pivotId,
			type: 'sort',
			config: {
				columns: ['avg_age'],
				descending: [true]
			},
			depends_on: [groupById],
			is_applied: true
		}
	];

	const response = await request.post(`${API_BASE}/analysis`, {
		data: {
			name,
			description: null,
			tabs: [
				{
					id: tabId,
					name: 'Source 1',
					parent_id: null,
					datasource: {
						id: datasourceId,
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
					steps
				}
			]
		}
	});
	if (!response.ok()) {
		throw new Error(
			`createLongRunningAnalysis failed: ${response.status()} ${await response.text()}`
		);
	}
	return ((await response.json()) as { id: string }).id;
}

// ── UDF ───────────────────────────────────────────────────────────────────────

export async function createUdf(request: APIRequestContext, name: string): Promise<string> {
	const response = await request.post(`${API_BASE}/udf`, {
		data: {
			name,
			description: `Test UDF: ${name}`,
			code: 'def transform(col):\n    return col\n',
			tags: ['test'],
			signature: { inputs: [], output: null }
		}
	});
	if (!response.ok()) {
		throw new Error(`createUdf failed: ${response.status()} ${await response.text()}`);
	}
	return ((await response.json()) as { id: string }).id;
}

// ── Schedule ──────────────────────────────────────────────────────────────────

export async function createSchedule(
	request: APIRequestContext,
	datasourceId: string,
	cron = '0 9 * * *'
): Promise<string> {
	const response = await request.post(`${API_BASE}/schedules`, {
		data: {
			datasource_id: datasourceId,
			cron_expression: cron,
			enabled: true
		}
	});
	if (!response.ok()) {
		throw new Error(`createSchedule failed: ${response.status()} ${await response.text()}`);
	}
	return ((await response.json()) as { id: string }).id;
}

// ── Health Check ──────────────────────────────────────────────────────────────

export async function createHealthCheck(
	request: APIRequestContext,
	datasourceId: string,
	name: string
): Promise<string> {
	const response = await request.post(`${API_BASE}/healthchecks`, {
		data: {
			datasource_id: datasourceId,
			name,
			check_type: 'row_count',
			config: { min_rows: 1 },
			enabled: true,
			critical: false
		}
	});
	if (!response.ok()) {
		throw new Error(`createHealthCheck failed: ${response.status()} ${await response.text()}`);
	}
	return ((await response.json()) as { id: string }).id;
}
