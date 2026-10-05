import { randomUUID } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { request as httpRequest } from 'node:http';
import type { Page } from '@playwright/test';
import { expect, test } from './fixtures.js';
import { createCsvDatasource, deleteDatasource } from './utils/api.js';
import { waitForLayoutReady } from './utils/readiness.js';

type ChatEvent = { type: string; [key: string]: unknown };
type SseEvent = { id: string; data: ChatEvent };
function chatDatabaseContainer(): string {
	const deploymentId = process.env.E2E_DEPLOYMENT_ID;
	if (!deploymentId) throw new Error('E2E_DEPLOYMENT_ID was not provided by the owned test recipe');
	const result = execFileSync(
		'docker',
		[
			'ps',
			'--filter',
			`label=com.docker.compose.project=${deploymentId}`,
			'--filter',
			'label=com.docker.compose.service=postgres',
			'--format',
			'{{.ID}}'
		],
		{ encoding: 'utf8' }
	);
	const containers = result.trim().split('\n');
	if (containers.length !== 1 || !containers[0])
		throw new Error('Expected the owned E2E PostgreSQL container');
	return containers[0];
}

function chatTurnState(containerId: string, sessionId: string): string {
	if (!/^[A-Za-z0-9_-]+$/.test(sessionId)) throw new Error('Invalid owned chat session ID');
	const result = execFileSync(
		'docker',
		[
			'exec',
			containerId,
			'psql',
			'-U',
			'dataforge',
			'-d',
			'dataforge',
			'-At',
			'-c',
			`SELECT status || ':' || COALESCE(checkpoint ->> 'phase', '') FROM public.chat_turns WHERE session_id = '${sessionId}' ORDER BY created_at DESC LIMIT 1`
		],
		{ encoding: 'utf8' }
	);
	return result.trim();
}

async function readChatStreams(
	page: Page,
	sessionId: string,
	count: number,
	after = 0,
	stopAfter: 'done' | 'turn_start' | 'user_message' = 'done'
): Promise<SseEvent[][]> {
	return page.evaluate(
		async ({ sessionId, count, after, stopAfter }) => {
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
							if (
								event.type === 'done' ||
								(stopAfter === 'turn_start' && event.type === 'turn_start') ||
								(stopAfter === 'user_message' && event.type === 'message' && event.role === 'user')
							) {
								await reader.cancel();
								return events;
							}
						}
					}
				})
			);
		},
		{ sessionId, count, after, stopAfter }
	);
}

async function createChatSession(page: Page, model: string): Promise<string> {
	const response = await page.context().request.post('/api/v1/ai/chat/sessions', {
		data: { provider: 'openrouter', model, api_key: 'e2e-provider-key' }
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

	test('chat stream helper serializes the default completion and early turn gate', async ({
		page
	}) => {
		await page.goto('/');
		const sessionId = `e2e-stream-helper-${randomUUID()}`;
		const events: SseEvent[] = [
			{ id: '1', data: { type: 'message', role: 'user', content: 'start' } },
			{ id: '2', data: { type: 'turn_start', turn: 1 } },
			{ id: '3', data: { type: 'message', role: 'assistant', content: 'finished' } },
			{ id: '4', data: { type: 'done' } }
		];
		await page.route(`**/api/v1/ai/chat/stream/${sessionId}?after=*`, (route) =>
			route.fulfill({
				contentType: 'text/event-stream',
				body: events
					.map((event) => `id: ${event.id}\ndata: ${JSON.stringify(event.data)}\n\n`)
					.join('')
			})
		);
		expect(await readChatStreams(page, sessionId, 2)).toEqual([events, events]);
		expect(await readChatStreams(page, sessionId, 1, 0, 'turn_start')).toEqual([
			events.slice(0, 2)
		]);
	});

	test('fresh API connections consume the current projected AI provider settings', async ({
		browser,
		page,
		request
	}) => {
		const settingsResponse = await page.context().request.get('/api/v1/settings');
		expect(settingsResponse.ok()).toBeTruthy();
		const original = (await settingsResponse.json()) as Record<string, unknown>;
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
		if (!fixtureUrl) throw new Error('E2E_OPENAI_FIXTURE_URL was not provided by the harness');

		const fixtureCheck = await page.context().request.get(`${fixtureUrl}/models`);
		expect(fixtureCheck.ok()).toBeTruthy();
		const settingsUpdate = {
			openrouter_api_key: 'e2e-provider-key',
			public_idb_debug: !original.public_idb_debug,
			openrouter_default_model: model
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
						const readSettings = (await read.json()) as { openrouter_default_model: string };
						expect(readSettings.openrouter_default_model).toBe(model);
						return { pid, debug, model: readSettings.openrouter_default_model };
					})
				);
				const configuredApiWorkers = process.env.E2E_API_WORKERS?.trim();
				const apiWorkers = Number(configuredApiWorkers || '4');
				expect(Number.isInteger(apiWorkers) && apiWorkers > 0).toBeTruthy();
				if (apiWorkers > 1) {
					const otherApiReader = observations.find(({ pid }) => pid !== writerApiPid);
					expect(otherApiReader).toBeDefined();
					expect(otherApiReader).toMatchObject({
						debug: !original.public_idb_debug,
						model
					});
				}
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
							provider: 'openrouter'
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
					openrouter_api_key: '',
					public_idb_debug: original.public_idb_debug,
					openrouter_default_model: original.openrouter_default_model
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

	test('deleting a session during a durable turn does not disrupt the runtime', async ({
		browser,
		page,
		request
	}) => {
		await page.goto('/');
		const datasourceId = await createCsvDatasource(
			request,
			`e2e-chat-delete-preview-${randomUUID()}`,
			'id,value\n1,while-chat-runs\n'
		);
		const sessionId = await createChatSession(page, `e2e-chat-delete-${randomUUID()}`);
		const apiContext = await browser.newContext({
			baseURL: request.baseURL,
			storageState: request.sessionState
		});
		let turnActive = false;
		let lastEventId = 0;
		let sessionDeleted = false;
		try {
			const databaseContainer = await chatDatabaseContainer();
			const slowContent = '[e2e-heartbeat] hold this durable turn';
			const send = await apiContext.request.post('/api/v1/ai/chat/message', {
				headers: { Connection: 'close' },
				data: { session_id: sessionId, content: slowContent }
			});
			expect(send.ok(), await send.text()).toBeTruthy();
			turnActive = true;

			const [startedEvents] = await readChatStreams(page, sessionId, 1, 0, 'user_message');
			expect(
				startedEvents.some((event) => event.data.type === 'message' && event.data.role === 'user')
			).toBeTruthy();
			const userEvent = startedEvents.find(
				(event) => event.data.type === 'message' && event.data.role === 'user'
			);
			if (!userEvent) throw new Error('The durable chat turn did not emit its user message');
			lastEventId = Number(userEvent.id);
			await expect
				.poll(() => chatTurnState(databaseContainer, sessionId))
				.toBe('running:provider_request');

			const deletion = await apiContext.request.delete(`/api/v1/ai/chat/sessions/${sessionId}`, {
				headers: { Connection: 'close' }
			});
			expect(deletion.status()).toBe(409);
			expect(await deletion.json()).toMatchObject({
				detail: 'Cannot delete a chat session while a turn is active'
			});
			const stillPresent = await apiContext.request.get('/api/v1/ai/chat/sessions', {
				headers: { Connection: 'close' }
			});
			expect(stillPresent.ok()).toBeTruthy();
			expect(
				((await stillPresent.json()) as Array<{ id?: string; session_id?: string }>).some(
					(session) => (session.id ?? session.session_id) === sessionId
				)
			).toBeTruthy();

			const pipeline = {
				analysis_id: randomUUID(),
				tabs: [
					{
						id: randomUUID(),
						name: 'Source',
						datasource: {
							id: datasourceId,
							analysis_tab_id: null,
							config: { branch: 'master' }
						},
						output: { result_id: randomUUID(), filename: 'source', format: 'parquet' },
						steps: []
					}
				]
			};
			const preview = await apiContext.request.post('/api/v1/compute/preview', {
				headers: { 'X-Namespace': process.env.DEFAULT_NAMESPACE ?? 'default' },
				data: {
					datasource_id: datasourceId,
					target_step_id: 'source',
					analysis_pipeline: pipeline,
					row_limit: 1,
					page: 1
				}
			});
			expect(preview.ok(), await preview.text()).toBeTruthy();
			expect((await preview.json()).data[0]?.value).toBe('while-chat-runs');
			expect(await chatTurnState(databaseContainer, sessionId)).toBe('running:provider_request');

			const stop = await apiContext.request.post(`/api/v1/ai/chat/sessions/${sessionId}/stop`, {
				headers: { Connection: 'close' }
			});
			expect(stop.ok()).toBeTruthy();
			const stoppedEvents = await readChatStreams(page, sessionId, 1, Number(userEvent.id));
			const terminalEvents = stoppedEvents[0] ?? [];
			expect(terminalEvents.at(-1)?.data.type).toBe('done');
			expect(
				terminalEvents.some(
					(event) => event.data.type === 'error' && event.data.content === 'Generation stopped'
				)
			).toBeTruthy();
			turnActive = false;

			const afterStop = terminalEvents.at(-1);
			if (!afterStop) throw new Error('The stopped chat turn did not emit a terminal event');
			lastEventId = Number(afterStop.id);
			const nextStreamReady = page.waitForResponse((response) =>
				isChatStreamResponse(sessionId, response.url())
			);
			const nextEvents = readChatStreams(page, sessionId, 1, Number(afterStop.id));
			await nextStreamReady;
			const nextTurn = await apiContext.request.post('/api/v1/ai/chat/message', {
				headers: { Connection: 'close' },
				data: { session_id: sessionId, content: 'a later turn still works' }
			});
			expect(nextTurn.ok(), await nextTurn.text()).toBeTruthy();
			turnActive = true;
			const [laterEvents] = await nextEvents;
			expect(laterEvents?.at(-1)?.data.type).toBe('done');
			expect(
				laterEvents?.some(
					(event) =>
						event.data.type === 'message' &&
						event.data.role === 'assistant' &&
						event.data.content === 'E2E fixture reply: a later turn still works'
				)
			).toBeTruthy();
			lastEventId = Number(laterEvents?.at(-1)?.id ?? lastEventId);
			turnActive = false;

			const idleDelete = await apiContext.request.delete(`/api/v1/ai/chat/sessions/${sessionId}`, {
				headers: { Connection: 'close' }
			});
			expect(idleDelete.ok()).toBeTruthy();
			sessionDeleted = true;
		} finally {
			if (turnActive) {
				await apiContext.request.post(`/api/v1/ai/chat/sessions/${sessionId}/stop`, {
					headers: { Connection: 'close' }
				});
				await readChatStreams(page, sessionId, 1, lastEventId);
			}
			if (!sessionDeleted) {
				await apiContext.request.delete(`/api/v1/ai/chat/sessions/${sessionId}`, {
					headers: { Connection: 'close' }
				});
			}
			await apiContext.close();
			await deleteDatasource(request, datasourceId);
		}
	});

	test('OpenRouter chat uses the key copied into settings, then a key saved from the profile', async ({
		page
	}, testInfo) => {
		testInfo.setTimeout(240_000);
		if (!process.env.E2E_OPENROUTER_API_KEY?.trim()) {
			throw new Error('E2E_OPENROUTER_API_KEY was not provided by the harness');
		}
		await page.goto('/');
		const settingsResponse = await page.context().request.get('/api/v1/settings');
		expect(settingsResponse.ok()).toBeTruthy();
		const original = (await settingsResponse.json()) as { openrouter_default_model?: string };
		const model = 'z-ai/glm-5.3-flash';
		const sessionIds: string[] = [];

		async function chatOutcome(waitMs: number): Promise<{ outcome: string; assistant: string }> {
			const sessionResponse = await page.context().request.post('/api/v1/ai/chat/sessions', {
				data: { provider: 'openrouter', model, api_key: '' }
			});
			expect(sessionResponse.ok(), await sessionResponse.text()).toBeTruthy();
			const sessionId = ((await sessionResponse.json()) as { session_id: string }).session_id;
			sessionIds.push(sessionId);
			const send = await page.context().request.post('/api/v1/ai/chat/message', {
				data: {
					session_id: sessionId,
					content: 'Reply with the single word pong.',
					tool_ids: ['e2e-no-tools']
				}
			});
			expect(send.ok(), await send.text()).toBeTruthy();
			const deadline = Date.now() + waitMs;
			let outcome = 'pending';
			let assistant = '';
			while (Date.now() < deadline && outcome === 'pending') {
				const historyResponse = await page
					.context()
					.request.get(`/api/v1/ai/chat/history/${sessionId}`);
				if (historyResponse.ok()) {
					const history = (await historyResponse.json()) as { history: ChatEvent[] };
					for (const event of history.history) {
						if (event.type === 'error') {
							outcome = `error:${String(event.content ?? '')}`;
							break;
						}
						if (
							event.type === 'message' &&
							event.role === 'assistant' &&
							String(event.content ?? '').trim().length > 0
						) {
							assistant = String(event.content);
							outcome = 'assistant';
							break;
						}
					}
				}
				if (outcome === 'pending') await new Promise((resolve) => setTimeout(resolve, 1_000));
			}
			return { outcome, assistant };
		}

		try {
			const cleared = await page.context().request.put('/api/v1/settings', {
				data: { openrouter_api_key: '', openrouter_default_model: model }
			});
			expect(cleared.ok()).toBeTruthy();
			expect(((await cleared.json()) as { openrouter_api_key?: string }).openrouter_api_key).toBe(
				''
			);

			const populated = await page.context().request.get('/api/v1/settings');
			expect(populated.ok()).toBeTruthy();
			expect(((await populated.json()) as { openrouter_api_key?: string }).openrouter_api_key).toBe(
				'••••••••'
			);

			const live = await chatOutcome(90_000);
			expect(live.outcome).toBe('assistant');
			expect(live.assistant).not.toContain('E2E fixture reply');
			expect(live.assistant.toLowerCase()).toContain('pong');

			const replaced = await page.context().request.put('/api/v1/settings', {
				data: { openrouter_api_key: 'sk-or-replaced-by-profile' }
			});
			expect(replaced.ok()).toBeTruthy();
			expect(((await replaced.json()) as { openrouter_api_key?: string }).openrouter_api_key).toBe(
				'••••••••'
			);

			const changed = await chatOutcome(45_000);
			expect(changed.outcome).toMatch(/^error:/);
			expect(changed.outcome).not.toContain('No API key configured');
			expect(changed.outcome).not.toContain('E2E fixture reply');
			expect(changed.assistant).toBe('');
		} finally {
			for (const sessionId of sessionIds) {
				await page.context().request.post(`/api/v1/ai/chat/sessions/${sessionId}/stop`);
				await page.context().request.delete(`/api/v1/ai/chat/sessions/${sessionId}`);
			}
			const restore = await page.context().request.put('/api/v1/settings', {
				data: {
					openrouter_api_key: '',
					openrouter_default_model: original.openrouter_default_model ?? ''
				}
			});
			expect(restore.ok()).toBeTruthy();
		}
	});
});
