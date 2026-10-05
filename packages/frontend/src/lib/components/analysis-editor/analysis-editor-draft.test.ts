import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import type { AnalysisTab } from '$lib/types/analysis';

const idbGet = vi.fn();
const idbSet = vi.fn();
const idbDelete = vi.fn();

vi.mock('$lib/utils/indexeddb', () => ({
	idbGet: (...args: unknown[]) => idbGet(...args),
	idbSet: (...args: unknown[]) => idbSet(...args),
	idbDelete: (...args: unknown[]) => idbDelete(...args)
}));

const { createDraftController } = await import('./analysis-editor-draft.svelte');

const ANALYSIS_ID = '11111111-1111-1111-1111-111111111111';
const RESULT_ID = '550e8400-e29b-41d4-a716-446655440000';

function tab(steps: AnalysisTab['steps']): AnalysisTab {
	return {
		id: 'tab-1',
		name: 'Source 1',
		parent_id: null,
		datasource: { id: 'ds-1', analysis_tab_id: null, config: { branch: 'master' } },
		output: {
			result_id: RESULT_ID,
			format: 'parquet',
			filename: 'source_1',
			build_mode: 'full',
			iceberg: { namespace: 'outputs', table_name: 'source_1', branch: 'master' }
		},
		steps
	};
}

function savedStep() {
	return {
		id: 'step-1',
		type: 'filter' as const,
		config: { column: 'value' },
		depends_on: [],
		is_applied: true
	};
}

function controller(options: { serverSteps: number; payload: () => ReturnType<typeof tab>[] }) {
	const applied: Array<{ tabs: boolean; stepIds: string[] }> = [];
	const draft = createDraftController({
		getStorageKey: () => `analysis-draft:${ANALYSIS_ID}`,
		getAnalysisId: () => ANALYSIS_ID,
		blockedFromHydration: () => false,
		readOnly: () => false,
		hasTabs: () => true,
		getServerVersion: () => 'v1',
		serverStepCount: () => options.serverSteps,
		buildPayload: () => ({
			analysisId: ANALYSIS_ID,
			version: 'v1',
			tabs: options.payload(),
			activeTabId: 'tab-1',
			resourceConfig: null,
			selectedStepId: 'step-1',
			leftPaneCollapsed: true,
			rightPaneCollapsed: false
		}),
		applyDraft: (parsed, apply) => {
			applied.push({
				tabs: apply.tabs,
				stepIds: parsed.tabs.flatMap((item) => item.steps.map((step) => step.id))
			});
		}
	});
	return { draft, applied };
}

describe('analysis editor draft', () => {
	beforeEach(() => {
		idbGet.mockReset();
		idbSet.mockReset();
		idbDelete.mockReset();
		idbSet.mockResolvedValue(undefined);
		idbDelete.mockResolvedValue(undefined);
		vi.useFakeTimers();
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	test('keeps saved steps when a same-revision draft has none', async () => {
		idbGet.mockResolvedValue(
			JSON.stringify({
				analysisId: ANALYSIS_ID,
				version: 'v1',
				tabs: [tab([])],
				activeTabId: 'tab-1',
				resourceConfig: null,
				selectedStepId: null,
				leftPaneCollapsed: true,
				rightPaneCollapsed: false
			})
		);
		const { draft, applied } = controller({ serverSteps: 2, payload: () => [tab([savedStep()])] });

		draft.hydrate();
		await vi.runAllTimersAsync();

		expect(applied).toEqual([{ tabs: false, stepIds: [] }]);
		expect(idbDelete).toHaveBeenCalledWith(`analysis-draft:${ANALYSIS_ID}`);
		expect(draft.draftLoaded).toBe(true);
	});

	test('restores a same-revision draft that still has steps', async () => {
		idbGet.mockResolvedValue(
			JSON.stringify({
				analysisId: ANALYSIS_ID,
				version: 'v1',
				tabs: [tab([savedStep()])],
				activeTabId: 'tab-1',
				resourceConfig: null,
				selectedStepId: 'step-1',
				leftPaneCollapsed: false,
				rightPaneCollapsed: false
			})
		);
		const { draft, applied } = controller({ serverSteps: 1, payload: () => [tab([savedStep()])] });

		draft.hydrate();
		await vi.runAllTimersAsync();

		expect(applied).toEqual([{ tabs: true, stepIds: ['step-1'] }]);
		expect(idbDelete).not.toHaveBeenCalled();
		expect(draft.draftLoaded).toBe(true);
	});

	test('persists a snapshot taken when the draft was scheduled', async () => {
		const live = [tab([savedStep()])];
		const { draft } = controller({ serverSteps: 1, payload: () => live });
		draft.markLoaded();

		draft.schedulePersist();
		live[0] = tab([]);
		await vi.advanceTimersByTimeAsync(400);

		expect(idbSet).toHaveBeenCalledTimes(1);
		const stored = JSON.parse(String(idbSet.mock.calls[0]?.[1])) as { tabs: AnalysisTab[] };
		expect(stored.tabs[0]?.steps.map((step) => step.id)).toEqual(['step-1']);
	});

	test('flush drops a pending draft write', async () => {
		const { draft } = controller({ serverSteps: 1, payload: () => [tab([savedStep()])] });
		draft.markLoaded();
		draft.schedulePersist();
		draft.flush();
		await vi.advanceTimersByTimeAsync(400);
		expect(idbSet).not.toHaveBeenCalled();
	});
});
