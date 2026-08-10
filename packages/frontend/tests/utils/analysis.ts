import { expect, type Locator, type Page } from '@playwright/test';
import { gotoAuthedRoute, readyTimeoutMs, waitForLayoutReady } from './readiness.js';

type EditorAccessState = 'editable' | 'locked';

async function findVisibleLocator(locator: Locator): Promise<Locator | null> {
	const count = await locator.count();
	for (let index = 0; index < count; index += 1) {
		const candidate = locator.nth(index);
		if (await candidate.isVisible().catch(() => false)) {
			return candidate;
		}
	}
	return null;
}

/**
 * Wait for the analysis editor to be fully interactive. Ensures:
 *  1. `[role="application"]` has mounted (analysis query resolved).
 *  2. At least one step button (`button[data-step]`) is visible,
 *     expanding the left pane if it was auto-collapsed.
 *  3. At least one step button is enabled (lock acquired, readOnly=false).
 *
 * Uses a single deadline for the entire chain so stacked sequential waits
 * cannot each consume the full timeout under parallel-test load.
 *
 * This does NOT depend on the "Operations" heading which becomes invisible
 * when the left pane is collapsed (`visibility: hidden; width: 0`).
 */
async function waitForAnalysisEditor(
	page: Page,
	deadline: number,
	accessState: EditorAccessState
): Promise<void> {
	const remaining = () => Math.max(deadline - Date.now(), 1_000);
	const editor = page.locator('[role="application"]');
	// Client-side analysis loads occasionally land on SvelteKit's 500 page under
	// Docker-engine host load. Soft-reload once with a reserved budget so the
	// suite recovers without Playwright-level retries.
	const firstAttemptMs = Math.max(5_000, Math.floor((deadline - Date.now()) / 2));
	let lastError: unknown;
	for (let attempt = 0; attempt < 2; attempt += 1) {
		const attemptTimeout = attempt === 0 ? Math.min(firstAttemptMs, remaining()) : remaining();
		try {
			await expect(editor).toBeVisible({ timeout: attemptTimeout });
			lastError = null;
			break;
		} catch (error) {
			lastError = error;
			const errorPage = page.getByText('Internal Error');
			const onErrorPage = await errorPage
				.first()
				.isVisible()
				.catch(() => false);
			if (attempt === 0 && Date.now() + 2_000 < deadline && !page.isClosed()) {
				await page.reload({ waitUntil: 'domcontentloaded' });
				await waitForLayoutReady(page, remaining());
				continue;
			}
			if (onErrorPage) {
				throw new Error(
					`Analysis editor failed with a client 500 (Internal Error) after ${attempt + 1} attempt(s)`,
					{ cause: error }
				);
			}
			throw error;
		}
	}
	if (lastError) throw lastError;

	await expect(editor).toHaveAttribute('data-editor-access-state', accessState, {
		timeout: remaining()
	});

	const stepButtons = page.locator('button[data-step]');
	let anyStepButton = await findVisibleLocator(stepButtons);
	const alreadyVisible = anyStepButton !== null;

	if (!alreadyVisible) {
		const expandBtn = await findVisibleLocator(page.locator('button[title="Expand panels"]'));
		if (expandBtn) {
			await expandBtn.click();
		}
	}

	await expect(stepButtons.filter({ visible: true }).first()).toBeVisible({
		timeout: remaining()
	});
	anyStepButton = await findVisibleLocator(stepButtons);
	if (!anyStepButton) {
		throw new Error('Analysis editor step library did not render a visible step button');
	}
	if (accessState === 'editable') {
		await expect(anyStepButton).toBeEnabled({ timeout: remaining() });
		return;
	}
	await expect(anyStepButton).toBeDisabled({ timeout: remaining() });
}

async function waitForCurrentAnalysisId(page: Page, deadline: number): Promise<string> {
	await page.waitForURL(/\/analysis\/(?!new(?:\/|$))[^/?#]+/, {
		timeout: Math.max(deadline - Date.now(), 1_000)
	});
	const match = page.url().match(/\/analysis\/([^/?#]+)/);
	return match?.[1] ?? '';
}

async function waitForCurrentAnalysisEditorByState(
	page: Page,
	accessState: EditorAccessState,
	timeout: number
): Promise<string> {
	// URL resolution (create/import redirect) can take most of a shared budget under
	// parallel CI load. Give layout + editor a fresh full timeout once the analysis
	// id is known so later stages are not starved down to the 1s floor.
	const analysisId = await waitForCurrentAnalysisId(page, Date.now() + timeout);
	const stageDeadline = Date.now() + timeout;
	await waitForLayoutReady(page, Math.max(stageDeadline - Date.now(), 1_000));
	await waitForAnalysisEditor(page, stageDeadline, accessState);
	return analysisId;
}

export async function waitForCurrentAnalysisEditor(
	page: Page,
	timeout = readyTimeoutMs()
): Promise<string> {
	return waitForCurrentAnalysisEditorByState(page, 'editable', timeout);
}

export async function waitForCurrentReadOnlyAnalysisEditor(
	page: Page,
	timeout = readyTimeoutMs()
): Promise<string> {
	return waitForCurrentAnalysisEditorByState(page, 'locked', timeout);
}

/**
 * Navigate to an analysis page and wait until the step library is fully
 * rendered and interactable. Handles the case where the left pane is
 * auto-collapsed on narrow viewports by expanding it first.
 *
 * All readiness checks share a single deadline (default 60s) so that
 * under parallel-test load, one slow stage cannot starve the next.
 *
 * Readiness chain:
 *  1. Navigation + URL confirmed.
 *  2. Layout ready (shell hydrated, `<main>` visible).
 *  3. `[role="application"]` mounted (analysis query succeeded).
 *  4. A step button is visible and enabled (lock acquired).
 */
export async function gotoAnalysisEditor(
	page: Page,
	analysisId: string,
	timeout = readyTimeoutMs()
): Promise<void> {
	await gotoAuthedRoute(page, `/analysis/${analysisId}`, timeout);
	await expect(page).toHaveURL(`/analysis/${analysisId}`, { timeout });
	await waitForCurrentAnalysisEditor(page, timeout);
}

export async function gotoReadOnlyAnalysisEditor(
	page: Page,
	analysisId: string,
	timeout = readyTimeoutMs()
): Promise<void> {
	await gotoAuthedRoute(page, `/analysis/${analysisId}`, timeout);
	await expect(page).toHaveURL(`/analysis/${analysisId}`, { timeout });
	await waitForCurrentReadOnlyAnalysisEditor(page, timeout);
}

/**
 * After a `page.reload()` inside the analysis editor, re-confirm readiness.
 * Same gates as `gotoAnalysisEditor` but without the navigation step.
 */
export async function waitForEditorReload(page: Page, timeout = readyTimeoutMs()): Promise<void> {
	await waitForCurrentAnalysisEditor(page, timeout);
}

/**
 * Navigate to an analysis, wait for the step library, add a step,
 * click "edit" on the resulting canvas node to open its config panel.
 * Returns the config panel locator.
 */
export async function addStepAndOpenConfig(
	page: Page,
	analysisId: string,
	stepType: string
): Promise<Locator> {
	await gotoAnalysisEditor(page, analysisId);

	const stepBtn = page.locator(`button[data-step="${stepType}"]`);
	await expect(stepBtn).toBeEnabled({ timeout: 5_000 });
	await stepBtn.click();

	const canvasNodes = page.locator(`[data-step-type="${stepType}"]`);
	await expect(canvasNodes.filter({ visible: true }).first()).toBeVisible({ timeout: 5_000 });
	const canvasNode = canvasNodes.nth((await canvasNodes.count()) - 1);
	await expect(canvasNode).toBeVisible({ timeout: 5_000 });

	const editBtn = canvasNode.locator('[data-action="edit"]');
	await expect(editBtn).toBeVisible({ timeout: 3_000 });
	await editBtn.click();

	const configPanel = page.locator(`[data-step-config="${stepType}"]`);
	await expect(configPanel).toBeVisible({ timeout: 5_000 });
	const configBody = configPanel.locator(':scope > *');
	await expect(configBody.first()).toBeVisible({ timeout: 5_000 });
	return configPanel;
}
