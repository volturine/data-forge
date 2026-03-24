import type { APIRequestContext } from '@playwright/test';

export const API_BASE = 'http://localhost:8000/api/v1';

const SAMPLE_CSV = 'id,name,age,city\n1,Alice,30,London\n2,Bob,25,Paris\n3,Charlie,35,Berlin\n';

const E2E_PREFIX_RE = /^e2e[^a-z]/i;

function generateLargeCsv(rows: number): string {
	const names = ['Alice', 'Bob', 'Charlie', 'Diana', 'Eve', 'Frank', 'Grace', 'Hank'];
	const cities = ['London', 'Paris', 'Berlin', 'Tokyo', 'Sydney', 'Oslo', 'Rome', 'Madrid'];
	const lines = ['id,name,age,city'];
	for (let i = 1; i <= rows; i++) {
		lines.push(`${i},${names[i % names.length]},${20 + (i % 50)},${cities[i % cities.length]}`);
	}
	return lines.join('\n') + '\n';
}

/**
 * Purge all resources whose names match the e2e prefix.
 * Safe to call before/after a run to ensure a clean slate.
 *
 * Deletion order: schedules + health checks → analyses + UDFs → datasources
 * (respects foreign-key dependencies).
 */
export async function purgeE2eResources(request: APIRequestContext): Promise<void> {
	const [dsResp, aResp, udfResp, schedResp] = await Promise.all([
		request.get(`${API_BASE}/datasource`),
		request.get(`${API_BASE}/analysis`),
		request.get(`${API_BASE}/udf`),
		request.get(`${API_BASE}/schedules`)
	]);

	// Build datasource name→id lookup from a single parse
	const datasources: Array<{ id: string; name: string }> = dsResp.ok()
		? ((await dsResp.json()) as Array<{ id: string; name: string }>)
		: [];
	const dsNames = new Map(datasources.map((ds) => [ds.id, ds.name]));
	const e2eDatasourceIds = datasources
		.filter((ds) => E2E_PREFIX_RE.test(ds.name))
		.map((ds) => ds.id);

	// ── Phase 1: schedules & health checks (reference datasources) ─────────
	const phase1: Promise<void>[] = [];

	if (schedResp.ok()) {
		const schedules = (await schedResp.json()) as Array<{ id: string; datasource_id?: string }>;
		for (const s of schedules) {
			const dsName = s.datasource_id ? dsNames.get(s.datasource_id) : undefined;
			if (dsName && E2E_PREFIX_RE.test(dsName)) {
				phase1.push(deleteSchedule(request, s.id).catch(() => undefined));
			}
		}
	}

	// Health checks require datasource_id — query per e2e datasource
	for (const dsId of e2eDatasourceIds) {
		const hcResp = await request.get(`${API_BASE}/healthchecks?datasource_id=${dsId}`);
		if (!hcResp.ok()) continue;
		const checks = (await hcResp.json()) as Array<{ id: string; name: string }>;
		for (const hc of checks) {
			phase1.push(deleteHealthCheck(request, hc.id).catch(() => undefined));
		}
	}

	await Promise.all(phase1);

	// ── Phase 2: analyses + UDFs (analyses reference datasources) ──────────
	const phase2: Promise<void>[] = [];

	if (aResp.ok()) {
		const analyses = (await aResp.json()) as Array<{ id: string; name: string }>;
		for (const a of analyses) {
			if (E2E_PREFIX_RE.test(a.name)) {
				phase2.push(deleteAnalysis(request, a.id).catch(() => undefined));
			}
		}
	}
	if (udfResp.ok()) {
		const udfs = (await udfResp.json()) as Array<{ id: string; name: string }>;
		for (const u of udfs) {
			if (E2E_PREFIX_RE.test(u.name)) {
				phase2.push(deleteUdf(request, u.id).catch(() => undefined));
			}
		}
	}

	await Promise.all(phase2);

	// ── Phase 3: datasources (must come after everything else) ─────────────
	const phase3: Promise<void>[] = [];
	for (const ds of datasources) {
		if (E2E_PREFIX_RE.test(ds.name)) {
			phase3.push(deleteDatasource(request, ds.id).catch(() => undefined));
		}
	}
	await Promise.all(phase3);
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

export async function deleteDatasource(request: APIRequestContext, id: string): Promise<void> {
	await request.delete(`${API_BASE}/datasource/${id}`);
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

export async function deleteAnalysis(request: APIRequestContext, id: string): Promise<void> {
	await request.delete(`${API_BASE}/analysis/${id}`);
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
