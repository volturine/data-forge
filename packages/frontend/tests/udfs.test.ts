import { test as baseTest, expect } from './fixtures.js';
import type { Page } from '@playwright/test';
import { nameForAnalysisId } from './utils/api.js';
import { addStepAndOpenConfig, gotoAnalysisEditor } from './utils/analysis.js';
import { dialogByHeading } from './utils/locators.js';
import { DEFAULT_NAMESPACE, switchNamespace } from './utils/namespace.js';
import {
	readyTimeoutMs,
	gotoAuthedRoute,
	gotoNewUdfPage,
	gotoUdfEditor,
	gotoUdfLibrary
} from './utils/readiness.js';
import { uid } from './utils/uid.js';
import { createAnalysisViaUi } from './utils/user-flows.js';
import { deleteAnalysisViaUI, deleteUdfViaUI } from './utils/ui-cleanup.js';
import { screenshot } from './utils/visual.js';

type UdfAnalysis = { id: string; name: string };
type UdfDraftFields = { name: string; description?: string; tags?: string; code?: string };

const test = baseTest.extend<{ udfAnalysis: UdfAnalysis }>({
	udfAnalysis: async ({ page, sharedDatasource }, use) => {
		await gotoAuthedRoute(page, '/');
		await switchNamespace(page, DEFAULT_NAMESPACE);
		const id = await createAnalysisViaUi(page, sharedDatasource.name);
		const name = nameForAnalysisId(id);
		if (!name) throw new Error(`New analysis ${id} was not registered for cleanup`);

		try {
			await gotoAnalysisEditor(page, id);
			await use({ id, name });
		} finally {
			await deleteAnalysisViaUI(page, name, { id, namespace: DEFAULT_NAMESPACE });
		}
	}
});

async function createUdfViaEditor(page: Page, fields: UdfDraftFields): Promise<string> {
	await gotoNewUdfPage(page);
	await page.locator('#udf-name').fill(fields.name);
	await page.locator('#udf-description').fill(fields.description ?? `Test UDF: ${fields.name}`);
	await page.locator('#udf-tags').fill(fields.tags ?? 'test');
	await page.locator('.cm-content').fill(fields.code ?? 'def udf(value):\n    return value\n');

	const [response] = await Promise.all([
		page.waitForResponse(
			(candidate) =>
				candidate.url().endsWith('/api/v1/udf') &&
				candidate.request().method() === 'POST' &&
				candidate.status() !== 0
		),
		page.getByTestId('udf-save-button').click()
	]);
	if (!response.ok()) throw new Error(`UDF create failed: HTTP ${response.status()}`);

	const created = (await response.json()) as { id: string };
	await expect(page.getByRole('dialog')).toHaveCount(0);
	await expect(page).toHaveURL(/\/analysis\/[^/]+$/);
	return created.id;
}

test.describe('UDF library in analysis', () => {
	test('lists seeded UDFs and filters created metadata by name', async ({ page, udfAnalysis }) => {
		const udf = `e2e_library_${uid()}`;
		try {
			await expect(page).toHaveURL(`/analysis/${udfAnalysis.id}`);
			await gotoUdfLibrary(page);
			const library = dialogByHeading(page, 'UDF Library');
			await expect(library.locator('[data-udf-card="Ratio"]')).toBeVisible();
			await expect(library.locator('[data-udf-card="Coalesce"]')).toBeVisible();
			await expect(library.locator('[data-udf-card="Normalize"]')).toBeVisible();

			await createUdfViaEditor(page, {
				name: udf,
				description: `Test UDF: ${udf}`,
				tags: 'test, library'
			});
			await gotoUdfLibrary(page);

			const card = page.locator(`[data-udf-card="${udf}"]`);
			await expect(card).toBeVisible();
			await expect(card.getByText(`Test UDF: ${udf}`)).toBeVisible();
			await expect(card.getByText('library', { exact: true })).toBeVisible();

			const search = page.getByPlaceholder(/Search UDFs/i);
			await search.fill('ZZZNOMATCH');
			await expect(card).not.toBeVisible();
			await search.fill(udf);
			await expect(card).toBeVisible();
			await screenshot(page, 'udfs', 'analysis-library-with-udf');
		} finally {
			await deleteUdfViaUI(page, udf);
		}
	});

	test('clone and delete actions work, and delete confirmation can be cancelled', async ({
		page,
		udfAnalysis
	}) => {
		const udf = `e2e_clone_${uid()}`;
		const cloneName = `${udf} (copy)`;
		try {
			await expect(page).toHaveURL(`/analysis/${udfAnalysis.id}`);
			await createUdfViaEditor(page, { name: udf });
			await gotoUdfLibrary(page);
			const card = page.locator(`[data-udf-card="${udf}"]`);

			await card.getByRole('button', { name: 'Delete', exact: true }).click();
			await card.getByRole('button', { name: 'Cancel', exact: true }).click();
			await expect(card).toBeVisible();

			await card.getByRole('button', { name: 'Clone', exact: true }).click();
			await expect(page.locator(`[data-udf-card="${cloneName}"]`)).toBeVisible({
				timeout: readyTimeoutMs()
			});

			await card.getByRole('button', { name: 'Delete', exact: true }).click();
			await card.getByRole('button', { name: 'Confirm', exact: true }).click();
			await expect(card).toHaveCount(0, { timeout: readyTimeoutMs() });
		} finally {
			await deleteUdfViaUI(page, cloneName);
			await deleteUdfViaUI(page, udf);
		}
	});

	test('exports and imports UDFs through the library dialog', async ({ page, udfAnalysis }) => {
		const udf = `e2e_roundtrip_${uid()}`;
		try {
			await expect(page).toHaveURL(`/analysis/${udfAnalysis.id}`);
			await createUdfViaEditor(page, { name: udf });
			await gotoUdfLibrary(page);
			const library = dialogByHeading(page, 'UDF Library');
			await expect(page.locator(`[data-udf-card="${udf}"]`)).toBeVisible();

			const [download] = await Promise.all([
				page.waitForEvent('download'),
				library.getByRole('button', { name: 'Export', exact: true }).click()
			]);
			expect(download.suggestedFilename()).toBe('udfs.json');
			const stream = await download.createReadStream();
			const chunks: Buffer[] = [];
			for await (const chunk of stream)
				chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
			const exported = JSON.parse(Buffer.concat(chunks).toString('utf8')) as {
				udfs: Array<{ name: string }>;
			};
			const ownUdfs = exported.udfs.filter((entry) => entry.name === udf);
			expect(ownUdfs).toHaveLength(1);

			await library.getByRole('button', { name: 'Import', exact: true }).click();
			const importDialog = page.getByRole('dialog', { name: /Import UDFs/i });
			await expect(importDialog).toBeVisible();
			await page.locator('#udf-import-json').fill('not-valid-json');
			await importDialog.getByRole('button', { name: /^Import$/i }).click();
			await expect(importDialog.getByText(/Invalid JSON/i)).toBeVisible();

			await page.locator('#udf-import-json').fill('{"other": []}');
			await importDialog.getByRole('button', { name: /^Import$/i }).click();
			await expect(importDialog.getByText(/udfs array/i)).toBeVisible();
			await importDialog.getByRole('button', { name: 'Cancel', exact: true }).click();
			await expect(importDialog).toBeHidden();

			await deleteUdfViaUI(page, udf, { strict: true });
			const ownImport = JSON.stringify({ udfs: ownUdfs });
			await library.getByRole('button', { name: 'Import', exact: true }).click();
			const roundtripDialog = page.getByRole('dialog', { name: /Import UDFs/i });
			await page.locator('#udf-import-json').fill(ownImport);
			await roundtripDialog.getByRole('button', { name: /^Import$/i }).click();
			await expect(roundtripDialog).toBeHidden({ timeout: readyTimeoutMs() });
			await expect(page.locator(`[data-udf-card="${udf}"]`)).toBeVisible({
				timeout: readyTimeoutMs()
			});
		} finally {
			await deleteUdfViaUI(page, udf);
		}
	});

	test('new editor saves code and input signature, then reloads from the library', async ({
		page,
		udfAnalysis
	}) => {
		const udf = `e2e_signature_${uid()}`;
		try {
			await expect(page).toHaveURL(`/analysis/${udfAnalysis.id}`);
			await gotoNewUdfPage(page);
			await expect(page.locator('#udf-name')).toHaveValue('');
			await expect(page.getByTestId('udf-save-button')).toBeDisabled();

			await page.locator('#udf-name').fill(udf);
			await page.getByRole('button', { name: 'Add input', exact: true }).click();
			await page.locator('#udf-input-0-label').fill('left');
			await page.locator('#udf-input-1-label').fill('right');
			const code = 'def udf(left, right):\n    return left + right\n';
			await page.locator('.cm-content').fill(code);
			await expect(page.getByTestId('udf-save-button')).toBeEnabled();

			const [response] = await Promise.all([
				page.waitForResponse(
					(candidate) =>
						candidate.url().endsWith('/api/v1/udf') && candidate.request().method() === 'POST'
				),
				page.getByTestId('udf-save-button').click()
			]);
			expect(response.ok()).toBeTruthy();
			const saved = (await response.json()) as {
				id: string;
				signature: { inputs: Array<{ label?: string | null }> };
				code: string;
			};
			expect(saved.signature.inputs.map((input) => input.label)).toEqual(['left', 'right']);
			expect(saved.code).toBe(code);
			await expect(page.getByRole('dialog')).toHaveCount(0);
			await expect(page).toHaveURL(/\/analysis\/[^/]+$/);

			await gotoUdfEditor(page, udf);
			await expect(page.locator('#udf-name')).toHaveValue(udf);
			await expect(page.locator('.cm-editor')).toContainText('return left + right');
			await screenshot(page, 'udfs', 'analysis-editor-saved-signature');
		} finally {
			await deleteUdfViaUI(page, udf);
		}
	});

	test('a rejected save retains the draft and allows correction', async ({ page, udfAnalysis }) => {
		const udf = `e2e_rejected_${uid()}`;
		try {
			await gotoNewUdfPage(page);
			await page.locator('#udf-name').fill(udf);
			await page.locator('#udf-description').fill('Keep this draft after a failed save');
			await page.locator('.cm-content').fill('def udf(value)\n    return value\n');
			const response = page.waitForResponse(
				(candidate) =>
					candidate.url().endsWith('/api/v1/udf') && candidate.request().method() === 'POST'
			);
			await page.getByTestId('udf-save-button').click();
			expect((await response).ok()).toBe(false);
			await expect(page.getByTestId('udf-save-error')).toContainText('Invalid Python syntax');
			await expect(page.locator('#udf-name')).toHaveValue(udf);
			await expect(page.locator('#udf-description')).toHaveValue(
				'Keep this draft after a failed save'
			);
			await expect(page.locator('.cm-editor')).toContainText('def udf(value)');
			await expect(page.getByTestId('udf-save-button')).toBeEnabled();
			await expect(page).toHaveURL(`/analysis/${udfAnalysis.id}`);

			await createUdfViaEditor(page, { name: udf });
			await gotoUdfEditor(page, udf);
			await expect(page.locator('.cm-editor')).toContainText('return value');
		} finally {
			await deleteUdfViaUI(page, udf);
		}
	});

	test('updates the selected UDF, saves a copy, and discards an editor draft', async ({
		page,
		udfAnalysis
	}) => {
		const udf = `e2e_edit_${uid()}`;
		const copy = `${udf} (copy)`;
		const renamedPredefined = `Ratio ${uid()}`;
		const predefinedCopy = `${renamedPredefined} (copy)`;
		try {
			await expect(page).toHaveURL(`/analysis/${udfAnalysis.id}`);
			const udfId = await createUdfViaEditor(page, { name: udf });
			await gotoUdfEditor(page, udf);
			await page.locator('#udf-description').fill('Updated description from E2E');

			const [updateResponse] = await Promise.all([
				page.waitForResponse(
					(response) =>
						response.url().endsWith(`/api/v1/udf/${udfId}`) && response.request().method() === 'PUT'
				),
				page.getByTestId('udf-save-button').click()
			]);
			expect(updateResponse.ok()).toBeTruthy();
			await expect(page.getByRole('dialog')).toHaveCount(0);
			await gotoUdfEditor(page, udf);
			await expect(page.locator('#udf-description')).toHaveValue('Updated description from E2E');

			await page.locator('#udf-description').fill('Copy-only description');
			await page.locator('.cm-content').fill('def udf(value):\n    return value * 9\n');
			const [copyResponse] = await Promise.all([
				page.waitForResponse(
					(response) =>
						response.url().endsWith('/api/v1/udf') && response.request().method() === 'POST'
				),
				page.getByTestId('udf-save-as-new-button').click()
			]);
			expect(copyResponse.ok()).toBeTruthy();
			const savedCopy = (await copyResponse.json()) as { id: string; name: string };
			expect(savedCopy.name).toBe(copy);
			await expect(page.getByRole('dialog')).toHaveCount(0);

			await gotoUdfLibrary(page);
			const originalCard = page.locator(`[data-udf-card="${udf}"]`);
			const copyCard = page.locator(`[data-udf-card="${copy}"]`);
			await expect(originalCard.getByText('Updated description from E2E')).toBeVisible();
			await expect(originalCard.getByText('Copy-only description')).toHaveCount(0);
			await expect(copyCard.getByText('Copy-only description')).toBeVisible();

			await gotoUdfEditor(page, udf);
			await expect(page.locator('.cm-editor')).not.toContainText('return value * 9');
			await page.locator('#udf-description').fill('Discarded draft');
			await page.getByRole('button', { name: 'Back to UDF library' }).click();
			const discardDialog = page.getByRole('alertdialog');
			await expect(discardDialog).toBeVisible();
			await discardDialog.getByRole('button', { name: 'Discard changes' }).click();
			await expect(dialogByHeading(page, 'UDF Library')).toBeVisible();
			await expect(originalCard.getByText('Updated description from E2E')).toBeVisible();

			await gotoUdfEditor(page, 'Ratio');
			const originalDescription = await page.locator('#udf-description').inputValue();
			await page.locator('#udf-name').fill(renamedPredefined);
			await page.locator('#udf-description').fill('Predefined copy draft');
			await page
				.locator('.cm-content')
				.fill('def udf(numerator, denominator):\n    return numerator / denominator + 2\n');
			const [predefinedResponse] = await Promise.all([
				page.waitForResponse(
					(response) =>
						response.url().endsWith('/api/v1/udf') && response.request().method() === 'POST'
				),
				page.getByTestId('udf-save-as-new-button').click()
			]);
			expect(predefinedResponse.ok()).toBeTruthy();
			const savedPredefinedCopy = (await predefinedResponse.json()) as { name: string };
			expect(savedPredefinedCopy.name).toBe(predefinedCopy);
			await expect(page.getByRole('dialog')).toHaveCount(0);

			await gotoUdfLibrary(page);
			await expect(page.locator(`[data-udf-card="${predefinedCopy}"]`)).toBeVisible();
			await gotoUdfEditor(page, 'Ratio');
			await expect(page.locator('#udf-name')).toHaveValue('Ratio');
			await expect(page.locator('#udf-description')).toHaveValue(originalDescription);
			await expect(page.locator('.cm-editor')).toContainText('return numerator / denominator');
			await screenshot(page, 'udfs', 'analysis-editor-save-as-new');
		} finally {
			await deleteUdfViaUI(page, predefinedCopy);
			await deleteUdfViaUI(page, copy);
			await deleteUdfViaUI(page, udf);
		}
	});

	test('inline UDF editor applies a draft and can save it to the library', async ({
		page,
		udfAnalysis
	}) => {
		const udf = `e2e_inline_${uid()}`;
		try {
			const config = await addStepAndOpenConfig(page, udfAnalysis.id, 'with_columns');
			await config.locator('#wc-expr-type').selectOption('udf');
			await config.locator('#wc-expr-name').fill(udf);
			await config.getByRole('button', { name: 'Edit UDF', exact: true }).click();
			const editor = page.getByRole('dialog');
			await expect(editor.getByRole('heading', { name: 'New UDF' })).toBeVisible();
			await expect(editor.getByRole('button', { name: 'Use in analysis' })).toBeVisible();
			await page.locator('#udf-name').fill(udf);
			const code = 'def udf():\n    return 1\n';
			await page.locator('.cm-content').fill(code);
			await editor.getByRole('button', { name: 'Use in analysis' }).click();
			await expect(page.getByRole('dialog')).toHaveCount(0);
			await expect(page).toHaveURL(`/analysis/${udfAnalysis.id}`);

			await config.getByRole('button', { name: 'Edit UDF', exact: true }).click();
			await expect(page.locator('.cm-editor')).toContainText('return 1');
			const [response] = await Promise.all([
				page.waitForResponse(
					(candidate) =>
						candidate.url().endsWith('/api/v1/udf') && candidate.request().method() === 'POST'
				),
				page.getByTestId('udf-save-button').click()
			]);
			expect(response.ok()).toBeTruthy();
			await expect(page.getByRole('dialog')).toHaveCount(0);
			await expect(page).toHaveURL(`/analysis/${udfAnalysis.id}`);

			await gotoUdfLibrary(page);
			await expect(page.locator(`[data-udf-card="${udf}"]`)).toBeVisible();
		} finally {
			await deleteUdfViaUI(page, udf);
		}
	});

	test('editor syntax colors follow the app theme when reopened', async ({ page, udfAnalysis }) => {
		await expect(page).toHaveURL(`/analysis/${udfAnalysis.id}`);
		await gotoNewUdfPage(page);
		const code = 'def udf(value):\n    return value * 9.0 / 5.0 + 32\n';
		await page.locator('.cm-content').fill(code);
		const editor = page.locator('.cm-editor');
		await expect(editor.locator('.cm-code-keyword').first()).toHaveText('def');
		await expect(editor.locator('.cm-code-number').first()).toHaveText('9.0');

		async function expectThemeColors(): Promise<void> {
			const colors = await editor.evaluate((element) => {
				const content = element.querySelector('.cm-content');
				const outerSurface = element.parentElement?.parentElement;
				const keyword = element.querySelector('.cm-code-keyword');
				const number = element.querySelector('.cm-code-number');
				if (!content || !outerSurface || !keyword || !number) {
					throw new Error('Expected code editor content and themed syntax tokens');
				}

				function tokenColor(token: string): string {
					const probe = document.createElement('span');
					probe.style.color = `var(${token})`;
					document.body.append(probe);
					const color = getComputedStyle(probe).color;
					probe.remove();
					return color;
				}

				return {
					background: getComputedStyle(element).backgroundColor,
					surface: getComputedStyle(outerSurface).backgroundColor,
					keyword: getComputedStyle(keyword).color,
					number: getComputedStyle(number).color,
					error: tokenColor('--colors-fg-error'),
					warning: tokenColor('--colors-fg-warning')
				};
			});
			expect(colors.background).toBe(colors.surface);
			expect(colors.keyword).toBe(colors.error);
			expect(colors.number).toBe(colors.warning);
		}

		await expectThemeColors();
		await page.getByRole('button', { name: 'Back to UDF library' }).click();
		await page.getByRole('alertdialog').getByRole('button', { name: 'Discard changes' }).click();
		await page.getByRole('button', { name: 'Close UDF dialog' }).click();
		await page.getByRole('button', { name: 'Toggle theme' }).click();
		await gotoNewUdfPage(page);
		await page.locator('.cm-content').fill(code);
		await expectThemeColors();
		await screenshot(page, 'udfs', 'analysis-editor-theme');
	});
});
