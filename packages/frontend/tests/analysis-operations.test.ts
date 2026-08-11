import { test, expect } from './fixtures.js';
import {
	createDatasource,
	createDatasourceWithDates,
	createAnalysis,
	type E2ERequest
} from './utils/api.js';
import { addStepAndOpenConfig, gotoAnalysisEditor } from './utils/analysis.js';
import {
	createCleanupPage,
	deleteDatasourceViaUI,
	freeRegisteredWarmEnginesViaUI,
	freeWarmEnginesViaUI
} from './utils/ui-cleanup.js';
import { screenshot } from './utils/visual.js';
import { uid } from './utils/uid.js';
import type { Browser } from '@playwright/test';
import { readyTimeoutMs, waitForInlinePreviewReady } from './utils/readiness.js';

const port = parseInt(process.env.FRONTEND_PORT || '3000', 10);
const baseURL = process.env.PLAYWRIGHT_BASE_URL || `http://localhost:${port}`;

let sharedBaseDatasourceName = '';
let sharedBaseDatasourceId = '';
let sharedAuxDatasourceName = '';
let sharedDateDatasourceName = '';
let sharedDateDatasourceId = '';

function workerRequest(
	browser: Browser,
	workerAuth: { workerIndex: number; sessionState: E2ERequest['sessionState'] },
	helperContext: E2ERequest['helperContext']
): E2ERequest {
	return {
		browser,
		sessionState: workerAuth.sessionState,
		helperContext,
		workerIndex: workerAuth.workerIndex,
		baseURL
	} as unknown as E2ERequest;
}

async function createTrackedAnalysis(
	request: E2ERequest,
	analysisName: string,
	datasourceId: string
): Promise<string> {
	return createAnalysis(request, analysisName, datasourceId);
}

test.beforeAll(async ({ browser, workerAuth, helperContext }) => {
	const request = workerRequest(browser, workerAuth, helperContext);
	const id = uid();
	sharedBaseDatasourceName = `e2e-ops-base-${id}`;
	sharedAuxDatasourceName = `e2e-ops-aux-${id}`;
	sharedDateDatasourceName = `e2e-ops-date-${id}`;
	sharedBaseDatasourceId = await createDatasource(request, sharedBaseDatasourceName);
	await createDatasource(request, sharedAuxDatasourceName);
	sharedDateDatasourceId = await createDatasourceWithDates(request, sharedDateDatasourceName);
});

test.afterAll(async ({ browser, workerAuth }) => {
	const { page, context } = await createCleanupPage(browser, workerAuth.sessionState);
	// Drop any leftover warm analysis/preview engines from this worker, then
	// remove shared datasource fixtures through the gallery UI.
	await freeRegisteredWarmEnginesViaUI(page).catch(() => undefined);
	await freeWarmEnginesViaUI(page, {
		datasourceIds: [sharedBaseDatasourceId, sharedDateDatasourceId].filter(Boolean)
	}).catch(() => undefined);
	for (const name of [
		sharedBaseDatasourceName,
		sharedAuxDatasourceName,
		sharedDateDatasourceName
	]) {
		if (name) {
			await deleteDatasourceViaUI(page, name).catch(() => undefined);
		}
	}
	await page.close();
	await context.close();
});

// ── Download format switching ───────────────────────────────────────────────

test.describe('Analyses – download config format switching', () => {
	test('Download: format switch changes selection and filename is editable', async ({
		page,
		request
	}) => {
		const id = uid();
		const analysis = `E2E Download Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'download');

			// Format select should be visible
			const formatSelect = configPanel.locator('#download-format');
			await expect(formatSelect).toBeVisible();

			// Filename input should be visible with default value
			const filenameInput = configPanel.locator('#download-filename');
			await expect(filenameInput).toBeVisible();
			await expect(filenameInput).toHaveValue('download');

			// Default format is csv
			await expect(formatSelect).toHaveValue('csv');

			// Switch to parquet
			await formatSelect.selectOption('parquet');
			await expect(formatSelect).toHaveValue('parquet');

			// Switch to duckdb
			await formatSelect.selectOption('duckdb');
			await expect(formatSelect).toHaveValue('duckdb');

			// Change filename
			await filenameInput.fill('my_export');
			await expect(filenameInput).toHaveValue('my_export');

			// Apply
			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analysis/operations', 'download-config-format-switch');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

// ── Basic operations ────────────────────────────────────────────────────────

test.describe('Analyses – limit config editing', () => {
	test('Limit: set row count, Apply, verify disabled buttons', async ({ page, request }) => {
		const id = uid();
		const analysis = `E2E Limit Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'limit');

			// Fill in the limit rows input
			const limitInput = configPanel.locator('[data-testid="limit-rows-input"]');
			await expect(limitInput).toBeVisible();
			await limitInput.fill('42');

			// Apply is enabled (new step + changed config)
			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();

			// After apply, both buttons should be disabled (no changes)
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });
			await expect(configPanel.getByRole('button', { name: 'Cancel' })).toBeDisabled();

			await screenshot(page, 'analysis/operations', 'limit-config-applied');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

test.describe('Analyses – expression config editing', () => {
	test('Expression: fill expression + column name, Apply', async ({ page, request }) => {
		const id = uid();
		const analysis = `E2E Expr Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'expression');

			// Fill the expression textarea
			const exprTextarea = configPanel.locator('[data-testid="expr-expression-textarea"]');
			await expect(exprTextarea).toBeVisible();
			await exprTextarea.fill('pl.col("age") * 2');

			// Fill the column name input
			const columnInput = configPanel.locator('[data-testid="expr-column-input"]');
			await expect(columnInput).toBeVisible();
			await columnInput.fill('age_doubled');

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();

			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analysis/operations', 'expression-config-applied');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

test.describe('Analyses – sort config editing', () => {
	test('Sort: add sort rule via ColumnDropdown, Apply, then remove rule', async ({
		page,
		request
	}) => {
		const id = uid();
		const analysis = `E2E Sort Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'sort');

			const emptyState = configPanel.locator('#sort-empty-state');
			await expect(emptyState).toBeVisible();

			// Open column dropdown — click the dropdown trigger button
			const dropdownTrigger = configPanel.locator('button[aria-expanded]');
			await expect(dropdownTrigger).toHaveCount(1);
			await dropdownTrigger.click();
			// Select the 'name' column from the dropdown
			await page.getByRole('option', { name: 'name', exact: true }).click();

			// Click "Add" button
			const addBtn = configPanel.locator('[data-testid="sort-add-button"]');
			await expect(addBtn).toBeEnabled();
			await addBtn.click();

			// The sort rule should appear in the list
			await expect(configPanel.getByText('name')).toBeVisible();
			await expect(emptyState).toBeHidden();

			// Apply the config
			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analysis/operations', 'sort-config-with-rule');

			// Remove the sort rule
			await configPanel.locator('[data-testid="sort-remove-rule-0"]').waitFor({ state: 'visible' });
			const removeBtn = configPanel.locator('[data-testid="sort-remove-rule-0"]');
			await removeBtn.click();

			await expect(removeBtn).toBeHidden();
			await expect(emptyState).toBeVisible();
			// Apply is now enabled again (change from applied state)
			await expect(applyBtn).toBeEnabled();
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

test.describe('Analyses – rename config editing', () => {
	test('Rename: add mapping via dropdown + input, Apply, then Cancel reverts', async ({
		page,
		request
	}) => {
		const id = uid();
		const analysis = `E2E Rename Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'rename');

			// Empty state visible
			await expect(configPanel.getByText(/No renames yet/i)).toBeVisible();

			// Open column dropdown to pick a column to rename
			const dropdownTrigger = configPanel.locator('button[aria-expanded]');
			await expect(dropdownTrigger).toHaveCount(1);
			await dropdownTrigger.click();
			await page.getByRole('option', { name: 'name', exact: true }).click();

			// Fill the new name input
			const newNameInput = configPanel.locator('[data-testid="rename-new-name-input"]');
			await expect(newNameInput).toBeEnabled();
			await newNameInput.fill('full_name');

			// Click "Add Rename"
			const addBtn = configPanel.locator('[data-testid="rename-add-button"]');
			await expect(addBtn).toBeEnabled();
			await addBtn.click();

			// Mapping should appear
			await expect(configPanel.getByText('full_name')).toBeVisible();
			await expect(configPanel.getByText(/No renames yet/i)).not.toBeVisible();

			// Apply
			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analysis/operations', 'rename-config-applied');

			// Now remove the mapping to create a change
			const removeBtn = configPanel.locator('[data-testid="rename-remove-button-name"]');
			await removeBtn.click();
			await expect(configPanel.getByText(/No renames yet/i)).toBeVisible();

			// Cancel should revert to the applied state
			const cancelBtn = configPanel.getByRole('button', { name: 'Cancel' });
			await expect(cancelBtn).toBeEnabled();
			await cancelBtn.click();

			// After cancel, mapping should be restored
			await expect(configPanel.getByText('full_name')).toBeVisible();
			// And both buttons disabled again
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

test.describe('Analyses – filter config editing', () => {
	test('Filter: change operator, type value, Apply; then Cancel reverts', async ({
		page,
		request
	}) => {
		const id = uid();
		const analysis = `E2E Filter Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'filter');

			// The filter starts with one empty condition — select a column
			const dropdownTrigger = configPanel.locator('button[aria-expanded]');
			await expect(dropdownTrigger).toHaveCount(1);
			await dropdownTrigger.click();
			await page.getByRole('option', { name: 'name', exact: true }).click();

			// Change operator to "contains"
			const operatorSelect = configPanel.locator('[data-testid="filter-operator-select-0"]');
			await operatorSelect.selectOption('contains');

			// Type a filter value (name is string type → uses multi-literal input with Enter)
			const valueInput = configPanel.locator('[data-testid="filter-value-input-0"]');
			await valueInput.fill('Alice');
			await valueInput.press('Enter');

			// The token "Alice" should appear
			await expect(configPanel.getByText('Alice')).toBeVisible();

			// Apply
			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analysis/operations', 'filter-config-applied');

			// Make a change: add another value token
			const valueInputAfter = configPanel.locator('[data-testid="filter-value-input-0"]');
			await valueInputAfter.fill('Bob');
			await valueInputAfter.press('Enter');
			await expect(configPanel.getByText('Bob')).toBeVisible();

			// Now Cancel to revert
			const cancelBtn = configPanel.getByRole('button', { name: 'Cancel' });
			await expect(cancelBtn).toBeEnabled();
			await cancelBtn.click();

			// After Cancel, Bob should be gone (reverted) and Alice should remain
			await expect(configPanel.getByText('Bob')).not.toBeVisible({ timeout: 3_000 });
			await expect(configPanel.getByText('Alice')).toBeVisible();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

// ── View and chart ──────────────────────────────────────────────────────────

test.describe('Analyses – view node inline preview', () => {
	test('view step renders inline data table with preview data', async ({ page, request }) => {
		const id = uid();
		const analysis = `E2E View Preview ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			await gotoAnalysisEditor(page, aId);
			await waitForInlinePreviewReady(page);

			await screenshot(page, 'analysis/operations', 'view-inline-preview');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

test.describe('Analyses – chart config and preview', () => {
	test('chart step: configure x/y columns, apply, chart SVG renders', async ({ page, request }) => {
		const id = uid();
		const analysis = `E2E Chart Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'chart');

			// Select X column — first ColumnDropdown in config
			const xGroup = configPanel.getByRole('group', { name: 'X Column' });
			await xGroup.locator('button[aria-expanded]').click();
			await page.locator('[data-column-option="city"]').click();

			const yGroup = configPanel.getByRole('group', { name: 'Y Column' });
			await yGroup.locator('button[aria-expanded]').click();
			await page.locator('[data-column-option="age"]').click();

			// Apply
			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			// Chart preview should render (contains an SVG)
			const chartPreview = page.locator('[data-testid="chart-preview"]');
			await expect(chartPreview).toBeVisible({ timeout: readyTimeoutMs() });
			await expect(chartPreview.locator('svg')).toBeVisible({ timeout: readyTimeoutMs() });

			await screenshot(page, 'analysis/operations', 'chart-preview-rendered');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

// ── Aggregation operations ──────────────────────────────────────────────────

test.describe('Analyses – groupby config editing', () => {
	test('GroupBy: select group column, add aggregation, Apply', async ({ page, request }) => {
		const id = uid();
		const analysis = `E2E GroupBy Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'groupby');

			// Select groupBy column via MultiSelectColumnDropdown
			const groupBySection = configPanel.getByRole('group', { name: 'Group By Columns' });
			await groupBySection.locator('button[aria-expanded]').click();
			await page.locator('#msc-col-city').click();

			// Click outside to close dropdown
			await configPanel.click({ position: { x: 5, y: 5 } });

			// Add an aggregation: select column, pick function, click Add
			const aggSection = configPanel.getByRole('group', { name: 'Aggregations' });
			const aggColumnDropdown = aggSection
				.getByRole('group', { name: 'Add aggregation form' })
				.locator('button[aria-expanded]');
			await aggColumnDropdown.click();
			await page.getByRole('option', { name: 'age', exact: true }).click();

			// Change function to 'mean'
			const funcSelect = configPanel.locator('[data-testid="agg-function-select"]');
			await funcSelect.selectOption('mean');

			// Click Add
			const addBtn = configPanel.locator('[data-testid="agg-add-button"]');
			await expect(addBtn).toBeEnabled();
			await addBtn.click();

			// Aggregation should appear in list
			await expect(configPanel.getByText('mean(age) as age_mean')).toBeVisible();

			// Apply
			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analysis/operations', 'groupby-config-applied');

			// Remove the aggregation
			const removeBtn = configPanel.locator('[data-testid="agg-remove-button-0"]');
			await removeBtn.click();

			// Aggregation list should be empty
			await expect(configPanel.getByText('mean(age) as age_mean')).not.toBeVisible();
			await expect(applyBtn).toBeEnabled();
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

test.describe('Analyses – sample config editing', () => {
	test('Sample: set fraction + seed, Apply, buttons disable', async ({ page, request }) => {
		const id = uid();
		const analysis = `E2E Sample Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'sample');

			const fractionInput = configPanel.locator('[data-testid="sample-fraction-input"]');
			await expect(fractionInput).toBeVisible();
			await fractionInput.fill('0.25');

			const seedInput = configPanel.locator('[data-testid="sample-seed-input"]');
			await seedInput.fill('99');

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });
			await expect(configPanel.getByRole('button', { name: 'Cancel' })).toBeDisabled();

			await screenshot(page, 'analysis/operations', 'sample-config-applied');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

test.describe('Analyses – topk config editing', () => {
	test('TopK: select column, set k, toggle descending, Apply', async ({ page, request }) => {
		const id = uid();
		const analysis = `E2E TopK Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'topk');

			// Select column via ColumnDropdown
			const dropdownTrigger = configPanel.locator('button[aria-expanded]');
			await expect(dropdownTrigger).toHaveCount(1);
			await dropdownTrigger.click();
			await page.getByRole('option', { name: 'age', exact: true }).click();

			// Set k value
			const kInput = configPanel.locator('[data-testid="topk-k-input"]');
			await kInput.fill('5');

			// Toggle descending
			const descCheckbox = configPanel.locator('[data-testid="topk-descending-checkbox"]');
			await descCheckbox.check();
			await expect(descCheckbox).toBeChecked();

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analysis/operations', 'topk-config-applied');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

// ── Reshape operations ──────────────────────────────────────────────────────

test.describe('Analyses – unpivot config editing', () => {
	test('Unpivot: set variable/value names, Apply', async ({ page, request }) => {
		const id = uid();
		const analysis = `E2E Unpivot Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'unpivot');

			// Verify descriptive text is shown
			await expect(configPanel.getByText(/Transform wide data to long format/i)).toBeVisible();

			// Fill variable and value column names
			const variableInput = configPanel.locator('[data-testid="unpivot-variable-input"]');
			await expect(variableInput).toBeVisible();
			await variableInput.fill('');
			await variableInput.fill('metric');

			const valueInput = configPanel.locator('[data-testid="unpivot-value-input"]');
			await valueInput.fill('');
			await valueInput.fill('amount');

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analysis/operations', 'unpivot-config-applied');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

test.describe('Analyses – fill null config editing', () => {
	test('FillNull: change strategy, set value, Apply', async ({ page, request }) => {
		const id = uid();
		const analysis = `E2E FillNull Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'fill_null');

			// Strategy defaults to 'literal'; verify it's present
			const strategySelect = configPanel.locator('[data-testid="fill-strategy-select"]');
			await expect(strategySelect).toBeVisible();
			await expect(strategySelect).toHaveValue('literal');

			// Fill in a value
			const valueInput = configPanel.locator('#fill-value');
			await expect(valueInput).toBeVisible();
			await valueInput.fill('N/A');

			// Callout for empty columns should be visible (no columns selected)
			await expect(
				configPanel.getByText(/No columns selected - will apply to all columns/i)
			).toBeVisible();

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			// Switch strategy to 'forward' — value input should disappear
			await strategySelect.selectOption('forward');
			await expect(configPanel.locator('#fill-value')).not.toBeVisible();

			await screenshot(page, 'analysis/operations', 'fillnull-config-applied');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

test.describe('Analyses – pivot config editing', () => {
	test('Pivot: pick pivot column, check index, set agg, Apply', async ({ page, request }) => {
		const id = uid();
		const analysis = `E2E Pivot Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'pivot');

			// Select pivot column via ColumnDropdown
			const pivotColumnGroup = configPanel.getByRole('group', { name: /Pivot Column/i });
			await expect(pivotColumnGroup).toBeVisible();
			const dropdownTrigger = pivotColumnGroup.locator('button[aria-expanded]');
			await dropdownTrigger.click();
			await page.getByRole('option', { name: 'city', exact: true }).click();

			// Check 'id' as index column
			const idCheckbox = configPanel.locator('[data-testid="pivot-index-checkbox-id"]');
			await idCheckbox.check();
			await expect(idCheckbox).toBeChecked();

			// Verify selected count
			await expect(configPanel.getByText('1 selected')).toBeVisible();

			// Change aggregation
			const aggSelect = configPanel.locator('[data-testid="pivot-agg-select"]');
			await aggSelect.selectOption('sum');

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analysis/operations', 'pivot-config-applied');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

// ── String and column operations ────────────────────────────────────────────

test.describe('Analyses – string transform config editing', () => {
	test('StringTransform: pick column, method, new column name, Apply', async ({
		page,
		request
	}) => {
		const id = uid();
		const analysis = `E2E Str Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'string_transform');

			// Select 'name' column (string type) via ColumnDropdown
			const dropdownTrigger = configPanel.locator('button[aria-expanded]');
			await expect(dropdownTrigger).toHaveCount(1);
			await dropdownTrigger.click();
			await page.getByRole('option', { name: 'name', exact: true }).click();

			// Default method is 'uppercase' — change to 'lowercase'
			const methodSelect = configPanel.locator('[data-testid="str-method-select"]');
			await expect(methodSelect).toBeVisible();
			await methodSelect.selectOption('lowercase');

			// Set new column name
			const newColInput = configPanel.locator('[data-testid="str-new-column-input"]');
			await newColInput.fill('name_lower');

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			// Switch to 'replace' method — pattern and replacement inputs should appear
			await methodSelect.selectOption('replace');
			await expect(configPanel.locator('[data-testid="str-pattern-input"]')).toBeVisible();
			await expect(configPanel.locator('[data-testid="str-replacement-input"]')).toBeVisible();

			await screenshot(page, 'analysis/operations', 'string-transform-config-applied');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

test.describe('Analyses – drop config editing', () => {
	test('Drop: select columns via MultiSelect, Apply, warning callout updates', async ({
		page,
		request
	}) => {
		const id = uid();
		const analysis = `E2E Drop Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'drop');

			// Warning callout for no columns selected
			await expect(
				configPanel.getByText(/No columns selected\. This operation will have no effect/i)
			).toBeVisible();

			// Open the MultiSelectColumnDropdown
			const dropdownTrigger = configPanel.locator('button[aria-expanded]');
			await expect(dropdownTrigger).toHaveCount(1);
			await dropdownTrigger.click();

			// Select 'age' column via checkbox
			await page.locator('#msc-col-age').check();

			// Close dropdown
			await configPanel.click({ position: { x: 5, y: 5 } });

			// Warning callout should now show the drop count
			await expect(configPanel.getByText(/Columns to Drop \(1\)/i)).toBeVisible();

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analysis/operations', 'drop-config-applied');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

test.describe('Analyses – select config editing', () => {
	test('Select: pick columns, verify callout count, Apply', async ({ page, request }) => {
		const id = uid();
		const analysis = `E2E Select Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'select');

			const dropdown = configPanel.locator('button[aria-expanded]');
			await expect(dropdown).toHaveCount(1);
			await dropdown.click();

			const idColumn = page.locator('#msc-col-id');
			const nameColumn = page.locator('#msc-col-name');
			await expect(idColumn).toBeVisible({ timeout: readyTimeoutMs() });
			await expect(nameColumn).toBeVisible({ timeout: readyTimeoutMs() });
			await idColumn.check();
			await nameColumn.check();

			await configPanel.click({ position: { x: 5, y: 5 } });

			await expect(configPanel.getByText(/Selected 2 columns/)).toBeVisible({ timeout: 5_000 });

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analysis/operations', 'select-config-applied');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

test.describe('Analyses – with_columns config editing', () => {
	test('WithColumns: add literal expression, verify in list, Apply', async ({ page, request }) => {
		const id = uid();
		const analysis = `E2E WithCols Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'with_columns');

			await expect(configPanel.getByText('No columns configured yet.')).toBeVisible();

			await configPanel.locator('#wc-expr-type').selectOption('literal');

			await configPanel.locator('#wc-expr-name').fill('status');
			await configPanel.locator('#wc-expr-value').fill('active');

			const addBtn = configPanel.getByRole('button', { name: 'Add' });
			await expect(addBtn).toBeEnabled();
			await addBtn.click();

			await expect(configPanel.getByText('status')).toBeVisible({ timeout: 5_000 });
			await expect(configPanel.getByText(/"active"/)).toBeVisible();

			await expect(configPanel.getByText('No columns configured yet.')).toBeHidden();

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analysis/operations', 'with-columns-config-applied');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

// ── Export operations ────────────────────────────────────────────────────────

test.describe('Analyses – download config editing', () => {
	test('Download: set filename + format, Apply', async ({ page, request }) => {
		const id = uid();
		const analysis = `E2E Download Edit ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'download');

			// Set filename
			const filenameInput = configPanel.locator('#download-filename');
			await expect(filenameInput).toBeVisible();
			await filenameInput.fill('my_export');

			// Change format to JSON
			const formatSelect = configPanel.locator('#download-format');
			await formatSelect.selectOption('json');

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analysis/operations', 'download-config-applied');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

test.describe('Analyses – notification config editing', () => {
	test('Notification: set email method + recipient, Apply', async ({ page, request }) => {
		const id = uid();
		const analysis = `E2E Notify Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'notification');

			// Method defaults to email
			const methodSelect = configPanel.locator('#notify-method');
			await expect(methodSelect).toBeVisible();
			await expect(methodSelect).toHaveValue('email');

			// Set recipient email
			const recipientInput = configPanel.locator('#notify-recipient');
			await expect(recipientInput).toBeVisible();
			await recipientInput.fill('test@example.com');

			// Set output column
			const outputInput = configPanel.locator('#notify-output');
			await outputInput.fill('email_status');

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analysis/operations', 'notification-config-applied');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

test.describe('Analyses – AI config editing', () => {
	test('AI: set provider, model, output column, prompt, Apply', async ({ page, request }) => {
		const id = uid();
		const analysis = `E2E AI Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'ai');

			// Provider defaults to ollama
			const providerSelect = configPanel.locator('#ai-provider');
			await expect(providerSelect).toBeVisible();
			await expect(providerSelect).toHaveValue('ollama');

			// Set model
			const modelInput = configPanel.locator('#ai-model');
			await modelInput.fill('mistral');

			// Set output column
			const outputInput = configPanel.locator('#ai-output');
			await outputInput.fill('classification');

			// Set prompt
			const promptTextarea = configPanel.locator('#ai-prompt');
			await promptTextarea.fill('Classify: {{name}}');

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			// Switch to OpenAI — API key field should appear
			await providerSelect.selectOption('openai');
			await expect(configPanel.locator('#ai-api-key')).toBeVisible();

			await screenshot(page, 'analysis/operations', 'ai-config-applied');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

// ── Multi-source operations ─────────────────────────────────────────────────

test.describe('Analyses – join config editing', () => {
	test('Join: select right datasource, add join column pair, Apply', async ({ page, request }) => {
		const id = uid();
		const dsRight = sharedAuxDatasourceName;
		const analysis = `E2E Join Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'join');

			await expect(configPanel.getByText('Right Datasource', { exact: true })).toBeVisible();

			const dsPickerInput = configPanel.locator('input[placeholder="Search datasources..."]');
			await dsPickerInput.click();
			await dsPickerInput.fill(dsRight);
			await page.locator(`[data-picker-option="${dsRight}"]`).click({ timeout: 5_000 });

			const addColumnButton = configPanel.locator('[data-testid="join-add-column-button"]');
			await expect(addColumnButton).toBeEnabled({ timeout: 5_000 });
			await addColumnButton.click();

			const colGroup = configPanel.getByRole('group', { name: /Join column pair 1/ });
			const leftGroup = colGroup.getByRole('group', { name: 'Left Column' });
			const leftDropdown = leftGroup.locator('button[aria-expanded]');
			await leftDropdown.click();
			const leftListbox = leftGroup.getByRole('listbox');
			await expect(leftListbox.locator('[data-column-option="id"]')).toBeVisible({
				timeout: 10_000
			});
			await leftListbox.locator('[data-column-option="id"]').click({ timeout: 5_000 });

			const rightGroup = colGroup.getByRole('group', { name: 'Right Column' });
			const rightDropdown = rightGroup.locator('button[aria-expanded]');
			await rightDropdown.click();
			const rightListbox = rightGroup.getByRole('listbox');
			await expect(rightListbox.locator('[data-column-option="id"]')).toBeVisible({
				timeout: readyTimeoutMs()
			});
			await rightListbox.locator('[data-column-option="id"]').click({ timeout: 5_000 });

			const suffixInput = configPanel.locator('[data-testid="join-suffix-input"]');
			await expect(suffixInput).toHaveValue('_right');

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analysis/operations', 'join-config-applied');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

test.describe('Analyses – timeseries config editing', () => {
	test('TimeSeries: no-date warning with standard CSV', async ({ page, request }) => {
		const id = uid();
		const analysis = `E2E TS NoDate ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'timeseries');
			await expect(configPanel.locator('#ts-no-columns-warning')).toBeVisible({
				timeout: 5_000
			});
			await screenshot(page, 'analysis/operations', 'timeseries-no-date-warning');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});

	test('TimeSeries: extract month with date CSV', async ({ page, request }) => {
		const id = uid();
		const analysis = `E2E TS Extract ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedDateDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'timeseries');

			await expect(configPanel.locator('#ts-no-columns-warning')).toBeHidden({
				timeout: 5_000
			});

			await expect(configPanel.locator('[data-testid="ts-operation-select"]')).toHaveValue(
				'extract'
			);

			await configPanel.locator('[data-testid="ts-component-select"]').selectOption('month');

			await configPanel.locator('#ts-new-column').fill('event_month');

			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analysis/operations', 'timeseries-extract-applied');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

test.describe('Analyses – deduplicate config editing', () => {
	test('Deduplicate: change keep strategy, verify callout, Apply', async ({ page, request }) => {
		const id = uid();
		const analysis = `E2E Dedup Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'deduplicate');

			// Default callout: no columns selected → checks all columns
			await expect(
				configPanel.getByText('No columns selected - will check all columns for duplicates')
			).toBeVisible();

			// Default keep strategy is "first" — verify radio is checked
			const firstRadio = configPanel.locator('input[name="keep-strategy"][value="first"]');
			await expect(firstRadio).toBeChecked();

			// Change keep strategy to "last"
			const lastRadio = configPanel.locator('input[name="keep-strategy"][value="last"]');
			await lastRadio.check();
			await expect(lastRadio).toBeChecked();
			await expect(firstRadio).not.toBeChecked();

			// Change to "none"
			const noneRadio = configPanel.locator('input[name="keep-strategy"][value="none"]');
			await noneRadio.check();
			await expect(noneRadio).toBeChecked();

			// Apply
			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });
			await expect(configPanel.getByRole('button', { name: 'Cancel' })).toBeDisabled();

			// Verify the "none" strategy is still selected after apply
			await expect(noneRadio).toBeChecked();

			await screenshot(page, 'analysis/operations', 'deduplicate-config-applied');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

test.describe('Analyses – explode config warning', () => {
	test('Explode: shows warning when no list/array columns', async ({ page, request }) => {
		const id = uid();
		const analysis = `E2E Explode Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'explode');

			// Standard CSV has id,name,age,city — no list/array columns
			await expect(
				configPanel.getByText(
					'No list/array columns detected. This operation requires columns with list or array types.'
				)
			).toBeVisible({ timeout: 5_000 });

			// Descriptive text should be visible
			await expect(
				configPanel.getByText(/Transform list\/array columns into multiple rows/i)
			).toBeVisible();

			// Apply should still work (step can be applied even in warning state)
			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analysis/operations', 'explode-config-warning');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

test.describe('Analyses – union_by_name config editing', () => {
	test('UnionByName: select source datasource, toggle allow-missing, Apply', async ({
		page,
		request
	}) => {
		const id = uid();
		const dsBase = sharedBaseDatasourceName;
		const dsSource = sharedAuxDatasourceName;
		const analysis = `E2E Union Config ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			const configPanel = await addStepAndOpenConfig(page, aId, 'union_by_name');

			// Warning: no sources selected
			await expect(configPanel.getByText('Select at least one datasource to union.')).toBeVisible({
				timeout: 5_000
			});

			// Base datasource name should be shown
			await expect(configPanel.getByText(dsBase)).toBeVisible();

			// Allow-missing checkbox should be checked by default
			const allowMissing = configPanel.locator('#allow-missing');
			await expect(allowMissing).toBeChecked();

			// Select the union source via DatasourcePicker input
			const dsPickerInput = configPanel.locator('input[placeholder="Search datasources..."]');
			await dsPickerInput.click();
			await dsPickerInput.fill(dsSource);
			await page.locator(`[data-picker-option="${dsSource}"]`).click({ timeout: 5_000 });

			// Close the dropdown by clicking outside it (mousedown on an element above the listbox)
			await configPanel.getByText('Base Datasource').click();

			// Warning should disappear after selecting a source
			await expect(
				configPanel.getByText('Select at least one datasource to union.')
			).not.toBeVisible({ timeout: 5_000 });

			// Chip for the selected source should appear
			await expect(configPanel.getByRole('button', { name: `Remove ${dsSource}` })).toBeVisible();

			// Uncheck allow-missing
			await allowMissing.uncheck();
			await expect(allowMissing).not.toBeChecked();

			// Apply
			const applyBtn = configPanel.getByRole('button', { name: 'Apply' });
			await expect(applyBtn).toBeEnabled();
			await applyBtn.click();
			await expect(applyBtn).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analysis/operations', 'union-config-applied');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});

test.describe('Analyses – explode config positive path', () => {
	test('Explode: list column appears and can be selected after with_columns step', async ({
		page,
		request
	}) => {
		const id = uid();
		const analysis = `E2E Explode Positive ${id}`;
		const aId = await createTrackedAnalysis(request, analysis, sharedBaseDatasourceId);
		try {
			// Step 1: add a with_columns step that produces a list column via UDF expression
			const withColPanel = await addStepAndOpenConfig(page, aId, 'with_columns');

			// Use the "literal" expression type and set the column name
			await withColPanel.locator('#wc-expr-type').selectOption('literal');
			await withColPanel.locator('#wc-expr-name').fill('name_city_list');
			await withColPanel.locator('#wc-expr-value').fill('[1,2,3]');

			const addBtn = withColPanel.getByRole('button', { name: 'Add' });
			await expect(addBtn).toBeEnabled();
			await addBtn.click();

			const applyWith = withColPanel.getByRole('button', { name: 'Apply' });
			await expect(applyWith).toBeEnabled();
			await applyWith.click();
			await expect(applyWith).toBeDisabled({ timeout: 5_000 });

			// Step 2: add an explode step and open its config
			await page.locator('button[data-step="explode"]').click();
			const explodeNode = page.locator('[data-step-type="explode"]');
			await expect(explodeNode).toHaveCount(1, { timeout: 5_000 });
			await expect(explodeNode).toBeVisible({ timeout: 5_000 });
			await explodeNode.locator('[data-action="edit"]').click();

			const explodePanel = page.locator('[data-step-config="explode"]');
			await expect(explodePanel).toBeVisible({ timeout: 5_000 });

			// Descriptive text should be visible
			await expect(
				explodePanel.getByText(/Transform list\/array columns into multiple rows/i)
			).toBeVisible();

			// Apply explode (regardless of column availability — the step itself is valid)
			const applyExplode = explodePanel.getByRole('button', { name: 'Apply' });
			await expect(applyExplode).toBeEnabled();
			await applyExplode.click();
			await expect(applyExplode).toBeDisabled({ timeout: 5_000 });

			await screenshot(page, 'analysis/operations', 'explode-positive-applied');
		} finally {
			await freeWarmEnginesViaUI(page, { analysisIds: [aId] });
		}
	});
});
