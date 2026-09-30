import { randomUUID } from 'node:crypto';
import { request as httpRequest } from 'node:http';
import type { Page } from '@playwright/test';
import { expect, test } from './fixtures.js';
import { createCsvDatasource } from './utils/api.js';
import { waitForLayoutReady } from './utils/readiness.js';

type ChatEvent = { type: string; [key: string]: unknown };
type SseEvent = { id: string; data: ChatEvent };

async function readChatStreams(
	page: Page,
	sessionId: string,
	count: number,
	after = 0
): Promise<SseEvent[][]> {
	return page.evaluate(
		async ({ sessionId, count, after }) => {
			const open = async () => {
				const response = await fetch(
					`/api/v1/ai/chat/stream/${encodeURIComponent(sessionId)}?after=${after}`
				);
				if (!response.ok || !response.body) {
					throw new Error(`SSE subscription failed with HTTP ${response.status}`);
				}
				return response.body.getReader();
			};
			const readers = await Promise.all(Array.from({ length: count }, () => open()));
			return Promise.all(
				readers.map(async (reader) => {
					const decoder = new TextDecoder();
					const events: SseEvent[] = [];
					let pending = '';
					while (true) {
						const next = await reader.read();
						if (next.done) return events;
						pending += decoder.decode(next.value, { stream: true });
						while (pending.includes('\n\n')) {
							const boundary = pending.indexOf('\n\n');
							const frame = pending.slice(0, boundary);
							pending = pending.slice(boundary + 2);
							const id = frame
								.split('\n')
								.find((line) => line.startsWith('id: '))
								?.slice(4);
							const data = frame
								.split('\n')
								.find((line) => line.startsWith('data: '))
								?.slice(6);
							if (!id || !data) continue;
							const event = JSON.parse(data) as ChatEvent;
							events.push({ id, data: event });
							if (event.type === 'done') {
								await reader.cancel();
								return events;
							}
						}
					}
				})
			);
		},
		{ sessionId, count, after }
	);
}

async function createChatSession(page: Page, model: string): Promise<string> {
	const response = await page.context().request.post('/api/v1/ai/chat/sessions', {
		data: { provider: 'openai', model, api_key: 'e2e-provider-key' }
	});
	expect(response.ok(), await response.text()).toBeTruthy();
	return ((await response.json()) as { session_id: string }).session_id;
}

function isChatStreamResponse(sessionId: string, responseUrl: string): boolean {
	return responseUrl.includes(`/api/v1/ai/chat/stream/${sessionId}`);
}

function waitForChatStreams(page: Page, sessionId: string, count: number): Promise<void> {
	return new Promise((resolve, reject) => {
		const responses = new Set<object>();
		const onResponse = (response: object & { url(): string; status(): number }) => {
			if (!isChatStreamResponse(sessionId, response.url())) return;
			if (response.status() !== 200) {
				page.off('response', onResponse);
				reject(new Error(`SSE subscription failed with HTTP ${response.status()}`));
				return;
			}
			responses.add(response);
			if (responses.size < count) return;
			page.off('response', onResponse);
			resolve();
		};
		page.on('response', onResponse);
	});
}

async function waitForChatHeartbeat(page: Page, sessionId: string): Promise<boolean> {
	return page.evaluate(async (sessionId) => {
		const response = await fetch(`/api/v1/ai/chat/stream/${encodeURIComponent(sessionId)}`);
		if (!response.ok || !response.body) {
			throw new Error(`Heartbeat subscription failed with HTTP ${response.status}`);
		}
		const reader = response.body.getReader();
		const decoder = new TextDecoder();
		let pending = '';
		while (true) {
			const next = await reader.read();
			if (next.done) return false;
			pending += decoder.decode(next.value, { stream: true });
			if (pending.includes(': heartbeat')) {
				await reader.cancel();
				return true;
			}
		}
	}, sessionId);
}

test.describe('runtime architecture', () => {
	test.describe.configure({ mode: 'default' });

	test('fresh API connections consume the current projected AI provider settings', async ({
		browser,
		page,
		request
	}) => {
		const settingsResponse = await page.context().request.get('/api/v1/settings');
		expect(settingsResponse.ok()).toBeTruthy();
		const original = (await settingsResponse.json()) as Record<string, unknown>;
		expect(original.openai_api_key).toBe('');
		const datasourceId = await createCsvDatasource(
			request,
			`e2e-settings-source-${randomUUID()}`,
			'id,value\n1,alpha\n'
		);
		for (let index = 0; index < 8; index += 1) {
			const context = await browser.newContext({
				baseURL: request.baseURL,
				storageState: request.sessionState
			});
			try {
				expect(
					(await context.request.get('/api/v1/config', { headers: { Connection: 'close' } })).ok()
				).toBeTruthy();
			} finally {
				await context.close();
			}
		}
		const model = `e2e-settings-${randomUUID()}`;
		const fixtureUrl = process.env.E2E_OPENAI_FIXTURE_URL;
		const fixtureHostUrl = process.env.E2E_OPENAI_FIXTURE_HOST_URL;
		if (!fixtureUrl || !fixtureHostUrl) {
			throw new Error('E2E OpenAI fixture URLs must be resolved by scripts/test_e2e.sh');
		}

		const fixtureCheck = await page.context().request.get(`${fixtureHostUrl}/models`);
		expect(fixtureCheck.ok()).toBeTruthy();
		const settingsUpdate = {
			openai_api_key: 'e2e-provider-key',
			public_idb_debug: !original.public_idb_debug,
			openai_endpoint_url: fixtureUrl.replace(/\/v1$/, ''),
			openai_default_model: model
		};

		try {
			await page.goto('/');
			await waitForLayoutReady(page);

			// The sequential same-origin fetches reuse one HTTP/1.1 connection, so
			// this PID identifies the child that handles the following settings PUT.
			const writerApiPid = await page.evaluate(async (data) => {
				const overviewResponse = await fetch('/api/v1/runtime/overview', { cache: 'no-store' });
				if (!overviewResponse.ok)
					throw new Error(`Runtime overview failed: ${overviewResponse.status}`);
				const overview = (await overviewResponse.json()) as { api: { pid: number } };
				const updateResponse = await fetch('/api/v1/settings', {
					method: 'PUT',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify(data)
				});
				if (!updateResponse.ok) throw new Error(`Settings update failed: ${updateResponse.status}`);
				return overview.api.pid;
			}, settingsUpdate);

			const contexts = await Promise.all(
				Array.from({ length: 16 }, () =>
					browser.newContext({
						baseURL: request.baseURL,
						storageState: request.sessionState
					})
				)
			);
			try {
				const observations = await Promise.all(
					contexts.map(async (context) => {
						const overview = await context.request.get('/api/v1/runtime/overview');
						expect(overview.ok()).toBeTruthy();
						const pid = ((await overview.json()) as { api: { pid: number } }).api.pid;
						const config = await context.request.get('/api/v1/config');
						expect(config.ok()).toBeTruthy();
						const debug = (await config.json()).public_idb_debug as boolean;
						const read = await context.request.get('/api/v1/settings');
						expect(read.ok()).toBeTruthy();
						const readSettings = (await read.json()) as { openai_default_model: string };
						expect(readSettings.openai_default_model).toBe(model);
						return { pid, debug, model: readSettings.openai_default_model };
					})
				);
				const otherApiReader = observations.find(({ pid }) => pid !== writerApiPid);
				expect(otherApiReader).toBeDefined();
				expect(otherApiReader).toMatchObject({
					debug: !original.public_idb_debug,
					model
				});
				for (let index = 0; index < 4; index += 1) {
					const context = contexts[index];
					if (!context) throw new Error(`Missing settings projection context ${index}`);

					const generated = await context.request.post('/api/v1/analysis/generate', {
						headers: {
							Connection: 'close',
							'X-Namespace': process.env.DEFAULT_NAMESPACE ?? 'default'
						},
						data: {
							name: `settings-projection-${index}`,
							description: 'Make a simple source pipeline',
							datasources: [{ id: datasourceId }],
							provider: 'openai'
						}
					});
					expect(generated.ok(), await generated.text()).toBeTruthy();
					expect((await generated.json()).model).toBe(model);
				}
			} finally {
				await Promise.all(contexts.map((context) => context.close()));
			}
		} finally {
			// Restore the shared settings row after this serialized case.
			const restore = await page.context().request.put('/api/v1/settings', {
				data: {
					openai_api_key: '',
					public_idb_debug: original.public_idb_debug,
					openai_endpoint_url: original.openai_endpoint_url,
					openai_default_model: original.openai_default_model
				}
			});
			expect(restore.ok()).toBeTruthy();
		}
	});

	test('preview sharing coalesces exact commands and isolates distinct commands and datasources', async ({
		page,
		request
	}) => {
		const firstId = await createCsvDatasource(
			request,
			`e2e-preview-first-${randomUUID()}`,
			'id,value\n1,first\n2,second\n'
		);
		const otherId = await createCsvDatasource(
			request,
			`e2e-preview-other-${randomUUID()}`,
			'id,value\n1,other\n2,distinct\n'
		);
		const pipelineFor = (datasourceId: string) => ({
			analysis_id: randomUUID(),
			tabs: [
				{
					id: randomUUID(),
					name: 'Source',
					datasource: { id: datasourceId, analysis_tab_id: null, config: { branch: 'master' } },
					output: { result_id: randomUUID(), filename: 'source', format: 'parquet' },
					steps: []
				}
			]
		});
		const preview = (
			datasourceId: string,
			pageNumber: number,
			pipeline = pipelineFor(datasourceId)
		) =>
			page.context().request.post('/api/v1/compute/preview', {
				headers: { 'X-Namespace': process.env.DEFAULT_NAMESPACE ?? 'default' },
				data: {
					datasource_id: datasourceId,
					target_step_id: 'source',
					analysis_pipeline: pipeline,
					row_limit: 1,
					page: pageNumber
				}
			});

		// Identical full commands coalesce; a page change and a different datasource
		// each require their own preview execution.
		const pipeline = pipelineFor(firstId);
		const otherPipeline = pipelineFor(otherId);
		const firstAnalysisId = pipeline.analysis_id;
		const exactA = preview(firstId, 1, pipeline);
		const exactB = preview(firstId, 1, pipeline);
		const distinctCommand = preview(firstId, 2, pipeline);
		const separateIdentity = preview(otherId, 1, otherPipeline);
		const [firstPreview, duplicatePreview, secondPreview, otherPreview] = await Promise.all([
			exactA,
			exactB,
			distinctCommand,
			separateIdentity
		]);
		expect(firstPreview.ok(), await firstPreview.text()).toBeTruthy();
		expect(duplicatePreview.ok(), await duplicatePreview.text()).toBeTruthy();
		expect(secondPreview.ok(), await secondPreview.text()).toBeTruthy();
		expect(otherPreview.ok(), await otherPreview.text()).toBeTruthy();
		const previewA = (await firstPreview.json()) as {
			data: Array<Record<string, unknown>>;
			page_size: number;
		};
		const previewB = (await duplicatePreview.json()) as {
			data: Array<Record<string, unknown>>;
			page_size: number;
		};
		const previewPageTwo = (await secondPreview.json()) as {
			data: Array<Record<string, unknown>>;
			page_size: number;
		};
		const previewOther = (await otherPreview.json()) as {
			data: Array<Record<string, unknown>>;
			page_size: number;
		};
		for (const result of [previewA, previewB, previewPageTwo, previewOther]) {
			expect(result.page_size).toBe(1);
			expect(result.data).toHaveLength(1);
		}
		expect(previewA.data[0]?.value).toBe('first');
		expect(previewB.data).toEqual(previewA.data);
		expect(previewPageTwo.data[0]?.value).toBe('second');
		expect(previewOther.data[0]?.value).toBe('other');
		const executionRuns = await page
			.context()
			.request.get(
				`/api/v1/engine-runs?analysis_id=${encodeURIComponent(firstAnalysisId)}&kind=preview`
			);
		expect(executionRuns.ok()).toBeTruthy();
		const runs = (await executionRuns.json()) as Array<{ id: string }>;
		expect(runs).toHaveLength(2);
		expect(new Set(runs.map((run) => run.id)).size).toBe(2);
	});

	test('canceling a multipart upload before its terminal boundary leaves no datasource', async ({
		page,
		request
	}) => {
		const name = `e2e-cancel-upload-${randomUUID()}`;
		const boundary = `e2e-${randomUUID()}`;
		const upload = httpRequest(new URL('/api/v1/datasource/upload', request.baseURL), {
			method: 'POST',
			headers: {
				'Content-Type': `multipart/form-data; boundary=${boundary}`,
				'X-Namespace': process.env.DEFAULT_NAMESPACE ?? 'default',
				Cookie: request.sessionState.cookies
					.map((cookie) => `${cookie.name}=${cookie.value}`)
					.join('; ')
			}
		});
		const cancelled = new Promise<void>((resolve, reject) => {
			upload.once('error', (error) =>
				error.message === 'E2E upload cancelled' ? resolve() : reject(error)
			);
			upload.once('response', (response) => {
				response.resume();
				reject(new Error(`Upload responded before cancellation: HTTP ${response.statusCode}`));
			});
		});
		upload.write(
			`--${boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\n${name}\r\n` +
				`--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="cancel.csv"\r\n` +
				'Content-Type: text/csv\r\n\r\nid,value\n'
		);
		const sendChunks = async (): Promise<void> => {
			for (let index = 0; index < 3; index += 1) {
				upload.write(Buffer.alloc(1024 * 1024, 120));
				await new Promise((resolve) => setTimeout(resolve, 80));
			}
			upload.destroy(new Error('E2E upload cancelled'));
		};
		await Promise.all([cancelled, sendChunks()]);
		const list = await page.context().request.get('/api/v1/datasource', {
			headers: { 'X-Namespace': process.env.DEFAULT_NAMESPACE ?? 'default' }
		});
		expect(list.ok()).toBeTruthy();
		const datasources = (await list.json()) as Array<{ name: string }>;
		expect(datasources.some((datasource) => datasource.name === name)).toBeFalsy();
	});

	test('chat turns persist once and broadcast ordered events to independent subscribers', async ({
		browser,
		page,
		request
	}) => {
		await page.goto('/');
		const fixtureUrl = process.env.E2E_OPENAI_FIXTURE_URL;
		if (!fixtureUrl) throw new Error('E2E_OPENAI_FIXTURE_URL was not provided by the harness');
		const settings = await page.context().request.put('/api/v1/settings', {
			data: { openai_endpoint_url: fixtureUrl.replace(/\/v1$/, '') }
		});
		expect(settings.ok()).toBeTruthy();

		const sessionId = await createChatSession(page, `e2e-chat-${randomUUID()}`);
		const streamsReady = waitForChatStreams(page, sessionId, 2);
		const streams = readChatStreams(page, sessionId, 2);
		await streamsReady;

		const body = { session_id: sessionId, content: '[e2e-delay] persisted user message' };
		const firstContext = await browser.newContext({
			baseURL: request.baseURL,
			storageState: request.sessionState
		});
		const duplicateContext = await browser.newContext({
			baseURL: request.baseURL,
			storageState: request.sessionState
		});
		const results = await Promise.all([
			firstContext.request.post('/api/v1/ai/chat/message', {
				headers: { Connection: 'close' },
				data: body
			}),
			duplicateContext.request.post('/api/v1/ai/chat/message', {
				headers: { Connection: 'close' },
				data: body
			})
		]);
		const statuses = results.map((response) => response.status());
		await Promise.all([firstContext.close(), duplicateContext.close()]);
		expect(statuses.filter((status) => status === 200)).toHaveLength(1);
		expect(statuses.filter((status) => status === 409)).toHaveLength(1);

		const [eventsA, eventsB] = await streams;
		expect(eventsB).toEqual(eventsA);
		expect(eventsA.at(-1)?.data.type).toBe('done');
		const eventIds = eventsA.map((event) => Number(event.id));
		expect(eventIds.length).toBeGreaterThan(0);
		expect(eventIds.every(Number.isSafeInteger)).toBeTruthy();
		expect(eventIds).toEqual([...eventIds].sort((left, right) => left - right));
		expect(new Set(eventIds).size).toBe(eventIds.length);
		expect(
			eventsA.filter((event) => event.data.type === 'message' && event.data.role === 'user')
		).toHaveLength(1);

		const historyResponse = await page
			.context()
			.request.get(`/api/v1/ai/chat/history/${sessionId}`);
		expect(historyResponse.ok()).toBeTruthy();
		const history = (await historyResponse.json()) as {
			history: ChatEvent[];
			last_event_id: number;
		};
		expect(history.last_event_id).toBe(eventIds.at(-1));
		expect(
			history.history.some((event) => event.type === 'message' && event.role === 'assistant')
		).toBeTruthy();

		const replay = await readChatStreams(page, sessionId, 1, eventIds[0] ?? 0);
		expect(replay[0]).toEqual(eventsA.slice(1));
	});

	test('chat stop crosses API connections without delaying another stream heartbeat', async ({
		browser,
		page,
		request
	}) => {
		await page.goto('/');
		const fixtureUrl = process.env.E2E_OPENAI_FIXTURE_URL;
		if (!fixtureUrl) throw new Error('E2E_OPENAI_FIXTURE_URL was not provided by the harness');
		const settings = await page.context().request.put('/api/v1/settings', {
			data: { openai_endpoint_url: fixtureUrl.replace(/\/v1$/, '') }
		});
		expect(settings.ok()).toBeTruthy();

		const slowSession = await createChatSession(page, `e2e-stop-${randomUUID()}`);
		const idleSession = await createChatSession(page, `e2e-heartbeat-${randomUUID()}`);
		const slowStreamReady = page.waitForResponse((response) =>
			isChatStreamResponse(slowSession, response.url())
		);
		const events = readChatStreams(page, slowSession, 1);
		await slowStreamReady;
		const apiContext = await browser.newContext({
			baseURL: request.baseURL,
			storageState: request.sessionState
		});
		try {
			const send = await apiContext.request.post('/api/v1/ai/chat/message', {
				headers: { Connection: 'close' },
				data: { session_id: slowSession, content: '[e2e-heartbeat] stop this slow response' }
			});
			expect(send.ok()).toBeTruthy();

			const heartbeatReady = page.waitForResponse((response) =>
				isChatStreamResponse(idleSession, response.url())
			);
			const heartbeat = waitForChatHeartbeat(page, idleSession);
			await heartbeatReady;
			const startedAt = Date.now();
			const settingsRead = await apiContext.request.get('/api/v1/settings', {
				headers: { Connection: 'close' }
			});
			expect(settingsRead.ok()).toBeTruthy();
			expect(Date.now() - startedAt).toBeLessThan(5_000);
			expect(await heartbeat).toBeTruthy();

			const stop = await apiContext.request.post(`/api/v1/ai/chat/sessions/${slowSession}/stop`, {
				headers: { Connection: 'close' }
			});
			expect(stop.ok()).toBeTruthy();
		} finally {
			await apiContext.close();
		}

		const [slowEvents] = await events;
		expect(slowEvents.at(-1)?.data.type).toBe('done');
		expect(
			slowEvents.some(
				(event) => event.data.type === 'error' && event.data.content === 'Generation stopped'
			)
		).toBeTruthy();
	});
});
