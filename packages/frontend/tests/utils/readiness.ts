import { expect, type Locator, type Page } from '@playwright/test';

function previewReadinessTimeoutMs(): number {
	return 120_000;
}

export function readyTimeoutMs(): number {
	// Docker engine cold start + shell hydrate. Fail faster than 60s, but allow
	// one full container health cycle under host load.
	return 45_000;
}

/** Builds need a full exclusive engine start plus pipeline work. */
export function buildTimeoutMs(): number {
	return 90_000;
}

function mainNavigation(page: Page): Locator {
	return page.locator('[aria-label="Main navigation"]').first();
}

function appRoute(page: Page): string {
	return new URL(page.url()).pathname;
}

async function waitForAnyVisible(locator: Locator, timeout: number): Promise<void> {
	await expect(locator.filter({ visible: true }).first()).toBeVisible({ timeout });
}

async function waitForPreviewReady(
	page: Page,
	preview: Locator,
	timeout: number,
	label: string
): Promise<void> {
	const deadline = Date.now() + timeout;

	while (true) {
		const remaining = deadline - Date.now();
		if (remaining <= 0) {
			const details = await preview
				.evaluate((element) => ({
					state: element.getAttribute('data-preview-state'),
					queryStatus: element.getAttribute('data-preview-query-status'),
					fetchStatus: element.getAttribute('data-preview-fetch-status'),
					hasData: element.getAttribute('data-preview-has-data'),
					error: element.getAttribute('data-preview-error')
				}))
				.catch(() => null);
			throw new Error(
				`${label} did not become ready within ${timeout}ms (state=${JSON.stringify(details)})`
			);
		}

		// Keep each browser-side lookup on a normal timeout. Passing the tiny
		// remaining tail of the overall deadline (often 1–100ms) makes
		// Playwright schedule a negative timer when the browser is busy under
		// parallel CI load. The outer deadline still bounds this loop.
		const pollTimeout = 1_000;
		const state = await preview
			.getAttribute('data-preview-state', { timeout: pollTimeout })
			.catch(() => null);
		if (state === 'error') {
			const message =
				(await preview.getAttribute('data-preview-error', { timeout: 1_000 }).catch(() => null)) ??
				`${label} failed`;
			throw new Error(`${label} failed before ready: ${message}`);
		}

		if (
			(await preview
				.getAttribute('data-preview-ready', { timeout: pollTimeout })
				.catch(() => null)) === 'true'
		) {
			return;
		}

		const sleepMs = Math.floor(Math.min(100, deadline - Date.now()));
		if (sleepMs > 0) {
			await page.waitForTimeout(sleepMs);
		}
	}
}

type MonitoringTabKey = 'builds' | 'schedules' | 'health';

/**
 * Wait for the app shell to finish hydrating by confirming the main
 * navigation sidebar is visible. The sidebar only renders once the layout
 * `ready` flag is true (configStore loaded, auth resolved), so the labeled
 * navigation container is the stable shell readiness signal.
 *
 * Call before any interaction with shell-level UI (profile, theme toggle,
 * nav links) that lives outside page-specific content.
 */
export async function waitForAppShell(page: Page, timeout = readyTimeoutMs()): Promise<void> {
	await expect(mainNavigation(page)).toBeVisible({ timeout });
	await expect(page.locator('[data-shell-interactive="true"]')).toBeVisible({ timeout });
	await expect(page.locator('main[data-app-route]').first()).toHaveAttribute(
		'data-app-route',
		appRoute(page),
		{ timeout }
	);
}

/**
 * Shared layout readiness gate. Confirms:
 *  1. The main navigation sidebar is visible (app shell hydrated).
 *  2. The `<main>` content area has mounted (page slot rendered).
 *
 * Use as the first await after `page.goto(...)` before any page-specific
 * assertions. This guarantees the layout `ready` flag resolved, auth
 * completed, and the Svelte page component has started rendering.
 *
 * Bootstrap failures surface as `[data-shell-bootstrap="error"]` — fail
 * immediately with that message instead of waiting out the full timeout.
 */
export async function waitForLayoutReady(page: Page, timeout = readyTimeoutMs()): Promise<void> {
	const bootstrapError = page.locator('[data-shell-bootstrap="error"]');
	const nav = mainNavigation(page);
	const shellState = nav.or(bootstrapError).filter({ visible: true }).first();
	await expect(shellState).toBeVisible({ timeout });
	if (await bootstrapError.isVisible()) {
		const message =
			(await bootstrapError.innerText().catch(() => null)) ?? 'App shell bootstrap failed';
		throw new Error(`App shell failed to bootstrap:\n${message}`);
	}
	await expect(page.locator('[data-shell-interactive="true"]')).toBeVisible({ timeout });
	await waitForAnyVisible(page.locator('main'), timeout);
	await expect(page.locator('main[data-app-route]').first()).toHaveAttribute(
		'data-app-route',
		appRoute(page),
		{ timeout }
	);
}

async function gotoAndWaitForLayout(page: Page, path: string, timeout: number): Promise<void> {
	// Wait only for the navigation commit. Under parallel CI load Playwright can
	// queue the document request behind other pages before the browser receives
	// its headers. Use the same bounded readiness deadline for that first
	// response; this is a single navigation wait, never a retry or reload.
	await page.goto(path, { waitUntil: 'commit', timeout });
	await waitForLayoutReady(page, timeout);
}

/**
 * Navigate to an authenticated route reliably on a fresh Playwright page.
 */
export async function gotoAuthedRoute(
	page: Page,
	path: string,
	timeout = readyTimeoutMs()
): Promise<void> {
	await gotoAndWaitForLayout(page, path, timeout);
}

/**
 * Wait for the lineage page toolbar to finish rendering by confirming
 * the layout buttons are visible. Call after `page.goto('/lineage')`.
 */
export async function waitForLineageToolbar(page: Page, timeout = readyTimeoutMs()): Promise<void> {
	await expect(page.locator('button[title="Horizontal tree layout"]')).toBeVisible({ timeout });
}

/**
 * Wait for the datasource list query to reach a terminal state.
 * Terminal states: at least one `[data-ds-row]`, the empty-state text,
 * the filtered-empty text, or an error callout.
 */
export async function waitForDatasourceList(page: Page, timeout = readyTimeoutMs()): Promise<void> {
	await waitForLayoutReady(page, timeout);
	await expect(page.getByRole('heading', { name: 'Data Sources', exact: true })).toBeVisible({
		timeout
	});
	const terminal = page.locator(
		'[data-ds-row], :text("No data sources yet"), :text("No datasources match"), main[data-app-route="/datasources"] [aria-live="polite"]'
	);
	await waitForAnyVisible(terminal, timeout);
}

export async function gotoDatasourcesPage(page: Page, timeout = readyTimeoutMs()): Promise<void> {
	await gotoAuthedRoute(page, '/datasources', timeout);
	await waitForDatasourceList(page, timeout);
}

/**
 * Wait for datasource preview to finish loading.
 *
 * Terminal outcomes:
 *  - ready state: `[data-preview-ready="true"]` becomes visible
 *  - failed state: a visible preview error appears
 *
 * Throws immediately on failed state so tests don't keep waiting on a preview
 * that will never become ready.
 */
export async function waitForDatasourcePreviewReady(
	page: Page,
	timeout = previewReadinessTimeoutMs()
): Promise<void> {
	await waitForLayoutReady(page, timeout);
	await expect(page.locator('[data-ds-config]')).toBeVisible({ timeout });
	const preview = page.locator('[data-testid="datasource-preview"]');
	await expect(preview).toBeVisible({ timeout });
	await waitForPreviewReady(page, preview, timeout, 'Datasource preview');
}

/**
 * Wait for an analysis inline preview to finish loading.
 *
 * Terminal outcomes:
 *  - ready state: the inline table advertises `[data-preview-ready="true"]`
 *  - failed state: a visible preview error appears
 *
 * The inline table can mount before its TanStack query has resolved, so tests
 * must wait on the preview readiness contract before asserting cell content.
 */
export async function waitForInlinePreviewReady(
	page: Page,
	timeout = previewReadinessTimeoutMs()
): Promise<void> {
	await waitForLayoutReady(page, timeout);
	const table = page.locator('[data-testid="inline-data-table"]').filter({ visible: true }).first();
	await expect(table).toBeVisible({ timeout });
	await waitForPreviewReady(page, table, timeout, 'Inline preview');
}

export async function waitForChartPreviewReady(
	page: Page,
	timeout = previewReadinessTimeoutMs()
): Promise<void> {
	await waitForLayoutReady(page, timeout);
	const preview = page
		.locator('[data-testid="chart-preview-container"]')
		.filter({ visible: true })
		.first();
	await expect(preview).toBeVisible({ timeout });
	await waitForPreviewReady(page, preview, timeout, 'Chart preview');
}

export async function waitForAnalysisLoadError(
	page: Page,
	timeout = readyTimeoutMs()
): Promise<void> {
	await waitForLayoutReady(page, timeout);
	await expect(page.locator('[data-testid="analysis-load-error"]')).toBeVisible({ timeout });
	await expect(page.getByText('Error loading analysis')).toBeVisible({ timeout });
}

/**
 * Navigate to the home page (analyses gallery), wait for the TanStack Query
 * data to load, and clear any persisted search filter from IndexedDB that
 * might hide analysis cards.
 *
 * Readiness chain:
 *  1. Layout ready (shell hydrated, `<main>` mounted).
 *  2. Gallery query settled — cards, empty-state, or "no match" visible.
 *  3. IndexedDB search state settled — clear stale filter if present so
 *     the full card list is visible for subsequent assertions.
 */
export async function gotoAnalysesGallery(page: Page, timeout = readyTimeoutMs()): Promise<void> {
	await gotoAuthedRoute(page, '/', timeout);

	// The analyses page hydrates the search box from IndexedDB asynchronously.
	// A prior test may leave a non-empty filter (e.g. "ZZZNOMATCH") that hides
	// cards. We must wait for the query AND the persisted state to settle before
	// treating gallery content as final.
	const anyContent = page.locator(
		'[data-analysis-card], :text("No analyses match"), :text("No analyses yet")'
	);
	await waitForAnyVisible(anyContent, timeout);

	// Wait for the search input to exist (only renders when analyses exist),
	// then let IndexedDB hydration settle before treating the value as final.
	const searchBox = page.getByRole('textbox', { name: 'Search analyses' });
	if (await searchBox.isVisible().catch(() => false)) {
		await expect(searchBox).toBeVisible({ timeout });

		const value = await searchBox.inputValue();
		if (value) {
			await searchBox.fill('');
			// After clearing, wait for gallery content to re-render
			await waitForAnyVisible(
				page.locator('[data-analysis-card], :text("No analyses yet")'),
				timeout
			);
		}
	}
}

/**
 * On the datasources page, select a datasource by clicking its row and wait
 * for the inline config panel to be fully rendered and interactive.
 *
 * Readiness signal: the `[data-ds-config]` container is visible AND contains
 * a tab with `aria-selected="true"` — proving the panel has hydrated.
 */
export async function selectDatasourceAndWaitForConfig(
	page: Page,
	name: string,
	timeout = readyTimeoutMs()
): Promise<void> {
	await waitForDatasourceList(page, timeout);

	const row = page.locator(`[data-ds-row="${name}"]`);
	await expect(row).toBeVisible({ timeout });
	await row.click();

	const config = page.locator('[data-ds-config]');
	await expect(config).toBeVisible({ timeout });
	await expect(config.locator('[role="tab"][aria-selected="true"]')).toBeVisible({ timeout });
}

/**
 * Navigate to `/analysis/new` and wait for the datasource picker to render.
 */
export async function gotoNewAnalysis(page: Page, timeout = readyTimeoutMs()): Promise<void> {
	await gotoAuthedRoute(page, '/analysis/new', timeout);
	await expect(page.getByRole('heading', { name: 'New Analysis' })).toBeVisible({ timeout });
}

export async function gotoMonitoringTab(
	page: Page,
	tab: MonitoringTabKey,
	timeout = readyTimeoutMs()
): Promise<Locator> {
	await gotoAuthedRoute(page, `/monitoring?tab=${tab}`, timeout);

	const labels = {
		builds: 'Builds',
		schedules: 'Schedules',
		health: 'Health Checks'
	} satisfies Record<MonitoringTabKey, string>;
	const panelIds = {
		builds: '#panel-builds',
		schedules: '#panel-schedules',
		health: '#panel-health'
	} satisfies Record<MonitoringTabKey, string>;

	const activeTab = page.getByRole('tab', { name: labels[tab] });
	await expect(activeTab).toHaveAttribute('aria-selected', 'true', { timeout });

	const panel = page.locator(panelIds[tab]);
	await expect(panel).toBeVisible({ timeout });
	return panel;
}

/**
 * Wait for the UDF list query to reach a terminal state.
 *
 * First waits for the page to mount (the "UDF Library" heading), then
 * waits for the query's terminal state: at least one `[data-udf-card]`,
 * the empty-state text, or an error callout.
 */
export async function waitForUdfList(page: Page, timeout = readyTimeoutMs()): Promise<void> {
	await waitForLayoutReady(page, timeout);
	await expect(page.getByRole('heading', { name: 'UDF Library' })).toBeVisible({ timeout });

	const terminal = page.locator(
		'[data-udf-card], :text("No UDFs yet"), main[data-app-route="/udfs"] [aria-live="polite"]'
	);
	await waitForAnyVisible(terminal, timeout);
}

export async function gotoUdfLibrary(page: Page, timeout = readyTimeoutMs()): Promise<void> {
	await gotoAuthedRoute(page, '/udfs', timeout);
	await waitForUdfList(page, timeout);
}

export async function gotoNewUdfPage(page: Page, timeout = readyTimeoutMs()): Promise<void> {
	await gotoAuthedRoute(page, '/udfs/new', timeout);
	await expect(page.locator('#udf-name')).toBeVisible({ timeout });
}

/**
 * Navigate to a UDF editor page and wait for the editor form to be ready.
 *
 * Readiness chain:
 *  1. Layout ready (shell hydrated).
 *  2. The `#udf-name` input is visible — proving the UDF query resolved
 *     and the editor form rendered.
 */
export async function gotoUdfEditor(
	page: Page,
	udfId: string,
	timeout = readyTimeoutMs()
): Promise<void> {
	await gotoAuthedRoute(page, `/udfs/${udfId}`, timeout);
	await expect(page.locator('#udf-name')).toBeVisible({ timeout });
}

/**
 * After the config panel is open, switch to the Schema tab and wait for
 * schema data to load. Handles the async TanStack Query fetch that backs
 * the schema column list.
 *
 * Readiness signal: a `[data-schema-column]` element or the "No schema"
 * empty state becomes visible inside the config panel.
 */
export async function openSchemaTabAndWait(page: Page, timeout = readyTimeoutMs()): Promise<void> {
	const config = page.locator('[data-ds-config]');
	await config.getByRole('tab', { name: 'Schema' }).click();

	const schemaReady = config.locator(
		'[data-schema-column], :text("No schema information available"), :text("Loading schema")'
	);
	await waitForAnyVisible(schemaReady, timeout);

	// If schema is still loading, wait for it to finish
	await waitForAnyVisible(
		config.locator('[data-schema-column], :text("No schema information available")'),
		timeout
	);
}

/**
 * Wait for the profile page tabbed interface to be ready.
 *
 * Readiness chain:
 *  1. Layout ready (shell hydrated, `<main>` mounted) — profile route content
 *     only mounts after auth/config resolve; waiting on the tablist alone races
 *     cold navigations under CI load.
 *  2. Tab list visible with a selected tab.
 *
 * Prefer `gotoProfile` / `gotoProfileTab` for navigation; call this after a
 * manual `page.goto` only when the shell gate has already been satisfied.
 */
export async function waitForProfileTabs(page: Page, timeout = readyTimeoutMs()): Promise<void> {
	await waitForLayoutReady(page, timeout);
	await expect(page.getByRole('tablist', { name: 'Profile sections' })).toBeVisible({ timeout });
	await expect(page.getByRole('tab', { selected: true })).toBeVisible({ timeout });
}

/**
 * Navigate to `/profile` (optionally with a hash tab) using the shared cold-start
 * shell warm-up, then wait for the profile tablist.
 */
export async function gotoProfile(
	page: Page,
	hash?: string,
	timeout = readyTimeoutMs()
): Promise<void> {
	const path = hash ? `/profile#${hash}` : '/profile';
	await gotoAuthedRoute(page, path, timeout);
	await waitForProfileTabs(page, timeout);
}

/**
 * Navigate to a specific profile tab and wait for it to load.
 *
 * Ensures the profile shell/tablist is ready, selects the tab if needed, and
 * for settings tabs (Notifications, AI Providers, System) waits for the Save
 * button as the data-loaded signal.
 */
export async function waitForProfileTab(
	page: Page,
	tabName: string,
	timeout = readyTimeoutMs()
): Promise<void> {
	await waitForProfileTabs(page, timeout);

	const tab = page.getByRole('tab', { name: tabName });
	await expect(tab).toBeVisible({ timeout });
	const selected = (await tab.getAttribute('aria-selected')) === 'true';
	if (!selected) {
		await tab.click();
	}
	await expect(tab).toHaveAttribute('aria-selected', 'true', { timeout });

	// For settings tabs, wait for Save button (proves data loaded)
	if (['Notifications', 'AI Providers', 'System'].includes(tabName)) {
		await expect(page.getByRole('button', { name: 'Save' })).toBeVisible({ timeout });
	}
}
