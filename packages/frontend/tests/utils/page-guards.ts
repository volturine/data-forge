import type { BrowserContext, Page } from '@playwright/test';

/**
 * Install per-page e2e guards so navigation cannot hang the full test wall.
 *
 * Playwright auto-dismisses browser dialogs. For `beforeunload`, dismiss means
 * "stay on the page", so `page.goto` never completes when the analysis editor is
 * dirty. Accept leave so cleanup and multi-step tests can navigate away.
 */
export function installE2ePageGuards(page: Page): void {
	page.on('dialog', async (dialog) => {
		try {
			if (dialog.type() === 'beforeunload') {
				await dialog.accept();
				return;
			}
			// Unexpected alert/confirm/prompt — do not block the suite.
			await dialog.dismiss();
		} catch {
			// Page may already be closing when a late dialog fires.
		}
	});
}

/** Attach guards to every page this context creates (including future ones). */
export function installE2eContextGuards(context: BrowserContext): void {
	context.on('page', (page) => {
		installE2ePageGuards(page);
	});
	for (const page of context.pages()) {
		installE2ePageGuards(page);
	}
}
