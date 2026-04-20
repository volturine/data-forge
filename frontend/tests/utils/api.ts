import fs from 'node:fs';
import path from 'node:path';
import type { APIRequestContext } from '@playwright/test';

// Hybrid Playwright seed helpers.
// These bypass the UI and should be treated as explicit state setup, not user-driven coverage.

const apiPort = process.env.PORT || '8000';
export const API_BASE = `http://localhost:${apiPort}/api/v1`;

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
const frontendOrigin = `http://localhost:${frontendPort}`;
const apiOrigin = new URL(API_BASE).origin;

export function buildStorageState(sessionToken: string | undefined): Record<string, unknown> {
	const cookies = sessionToken
		? [
				{
					name: 'session_token',
					value: sessionToken,
					domain: 'localhost',
					path: '/',
					expires: -1,
					httpOnly: true,
					secure: false,
					sameSite: 'Lax'
				}
			]
		: [];

	return {
		cookies,
		origins: [
			{ origin: apiOrigin, localStorage: [] },
			{ origin: frontendOrigin, localStorage: [] }
		]
	};
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
	namespace?: string
): Promise<string> {
	const headers: Record<string, string> = {};
	if (namespace) headers['X-Namespace'] = namespace;
	const response = await request.post(`${API_BASE}/datasource/upload`, {
		headers,
		multipart: {
			file: {
				name: `${name}.csv`,
				mimeType: 'text/csv',
				buffer: Buffer.from(SAMPLE_CSV)
			},
			name
		}
	});
	if (!response.ok()) {
		throw new Error(`createDatasource failed: ${response.status()} ${await response.text()}`);
	}
	return ((await response.json()) as { id: string }).id;
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
	return ((await response.json()) as { id: string }).id;
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

export async function shutdownEngine(
	request: APIRequestContext,
	analysisId: string
): Promise<void> {
	const maxRetries = 5;
	const delayMs = 500;
	for (let attempt = 0; attempt < maxRetries; attempt++) {
		const response = await request.delete(`${API_BASE}/compute/engine/${analysisId}`);
		if (response.ok() || response.status() === 404) return;
		if (response.status() === 409 && attempt < maxRetries - 1) {
			await new Promise((r) => setTimeout(r, delayMs));
			continue;
		}
		throw new Error(`shutdownEngine failed: ${response.status()} ${await response.text()}`);
	}
}

export async function shutdownEngineByToken(token: string, analysisId: string): Promise<void> {
	const maxRetries = 5;
	const delayMs = 500;
	for (let attempt = 0; attempt < maxRetries; attempt++) {
		const resp = await fetch(`${API_BASE}/compute/engine/${analysisId}`, {
			method: 'DELETE',
			headers: { Cookie: `session_token=${token}` }
		});
		if (resp.ok || resp.status === 404) return;
		if (resp.status === 409 && attempt < maxRetries - 1) {
			await new Promise((r) => setTimeout(r, delayMs));
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
