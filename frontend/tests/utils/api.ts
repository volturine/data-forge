import path from 'node:path';
import type { APIRequestContext } from '@playwright/test';

const apiPort = process.env.PORT || '8000';
export const API_BASE = `http://localhost:${apiPort}/api/v1`;
export const AUTH_FILE = path.resolve('tests/.auth/state.json');

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
