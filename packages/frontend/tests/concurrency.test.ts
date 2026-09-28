import {
	chromium,
	type APIRequestContext,
	type Browser,
	type BrowserContext,
	type Page,
	type Request,
	type TestInfo
} from '@playwright/test';
import { expect, test } from './fixtures.js';
import { E2E_RUN_STAMP } from './utils/api.js';
import { gotoAnalysisEditor } from './utils/analysis.js';
import { e2eBaseURL } from './utils/base-url.js';
import { installE2eContextGuards } from './utils/page-guards.js';
import {
	gotoAuthedRoute,
	readyTimeoutMs,
	waitForDatasourceList,
	waitForDatasourcePreviewReady,
	waitForInlinePreviewReady
} from './utils/readiness.js';
import { deleteAnalysisViaUI } from './utils/ui-cleanup.js';
import { DEFAULT_NAMESPACE } from './utils/namespace.js';
import { E2E_PASSWORD } from './utils/user-flows.js';
import { createRequestTrace, type RequestTrace } from './utils/request-trace.js';

const rawBrowserCount = process.env.E2E_CONCURRENCY_BROWSERS?.trim() ?? '';
const browserCount = rawBrowserCount ? Number.parseInt(rawBrowserCount, 10) : 50;
const accountCount = Math.min(30, browserCount);
const browserTabsPerProcess = 10;
const browserProcessCount = Math.min(browserCount, Math.ceil(browserCount / browserTabsPerProcess));
const authRequired = process.env.AUTH_REQUIRED !== 'false';

if (!Number.isInteger(browserCount) || browserCount < 1) {
	throw new Error(`E2E_CONCURRENCY_BROWSERS must be a positive integer, got "${rawBrowserCount}"`);
}

type LoadAnalysis = {
	id: string;
	name: string;
};

type PageDiagnostics = {
	documentResponses: string[];
	apiResponses: string[];
	previewRequestStarts: string[];
	apiErrorResponses: string[];
	httpErrors: string[];
	failedRequests: string[];
	pageErrors: string[];
	consoleErrors: string[];
	lockEvents: string[];
};

function recordDiagnostic(items: string[], value: string): void {
	if (items.length < 40) items.push(value);
}

function installPageDiagnostics(
	page: Page,
	diagnostics: PageDiagnostics,
	pendingResponseReads: Promise<void>[]
): Map<Request, { startedAt: number; resourceId: string | null }> {
	const pendingPreviewRequests = new Map<
		Request,
		{ startedAt: number; resourceId: string | null }
	>();
	page.on('request', (request) => {
		const path = new URL(request.url()).pathname;
		if (path !== '/api/v1/compute/preview') return;
		const startedAt = Date.now();
		let resourceId: string | null = null;
		try {
			const body = request.postDataJSON() as { analysis_id?: unknown; datasource_id?: unknown };
			const candidate = body.analysis_id ?? body.datasource_id;
			if (typeof candidate === 'string') resourceId = candidate;
		} catch {
			// Keep request-start evidence even if the body is unavailable.
		}
		pendingPreviewRequests.set(request, { startedAt, resourceId });
		recordDiagnostic(
			diagnostics.previewRequestStarts,
			`${request.method()} ${path}${resourceId ? ` resource_id=${resourceId}` : ''}`
		);
	});
	page.on('response', (response) => {
		const request = response.request();
		pendingPreviewRequests.delete(request);
		const path = new URL(response.url()).pathname;
		const summary = `${response.status()} ${request.method()} ${path}`;
		if (
			/^\/api\/v1\/(config|auth\/me|namespaces?|analysis|datasource)(\/|$)/.test(path) ||
			path === '/api/v1/compute/preview'
		) {
			pendingResponseReads.push(
				response
					.allHeaders()
					.then((headers) => {
						const serverDuration = headers['server-timing']?.match(/app;dur=([\d.]+)/)?.[1];
						const requestId = headers['x-request-id'] ?? 'missing';
						const serverTime = serverDuration ? `${serverDuration}ms` : 'missing';
						recordDiagnostic(
							diagnostics.apiResponses,
							`${summary} server_ms=${serverTime} request_id=${requestId}`
						);
					})
					.catch(() =>
						recordDiagnostic(
							diagnostics.apiResponses,
							`${summary} server_ms=unavailable request_id=unavailable`
						)
					)
			);
		}
		if (request.resourceType() === 'document') {
			recordDiagnostic(diagnostics.documentResponses, summary);
		}
		if (response.status() >= 400) {
			recordDiagnostic(diagnostics.httpErrors, summary);
			if (path === '/api/v1/compute/preview') {
				pendingResponseReads.push(
					response
						.text()
						.then((body) =>
							recordDiagnostic(diagnostics.apiErrorResponses, `${summary}: ${body.slice(0, 2_000)}`)
						)
						.catch(() =>
							recordDiagnostic(
								diagnostics.apiErrorResponses,
								`${summary}: <response body unavailable>`
							)
						)
				);
			}
		}
	});
	page.on('requestfailed', (request) => {
		pendingPreviewRequests.delete(request);
		const path = new URL(request.url()).pathname;
		recordDiagnostic(
			diagnostics.failedRequests,
			`${request.method()} ${path}: ${request.failure()?.errorText ?? 'unknown failure'}`
		);
	});
	page.on('pageerror', (error) => recordDiagnostic(diagnostics.pageErrors, error.message));
	page.on('console', (message) => {
		if (message.type() === 'error') recordDiagnostic(diagnostics.consoleErrors, message.text());
	});
	page.on('websocket', (socket) => {
		if (!new URL(socket.url()).pathname.includes('/v1/locks/ws')) return;
		socket.on('framereceived', ({ payload }) => {
			try {
				const message = JSON.parse(String(payload)) as Record<string, unknown>;
				if (message.type === 'status') {
					const lock =
						typeof message.lock === 'object' && message.lock !== null
							? (message.lock as Record<string, unknown>)
							: null;
					recordDiagnostic(
						diagnostics.lockEvents,
						JSON.stringify({
							resource_id: message.resource_id,
							owner_id: lock?.owner_id ?? null
						})
					);
				} else if (message.type === 'error') {
					recordDiagnostic(
						diagnostics.lockEvents,
						JSON.stringify({ status_code: message.status_code, error: message.error })
					);
				}
			} catch {
				// Ignore protocol frames that aren't JSON lock messages.
			}
		});
	});
	return pendingPreviewRequests;
}

async function capturePageState(
	page: Page,
	index: number,
	datasourceName: string
): Promise<unknown> {
	const snapshot = page.evaluate((targetDatasourceName) => {
		const describe = (element: Element | null) => {
			if (!element) return null;
			const rect = element.getBoundingClientRect();
			const style = getComputedStyle(element);
			return {
				tag: element.tagName,
				text: element.textContent?.trim().slice(0, 300) ?? '',
				rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
				display: style.display,
				visibility: style.visibility,
				opacity: style.opacity,
				interactive: element.getAttribute('data-shell-interactive'),
				state: element.getAttribute('data-preview-state'),
				ready: element.getAttribute('data-preview-ready'),
				outerHTML: element.outerHTML.slice(0, 1_000)
			};
		};
		const datasourceRow = Array.from(document.querySelectorAll('[data-ds-row]')).find(
			(element) => element.getAttribute('data-ds-row') === targetDatasourceName
		);
		const rowRect = datasourceRow?.getBoundingClientRect();
		const hitTarget = rowRect
			? document.elementFromPoint(rowRect.x + rowRect.width / 2, rowRect.y + rowRect.height / 2)
			: null;
		return {
			readyState: document.readyState,
			visibilityState: document.visibilityState,
			title: document.title,
			bodyText: document.body?.innerText.slice(0, 1_200) ?? '',
			navigation: describe(document.querySelector('[aria-label="Main navigation"]')),
			main: describe(document.querySelector('main')),
			analysisEditor: describe(
				document.querySelector('[role="application"][data-editor-access-state]')
			),
			preview: describe(
				document.querySelector(
					'[data-testid="inline-data-table"], [data-testid="datasource-preview"]'
				)
			),
			datasourceRow: describe(datasourceRow ?? null),
			datasourceRowHitTarget: hitTarget
				? { tag: hitTarget.tagName, text: hitTarget.textContent?.trim().slice(0, 120) ?? '' }
				: null,
			resourceCount: performance.getEntriesByType('resource').length
		};
	}, datasourceName);
	const timeout = new Promise<unknown>((resolve) =>
		setTimeout(() => resolve({ snapshotError: 'page evaluation exceeded 2 seconds' }), 2_000)
	);
	return { index, url: page.url(), ...((await Promise.race([snapshot, timeout])) as object) };
}

async function createLoadAnalysis(
	request: APIRequestContext,
	datasourceId: string,
	index: number
): Promise<LoadAnalysis> {
	const name = `E2E Load Analysis ${E2E_RUN_STAMP} ${index}`;
	const datasourceRef = `load-source-${E2E_RUN_STAMP}-${index}`;
	const filterStepId = crypto.randomUUID();
	const viewStepId = crypto.randomUUID();
	const tabId = crypto.randomUUID();
	const outputId = crypto.randomUUID();
	const pipeline = {
		tabs: [
			{
				id: tabId,
				name: `Account ${index + 1} data`,
				parent_id: null,
				datasource: {
					id: datasourceRef,
					analysis_tab_id: null,
					config: { branch: 'master' }
				},
				output: {
					result_id: outputId,
					datasource_type: 'iceberg',
					format: 'parquet',
					filename: `load_analysis_${index}`,
					build_mode: 'full',
					iceberg: {
						namespace: 'outputs',
						table_name: `load_analysis_${index}`,
						branch: 'master'
					}
				},
				steps: [
					{
						id: filterStepId,
						type: 'filter',
						config: {
							conditions: [
								{ column: 'age', operator: '>', value: String(20 + index), value_type: 'number' }
							],
							logic: 'AND'
						},
						depends_on: [],
						is_applied: true
					},
					{
						id: viewStepId,
						type: 'view',
						config: {},
						depends_on: [filterStepId],
						is_applied: true
					}
				]
			}
		]
	};
	const response = await request.post('/api/v1/analysis/import', {
		headers: { 'X-Namespace': DEFAULT_NAMESPACE },
		data: {
			name,
			pipeline,
			datasource_remap: { [datasourceRef]: datasourceId }
		}
	});
	if (!response.ok()) {
		throw new Error(
			`Failed to create load analysis ${name}: HTTP ${response.status()} ${await response.text()}`
		);
	}
	const created = (await response.json()) as { id?: unknown };
	if (typeof created.id !== 'string') {
		throw new Error(`Analysis import returned no id for ${name}`);
	}
	const id = created.id;
	return { id, name };
}

test.describe('Concurrent authenticated browser sessions', () => {
	test.describe.configure({ mode: 'parallel' });

	test(`runs ${browserCount} parallel tabs across ${accountCount} accounts`, async ({
		browser,
		workerAuth,
		sharedDatasource
	}, testInfo: TestInfo) => {
		// This probe creates up to 30 authenticated accounts and analyses before
		// starting its synchronized tab burst. Keep one no-retry test deadline
		// large enough for setup, measured readiness, and deterministic cleanup;
		// the per-stage readiness deadlines still fail stalled pages promptly.
		testInfo.setTimeout(300_000);
		const baseURL = e2eBaseURL();
		const probeBrowsers: Browser[] = [browser];
		const accountContexts: BrowserContext[] = [];
		const analyses: LoadAnalysis[] = [];
		let pages: Page[] = [];
		const requestTracesByPage = new Map<Page, RequestTrace | null>();
		const previewBodiesByPage = new Map<Page, string[]>();
		const diagnosticsByPage = new Map<Page, PageDiagnostics>();
		const pendingResponseReadsByPage = new Map<Page, Promise<void>[]>();
		const pendingPreviewRequestsByPage = new Map<
			Page,
			Map<Request, { startedAt: number; resourceId: string | null }>
		>();

		let probeFailure: unknown;
		try {
			// Keep the API burst at 50 simultaneous pages, but spread rendering and
			// response draining across browser processes instead of measuring one
			// Chromium process's ability to service 50 cold pages at once.
			const additionalBrowsers = await Promise.all(
				Array.from({ length: browserProcessCount - 1 }, () =>
					chromium.launch(testInfo.project.use.launchOptions)
				)
			);
			probeBrowsers.push(...additionalBrowsers);

			for (let index = 0; index < accountCount; index += 1) {
				const accountBrowser = probeBrowsers[index % browserProcessCount] ?? browser;
				const context =
					index === 0
						? await accountBrowser.newContext({ baseURL, storageState: workerAuth.sessionState })
						: await accountBrowser.newContext({ baseURL });
				accountContexts.push(context);
				installE2eContextGuards(context);

				if (index > 0 && authRequired) {
					const response = await context.request.post('/api/v1/auth/register', {
						data: {
							email: `e2e-load-${E2E_RUN_STAMP}-account-${index}@example.com`,
							password: E2E_PASSWORD,
							display_name: `E2E Load Account ${index + 1}`
						}
					});
					if (!response.ok()) {
						throw new Error(
							`Failed to create load account ${index + 1}: HTTP ${response.status()} ${(
								await response.text()
							).slice(0, 500)}`
						);
					}
				}
			}

			if (authRequired) {
				const sessionTokens = await Promise.all(
					accountContexts.map(async (context) => {
						const cookie = (await context.cookies(baseURL)).find(
							(item) => item.name === 'session_token'
						);
						return cookie?.value ?? '';
					})
				);
				expect(new Set(sessionTokens).size).toBe(accountCount);
			}

			for (let index = 0; index < accountCount; index += 1) {
				analyses.push(
					await createLoadAnalysis(accountContexts[index].request, sharedDatasource.id, index)
				);
			}

			pages = await Promise.all(
				Array.from({ length: browserCount }, (_, index) =>
					accountContexts[index % accountCount].newPage()
				)
			);
			pages.forEach((page, index) => {
				requestTracesByPage.set(
					page,
					createRequestTrace(
						page,
						testInfo.workerIndex,
						`${testInfo.title} tab ${index}`,
						`${testInfo.testId}-tab-${index}`
					)
				);
			});
			const analysisPages = pages.slice(0, accountCount);
			const datasourcePages = pages.slice(accountCount);
			for (const page of pages) {
				const bodies: string[] = [];
				const diagnostics: PageDiagnostics = {
					documentResponses: [],
					apiResponses: [],
					previewRequestStarts: [],
					apiErrorResponses: [],
					httpErrors: [],
					failedRequests: [],
					pageErrors: [],
					consoleErrors: [],
					lockEvents: []
				};
				const pendingResponseReads: Promise<void>[] = [];
				previewBodiesByPage.set(page, bodies);
				diagnosticsByPage.set(page, diagnostics);
				pendingResponseReadsByPage.set(page, pendingResponseReads);
				pendingPreviewRequestsByPage.set(
					page,
					installPageDiagnostics(page, diagnostics, pendingResponseReads)
				);
				page.on('request', (request) => {
					if (!request.url().endsWith('/api/v1/compute/preview')) return;
					const body = request.postData();
					if (body) bodies.push(body);
				});
			}

			// Start all 30 distinct analysis transforms and all shared datasource
			// previews together, so the probe measures the mixed 50-tab burst.
			const navigationResults = await Promise.allSettled([
				...analysisPages.map(async (page, index) => {
					try {
						await gotoAnalysisEditor(page, analyses[index].id, readyTimeoutMs());
					} catch (error) {
						throw new Error(`analysis tab ${index} editor navigation failed: ${String(error)}`, {
							cause: error
						});
					}
				}),
				...datasourcePages.map(async (page, index) => {
					const tabIndex = accountCount + index;
					try {
						// Opening the datasource route by ID selects the same UI preview as
						// clicking its row, without making a saturated 50-page browser spend
						// the navigation phase on 20 pointer-action acknowledgements.
						await gotoAuthedRoute(page, `/datasources/${sharedDatasource.id}`, readyTimeoutMs());
						await waitForDatasourceList(page, readyTimeoutMs());
					} catch (error) {
						throw new Error(`datasource tab ${tabIndex} page navigation failed: ${String(error)}`, {
							cause: error
						});
					}
				})
			]);
			const navigationFailures = navigationResults
				.filter((result): result is PromiseRejectedResult => result.status === 'rejected')
				.map((result) => result.reason);
			if (navigationFailures.length > 0) {
				throw new AggregateError(
					navigationFailures,
					`Load probe navigation failed in ${navigationFailures.length} of ${browserCount} tabs`
				);
			}

			const previewResults = await Promise.allSettled([
				...analysisPages.map((page) => waitForInlinePreviewReady(page, 120_000)),
				...datasourcePages.map(async (page) => {
					await waitForDatasourcePreviewReady(page, 120_000);
					await expect(
						page.locator('[data-preview-ready="true"]').getByText('Alice', { exact: true })
					).toBeVisible();
					await expect(page.locator('[data-column-id="id"]')).toBeVisible();
				})
			]);
			const previewFailures = previewResults
				.filter((result): result is PromiseRejectedResult => result.status === 'rejected')
				.map((result) => result.reason);
			if (previewFailures.length > 0) {
				throw new AggregateError(
					previewFailures,
					`Load probe previews failed in ${previewFailures.length} of ${browserCount} tabs`
				);
			}
			await Promise.all([...pendingResponseReadsByPage.values()].flat());
			const tabApiResponsesByPage = new Map(
				pages.map((page) => [page, [...(diagnosticsByPage.get(page)?.apiResponses ?? [])]])
			);
			const tabComputePreviewResponses = [...tabApiResponsesByPage.values()]
				.flat()
				.filter((response) => response.includes('/api/v1/compute/preview'));
			expect(
				tabComputePreviewResponses.every((response) =>
					/server_ms=[\d.]+ms request_id=\S+/.test(response)
				),
				'Preview diagnostics must contain API timing and request IDs'
			).toBe(true);

			const datasourcePreviewBodies = datasourcePages.flatMap(
				(page) => previewBodiesByPage.get(page) ?? []
			);
			if (datasourcePages.length > 0) {
				expect(datasourcePreviewBodies).toHaveLength(datasourcePages.length);
				expect(new Set(datasourcePreviewBodies).size).toBe(1);
			}
			const distinctDatasourceCommands = new Set(datasourcePreviewBodies).size;

			const templateBody =
				(datasourcePages.length > 0
					? previewBodiesByPage.get(datasourcePages[0])?.[0]
					: previewBodiesByPage.get(analysisPages[0])?.[0]) ?? '';
			if (!templateBody) throw new Error('No preview request body was captured by the load probe');
			const template = JSON.parse(templateBody) as Record<string, unknown>;
			const workPages = datasourcePages.length > 0 ? datasourcePages : analysisPages;
			const distinctResponses = await Promise.all(
				[1, 2].map((rowLimit, index) =>
					workPages[index % workPages.length].evaluate(
						async (body) => {
							const response = await fetch('/api/v1/compute/preview', {
								method: 'POST',
								headers: { 'content-type': 'application/json' },
								body: JSON.stringify(body)
							});
							const payload = (await response.json()) as { data?: unknown[] };
							return { status: response.status, rowCount: payload.data?.length ?? null };
						},
						{ ...template, page: 1, row_limit: rowLimit }
					)
				)
			);
			expect(distinctResponses.map(({ status }) => status)).toEqual([200, 200]);
			expect(distinctResponses.map(({ rowCount }) => rowCount)).toEqual([1, 2]);

			const previewLatenciesForPages = (selectedPages: Page[]): number[] =>
				selectedPages
					.flatMap((page) => tabApiResponsesByPage.get(page) ?? [])
					.filter((response) => response.includes('/api/v1/compute/preview'))
					.map((response) => Number(response.match(/ server_ms=([\d.]+)ms /)?.[1]))
					.filter(Number.isFinite)
					.sort((left, right) => left - right);
			const percentile = (latencies: number[], fraction: number): number | null =>
				latencies.length === 0
					? null
					: (latencies[Math.ceil(latencies.length * fraction) - 1] ?? null);
			const allPreviewLatencies = previewLatenciesForPages(pages);
			const analysisPreviewLatencies = previewLatenciesForPages(analysisPages);
			const datasourcePreviewLatencies = previewLatenciesForPages(datasourcePages);
			const loadMetrics = {
				browserTabs: browserCount,
				accounts: accountCount,
				browserProcesses: probeBrowsers.length,
				previewTimingSource: 'API Server-Timing app;dur',
				computePreviewResponses: tabComputePreviewResponses.length,
				previewP50Ms: percentile(allPreviewLatencies, 0.5),
				previewP95Ms: percentile(allPreviewLatencies, 0.95),
				previewMaxMs: allPreviewLatencies.at(-1) ?? null,
				analysisPreviewP50Ms: percentile(analysisPreviewLatencies, 0.5),
				analysisPreviewP95Ms: percentile(analysisPreviewLatencies, 0.95),
				datasourcePreviewP50Ms: percentile(datasourcePreviewLatencies, 0.5),
				datasourcePreviewP95Ms: percentile(datasourcePreviewLatencies, 0.95),
				commandIsolationRowCounts: distinctResponses.map(({ rowCount }) => rowCount),
				distinctDatasourceCommands
			};
			await testInfo.attach('load-probe-metrics', {
				body: JSON.stringify(loadMetrics, null, 2),
				contentType: 'application/json'
			});
			console.info(`[load-probe-metrics] ${JSON.stringify(loadMetrics)}`);
		} catch (error) {
			probeFailure = error;
			await Promise.all([...pendingResponseReadsByPage.values()].flat());
			const browserDiagnostics = await Promise.all(
				pages.map(async (page, index) => {
					const pendingPreviewRequests = [...(pendingPreviewRequestsByPage.get(page) ?? [])].map(
						([_request, pending]) => ({
							resourceId: pending.resourceId,
							startedMsAgo: Date.now() - pending.startedAt
						})
					);
					return {
						...((await capturePageState(page, index, sharedDatasource.name)) as object),
						...diagnosticsByPage.get(page),
						pendingPreviewRequests
					};
				})
			);
			const accountUserIds = await Promise.all(
				accountContexts.map(async (context) => {
					try {
						const response = await context.request.get('/api/v1/auth/me');
						if (!response.ok()) return null;
						const user = (await response.json()) as { id?: unknown };
						return typeof user.id === 'string' ? user.id : null;
					} catch {
						return null;
					}
				})
			);
			const analysisLockDiagnostics = await Promise.all(
				analyses.map(async (analysis, index) => {
					try {
						const response = await accountContexts[index].request.get(
							`/api/v1/locks/analysis/${encodeURIComponent(analysis.id)}`,
							{ headers: { 'X-Namespace': DEFAULT_NAMESPACE } }
						);
						if (!response.ok()) return { index, status: response.status() };
						const lock = (await response.json()) as { owner_id?: unknown } | null;
						const lockOwnerId = typeof lock?.owner_id === 'string' ? lock.owner_id : null;
						return {
							index,
							lockOwnerAccountIndex: lockOwnerId ? accountUserIds.indexOf(lockOwnerId) : -1,
							lockOwnedByExpectedAccount: lockOwnerId === accountUserIds[index]
						};
					} catch (error) {
						return { index, error: String(error) };
					}
				})
			);
			await testInfo
				.attach('load-probe-analysis-locks', {
					body: JSON.stringify(analysisLockDiagnostics, null, 2),
					contentType: 'application/json'
				})
				.catch((attachError: unknown) => {
					console.error(`Could not attach analysis-lock diagnostics: ${String(attachError)}`);
				});
			await testInfo
				.attach('load-probe-browser-diagnostics', {
					body: JSON.stringify(browserDiagnostics, null, 2),
					contentType: 'application/json'
				})
				.catch((attachError: unknown) => {
					console.error(`Could not attach load-probe diagnostics: ${String(attachError)}`);
				});
			const summary = browserDiagnostics.map((diagnostic) => {
				const page = diagnostic as {
					index: number;
					url: string;
					analysisEditor?: { interactive?: string | null } | null;
					preview?: { state?: string | null; ready?: string | null } | null;
					documentResponses: string[];
					apiResponses: string[];
					previewRequestStarts: string[];
					pendingPreviewRequests: Array<{ resourceId: string | null; startedMsAgo: number }>;
					httpErrors: string[];
					failedRequests: string[];
					pageErrors: string[];
					lockEvents: string[];
				};
				return {
					index: page.index,
					path: new URL(page.url).pathname,
					editor: page.analysisEditor?.interactive ?? null,
					previewState: page.preview?.state ?? null,
					previewReady: page.preview?.ready ?? null,
					previewRequestStarts: page.previewRequestStarts,
					pendingPreviewRequests: page.pendingPreviewRequests,
					documentResponses: page.documentResponses,
					apiResponses: page.apiResponses.filter((response) =>
						response.includes('/compute/preview')
					),
					httpErrors: page.httpErrors,
					failedRequests: page.failedRequests,
					pageErrors: page.pageErrors,
					lockEvents: page.lockEvents
				};
			});
			console.error(`[load-probe-browser-summary] ${JSON.stringify(summary)}`);
		}

		const cleanupFailures: unknown[] = [];
		await Promise.all(
			pages.map(async (page) => {
				if (page.isClosed()) return;
				await page.close().catch((error: unknown) => cleanupFailures.push(error));
			})
		);
		await Promise.all(
			[...requestTracesByPage.values()].map(async (trace) => {
				try {
					await trace?.attach();
				} catch (error) {
					cleanupFailures.push(error);
				}
			})
		);

		for (let index = 0; index < analyses.length; index += 1) {
			const analysis = analyses[index];
			const context = accountContexts[index];
			if (!analysis || !context) continue;
			try {
				await expect
					.poll(
						async () => {
							const response = await context.request.get(
								`/api/v1/locks/analysis/${encodeURIComponent(analysis.id)}`,
								{ headers: { 'X-Namespace': DEFAULT_NAMESPACE } }
							);
							if (!response.ok()) {
								throw new Error(`Failed to check analysis lock: HTTP ${response.status()}`);
							}
							return response.json();
						},
						{
							timeout: 10_000,
							message: `Analysis ${analysis.id} lock did not release after closing its editor`
						}
					)
					.toBeNull();
				const cleanupPage = await context.newPage();
				try {
					await deleteAnalysisViaUI(cleanupPage, analysis.name, { id: analysis.id });
				} finally {
					await cleanupPage.close();
				}
			} catch (error) {
				cleanupFailures.push(error);
			}
		}

		await Promise.all(
			accountContexts.map((context) =>
				context.close().catch((error: unknown) => cleanupFailures.push(error))
			)
		);
		await Promise.all(
			probeBrowsers
				.slice(1)
				.map((probeBrowser) =>
					probeBrowser.close().catch((error: unknown) => cleanupFailures.push(error))
				)
		);
		if (probeFailure !== undefined) cleanupFailures.unshift(probeFailure);
		if (cleanupFailures.length === 1) throw cleanupFailures[0];
		if (cleanupFailures.length > 1) {
			throw new AggregateError(cleanupFailures, 'Load probe and/or deterministic cleanup failed');
		}
	});
});
