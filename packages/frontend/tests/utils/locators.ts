import type { Locator, Page } from '@playwright/test';

export function dialogByHeading(page: Page, heading: string | RegExp): Locator {
	return page.getByRole('dialog').filter({ has: page.getByRole('heading', { name: heading }) });
}

export function dialogByTextbox(page: Page, name: string | RegExp): Locator {
	return page.getByRole('dialog').filter({ has: page.getByRole('textbox', { name }) });
}
