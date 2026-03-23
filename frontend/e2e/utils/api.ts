import type { APIRequestContext } from '@playwright/test';

export const API_BASE = 'http://localhost:8000/api/v1';

const SAMPLE_CSV = 'id,name,age,city\n1,Alice,30,London\n2,Bob,25,Paris\n3,Charlie,35,Berlin\n';

// ── Datasource ────────────────────────────────────────────────────────────────

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

export async function deleteDatasource(request: APIRequestContext, id: string): Promise<void> {
	await request.delete(`${API_BASE}/datasource/${id}`);
}

// ── Analysis ──────────────────────────────────────────────────────────────────

export async function createAnalysis(
	request: APIRequestContext,
	name: string,
	datasourceId: string
): Promise<string> {
	// Proper UUID v4 is required by the backend (result_id validator)
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

export async function deleteAnalysis(request: APIRequestContext, id: string): Promise<void> {
	await request.delete(`${API_BASE}/analysis/${id}`);
}

// ── UDF ───────────────────────────────────────────────────────────────────────

export async function createUdf(request: APIRequestContext, name: string): Promise<string> {
	const response = await request.post(`${API_BASE}/udf`, {
		data: {
			name,
			description: `Test UDF: ${name}`,
			code: 'def transform(col):\n    return col\n', // backend requires 'code', not 'source'
			tags: ['test'],
			signature: { inputs: [], output: null }
		}
	});
	if (!response.ok()) {
		throw new Error(`createUdf failed: ${response.status()} ${await response.text()}`);
	}
	return ((await response.json()) as { id: string }).id;
}

export async function deleteUdf(request: APIRequestContext, id: string): Promise<void> {
	await request.delete(`${API_BASE}/udf/${id}`);
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

export async function deleteSchedule(request: APIRequestContext, id: string): Promise<void> {
	await request.delete(`${API_BASE}/schedules/${id}`);
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

export async function deleteHealthCheck(request: APIRequestContext, id: string): Promise<void> {
	await request.delete(`${API_BASE}/healthchecks/${id}`);
}
