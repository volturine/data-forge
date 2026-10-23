import type { Page } from '@playwright/test';
import { E2E_SHARED_NAMESPACE_B, test, expect } from './fixtures.js';
import { createLongRunningAnalysis } from './utils/api.js';
import { screenshot } from './utils/visual.js';
import {
	gotoAuthedRoute,
	gotoMonitoringTab,
	gotoNewAnalysis,
	gotoProfile,
	waitForProfileTab,
	readyTimeoutMs,
	waitForAppShell,
	waitForLayoutReady
} from './utils/readiness.js';
import { addStepAndOpenConfig, gotoAnalysisEditor } from './utils/analysis.js';
import { closeComputeWorkersPopup, deleteAnalysisViaUI } from './utils/ui-cleanup.js';
import { createAnalysisViaUi } from './utils/user-flows.js';
import { nameForAnalysisId } from './utils/api.js';
import { DEFAULT_NAMESPACE, switchNamespace } from './utils/namespace.js';
import { uid } from './utils/uid.js';
import { dialogByHeading, dialogByTextbox } from './utils/locators.js';
import { waitForBuildPreview, waitForBuildPreviewId } from './utils/builds.js';

/**
 * Smoke tests: every top-level route renders without a JS crash,
 * and primary navigation links work.
 */
test.describe('Navigation – page load smoke tests', () => {
	test('home page recovers from a startup failure without reloading', async ({ page }) => {
		await page.route(
			'**/api/v1/config',
			(route) => route.fulfill({ status: 503, json: { detail: 'Temporarily unavailable' } }),
			{ times: 1 }
		);
		await page.goto('/');
		await expect(page.getByRole('heading', { name: 'Unable to start the app' })).toBeVisible();
		const documentStarted = await page.evaluate(() => performance.timeOrigin);
		await page.getByRole('button', { name: 'Retry', exact: true }).click();
		// The previous failure remains visible while Retry is in flight. Wait for
		// recovery before using the normal fail-fast bootstrap readiness helper.
		await expect(page.getByRole('heading', { name: 'Unable to start the app' })).toBeHidden({
			timeout: readyTimeoutMs()
		});
		await waitForLayoutReady(page);
		expect(await page.evaluate(() => performance.timeOrigin)).toBe(documentStarted);
		await expect(page.getByRole('heading', { name: 'Analyses', level: 1 })).toBeVisible();
		await expect(page.getByRole('link', { name: /New Analysis/i })).toBeVisible();
		await screenshot(page, 'navigation', 'home-page');
	});

	test('datasources page renders Data Sources heading', async ({ page }) => {
		await page.goto('/datasources');
		await waitForLayoutReady(page);
		await expect(page.getByRole('heading', { name: 'Data Sources' })).toBeVisible();
		await screenshot(page, 'navigation', 'datasources-page');
	});

	test('UDFs are not a sidebar destination', async ({ page }) => {
		await gotoAuthedRoute(page, '/');
		const sidebar = page.locator('aside[aria-label="Main navigation"]');
		await expect(sidebar.getByRole('link', { name: 'UDFs', exact: true })).toHaveCount(0);
	});

	test('monitoring page renders Monitoring heading', async ({ page }) => {
		await page.goto('/monitoring');
		await waitForLayoutReady(page);
		await expect(page.getByRole('heading', { name: 'Monitoring' })).toBeVisible({
			timeout: 5_000
		});
		await expect(page.getByRole('tab', { name: 'Builds' })).toBeVisible({ timeout: 5_000 });
		await screenshot(page, 'navigation', 'monitoring-page');
	});

	test('new analysis page renders the datasource picker', async ({ page }) => {
		await gotoNewAnalysis(page);
		await expect(page.getByRole('heading', { name: 'New Analysis' })).toBeVisible();
		await expect(page.getByPlaceholder('Search datasources...')).toBeVisible();
		await screenshot(page, 'navigation', 'new-analysis-datasource-picker');
	});

	test('new datasource page loads', async ({ page }) => {
		await gotoAuthedRoute(page, '/datasources/new');
		await expect(page).toHaveURL(/datasources\/new/);
	});

	// ── header nav links ──────────────────────────────────────────────────────

	test('clicking Analyses nav link goes to /', async ({ page }) => {
		await page.goto('/datasources');
		await waitForLayoutReady(page);
		await page.getByRole('link', { name: 'Analyses' }).click();
		await expect(page).toHaveURL('/');
	});

	test('"New Analysis" link navigates to /analysis/new', async ({ page }) => {
		await page.goto('/');
		await waitForLayoutReady(page);
		const link = page.getByRole('link', { name: /New Analysis/i });
		await expect(link).toBeVisible();
		await link.click();
		await expect(page).toHaveURL(/analysis\/new/, { timeout: 5_000 });
	});

	test('datasources "Add" link navigates to /datasources/new', async ({ page }) => {
		await page.goto('/datasources');
		await waitForLayoutReady(page);
		// The "Add" link is the primary CTA in the datasource left panel header
		await page.getByRole('link', { name: /^Add$/ }).click();
		await expect(page).toHaveURL(/datasources\/new/, { timeout: 5_000 });
	});

	test('UDF library opens from With Columns without changing the analysis URL', async ({
		page,
		sharedDatasource
	}) => {
		await gotoAuthedRoute(page, '/');
		await switchNamespace(page, DEFAULT_NAMESPACE);
		const analysisId = await createAnalysisViaUi(page, sharedDatasource.name);
		const analysisName = nameForAnalysisId(analysisId);
		if (!analysisName) throw new Error(`Analysis ${analysisId} was not registered for cleanup`);

		try {
			const config = await addStepAndOpenConfig(page, analysisId, 'with_columns');
			await config.locator('#wc-expr-type').selectOption('udf');
			await config.locator('#wc-use-lib-yes').check();
			const selectUdf = config.getByRole('button', { name: 'Select UDF', exact: true });
			await selectUdf.click();

			const library = dialogByHeading(page, 'UDF Library');
			await expect(library).toBeVisible();
			await expect(page).toHaveURL(`/analysis/${analysisId}`);
			const treatment = await library.evaluate((panel) => {
				if (!panel.parentElement) throw new Error('UDF dialog has no backdrop');
				const backdrop = getComputedStyle(panel.parentElement);
				return { background: backdrop.backgroundColor, filter: backdrop.backdropFilter };
			});
			expect(treatment.background).not.toBe('rgba(0, 0, 0, 0)');
			expect(treatment.filter).toContain('blur(');
			await page.keyboard.press('Tab');
			expect(await library.evaluate((panel) => panel.contains(document.activeElement))).toBe(true);
			await library.getByRole('button', { name: 'Close UDF dialog' }).click();
			await expect(page.getByRole('dialog')).toHaveCount(0);
			await expect(selectUdf).toBeFocused();

			await selectUdf.click();
			await expect(library).toBeVisible();
			await page.setViewportSize({ width: 720, height: 900 });
			const bounds = await library.boundingBox();
			if (!bounds) throw new Error('UDF library dialog has no visible bounds');
			expect(bounds.x).toBeGreaterThanOrEqual(0);
			expect(bounds.x + bounds.width).toBeLessThanOrEqual(720);
			expect(bounds.y).toBeGreaterThanOrEqual(0);
			expect(bounds.y + bounds.height).toBeLessThanOrEqual(900);
			await page.keyboard.press('Escape');
			await expect(page.getByRole('dialog')).toHaveCount(0);
		} finally {
			await deleteAnalysisViaUI(page, analysisName, { id: analysisId });
		}
	});
});

test.describe('Navigation – theme toggle', () => {
	test('theme toggle switches between light and dark', async ({ page }) => {
		await page.goto('/');
		await waitForAppShell(page);

		const theme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
		const initial = theme === 'dark' ? 'dark' : 'light';

		await page.getByRole('button', { name: 'Toggle theme' }).click();
		const afterToggle = await page.evaluate(() =>
			document.documentElement.getAttribute('data-theme')
		);
		expect(afterToggle).toBe(initial === 'light' ? 'dark' : 'light');

		// Toggle back
		await page.getByRole('button', { name: 'Toggle theme' }).click();
		const afterSecond = await page.evaluate(() =>
			document.documentElement.getAttribute('data-theme')
		);
		expect(afterSecond).toBe(initial);
	});
});

test.describe('Navigation – profile access', () => {
	test('profile link navigates to profile page', async ({ page }) => {
		await gotoAuthedRoute(page, '/');
		await page.getByRole('link', { name: 'Profile' }).click();

		// The SPA can update the URL before Playwright attaches a navigation
		// event waiter. Assert the current URL instead of waiting for a missed
		// event; this also ensures the page content is checked below.
		await expect(page).toHaveURL(/\/profile/, { timeout: 5_000 });
		await expect(page.getByRole('heading', { name: 'Profile', level: 1 })).toBeVisible();
		await expect(page.getByRole('tab', { name: 'Account' })).toHaveAttribute(
			'aria-selected',
			'true'
		);

		await screenshot(page, 'navigation', 'profile-via-sidebar');
	});
});

async function gotoMonitoringBuilds(page: Page, analysisId?: string) {
	if (analysisId) {
		const params = new URLSearchParams({ tab: 'builds', analysis_id: analysisId });
		await page.goto(`/monitoring?${params.toString()}`);
		await waitForLayoutReady(page);
	} else {
		await gotoMonitoringTab(page, 'builds');
	}
	await expect(page.getByRole('tab', { name: 'Builds', selected: true })).toBeVisible({
		timeout: 5_000
	});
	await expect(page.locator('#panel-builds')).toBeVisible({ timeout: 5_000 });
}

function cancelBuildDialog(page: Page) {
	const title = page.getByRole('heading', { name: 'Cancel this build?' });
	return page.getByRole('dialog').filter({ has: title });
}

async function confirmCancelBuild(page: Page) {
	const dialog = cancelBuildDialog(page);
	const confirmButton = dialog.getByRole('button', { name: 'Cancel Build', exact: true });
	await expect(dialog).toBeVisible({ timeout: 5_000 });
	await expect(confirmButton).toBeVisible({ timeout: 5_000 });
	await expect(confirmButton).toBeEnabled({ timeout: 5_000 });
	const responsePromise = page
		.waitForResponse(
			(apiResponse) =>
				apiResponse.url().includes('/api/v1/compute/builds/') &&
				apiResponse.url().includes('/cancel') &&
				apiResponse.status() === 200,
			{ timeout: 10_000 }
		)
		.then(async (response) => (await response.json()) as { status: string });
	await confirmButton.click({ force: true, timeout: 5_000 });
	const payload = await responsePromise;
	expect(payload.status).toBe('cancelled');
	await expect(dialog).not.toBeVisible({ timeout: 5_000 });
}

async function previewBuildId(page: Page) {
	await waitForBuildPreview(page);
	return waitForBuildPreviewId(page);
}

async function waitForBuildRowById(
	page: Page,
	panel: ReturnType<Page['locator']>,
	runId: string,
	statuses:
		| 'running'
		| 'completed'
		| 'failed'
		| 'cancelled'
		| 'queued'
		| Array<'queued' | 'running' | 'completed' | 'failed' | 'cancelled'>,
	timeout = 5_000
) {
	const acceptedStatuses = Array.isArray(statuses) ? statuses : [statuses];
	const failedToLoad = panel.getByText(/Failed to load builds/i).first();
	await expect(failedToLoad).not.toBeVisible({ timeout: 5_000 });
	const row = panel
		.locator(
			acceptedStatuses
				.map((status) => `[data-build-row="${runId}"][data-build-status="${status}"]`)
				.join(',')
		)
		.first();
	await expect(row).toBeVisible({ timeout });
	if (acceptedStatuses.includes('cancelled')) {
		const completed = panel.locator(`[data-build-row="${runId}"][data-build-status="completed"]`);
		const failed = panel.locator(`[data-build-row="${runId}"][data-build-status="failed"]`);
		if (await completed.isVisible().catch(() => false)) {
			throw new Error(`Build row ${runId} completed after a confirmed cancellation`);
		}
		if (await failed.isVisible().catch(() => false)) {
			throw new Error(`Build row ${runId} failed after a confirmed cancellation`);
		}
	}
	return row;
}

async function waitForBuildRowEventually(
	page: Page,
	panel: ReturnType<Page['locator']>,
	runId: string,
	statuses:
		| 'running'
		| 'completed'
		| 'failed'
		| 'cancelled'
		| 'queued'
		| Array<'queued' | 'running' | 'completed' | 'failed' | 'cancelled'>
) {
	return waitForBuildRowById(page, panel, runId, statuses, 5_000);
}

test.describe('Navigation – compute worker monitor', () => {
	test('compute workers popup lists active compute workers on demand', async ({
		page,
		request,
		sharedCancellationDatasource
	}) => {
		const analysisName = `E2E Compute Workers ${uid()}`;
		const analysisId = await createLongRunningAnalysis(
			request,
			analysisName,
			sharedCancellationDatasource.id
		);

		try {
			await gotoAnalysisEditor(page, analysisId);
			await waitForAppShell(page);
			const buildBtn = page.locator('[data-testid="output-build-button"]');
			await expect(buildBtn).toBeVisible({ timeout: 5_000 });
			await buildBtn.click();
			const openPreviewBtn = page.locator('[data-testid="output-build-preview-trigger"]');
			await expect(openPreviewBtn).toBeVisible({ timeout: 5_000 });
			await openPreviewBtn.click();
			const runId = await previewBuildId(page);
			await page.keyboard.press('Escape');
			await expect(page.locator('[data-testid="build-preview"]')).not.toBeVisible({
				timeout: 5_000
			});

			await gotoMonitoringBuilds(page, analysisId);

			const computeWorkersButton = page.getByRole('button', { name: 'Compute workers' });
			await expect(computeWorkersButton).toBeVisible({ timeout: 5_000 });
			const computeWorkersPopup = page.locator('[data-compute-workers-popup="true"]');
			await computeWorkersButton.click();
			await expect(computeWorkersPopup).toBeVisible({ timeout: 5_000 });
			await expect(page.getByTestId('compute-worker-monitor-count')).toBeVisible({
				timeout: 10_000
			});
			await expect(
				computeWorkersPopup
					.locator(
						`[data-compute-worker-row="analysis_interactive:${analysisId}"], [data-compute-worker-row="build:${runId}"]`
					)
					.first()
			).toBeVisible({
				timeout: readyTimeoutMs()
			});
			await closeComputeWorkersPopup(page);

			const panel = page.locator('#panel-builds');
			// Build may finish before cancel under load (especially with multi-thread
			// Polars). The Compute workers popup already verified; only cancel while still active.
			const historyRow = await waitForBuildRowEventually(page, panel, runId, [
				'queued',
				'running',
				'completed',
				'failed',
				'cancelled'
			]);
			const status = await historyRow.getAttribute('data-build-status');
			if (status === 'queued' || status === 'running') {
				const cancelButton = historyRow.getByLabel('Cancel build');
				await expect(cancelButton).toBeVisible({ timeout: 5_000 });
				await expect(cancelButton).toBeEnabled({ timeout: 5_000 });
				await cancelButton.click({ timeout: 5_000 });
				await confirmCancelBuild(page);

				const cancelledRow = await waitForBuildRowEventually(page, panel, runId, 'cancelled');
				await expect(cancelledRow.getByText('Cancelled')).toBeVisible({ timeout: 5_000 });
			}
		} finally {
			await deleteAnalysisViaUI(page, analysisName);
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Chat panel – minimal smoke tests
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Navigation – chat panel smoke', () => {
	test('chat trigger opens panel and close button dismisses it', async ({ page }) => {
		await gotoAuthedRoute(page, '/');

		const trigger = page.getByRole('button', { name: 'AI Assistant' });
		await expect(trigger).toBeVisible();
		await trigger.click();

		const panel = page.locator('#chat-panel');
		await expect(panel).toBeVisible({ timeout: 5_000 });

		await screenshot(page, 'navigation', 'chat-panel-open');

		// Close via the close button
		await panel.getByRole('button', { name: 'Close chat' }).click();
		await expect(panel).not.toBeVisible({ timeout: 3_000 });
	});

	test('chat panel closes via Escape key', async ({ page }) => {
		await gotoAuthedRoute(page, '/');

		await page.getByRole('button', { name: 'AI Assistant' }).click();
		const panel = page.locator('#chat-panel');
		await expect(panel).toBeVisible({ timeout: 5_000 });

		await page.keyboard.press('Escape');
		await expect(panel).not.toBeVisible({ timeout: 3_000 });
	});

	test('chat panel toggle: second click closes the panel', async ({ page }) => {
		await gotoAuthedRoute(page, '/');

		const trigger = page.getByRole('button', { name: 'AI Assistant' });
		await trigger.click();
		const panel = page.locator('#chat-panel');
		await expect(panel).toBeVisible({ timeout: 5_000 });

		// Click trigger again to close
		await trigger.click();
		await expect(panel).not.toBeVisible({ timeout: 3_000 });
	});

	test('chat panel provider switch updates model selector without a local Ollama service', async ({
		page
	}) => {
		await gotoAuthedRoute(page, '/');
		await page.route('**/api/v1/settings', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					smtp_host: '',
					smtp_port: 587,
					smtp_user: '',
					smtp_password: '',
					telegram_bot_token: '',
					telegram_bot_enabled: false,
					openrouter_api_key: 'sk-test',
					openrouter_default_model: 'openai/gpt-4o-mini',
					ollama_endpoint_url: 'http://ollama.test',
					ollama_default_model: 'llama3.2',
					public_idb_debug: false
				})
			})
		);
		await page.route('**/api/v1/mcp/tools', (route) =>
			route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
		);
		await page.route('**/api/v1/ai/chat/models', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify([{ name: 'gpt-4o-mini' }, { name: 'llama3.2' }])
			})
		);
		const settingsResponsePromise = page.waitForResponse(
			(response) =>
				response.request().method() === 'GET' &&
				new URL(response.url()).pathname === '/api/v1/settings'
		);
		const toolsResponsePromise = page.waitForResponse(
			(response) =>
				response.request().method() === 'GET' &&
				new URL(response.url()).pathname === '/api/v1/mcp/tools'
		);

		const trigger = page.getByRole('button', { name: 'AI Assistant' });
		await trigger.click();
		const panel = page.locator('#chat-panel');
		await expect(panel).toBeVisible({ timeout: 5_000 });
		const [settingsResponse, toolsResponse] = await Promise.all([
			settingsResponsePromise,
			toolsResponsePromise
		]);
		expect(settingsResponse.ok()).toBe(true);
		expect(toolsResponse.ok()).toBe(true);

		const providerSelect = panel.locator('select[title="Chat provider"]');
		await expect(providerSelect).toBeVisible({ timeout: 3_000 });
		await expect(providerSelect).toHaveValue('openrouter', { timeout: 5_000 });
		await expect(panel.getByRole('button', { name: 'gpt-4o-mini' })).toBeVisible({
			timeout: 5_000
		});

		// The model catalogue is stubbed: this test covers provider UI state,
		// not the availability of a local Ollama service.
		const ollamaModelsResponsePromise = page.waitForResponse((response) => {
			if (
				response.request().method() !== 'POST' ||
				new URL(response.url()).pathname !== '/api/v1/ai/chat/models'
			) {
				return false;
			}
			return response.request().postDataJSON().provider === 'ollama';
		});
		await providerSelect.selectOption('ollama');
		await expect(providerSelect).toHaveValue('ollama');
		const ollamaModelsResponse = await ollamaModelsResponsePromise;
		expect(ollamaModelsResponse.ok()).toBe(true);

		// Model button should update to Ollama default
		await expect(panel.getByRole('button', { name: 'llama3.2' })).toBeVisible({ timeout: 5_000 });
	});

	test('first chat open stays neutral while provider settings and tools load', async ({ page }) => {
		await page.addInitScript(() => localStorage.setItem('chat_session_id', 'session-1'));
		await page.route('**/api/v1/settings', async (route) => {
			if (route.request().method() === 'GET')
				await new Promise((resolve) => setTimeout(resolve, 800));
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					smtp_host: '',
					smtp_port: 587,
					smtp_user: '',
					smtp_password: '',
					telegram_bot_token: '',
					telegram_bot_enabled: false,
					openrouter_api_key: 'sk-test',
					openrouter_default_model: 'openai/gpt-4o-mini',
					ollama_endpoint_url: 'http://ollama.test',
					ollama_default_model: 'llama3.2',
					public_idb_debug: false
				})
			});
		});
		await page.route('**/api/v1/mcp/tools', async (route) => {
			await new Promise((resolve) => setTimeout(resolve, 800));
			await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
		});
		await page.route('**/api/v1/ai/chat/sessions', (route) =>
			route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
		);
		await page.route('**/api/v1/ai/chat/history/session-1', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					session_id: 'session-1',
					history: [{ type: 'message', role: 'assistant', content: 'OpenRouter session ready' }],
					last_event_id: 0,
					history_gap: false
				})
			})
		);
		await page.route('**/api/v1/ai/chat/stream/session-1**', (route) =>
			route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
		);
		await page.route('**/api/v1/ai/chat/models', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify([{ id: 'openai/gpt-4o-mini', name: 'gpt-4o-mini', context_length: 0 }])
			})
		);

		await gotoAuthedRoute(page, '/');
		await page.reload();
		const settingsRequest = page.waitForRequest(
			(request) =>
				request.method() === 'GET' && new URL(request.url()).pathname === '/api/v1/settings'
		);
		const toolsRequest = page.waitForRequest(
			(request) =>
				request.method() === 'GET' && new URL(request.url()).pathname === '/api/v1/mcp/tools'
		);
		await page.getByRole('button', { name: 'AI Assistant' }).click();
		const panel = page.locator('#chat-panel');
		await expect(panel).toBeVisible();
		await Promise.all([settingsRequest, toolsRequest]);

		await expect(panel.getByRole('status').first()).toContainText('Loading chat');
		await expect(panel.getByRole('button', { name: 'Configure' })).toBeDisabled();
		await expect(panel.getByText(/No AI provider is configured/)).toHaveCount(0);
		await expect(panel.locator('select[title="Chat provider"]')).toHaveCount(0);
		await expect(panel.getByText(/Ollama|settings unavailable|failed|not configured/i)).toHaveCount(
			0
		);

		await expect(panel.locator('select[title="Chat provider"]')).toHaveValue('openrouter', {
			timeout: 5_000
		});
		await expect(panel.getByText('OpenRouter session ready')).toBeVisible({ timeout: 5_000 });
	});

	test('chat reloads provider settings after saving them in Profile', async ({ page }) => {
		let delayNextSettingsGet = false;
		let settings: Record<string, unknown> = {
			smtp_host: '',
			smtp_port: 587,
			smtp_user: '',
			smtp_password: '',
			telegram_bot_token: '',
			telegram_bot_enabled: false,
			openrouter_api_key: '',
			openrouter_default_model: 'openai/gpt-4o-mini',
			ollama_endpoint_url: 'http://ollama.test',
			ollama_default_model: 'llama3.2',
			public_idb_debug: false
		};
		await page.route('**/api/v1/settings', async (route) => {
			if (route.request().method() === 'GET') {
				if (delayNextSettingsGet) {
					delayNextSettingsGet = false;
					await new Promise((resolve) => setTimeout(resolve, 700));
				}
				await route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify(settings)
				});
				return;
			}
			if (route.request().method() === 'PUT') {
				const update = route.request().postDataJSON() as Record<string, unknown>;
				settings = { ...settings, ...update };
				if (typeof update.openrouter_api_key === 'string' && update.openrouter_api_key.length > 0) {
					settings.openrouter_api_key = '••••••••';
				}
				await route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify(settings)
				});
				return;
			}
			await route.continue();
		});
		await page.route('**/api/v1/mcp/tools', (route) =>
			route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
		);
		await page.route('**/api/v1/ai/chat/sessions', (route) =>
			route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
		);
		await page.route('**/api/v1/ai/chat/models', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify([{ id: 'openai/gpt-4o-mini', name: 'gpt-4o-mini', context_length: 0 }])
			})
		);

		await gotoAuthedRoute(page, '/');
		await page.getByRole('button', { name: 'AI Assistant' }).click();
		let panel = page.locator('#chat-panel');
		await expect(panel.locator('select[title="Chat provider"]')).toBeVisible();
		await panel.locator('select[title="Chat provider"]').selectOption('openrouter');
		await expect(panel.getByText(/No AI provider is configured/)).toBeVisible();
		await panel.getByRole('button', { name: 'Close chat' }).click();

		await gotoProfile(page, 'ai-providers');
		await waitForProfileTab(page, 'AI Providers');
		await page.locator('input[type="password"]').first().fill('sk-test-profile-key');
		await page.getByRole('button', { name: 'Save' }).click();
		await expect(page.getByText('AI provider settings saved')).toBeVisible({ timeout: 5_000 });

		await gotoAuthedRoute(page, '/');
		delayNextSettingsGet = true;
		await page.getByRole('button', { name: 'AI Assistant' }).click();
		panel = page.locator('#chat-panel');
		await expect(panel.getByRole('status').first()).toContainText('Loading chat');
		await expect(panel.getByText(/No AI provider is configured/)).toHaveCount(0);
		await expect(panel.locator('select[title="Chat provider"]')).toHaveCount(0);
		await expect(panel.locator('select[title="Chat provider"]')).toHaveValue('openrouter');
		await expect(panel.getByText('Start a session and ask anything.')).toBeVisible({
			timeout: 5_000
		});
	});
});

test.describe('Navigation – namespace persistence', () => {
	test('selected namespace persists across page refresh', async ({ page }) => {
		const ns = E2E_SHARED_NAMESPACE_B;

		await page.goto('/');
		await waitForAppShell(page);

		await page.getByRole('button', { name: 'Select namespace' }).click();
		const dialog = dialogByTextbox(page, 'Search namespaces');
		await expect(dialog).toBeVisible({ timeout: 5_000 });

		const search = dialog.getByRole('textbox', { name: 'Search namespaces' });
		await search.fill(ns);

		await dialog.locator(`[data-namespace-option="${ns}"]`).click();
		await expect(dialog).not.toBeVisible({ timeout: readyTimeoutMs() });

		const sidebar = page.locator('aside[aria-label="Main navigation"]');
		await expect(sidebar.getByRole('button', { name: 'Select namespace' })).toContainText(ns, {
			timeout: 5_000
		});

		await page.getByRole('button', { name: 'Select namespace' }).click();
		const reopenedDialog = dialogByTextbox(page, 'Search namespaces');
		await expect(reopenedDialog).toBeVisible({ timeout: 5_000 });
		await expect(reopenedDialog.locator(`[data-namespace-option="${ns}"]`)).toBeVisible({
			timeout: 5_000
		});
		await page.keyboard.press('Escape');
		await expect(reopenedDialog).not.toBeVisible({ timeout: 5_000 });

		await page.reload();
		await waitForAppShell(page);

		await expect(sidebar.getByText(ns)).toBeVisible({ timeout: 5_000 });
		await screenshot(page, 'navigation', 'namespace-persisted');
	});

	test('namespace picker search filters and selecting closes modal', async ({ page }) => {
		await page.goto('/');
		await waitForAppShell(page);

		const namespacesResponse = page.waitForResponse(
			(response) =>
				new URL(response.url()).pathname === '/api/v1/namespaces' &&
				response.request().method() === 'GET'
		);
		await page.getByRole('button', { name: 'Select namespace' }).click();
		expect((await namespacesResponse).ok()).toBeTruthy();
		const dialog = page.locator('[role="dialog"]');
		await expect(dialog).toBeVisible({ timeout: 5_000 });

		const search = dialog.locator('#namespace-picker-search');
		await expect(search).toBeFocused();
		const treatment = await dialog.evaluate((panel) => {
			const backdrop = getComputedStyle(panel.parentElement!);
			return {
				width: panel.getBoundingClientRect().width,
				filter: backdrop.backdropFilter,
				background: backdrop.backgroundColor
			};
		});
		expect(treatment.width).toBeGreaterThan(800);
		expect(treatment.filter).toContain('blur(');
		expect(treatment.background).not.toBe('rgba(0, 0, 0, 0)');
		await page.keyboard.press('Tab');
		expect(await dialog.evaluate((panel) => panel.contains(document.activeElement))).toBe(true);
		await page.setViewportSize({ width: 390, height: 844 });
		const bounds = await dialog.boundingBox();
		expect(bounds!.x).toBeGreaterThanOrEqual(0);
		expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
		expect(await dialog.evaluate((panel) => panel.scrollWidth <= panel.clientWidth)).toBe(true);
		await search.fill('default');
		await expect(dialog.locator('[data-namespace-option="default"]')).toBeVisible({
			timeout: 3_000
		});

		await dialog.locator('[data-namespace-option="default"]').click();
		await expect(dialog).not.toBeVisible({ timeout: 5_000 });
		await expect(page.getByRole('button', { name: 'Select namespace' })).toContainText('default');
		await expect(page.getByRole('button', { name: 'Select namespace' })).toBeFocused();
	});
});
