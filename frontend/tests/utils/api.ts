import fs from 'node:fs';
import path from 'node:path';
import type { APIRequestContext } from '@playwright/test';

const apiPort = process.env.PORT || '8000';
export const API_BASE = `http://localhost:${apiPort}/api/v1`;
export const AUTH_FILE = path.resolve('tests/.auth/state.json');

export const E2E_EMAIL = 'e2e-test@example.com';
export const E2E_PASSWORD = 'E2eTestPw12345';
export const E2E_DISPLAY_NAME = 'E2E Test';

// ── Auth helpers (shared by global-setup / global-teardown) ───────────────────

export function readStoredSessionToken(): string | undefined {
	try {
		const raw = fs.readFileSync(AUTH_FILE, 'utf-8');
		const state = JSON.parse(raw) as { cookies?: Array<{ name: string; value: string }> };
		return state.cookies?.find((c) => c.name === 'session_token')?.value;
	} catch {
		return undefined;
	}
}

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

export async function login(): Promise<LoginResult> {
	const resp = await fetch(`${API_BASE}/auth/login`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ email: E2E_EMAIL, password: E2E_PASSWORD })
	});
	if (resp.ok) {
		const token = parseSessionToken(resp);
		if (!token) return { status: 'error', code: resp.status };
		return { status: 'ok', token };
	}
	if (resp.status === 401) return { status: 'invalid_credentials' };
	return { status: 'error', code: resp.status };
}

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

// ── Datasource ────────────────────────────────────────────────────────────────

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

export async function createDatasource(request: APIRequestContext, name: string): Promise<string> {
	const response = await request.post(`${API_BASE}/datasource/upload`, {
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
						filename: 'source_1'
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

export interface AnalysisWithDashboardResult {
	analysisId: string;
	tabId: string;
	dashboardId: string;
	widgetIds: Record<string, string>;
}

export async function createAnalysisWithDashboard(
	request: APIRequestContext,
	name: string,
	datasourceId: string
): Promise<AnalysisWithDashboardResult> {
	const tabId = crypto.randomUUID();
	const resultId = crypto.randomUUID();
	const dashboardId = crypto.randomUUID();
	const datasetWidgetId = crypto.randomUUID();
	const metricWidgetId = crypto.randomUUID();
	const headerWidgetId = crypto.randomUUID();

	const response = await request.post(`${API_BASE}/analysis`, {
		data: {
			name,
			description: 'E2E dashboard test',
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
						filename: 'source_1'
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
			],
			variables: [],
			dashboards: [
				{
					id: dashboardId,
					name: 'Test Dashboard',
					description: 'Created by e2e test',
					layout: [
						{ widget_id: datasetWidgetId, x: 0, y: 0, w: 12, h: 3 },
						{ widget_id: metricWidgetId, x: 0, y: 3, w: 6, h: 2 },
						{ widget_id: headerWidgetId, x: 6, y: 3, w: 6, h: 1 }
					],
					widgets: [
						{
							id: datasetWidgetId,
							type: 'dataset_preview',
							title: 'Dataset Preview',
							source_tab_id: tabId,
							config: { page_size: 25, searchable: true }
						},
						{
							id: metricWidgetId,
							type: 'metric_kpi',
							title: 'Row Count',
							source_tab_id: tabId,
							config: { label: 'Total Rows', aggregation: 'count' }
						},
						{
							id: headerWidgetId,
							type: 'text_header',
							title: 'Section Header',
							source_tab_id: null,
							config: { text: 'Summary', level: 2 }
						}
					]
				}
			]
		}
	});
	if (!response.ok()) {
		throw new Error(
			`createAnalysisWithDashboard failed: ${response.status()} ${await response.text()}`
		);
	}
	const analysisId = ((await response.json()) as { id: string }).id;
	return {
		analysisId,
		tabId,
		dashboardId,
		widgetIds: {
			dataset: datasetWidgetId,
			metric: metricWidgetId,
			header: headerWidgetId
		}
	};
}

export interface AnalysisWithChartDashboardResult {
	analysisId: string;
	tabId: string;
	dashboardId: string;
	widgetIds: Record<string, string>;
}

export async function createAnalysisWithChartDashboard(
	request: APIRequestContext,
	name: string,
	datasourceId: string
): Promise<AnalysisWithChartDashboardResult> {
	const tabId = crypto.randomUUID();
	const resultId = crypto.randomUUID();
	const dashboardId = crypto.randomUUID();
	const chartWidgetId = crypto.randomUUID();
	const datasetWidgetId = crypto.randomUUID();

	const response = await request.post(`${API_BASE}/analysis`, {
		data: {
			name,
			description: 'E2E chart selection test',
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
						filename: 'source_1'
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
			],
			variables: [],
			dashboards: [
				{
					id: dashboardId,
					name: 'Chart Dashboard',
					description: 'Dashboard with chart + dataset for selection tests',
					layout: [
						{ widget_id: chartWidgetId, x: 0, y: 0, w: 12, h: 4 },
						{ widget_id: datasetWidgetId, x: 0, y: 4, w: 12, h: 3 }
					],
					widgets: [
						{
							id: chartWidgetId,
							type: 'chart',
							title: 'City Chart',
							source_tab_id: tabId,
							config: {
								chart_type: 'bar',
								x_column: 'city',
								y_column: 'age',
								aggregation: 'sum',
								selection_enabled: true,
								selection_filters_widgets: true,
								pan_zoom_enabled: false,
								area_selection_enabled: false,
								legend_position: 'right'
							}
						},
						{
							id: datasetWidgetId,
							type: 'dataset_preview',
							title: 'City Data',
							source_tab_id: tabId,
							config: { page_size: 25, searchable: true }
						}
					]
				}
			]
		}
	});
	if (!response.ok()) {
		throw new Error(
			`createAnalysisWithChartDashboard failed: ${response.status()} ${await response.text()}`
		);
	}
	const analysisId = ((await response.json()) as { id: string }).id;
	return {
		analysisId,
		tabId,
		dashboardId,
		widgetIds: {
			chart: chartWidgetId,
			dataset: datasetWidgetId
		}
	};
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
