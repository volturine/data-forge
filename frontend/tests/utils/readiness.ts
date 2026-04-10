import { expect, type Locator, type Page } from '@playwright/test';

/**
 * Wait for the app shell to finish hydrating by confirming the Settings
 * button in the sidebar is visible and enabled. The sidebar only renders
 * once the layout `ready` flag is true (configStore loaded, auth resolved),
 * so a visible actionable button is a stronger readiness signal than the
 * container element alone.
 *
 * Call before any interaction with shell-level UI (Settings, theme toggle,
 * nav links) that lives outside page-specific content.
 */
export async function waitForAppShell(page: Page, timeout = 15_000): Promise<void> {
	await expect(page.getByRole('button', { name: 'Settings' })).toBeVisible({ timeout });
}

/**
 * Shared layout readiness gate. Confirms:
 *  1. The sidebar Settings button is visible (app shell hydrated).
 *  2. The `<main>` content area has mounted (page slot rendered).
 *
 * Use as the first await after `page.goto(...)` before any page-specific
 * assertions. This guarantees the layout `ready` flag resolved, auth
 * completed, and the Svelte page component has started rendering.
 */
export async function waitForLayoutReady(page: Page, timeout = 30_000): Promise<void> {
	await expect(page.getByRole('button', { name: 'Settings' })).toBeVisible({ timeout });
	await expect(page.getByRole('main').first()).toBeVisible({ timeout });
}

/**
 * Wait for the lineage page toolbar to finish rendering by confirming
 * the layout buttons are visible. Call after `page.goto('/lineage')`.
 */
export async function waitForLineageToolbar(page: Page, timeout = 15_000): Promise<void> {
	await expect(page.locator('button[title="Horizontal tree layout"]')).toBeVisible({ timeout });
}

/**
 * Wait for the datasource list query to reach a terminal state.
 * Terminal states: at least one `[data-ds-row]`, the empty-state text,
 * the filtered-empty text, or an error callout.
 */
export async function waitForDatasourceList(page: Page, timeout = 15_000): Promise<void> {
	const terminal = page.locator(
		'[data-ds-row], :text("No data sources yet"), :text("No datasources match"), [aria-live="polite"]'
	);
	await expect(terminal.first()).toBeVisible({ timeout });
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
export async function gotoAnalysesGallery(page: Page, timeout = 15_000): Promise<void> {
	await page.goto('/');
	await waitForLayoutReady(page, timeout);

	// The analyses page hydrates the search box from IndexedDB asynchronously.
	// A prior test may leave a non-empty filter (e.g. "ZZZNOMATCH") that hides
	// cards. We must wait for the query AND the persisted state to settle before
	// treating gallery content as final.
	const anyContent = page.locator(
		'[data-analysis-card], :text("No analyses match"), :text("No analyses yet")'
	);
	await expect(anyContent.first()).toBeVisible({ timeout });

	// Wait for the search input to exist (only renders when analyses exist),
	// then let IndexedDB hydration settle by polling until the value stabilizes.
	const searchBox = page.getByRole('textbox').first();
	const visible = await searchBox.isVisible().catch(() => false);
	if (visible) {
		// Poll until the search value stabilizes (IndexedDB hydration is async).
		let prev = '';
		let stable = 0;
		for (let i = 0; i < 20; i++) {
			const current = await searchBox.inputValue();
			if (current === prev) {
				stable++;
				if (stable >= 3) break;
			} else {
				prev = current;
				stable = 0;
			}
			await page.waitForTimeout(50);
		}

		const value = await searchBox.inputValue();
		if (value) {
			await searchBox.fill('');
			// After clearing, wait for gallery content to re-render
			await expect(
				page.locator('[data-analysis-card], :text("No analyses yet")').first()
			).toBeVisible({ timeout });
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
	timeout = 15_000
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
 * Navigate to `/analysis/new` and wait for the step-1 form to render.
 *
 * Readiness chain:
 *  1. Layout ready (shell hydrated).
 *  2. The `#name` input field is visible — proving the wizard mounted and
 *     step 1 rendered its form. This is a stronger gate than the heading
 *     alone because the input is the interactable element tests need next.
 */
export async function gotoNewAnalysis(page: Page, timeout = 15_000): Promise<void> {
	await page.goto('/analysis/new');
	await waitForLayoutReady(page, timeout);
	await expect(page.locator('#name')).toBeVisible({ timeout });
}

/**
 * Wait for the UDF list query to reach a terminal state.
 *
 * First waits for the page to mount (the "UDF Library" heading), then
 * waits for the query's terminal state: at least one `[data-udf-card]`,
 * the empty-state text, or an error callout.
 */
export async function waitForUdfList(page: Page, timeout = 15_000): Promise<void> {
	await expect(page.getByRole('heading', { name: 'UDF Library' })).toBeVisible({ timeout });

	const terminal = page.locator('[data-udf-card], :text("No UDFs yet"), [aria-live="polite"]');
	await expect(terminal.first()).toBeVisible({ timeout });
}

/**
 * Navigate to a UDF editor page and wait for the editor form to be ready.
 *
 * Readiness chain:
 *  1. Layout ready (shell hydrated).
 *  2. The `#udf-name` input is visible — proving the UDF query resolved
 *     and the editor form rendered.
 */
export async function gotoUdfEditor(page: Page, udfId: string, timeout = 15_000): Promise<void> {
	await page.goto(`/udfs/${udfId}`);
	await waitForLayoutReady(page, timeout);
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
export async function openSchemaTabAndWait(page: Page, timeout = 15_000): Promise<void> {
	const config = page.locator('[data-ds-config]');
	await config.getByRole('tab', { name: 'Schema' }).click();

	const schemaReady = config.locator(
		'[data-schema-column], :text("No schema information available"), :text("Loading schema")'
	);
	await expect(schemaReady.first()).toBeVisible({ timeout });

	// If schema is still loading, wait for it to finish
	await expect(
		config.locator('[data-schema-column], :text("No schema information available")').first()
	).toBeVisible({ timeout });
}

/**
 * Wait for the settings popup form to finish loading.
 *
 * The SettingsPopup component shows a spinner while fetching GET /settings
 * and only renders the form (including the Save button) once loading
 * completes — success or failure. The Save button is the strongest
 * readiness signal: it sits at the bottom of the form branch and proves
 * the entire settings form tree has rendered.
 */
export async function waitForSettingsForm(dialog: Locator, timeout = 10_000): Promise<void> {
	await expect(dialog.getByRole('button', { name: 'Save' })).toBeVisible({ timeout });
}
