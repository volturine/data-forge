import { expect, type Locator, type Page } from '@playwright/test';

async function waitForAnyVisible(locator: Locator, timeout: number): Promise<void> {
	await expect
		.poll(
			async () => {
				const count = await locator.count();
				for (let index = 0; index < count; index += 1) {
					if (
						await locator
							.nth(index)
							.isVisible()
							.catch(() => false)
					) {
						return true;
					}
				}
				return false;
			},
			{ timeout }
		)
		.toBe(true);
}

/**
 * Wait for the app shell to finish hydrating by confirming the main
 * navigation sidebar is visible. The sidebar only renders once the layout
 * `ready` flag is true (configStore loaded, auth resolved), so the labeled
 * navigation container is the stable shell readiness signal.
 *
 * Call before any interaction with shell-level UI (profile, theme toggle,
 * nav links) that lives outside page-specific content.
 */
export async function waitForAppShell(page: Page, timeout = 15_000): Promise<void> {
	await expect(page.getByLabel('Main navigation')).toBeVisible({ timeout });
	await expect(page.locator('[data-shell-interactive="true"]')).toBeVisible({ timeout });
}

/**
 * Shared layout readiness gate. Confirms:
 *  1. The main navigation sidebar is visible (app shell hydrated).
 *  2. The `<main>` content area has mounted (page slot rendered).
 *
 * Use as the first await after `page.goto(...)` before any page-specific
 * assertions. This guarantees the layout `ready` flag resolved, auth
 * completed, and the Svelte page component has started rendering.
 */
export async function waitForLayoutReady(page: Page, timeout = 30_000): Promise<void> {
	await expect(page.getByLabel('Main navigation')).toBeVisible({ timeout });
	await expect(page.locator('[data-shell-interactive="true"]')).toBeVisible({ timeout });
	await waitForAnyVisible(page.locator('main'), timeout);
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
	await waitForAnyVisible(terminal, timeout);
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
	await waitForAnyVisible(anyContent, timeout);

	// Wait for the search input to exist (only renders when analyses exist),
	// then let IndexedDB hydration settle by polling until the value stabilizes.
	const searchBox = page.getByRole('textbox', { name: 'Search analyses' });
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
	await waitForAnyVisible(terminal, timeout);
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
	await waitForAnyVisible(schemaReady, timeout);

	// If schema is still loading, wait for it to finish
	await waitForAnyVisible(
		config.locator('[data-schema-column], :text("No schema information available")'),
		timeout
	);
}

/**
 * Wait for the settings popup form to finish loading.
 *
 * The SettingsPopup component shows a spinner while fetching GET /settings
 * and only renders the form (including the Save button) once loading
 * completes — success or failure. The Save button is the strongest
 * readiness signal: it sits at the bottom of the form branch and proves
 * the entire settings form tree has rendered.
 *
 * @deprecated Settings now live under the profile page tabs. Use
 * {@link waitForProfileTab} instead.
 */
export async function waitForSettingsForm(dialog: Locator, timeout = 10_000): Promise<void> {
	await expect(dialog.getByRole('button', { name: 'Save' })).toBeVisible({ timeout });
}

/**
 * Wait for the profile page tabbed interface to be ready.
 *
 * Readiness signal: the tab list renders and at least one tab is selected.
 * Call after `page.goto('/profile')` or navigating to a specific hash tab.
 */
export async function waitForProfileTabs(page: Page, timeout = 15_000): Promise<void> {
	await expect(page.getByRole('tablist', { name: 'Profile sections' })).toBeVisible({ timeout });
	await expect(page.getByRole('tab', { selected: true })).toBeVisible({ timeout });
}

/**
 * Navigate to a specific profile tab and wait for it to load.
 *
 * Clicks the tab button and waits for the corresponding panel to be visible
 * and for any loading spinners to clear. For settings tabs (notifications,
 * ai-providers, system) the Save button is the readiness signal.
 */
export async function waitForProfileTab(
	page: Page,
	tabName: string,
	timeout = 15_000
): Promise<void> {
	const tab = page.getByRole('tab', { name: tabName });
	await expect(tab).toBeVisible({ timeout });
	await tab.click();
	await expect(tab).toHaveAttribute('aria-selected', 'true', { timeout });

	// For settings tabs, wait for Save button (proves data loaded)
	if (['Notifications', 'AI Providers', 'System'].includes(tabName)) {
		await expect(page.getByRole('button', { name: 'Save' })).toBeVisible({ timeout });
	}
}
