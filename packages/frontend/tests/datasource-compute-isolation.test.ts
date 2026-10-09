import { randomUUID } from 'node:crypto';
import type { Page } from '@playwright/test';
import { expect, test } from './fixtures.js';

const workbook = Buffer.from(
	'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',
	'base64'
);
const namespace = process.env.DEFAULT_NAMESPACE ?? 'default';

type ComputeWorkerStatus = {
	resource_id: string;
	container_id: string;
	scope: string;
	reuse_policy: string;
};

async function engineStatus(page: Page, id: string): Promise<ComputeWorkerStatus> {
	const response = await page
		.context()
		.request.post(`/api/v1/compute/compute-worker/spawn/datasource-preview/${id}`, {
			headers: { 'X-Namespace': namespace }
		});
	expect(response.ok(), await response.text()).toBeTruthy();
	return response.json();
}

test('datasource computation shares only its exact RID container and imports multiple Arrow batches', async ({
	page
}) => {
	const source = [
		'id,value',
		...Array.from({ length: 70000 }, (_, index) => `${index},${index * 2}`)
	].join('\n');
	const ids: string[] = [];
	try {
		for (let index = 0; index < 2; index += 1) {
			const upload = await page.context().request.post('/api/v1/datasource/upload', {
				headers: { 'X-Namespace': namespace },
				multipart: {
					name: `e2e-isolated-source-${randomUUID()}`,
					file: { name: 'source.csv', mimeType: 'text/csv', buffer: Buffer.from(source) }
				}
			});
			expect(upload.ok(), await upload.text()).toBeTruthy();
			const datasource = (await upload.json()) as {
				id: string;
				schema_cache: { row_count: number };
			};
			ids.push(datasource.id);
			expect(datasource.schema_cache.row_count).toBe(70000);
		}
		const first = await engineStatus(page, ids[0]);
		expect(first.resource_id).toBe(ids[0]);
		expect(first.scope).toBe('datasource_preview');
		expect(first.reuse_policy).toBe('shared');
		expect(first.container_id).toBeTruthy();
		const statistics = await Promise.all(
			Array.from({ length: 3 }, () =>
				page.context().request.get(`/api/v1/datasource/${ids[0]}/column/value/stats`, {
					headers: { 'X-Namespace': namespace }
				})
			)
		);
		for (const result of statistics) expect(result.ok(), await result.text()).toBeTruthy();
		expect((await engineStatus(page, ids[0])).container_id).toBe(first.container_id);
		expect((await engineStatus(page, ids[1])).container_id).not.toBe(first.container_id);
		expect((await page.context().request.get('/api/v1/config')).ok()).toBeTruthy();
	} finally {
		for (const id of ids)
			await page
				.context()
				.request.delete(`/api/v1/datasource/${id}`, { headers: { 'X-Namespace': namespace } });
	}
});

test('Excel parsing uses a stable draft container and confirmation transfers durable source ownership', async ({
	page
}) => {
	const preflight = await page.context().request.post('/api/v1/datasource/preflight', {
		headers: { 'X-Namespace': namespace },
		multipart: {
			file: {
				name: 'source.xlsx',
				mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
				buffer: workbook
			}
		}
	});
	expect(preflight.ok(), await preflight.text()).toBeTruthy();
	const draft = (await preflight.json()) as {
		preflight_id: string;
		preview: Array<Array<string | null>>;
	};
	expect(draft.preview[0]).toEqual(['id', 'value']);
	const initialEngine = await engineStatus(page, draft.preflight_id);
	const preview = await page
		.context()
		.request.get(`/api/v1/datasource/preflight/${draft.preflight_id}/preview?sheet_name=Data`, {
			headers: { 'X-Namespace': namespace }
		});
	expect(preview.ok(), await preview.text()).toBeTruthy();
	expect((await engineStatus(page, draft.preflight_id)).container_id).toBe(
		initialEngine.container_id
	);
	const confirmed = await page.context().request.post('/api/v1/datasource/confirm', {
		headers: { 'X-Namespace': namespace },
		multipart: {
			preflight_id: draft.preflight_id,
			name: `e2e-isolated-excel-${randomUUID()}`,
			sheet_name: 'Data'
		}
	});
	expect(confirmed.ok(), await confirmed.text()).toBeTruthy();
	const datasource = (await confirmed.json()) as {
		id: string;
		schema_cache: { row_count: number };
	};
	try {
		expect(datasource.schema_cache.row_count).toBe(3);
		expect(datasource.id).not.toBe(draft.preflight_id);
		const assigned = await engineStatus(page, datasource.id);
		expect(assigned.resource_id).toBe(datasource.id);
		expect(assigned.container_id).not.toBe(initialEngine.container_id);
		const ingest = await page.context().request.post(`/api/v1/datasource/${datasource.id}/ingest`, {
			headers: { 'X-Namespace': namespace }
		});
		expect(ingest.ok(), await ingest.text()).toBeTruthy();
		expect(
			((await ingest.json()) as { schema_cache: { row_count: number } }).schema_cache.row_count
		).toBe(3);
	} finally {
		await page.context().request.delete(`/api/v1/datasource/${datasource.id}`, {
			headers: { 'X-Namespace': namespace }
		});
	}
});
