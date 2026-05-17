import { describe, test, expect, vi, beforeEach } from 'vitest';
import type { AnalysisTab, PipelineStep } from '$lib/types/analysis';

vi.mock('$lib/utils/indexeddb', () => ({
	idbGet: vi.fn().mockResolvedValue(null),
	idbSet: vi.fn().mockResolvedValue(undefined)
}));

vi.mock('$lib/utils/audit-log', () => ({
	track: vi.fn()
}));

vi.mock('$lib/stores/schema.svelte', () => ({
	schemaStore: { getLastOutput: () => null }
}));

vi.mock('$lib/api/analysis', () => ({
	getAnalysisWithHeaders: vi.fn(),
	updateAnalysis: vi.fn()
}));

const { AnalysisStore } = await import('./analysis.svelte');

function makeStep(overrides: Partial<PipelineStep> = {}): PipelineStep {
	return {
		id: `step-${crypto.randomUUID().slice(0, 8)}`,
		type: 'filter',
		config: {},
		depends_on: [],
		is_applied: true,
		...overrides
	};
}

function makeTab(overrides: Partial<AnalysisTab> = {}): AnalysisTab {
	return {
		id: `tab-${crypto.randomUUID().slice(0, 8)}`,
		name: 'Source 1',
		parent_id: null,
		datasource: {
			id: 'ds-1',
			analysis_tab_id: null,
			config: { branch: 'master' }
		},
		output: {
			result_id: '550e8400-e29b-41d4-a716-446655440000',
			format: 'parquet',
			filename: 'source_1',
			build_mode: 'full',
			iceberg: { namespace: 'outputs', table_name: 'source_1', branch: 'master' }
		},
		steps: [],
		...overrides
	};
}

describe('AnalysisStore.buildTabs', () => {
	let store: InstanceType<typeof AnalysisStore>;

	beforeEach(() => {
		store = new AnalysisStore();
	});

	test('returns empty array for empty input', () => {
		expect(store.buildTabs([])).toEqual([]);
	});

	test('creates one tab per datasource ID', () => {
		const tabs = store.buildTabs(['ds-a', 'ds-b']);
		expect(tabs).toHaveLength(2);
		expect(tabs[0].id).toBe('tab-ds-a');
		expect(tabs[1].id).toBe('tab-ds-b');
	});

	test('sets correct datasource references', () => {
		const tabs = store.buildTabs(['ds-x']);
		expect(tabs[0].datasource.id).toBe('ds-x');
		expect(tabs[0].datasource.analysis_tab_id).toBeNull();
		expect(tabs[0].datasource.config.branch).toBe('master');
	});

	test('names tabs sequentially', () => {
		const tabs = store.buildTabs(['a', 'b', 'c']);
		expect(tabs[0].name).toBe('Source 1');
		expect(tabs[1].name).toBe('Source 2');
		expect(tabs[2].name).toBe('Source 3');
	});

	test('initializes steps as empty array', () => {
		const tabs = store.buildTabs(['ds-1']);
		expect(tabs[0].steps).toEqual([]);
	});

	test('output has valid result_id (UUID format)', () => {
		const tabs = store.buildTabs(['ds-1']);
		const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
		expect(tabs[0].output.result_id).toMatch(uuidPattern);
	});

	test('output has parquet format and full build_mode', () => {
		const tabs = store.buildTabs(['ds-1']);
		expect(tabs[0].output.format).toBe('parquet');
		expect(tabs[0].output.build_mode).toBe('full');
	});
});

describe('AnalysisStore.setTabs', () => {
	let store: InstanceType<typeof AnalysisStore>;

	beforeEach(() => {
		store = new AnalysisStore();
	});

	test('replaces tabs and sets first tab as active', () => {
		const tabs = [makeTab({ id: 'tab-a' }), makeTab({ id: 'tab-b' })];
		store.setTabs(tabs);
		expect(store.tabs).toHaveLength(2);
		expect(store.activeTabId).toBe('tab-a');
	});

	test('preserves active tab if still present', () => {
		store.setTabs([makeTab({ id: 'tab-a' }), makeTab({ id: 'tab-b' })]);
		store.activeTabId = 'tab-b';
		store.setTabs([makeTab({ id: 'tab-a' }), makeTab({ id: 'tab-b' })]);
		expect(store.activeTabId).toBe('tab-b');
	});

	test('resets active tab if removed', () => {
		store.setTabs([makeTab({ id: 'tab-a' }), makeTab({ id: 'tab-b' })]);
		store.activeTabId = 'tab-b';
		store.setTabs([makeTab({ id: 'tab-c' })]);
		expect(store.activeTabId).toBe('tab-c');
	});

	test('sets null active tab for empty array', () => {
		store.setTabs([]);
		expect(store.activeTabId).toBeNull();
	});
});

describe('AnalysisStore.addTab', () => {
	let store: InstanceType<typeof AnalysisStore>;

	beforeEach(() => {
		store = new AnalysisStore();
	});

	test('appends tab and activates it', () => {
		store.setTabs([makeTab({ id: 'tab-a' })]);
		const newTab = makeTab({ id: 'tab-new' });
		store.addTab(newTab);
		expect(store.tabs).toHaveLength(2);
		expect(store.activeTabId).toBe('tab-new');
	});
});

describe('AnalysisStore.duplicateTab', () => {
	let store: InstanceType<typeof AnalysisStore>;

	beforeEach(() => {
		store = new AnalysisStore();
		store.setTabs([
			makeTab({
				id: 'tab-source',
				name: 'Source',
				datasource: {
					id: 'ds-source',
					analysis_tab_id: null,
					config: { branch: 'dev', time_travel_snapshot_id: 'snap-1' }
				},
				output: {
					result_id: '550e8400-e29b-41d4-a716-446655440001',
					format: 'parquet',
					filename: 'source_output',
					iceberg: { namespace: 'outputs', table_name: 'source_output', branch: 'dev' }
				},
				steps: [
					makeStep({ id: 'A', depends_on: [], config: { threshold: 1 } }),
					makeStep({ id: 'B', depends_on: ['A'], config: { threshold: 2 } })
				]
			}),
			makeTab({
				id: 'tab-other',
				name: 'Other',
				output: {
					result_id: '550e8400-e29b-41d4-a716-446655440002',
					format: 'parquet',
					filename: 'other'
				}
			})
		]);
	});

	test('duplicates tab adjacent to source and activates duplicate', () => {
		const duplicated = store.duplicateTab('tab-source');
		expect(duplicated).not.toBeNull();
		expect(store.tabs.map((tab) => tab.id)).toHaveLength(3);
		expect(store.tabs[1]?.id).toBe(duplicated?.id);
		expect(store.activeTabId).toBe(duplicated?.id);
		expect(duplicated?.output.result_id).not.toBe(store.tabs[0]?.output.result_id);
	});

	test('rewrites duplicated step ids and depends_on references', () => {
		const duplicated = store.duplicateTab('tab-source');
		expect(duplicated).not.toBeNull();
		const source = store.tabs[0]!;
		const copy = duplicated!;
		expect(copy.steps).toHaveLength(2);
		expect(copy.steps[0]?.id).not.toBe(source.steps[0]?.id);
		expect(copy.steps[1]?.id).not.toBe(source.steps[1]?.id);
		expect(copy.steps[1]?.depends_on).toEqual([copy.steps[0]?.id]);
	});

	test('preserves derived datasource reference and regenerates output table identity', () => {
		store.tabs[0] = {
			...store.tabs[0]!,
			datasource: {
				id: '550e8400-e29b-41d4-a716-446655440010',
				analysis_tab_id: 'tab-upstream',
				config: { branch: 'master' }
			}
		};
		const duplicated = store.duplicateTab('tab-source');
		expect(duplicated).not.toBeNull();
		expect(duplicated?.datasource.id).toBe('550e8400-e29b-41d4-a716-446655440010');
		expect(duplicated?.datasource.analysis_tab_id).toBe('tab-upstream');
		expect(duplicated?.output.filename).toBe('source_copy');
		expect(duplicated?.output.iceberg?.table_name).toBe('source_copy');
	});

	test('assigns incrementing copy names for repeated duplicates', () => {
		const first = store.duplicateTab('tab-source');
		const second = store.duplicateTab('tab-source');
		expect(first?.name).toBe('Source Copy');
		expect(second?.name).toBe('Source Copy 2');
	});

	test('returns null when source tab does not exist', () => {
		const duplicated = store.duplicateTab('missing');
		expect(duplicated).toBeNull();
		expect(store.tabs).toHaveLength(2);
	});
});

describe('AnalysisStore.removeTab', () => {
	let store: InstanceType<typeof AnalysisStore>;

	beforeEach(() => {
		store = new AnalysisStore();
		store.setTabs([makeTab({ id: 'tab-a' }), makeTab({ id: 'tab-b' }), makeTab({ id: 'tab-c' })]);
	});

	test('removes the specified tab', () => {
		store.removeTab('tab-b');
		expect(store.tabs).toHaveLength(2);
		expect(store.tabs.map((t) => t.id)).toEqual(['tab-a', 'tab-c']);
	});

	test('resets active to first tab when active is removed', () => {
		store.activeTabId = 'tab-b';
		store.removeTab('tab-b');
		expect(store.activeTabId).toBe('tab-a');
	});

	test('does not change active tab if non-active removed', () => {
		store.activeTabId = 'tab-c';
		store.removeTab('tab-a');
		expect(store.activeTabId).toBe('tab-c');
	});

	test('sets null when last tab removed', () => {
		store.setTabs([makeTab({ id: 'tab-only' })]);
		store.removeTab('tab-only');
		expect(store.tabs).toHaveLength(0);
		expect(store.activeTabId).toBeNull();
	});
});

describe('AnalysisStore.addStep', () => {
	let store: InstanceType<typeof AnalysisStore>;

	beforeEach(() => {
		store = new AnalysisStore();
		store.setTabs([makeTab({ id: 'tab-1', steps: [] })]);
	});

	test('adds step to active tab', () => {
		const step = makeStep({ id: 'step-1' });
		store.addStep(step);
		expect(store.tabs[0].steps).toHaveLength(1);
		expect(store.tabs[0].steps[0].id).toBe('step-1');
	});

	test('first step has empty depends_on', () => {
		const step = makeStep({ id: 'step-1' });
		store.addStep(step);
		expect(store.tabs[0].steps[0].depends_on).toEqual([]);
	});

	test('second step depends on first', () => {
		store.addStep(makeStep({ id: 'step-1' }));
		store.addStep(makeStep({ id: 'step-2' }));
		expect(store.tabs[0].steps[1].depends_on).toEqual(['step-1']);
	});

	test('does nothing when no active tab', () => {
		store.setTabs([]);
		store.addStep(makeStep());
		expect(store.tabs).toHaveLength(0);
	});
});

describe('AnalysisStore.removeStep', () => {
	let store: InstanceType<typeof AnalysisStore>;

	beforeEach(() => {
		store = new AnalysisStore();
		store.setTabs([
			makeTab({
				id: 'tab-1',
				steps: [
					makeStep({ id: 'A', depends_on: [] }),
					makeStep({ id: 'B', depends_on: ['A'] }),
					makeStep({ id: 'C', depends_on: ['B'] })
				]
			})
		]);
	});

	test('removes the step from pipeline', () => {
		store.removeStep('B');
		expect(store.tabs[0].steps).toHaveLength(2);
		expect(store.tabs[0].steps.map((s) => s.id)).toEqual(['A', 'C']);
	});

	test('relinks dependent step to removed step parent', () => {
		store.removeStep('B');
		expect(store.tabs[0].steps[1].depends_on).toEqual(['A']);
	});

	test('removes first step and clears dependent dependency', () => {
		store.removeStep('A');
		expect(store.tabs[0].steps[0].id).toBe('B');
		expect(store.tabs[0].steps[0].depends_on).toEqual([]);
	});

	test('does nothing for non-existent step', () => {
		store.removeStep('Z');
		expect(store.tabs[0].steps).toHaveLength(3);
	});
});

describe('AnalysisStore.moveStep', () => {
	let store: InstanceType<typeof AnalysisStore>;

	beforeEach(() => {
		store = new AnalysisStore();
		store.setTabs([
			makeTab({
				id: 'tab-1',
				steps: [
					makeStep({ id: 'A', depends_on: [] }),
					makeStep({ id: 'B', depends_on: ['A'] }),
					makeStep({ id: 'C', depends_on: ['B'] })
				]
			})
		]);
	});

	test('moves step forward in the chain', () => {
		const result = store.moveStep('A', 2, 'B', 'C');
		expect(result).toBe(true);
		const ids = store.tabs[0].steps.map((s) => s.id);
		expect(ids).toEqual(['B', 'A', 'C']);
	});

	test('returns false for non-existent step', () => {
		const result = store.moveStep('Z', 1, null, null);
		expect(result).toBe(false);
	});

	test('returns false when no active tab', () => {
		store.setTabs([]);
		const result = store.moveStep('A', 1, null, null);
		expect(result).toBe(false);
	});
});

describe('AnalysisStore.insertStep', () => {
	let store: InstanceType<typeof AnalysisStore>;

	beforeEach(() => {
		store = new AnalysisStore();
		store.setTabs([
			makeTab({
				id: 'tab-1',
				steps: [makeStep({ id: 'A', depends_on: [] }), makeStep({ id: 'B', depends_on: ['A'] })]
			})
		]);
	});

	test('inserts between two steps', () => {
		const newStep = makeStep({ id: 'X' });
		const result = store.insertStep(newStep, 1, 'A', 'B');
		expect(result).toBe(true);
		const ids = store.tabs[0].steps.map((s) => s.id);
		expect(ids).toEqual(['A', 'X', 'B']);
	});

	test('inserted step gets correct depends_on', () => {
		const newStep = makeStep({ id: 'X' });
		store.insertStep(newStep, 1, 'A', 'B');
		const inserted = store.tabs[0].steps.find((s) => s.id === 'X');
		expect(inserted?.depends_on).toEqual(['A']);
	});

	test('next step is relinked to inserted step', () => {
		const newStep = makeStep({ id: 'X' });
		store.insertStep(newStep, 1, 'A', 'B');
		const nextStep = store.tabs[0].steps.find((s) => s.id === 'B');
		expect(nextStep?.depends_on).toEqual(['X']);
	});

	test('returns false when no active tab', () => {
		store.setTabs([]);
		const result = store.insertStep(makeStep(), 0, null, null);
		expect(result).toBe(false);
	});
});

describe('AnalysisStore.isDirty', () => {
	let store: InstanceType<typeof AnalysisStore>;

	beforeEach(() => {
		store = new AnalysisStore();
	});

	test('returns false when no analysis loaded', () => {
		expect(store.isDirty()).toBe(false);
	});

	test('returns false when tabs match saved state', () => {
		const tab = makeTab({ id: 'tab-1' });
		store.current = {
			id: 'a-1',
			name: 'Test',
			description: null,
			pipeline_definition: {},
			created_at: '',
			updated_at: '',
			result_path: null,
			thumbnail: null
		};
		store.lastSaved = { name: 'Test', description: null };
		store.tabs = [tab];
		store.savedTabs = [JSON.parse(JSON.stringify(tab))];
		expect(store.isDirty()).toBe(false);
	});

	test('returns true when tabs differ from saved', () => {
		const tab = makeTab({ id: 'tab-1' });
		store.current = {
			id: 'a-1',
			name: 'Test',
			description: null,
			pipeline_definition: {},
			created_at: '',
			updated_at: '',
			result_path: null,
			thumbnail: null
		};
		store.lastSaved = { name: 'Test', description: null };
		store.tabs = [tab];
		store.savedTabs = [];
		expect(store.isDirty()).toBe(true);
	});

	test('returns true when name differs', () => {
		store.current = {
			id: 'a-1',
			name: 'Changed Name',
			description: null,
			pipeline_definition: {},
			created_at: '',
			updated_at: '',
			result_path: null,
			thumbnail: null
		};
		store.lastSaved = { name: 'Original', description: null };
		store.tabs = [];
		store.savedTabs = [];
		expect(store.isDirty()).toBe(true);
	});

	test('returns true when description differs', () => {
		store.current = {
			id: 'a-1',
			name: 'Test',
			description: 'new desc',
			pipeline_definition: {},
			created_at: '',
			updated_at: '',
			result_path: null,
			thumbnail: null
		};
		store.lastSaved = { name: 'Test', description: null };
		store.tabs = [];
		store.savedTabs = [];
		expect(store.isDirty()).toBe(true);
	});
});

describe('AnalysisStore.reset', () => {
	test('clears all state', () => {
		const store = new AnalysisStore();
		store.setTabs([makeTab()]);
		store.current = {
			id: 'a-1',
			name: 'Test',
			description: null,
			pipeline_definition: {},
			created_at: '',
			updated_at: '',
			result_path: null,
			thumbnail: null
		};
		store.error = 'something';
		store.loading = true;

		store.reset();

		expect(store.current).toBeNull();
		expect(store.tabs).toEqual([]);
		expect(store.savedTabs).toEqual([]);
		expect(store.activeTabId).toBeNull();
		expect(store.error).toBeNull();
		expect(store.loading).toBe(false);
	});
});

describe('AnalysisStore.updateStepConfig', () => {
	let store: InstanceType<typeof AnalysisStore>;

	beforeEach(() => {
		store = new AnalysisStore();
		store.current = {
			id: 'a-1',
			name: 'Test',
			description: null,
			pipeline_definition: {},
			created_at: '',
			updated_at: '',
			result_path: null,
			thumbnail: null
		};
		store.setTabs([
			makeTab({
				id: 'tab-1',
				steps: [makeStep({ id: 'step-1', type: 'filter', config: { column: 'name' } })]
			})
		]);
	});

	test('updates config for matching step', () => {
		store.updateStepConfig('step-1', { column: 'age', operator: '>' });
		const step = store.tabs[0].steps[0];
		expect(step.config).toEqual({ column: 'age', operator: '>' });
	});

	test('does not mutate original config object', () => {
		const config = { column: 'new' };
		store.updateStepConfig('step-1', config);
		config.column = 'mutated';
		expect(store.tabs[0].steps[0].config).toEqual({ column: 'new' });
	});
});

describe('AnalysisStore.reorderSteps', () => {
	let store: InstanceType<typeof AnalysisStore>;

	beforeEach(() => {
		store = new AnalysisStore();
		store.setTabs([
			makeTab({
				id: 'tab-1',
				steps: [
					makeStep({ id: 'A', depends_on: [] }),
					makeStep({ id: 'B', depends_on: ['A'] }),
					makeStep({ id: 'C', depends_on: ['B'] })
				]
			})
		]);
	});

	test('reorders steps by index', () => {
		store.reorderSteps(0, 2);
		const ids = store.tabs[0].steps.map((s) => s.id);
		expect(ids).toEqual(['B', 'C', 'A']);
	});
});

describe('AnalysisStore.updateTab', () => {
	let store: InstanceType<typeof AnalysisStore>;

	beforeEach(() => {
		store = new AnalysisStore();
		store.setTabs([makeTab({ id: 'tab-1', name: 'Old Name' })]);
	});

	test('updates tab properties', () => {
		store.updateTab('tab-1', { name: 'New Name' });
		expect(store.tabs[0].name).toBe('New Name');
	});

	test('does not affect other tabs', () => {
		store.addTab(makeTab({ id: 'tab-2', name: 'Other' }));
		store.updateTab('tab-1', { name: 'Changed' });
		expect(store.tabs[1].name).toBe('Other');
	});

	test('preserves output when only datasource changes', () => {
		const original = store.tabs[0].output;
		store.updateTab('tab-1', {
			datasource: { id: 'ds-new', analysis_tab_id: null, config: { branch: 'master' } }
		});
		expect(store.tabs[0].output).toEqual(original);
		expect(store.tabs[0].datasource.id).toBe('ds-new');
	});

	test('preserves output when datasource switches to analysis source', () => {
		const original = store.tabs[0].output;
		store.updateTab('tab-1', {
			datasource: {
				id: 'output-uuid',
				analysis_tab_id: 'tab-upstream',
				config: { branch: 'master' }
			}
		});
		expect(store.tabs[0].output).toEqual(original);
		expect(store.tabs[0].datasource.analysis_tab_id).toBe('tab-upstream');
	});
});

describe('AnalysisStore.moveStep – backward', () => {
	let store: InstanceType<typeof AnalysisStore>;

	beforeEach(() => {
		store = new AnalysisStore();
		store.setTabs([
			makeTab({
				id: 'tab-1',
				steps: [
					makeStep({ id: 'A', depends_on: [] }),
					makeStep({ id: 'B', depends_on: ['A'] }),
					makeStep({ id: 'C', depends_on: ['B'] }),
					makeStep({ id: 'D', depends_on: ['C'] })
				]
			})
		]);
	});

	test('moves step backward (later to earlier position)', () => {
		const result = store.moveStep('C', 1, 'A', 'B');
		expect(result).toBe(true);
		const ids = store.tabs[0].steps.map((s) => s.id);
		expect(ids).toEqual(['A', 'C', 'B', 'D']);
	});

	test('updates dependency chains when moving backward', () => {
		store.moveStep('C', 1, 'A', 'B');
		const steps = store.tabs[0].steps;
		const stepMap = new Map(steps.map((s) => [s.id, s]));
		expect(stepMap.get('C')!.depends_on).toEqual(['A']);
		expect(stepMap.get('B')!.depends_on).toEqual(['C']);
	});

	test('relinks old dependent to old parent when moved', () => {
		store.moveStep('B', 3, 'C', 'D');
		const steps = store.tabs[0].steps;
		const stepMap = new Map(steps.map((s) => [s.id, s]));
		expect(stepMap.get('C')!.depends_on).toEqual(['A']);
		expect(stepMap.get('B')!.depends_on).toEqual(['C']);
		expect(stepMap.get('D')!.depends_on).toEqual(['B']);
	});

	test('moves last step to first position', () => {
		const result = store.moveStep('D', 0, null, 'A');
		expect(result).toBe(true);
		const ids = store.tabs[0].steps.map((s) => s.id);
		expect(ids).toEqual(['D', 'A', 'B', 'C']);
		expect(store.tabs[0].steps[0].depends_on).toEqual([]);
		expect(store.tabs[0].steps[1].depends_on).toEqual(['D']);
	});
});

describe('AnalysisStore.normalizeSteps', () => {
	let store: InstanceType<typeof AnalysisStore>;

	beforeEach(() => {
		store = new AnalysisStore();
	});

	test('converts plot_scatter type to chart', () => {
		const tab = makeTab({
			id: 'tab-1',
			steps: [makeStep({ id: 'A', type: 'plot_scatter', config: { x_column: 'age' } })]
		});
		store.setTabs([tab]);
		const analysis = {
			id: 'a-1',
			name: 'Test',
			description: null,
			pipeline_definition: { tabs: [tab] },
			created_at: '',
			updated_at: '',
			result_path: null,
			thumbnail: null
		};
		store.current = analysis;
		store.applyAnalysis(analysis);
		expect(store.tabs[0].steps[0].type).toBe('chart');
	});

	test('converts plot_bar type to chart with chart_type in config', () => {
		const tab = makeTab({
			id: 'tab-1',
			steps: [makeStep({ id: 'A', type: 'plot_bar', config: {} })]
		});
		const analysis = {
			id: 'a-1',
			name: 'Test',
			description: null,
			pipeline_definition: { tabs: [tab] },
			created_at: '',
			updated_at: '',
			result_path: null,
			thumbnail: null
		};
		store.current = analysis;
		store.applyAnalysis(analysis);
		expect(store.tabs[0].steps[0].type).toBe('chart');
		expect(store.tabs[0].steps[0].config).toHaveProperty('chart_type', 'bar');
	});

	test('leaves non-plot types unchanged', () => {
		const tab = makeTab({
			id: 'tab-1',
			steps: [makeStep({ id: 'A', type: 'filter', config: {} })]
		});
		const analysis = {
			id: 'a-1',
			name: 'Test',
			description: null,
			pipeline_definition: { tabs: [tab] },
			created_at: '',
			updated_at: '',
			result_path: null,
			thumbnail: null
		};
		store.current = analysis;
		store.applyAnalysis(analysis);
		expect(store.tabs[0].steps[0].type).toBe('filter');
	});

	test('rejects steps that lack dependency metadata', () => {
		const stepA = makeStep({ id: 'A' });
		delete stepA.depends_on;
		const stepB = makeStep({ id: 'B' });
		delete stepB.depends_on;
		const tab = makeTab({
			id: 'tab-1',
			steps: [stepA, stepB]
		});
		const analysis = {
			id: 'a-1',
			name: 'Test',
			description: null,
			pipeline_definition: { tabs: [tab] },
			created_at: '',
			updated_at: '',
			result_path: null,
			thumbnail: null
		};
		store.current = analysis;
		expect(() => store.applyAnalysis(analysis)).toThrow(/missing depends_on/);
	});

	test('rejects steps that lack is_applied', () => {
		const step = makeStep({ id: 'A' });
		delete step.is_applied;
		const tab = makeTab({
			id: 'tab-1',
			steps: [step]
		});
		const analysis = {
			id: 'a-1',
			name: 'Test',
			description: null,
			pipeline_definition: { tabs: [tab] },
			created_at: '',
			updated_at: '',
			result_path: null,
			thumbnail: null
		};
		store.current = analysis;
		expect(() => store.applyAnalysis(analysis)).toThrow(/missing is_applied/);
	});
});

describe('AnalysisStore.applyAnalysis', () => {
	let store: InstanceType<typeof AnalysisStore>;

	beforeEach(() => {
		store = new AnalysisStore();
	});

	test('clears activeTabId when switching to different analysis', () => {
		store.current = {
			id: 'a-1',
			name: 'First',
			description: null,
			pipeline_definition: { tabs: [makeTab({ id: 'tab-1' })] },
			created_at: '',
			updated_at: '',
			result_path: null,
			thumbnail: null
		};
		store.applyAnalysis(store.current);
		store.activeTabId = 'tab-1';

		const second = {
			id: 'a-2',
			name: 'Second',
			description: null,
			pipeline_definition: { tabs: [makeTab({ id: 'tab-2' })] },
			created_at: '',
			updated_at: '',
			result_path: null,
			thumbnail: null
		};
		store.applyAnalysis(second);
		expect(store.activeTabId).toBe('tab-2');
	});

	test('clears sourceSchemas when switching analysis', () => {
		store.current = {
			id: 'a-1',
			name: 'First',
			description: null,
			pipeline_definition: {},
			created_at: '',
			updated_at: '',
			result_path: null,
			thumbnail: null
		};
		store.applyAnalysis(store.current);
		store.sourceSchemas.set('ds-1', {
			columns: [{ name: 'col', dtype: 'Utf8', nullable: false }],
			row_count: 10
		});

		const second = {
			id: 'a-2',
			name: 'Second',
			description: null,
			pipeline_definition: {},
			created_at: '',
			updated_at: '',
			result_path: null,
			thumbnail: null
		};
		store.applyAnalysis(second);
		expect(store.sourceSchemas.size).toBe(0);
	});

	test('preserves sourceSchemas when re-applying same analysis', () => {
		const analysis = {
			id: 'a-1',
			name: 'Same',
			description: null,
			pipeline_definition: {},
			created_at: '',
			updated_at: '',
			result_path: null,
			thumbnail: null
		};
		store.applyAnalysis(analysis);
		store.sourceSchemas.set('ds-1', {
			columns: [{ name: 'col', dtype: 'Utf8', nullable: false }],
			row_count: 10
		});
		store.applyAnalysis(analysis);
		expect(store.sourceSchemas.size).toBe(1);
	});

	test('sets lastSaved from analysis name and description', () => {
		const analysis = {
			id: 'a-1',
			name: 'My Analysis',
			description: 'A description',
			pipeline_definition: {},
			created_at: '',
			updated_at: '',
			result_path: null,
			thumbnail: null
		};
		store.applyAnalysis(analysis);
		expect(store.lastSaved).toEqual({ name: 'My Analysis', description: 'A description' });
	});
});

describe('AnalysisStore.update', () => {
	let store: InstanceType<typeof AnalysisStore>;

	beforeEach(() => {
		store = new AnalysisStore();
		store.current = {
			id: 'a-1',
			name: 'Original',
			description: 'Desc',
			pipeline_definition: {},
			created_at: '',
			updated_at: '',
			result_path: null,
			thumbnail: null
		};
	});

	test('updates analysis name', () => {
		store.update({ name: 'Renamed' });
		expect(store.current?.name).toBe('Renamed');
	});

	test('updates analysis description', () => {
		store.update({ description: 'New desc' });
		expect(store.current?.description).toBe('New desc');
	});

	test('clears analysis description', () => {
		store.update({ description: null });
		expect(store.current?.description).toBeNull();
	});

	test('does nothing when no current analysis', () => {
		store.current = null;
		store.update({ name: 'test' });
		expect(store.current).toBeNull();
	});
});
