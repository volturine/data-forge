<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { createQuery } from '@tanstack/svelte-query';
	import { SvelteSet } from 'svelte/reactivity';
	import {
		createAnalysis,
		duplicateAnalysis,
		generateAnalysis,
		getAnalysisTemplate,
		importAnalysis,
		listAnalysisTemplates,
		validateAnalysis
	} from '$lib/api/analysis';
	import { listAIProviders } from '$lib/api/ai';
	import { listDatasources } from '$lib/api/datasource';
	import DatasourcePicker from '$lib/components/common/DatasourcePicker.svelte';
	import SnapshotPicker from '$lib/components/datasources/SnapshotPicker.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { css, spinner } from '$lib/styles/panda';
	import { configStore } from '$lib/stores/config.svelte';
	import { useNamespace } from '$lib/stores/namespace.svelte';
	import type {
		AnalysisCreate,
		AnalysisTab,
		AnalysisTabDatasourceConfig,
		AnalysisTemplateDetail,
		PipelineStep
	} from '$lib/types/analysis';
	import type { DataSource } from '$lib/types/datasource';
	import {
		validatePipelineTabs,
		formatPipelineErrors,
		buildOutputConfig
	} from '$lib/utils/analysis-tab';
	import { uuid } from '$lib/utils/uuid';

	type CreationMode = 'template' | 'ai' | 'clone' | 'import';

	type ValidationState = {
		loading: boolean;
		valid: boolean;
		error: string;
	};

	const ns = useNamespace();

	let mode = $state<CreationMode>('template');
	let step = $state(1);
	let name = $state('');
	let description = $state('');
	let error = $state('');
	let creating = $state(false);

	let selectedDatasourceIds = $state.raw<string[]>([]);
	let datasourceConfigs = $state<Record<string, AnalysisTabDatasourceConfig>>({});
	let draggedDatasourceId = $state<string | null>(null);

	let selectedTemplateId = $state('blank');
	let designTabs = $state<AnalysisTab[]>([]);
	let aiPrompt = $state('');
	let aiExplanation = $state('');
	let aiProvider = $state<string | null>(null);
	let aiModel = $state<string | null>(null);
	let generating = $state(false);

	let cloneSourceId = $state('');
	let cloneSourceName = $state('');

	let importFileName = $state('');
	let importedPipeline = $state.raw<Record<string, unknown> | null>(null);
	let importError = $state('');
	let datasourceRemap = $state<Record<string, string>>({});

	let reviewValidation = $state<ValidationState>({ loading: false, valid: true, error: '' });

	const datasourcesQuery = createQuery(() => ({
		queryKey: ['datasources', ns.value],
		queryFn: async () => {
			const result = await listDatasources();
			if (result.isErr()) throw new Error(result.error.message);
			return result.value.filter((ds) => ds.source_type !== 'analysis');
		},
		enabled: !ns.switching
	}));

	const templatesQuery = createQuery(() => ({
		queryKey: ['analysis-templates'],
		queryFn: async () => {
			const result = await listAnalysisTemplates();
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		}
	}));

	const templateDetailQuery = createQuery(() => ({
		queryKey: ['analysis-template', selectedTemplateId],
		queryFn: async () => {
			const result = await getAnalysisTemplate(selectedTemplateId);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		enabled: mode === 'template'
	}));

	const aiProvidersQuery = createQuery(() => ({
		queryKey: ['ai-providers'],
		queryFn: async () => {
			const result = await listAIProviders();
			if (result.isErr()) throw new Error(result.error.message);
			return result.value.filter((provider) => provider.configured);
		},
		enabled: mode === 'ai'
	}));

	const datasources = $derived(datasourcesQuery.data ?? []);
	const selectedDatasources = $derived.by((): DataSource[] =>
		selectedDatasourceIds.flatMap((id) => {
			const datasource = datasources.find((ds) => ds.id === id);
			return datasource ? [datasource] : [];
		})
	);
	const configuredProviders = $derived(aiProvidersQuery.data ?? []);
	const defaultOutputNamespace = $derived(configStore.config?.default_namespace ?? ns.value);
	const steps = $derived.by(() => {
		if (mode === 'clone') return ['Start', 'Clone', 'Review'];
		if (mode === 'import') return ['Start', 'Import', 'Review'];
		return ['Start', 'Data', 'Design', 'Output', 'Review'];
	});
	const currentStepLabel = $derived(steps[step - 1] ?? 'Start');
	const templateSummary = $derived(
		(templatesQuery.data ?? []).find((template) => template.id === selectedTemplateId) ?? null
	);
	const missingImportDatasourceIds = $derived.by(() => {
		if (!importedPipeline) return [];
		const tabs = importedPipeline.tabs;
		if (!Array.isArray(tabs)) return [];
		const available = new SvelteSet(datasources.map((ds) => ds.id));
		const internalTabIds = new SvelteSet<string>();
		const internalOutputIds = new SvelteSet<string>();
		for (const tab of tabs) {
			if (typeof tab !== 'object' || tab === null) continue;
			const typedTab = tab as Record<string, unknown>;
			if (typeof typedTab.id === 'string') internalTabIds.add(typedTab.id);
			const output = typedTab.output;
			if (typeof output === 'object' && output !== null) {
				const resultId = (output as Record<string, unknown>).result_id;
				if (typeof resultId === 'string') internalOutputIds.add(resultId);
			}
		}
		const missing = new SvelteSet<string>();
		for (const tab of tabs) {
			if (typeof tab !== 'object' || tab === null) continue;
			const typedTab = tab as Record<string, unknown>;
			const datasource = typedTab.datasource;
			if (typeof datasource === 'object' && datasource !== null) {
				const typedDatasource = datasource as Record<string, unknown>;
				const datasourceId = typedDatasource.id;
				const analysisTabId = typedDatasource.analysis_tab_id;
				if (
					typeof datasourceId === 'string' &&
					analysisTabId == null &&
					!available.has(datasourceId) &&
					!internalOutputIds.has(datasourceId) &&
					!datasourceRemap[datasourceId]
				) {
					missing.add(datasourceId);
				}
			}
			const steps = typedTab.steps;
			if (!Array.isArray(steps)) continue;
			for (const rawStep of steps) {
				if (typeof rawStep !== 'object' || rawStep === null) continue;
				const config = (rawStep as Record<string, unknown>).config;
				if (typeof config !== 'object' || config === null) continue;
				const rightSource = (config as Record<string, unknown>).right_source;
				if (
					typeof rightSource === 'string' &&
					!available.has(rightSource) &&
					!internalTabIds.has(rightSource) &&
					!internalOutputIds.has(rightSource) &&
					!datasourceRemap[rightSource]
				) {
					missing.add(rightSource);
				}
			}
		}
		return Array.from(missing);
	});
	const payload = $derived(buildPayload());
	const localPipelineErrors = $derived(payload ? validatePipelineTabs(payload.tabs) : []);
	const outputErrors = $derived(validateOutputConfig(designTabs));
	const complexity = $derived.by(() => {
		if (!payload) return { tabs: 0, steps: 0, size: 'N/A' };
		const stepCount = payload.tabs.reduce((count, tab) => count + tab.steps.length, 0);
		return {
			tabs: payload.tabs.length,
			steps: stepCount,
			size: stepCount >= 8 ? 'High' : stepCount >= 4 ? 'Medium' : 'Low'
		};
	});
	const estimatedOutputSize = $derived.by(() => {
		const rowCount = selectedDatasources.reduce((total, datasource) => {
			const raw = datasource.schema_cache?.row_count;
			return total + (typeof raw === 'number' ? raw : 0);
		}, 0);
		if (rowCount >= 1_000_000 || complexity.steps >= 10) return 'Large';
		if (rowCount >= 100_000 || complexity.steps >= 5) return 'Medium';
		return 'Small';
	});

	function getDatasourceById(id: string): DataSource | null {
		return datasources.find((ds) => ds.id === id) ?? null;
	}

	function getBranchOptions(datasource: DataSource): string[] {
		const raw = datasource.config?.branches;
		if (Array.isArray(raw)) {
			const branches = raw.filter(
				(branch): branch is string => typeof branch === 'string' && !!branch.trim()
			);
			if (branches.length > 0) return branches;
		}
		const current = datasource.config?.branch;
		if (typeof current === 'string' && current.trim()) return [current.trim()];
		return ['master'];
	}

	function defaultDatasourceConfig(datasource: DataSource): AnalysisTabDatasourceConfig {
		const branches = getBranchOptions(datasource);
		return {
			branch: branches[0] ?? 'master'
		};
	}

	function slugify(value: string): string {
		return (
			value
				.trim()
				.toLowerCase()
				.replace(/[^a-z0-9]+/g, '_')
				.replace(/^_+|_+$/g, '') || 'analysis'
		);
	}

	function buildDefaultOutput(tabName: string, branch: string) {
		const outputName = slugify(`${name || 'analysis'}_${tabName}`);
		return buildOutputConfig({
			outputId: uuid(),
			name: outputName,
			branch,
			namespace: defaultOutputNamespace
		});
	}

	function cloneTemplateSteps(
		steps: AnalysisTemplateDetail['steps'],
		index: number,
		datasourceId: string,
		rightSourceId: string | null
	): PipelineStep[] {
		return steps.map((step) => {
			const config = structuredClone(step.config);
			if (step.type === 'join' && rightSourceId && index === 0) {
				config.right_source = rightSourceId;
			}
			return {
				id: uuid(),
				type: step.type,
				config,
				depends_on: [],
				is_applied: true
			};
		});
	}

	function synchronizeTemplateTabs(template: AnalysisTemplateDetail | null): void {
		if (!template) {
			designTabs = [];
			return;
		}
		const nextTabs: AnalysisTab[] = [];
		const rightSourceId = selectedDatasourceIds[1] ?? null;
		for (const [index, datasourceId] of selectedDatasourceIds.entries()) {
			const datasource = getDatasourceById(datasourceId);
			if (!datasource) continue;
			const config = datasourceConfigs[datasourceId] ?? defaultDatasourceConfig(datasource);
			const branch = config.branch ?? 'master';
			const tabName =
				template.id === 'join_and_enrich' && index > 0
					? `Joined Output ${index + 1}`
					: `Source ${index + 1}`;
			const output = buildDefaultOutput(tabName, branch);
			const datasourceRef =
				template.id === 'join_and_enrich' && index > 0 && nextTabs[0]
					? {
							id: nextTabs[0].output.result_id,
							analysis_tab_id: nextTabs[0].id,
							config
						}
					: {
							id: datasourceId,
							analysis_tab_id: null,
							config
						};
			nextTabs.push({
				id: uuid(),
				name: tabName,
				parent_id:
					template.id === 'join_and_enrich' && index > 0 && nextTabs[0] ? nextTabs[0].id : null,
				datasource: datasourceRef,
				output: {
					...output,
					iceberg: {
						namespace: output.iceberg?.namespace ?? defaultOutputNamespace,
						table_name: output.iceberg?.table_name ?? slugify(output.filename),
						branch: output.iceberg?.branch ?? branch
					}
				},
				steps:
					template.id === 'join_and_enrich' && index > 0
						? []
						: cloneTemplateSteps(template.steps, index, datasourceId, rightSourceId)
			});
		}
		designTabs = nextTabs;
	}

	function buildPayload(): AnalysisCreate | null {
		if (mode === 'template' || mode === 'ai') {
			if (!name.trim() || designTabs.length === 0) return null;
			return {
				name: name.trim(),
				description: description.trim() || null,
				tabs: designTabs
			};
		}
		return null;
	}

	function validateOutputConfig(tabs: AnalysisTab[]): string[] {
		const errors: string[] = [];
		const filenames = new SvelteSet<string>();
		const tableNames = new SvelteSet<string>();
		for (const tab of tabs) {
			const filename = tab.output.filename.trim();
			const namespace = tab.output.iceberg?.namespace?.trim() ?? '';
			const tableName = tab.output.iceberg?.table_name?.trim() ?? '';
			if (!filename) errors.push(`${tab.name}: output name is required`);
			if (filename && filenames.has(filename))
				errors.push(`${tab.name}: output names must be unique`);
			filenames.add(filename);
			if (!namespace) errors.push(`${tab.name}: namespace is required`);
			if (!/^[a-z0-9_]+$/.test(tableName))
				errors.push(`${tab.name}: table name must be snake_case`);
			if (tableName && tableNames.has(tableName))
				errors.push(`${tab.name}: table names must be unique`);
			tableNames.add(tableName);
		}
		return errors;
	}

	function setMode(nextMode: CreationMode): void {
		if (mode === nextMode) return;
		mode = nextMode;
		resetDesignState(nextMode);
		step = 1;
	}

	function resetDesignState(nextMode: CreationMode): void {
		if (nextMode !== 'template') selectedTemplateId = 'blank';
		if (nextMode !== 'ai') {
			aiPrompt = '';
			aiExplanation = '';
			aiProvider = null;
			aiModel = null;
		}
		if (nextMode !== 'clone') {
			cloneSourceId = '';
			cloneSourceName = '';
		}
		if (nextMode !== 'import') {
			importFileName = '';
			importedPipeline = null;
			importError = '';
			datasourceRemap = {};
		}
		if (nextMode === 'ai') {
			designTabs = [];
		}
	}

	function canProceed(): boolean {
		if (step === 1) {
			return mode === 'clone' ? true : name.trim().length > 0;
		}
		if (mode === 'template') {
			if (step === 2) return selectedDatasourceIds.length > 0;
			if (step === 3) return !!templateDetailQuery.data;
			if (step === 4) return designTabs.length > 0 && outputErrors.length === 0;
			return true;
		}
		if (mode === 'ai') {
			if (step === 2) return selectedDatasourceIds.length > 0;
			if (step === 3) return designTabs.length > 0;
			if (step === 4) return designTabs.length > 0 && outputErrors.length === 0;
			return true;
		}
		if (mode === 'clone') {
			if (step === 2) return cloneSourceId.length > 0 && name.trim().length > 0;
			return true;
		}
		if (mode === 'import') {
			if (step === 2)
				return (
					!!importedPipeline && missingImportDatasourceIds.length === 0 && name.trim().length > 0
				);
			return true;
		}
		return false;
	}

	function nextStep(): void {
		if (!canProceed()) return;
		step = Math.min(step + 1, steps.length);
	}

	function prevStep(): void {
		step = Math.max(step - 1, 1);
	}

	function ensureDatasourceConfig(id: string): void {
		if (datasourceConfigs[id]) return;
		const datasource = datasources.find((item) => item.id === id);
		if (!datasource) return;
		datasourceConfigs = { ...datasourceConfigs, [id]: defaultDatasourceConfig(datasource) };
	}

	function removeDatasourceConfig(id: string): void {
		if (!datasourceConfigs[id]) return;
		const next = { ...datasourceConfigs };
		delete next[id];
		datasourceConfigs = next;
	}

	function reorderDatasource(targetId: string): void {
		if (!draggedDatasourceId || draggedDatasourceId === targetId) return;
		const next = selectedDatasourceIds.slice();
		const from = next.indexOf(draggedDatasourceId);
		const to = next.indexOf(targetId);
		if (from < 0 || to < 0) return;
		next.splice(from, 1);
		next.splice(to, 0, draggedDatasourceId);
		selectedDatasourceIds = next;
	}

	async function handleGenerate(): Promise<void> {
		if (!name.trim() || !aiPrompt.trim() || selectedDatasourceIds.length === 0) return;
		generating = true;
		error = '';
		const result = await generateAnalysis({
			name: name.trim(),
			description: aiPrompt.trim(),
			datasources: selectedDatasourceIds
				.map((id) => ({
					id,
					branch: datasourceConfigs[id]?.branch ?? 'master',
					snapshot_id: datasourceConfigs[id]?.snapshot_id ?? null,
					snapshot_timestamp_ms: datasourceConfigs[id]?.snapshot_timestamp_ms ?? null
				}))
				.filter((item) => !!item.id),
			provider: aiProvider,
			model: aiModel
		});
		result.match(
			(value) => {
				designTabs = value.pipeline.tabs;
				aiExplanation = value.explanation;
				aiProvider = value.provider;
				aiModel = value.model;
			},
			(err) => {
				error = err.message;
			}
		);
		generating = false;
	}

	async function handleImportFile(event: Event): Promise<void> {
		const input = event.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;
		importError = '';
		try {
			const text = await file.text();
			const parsed = JSON.parse(text) as Record<string, unknown>;
			importedPipeline =
				parsed.pipeline_definition && typeof parsed.pipeline_definition === 'object'
					? (parsed.pipeline_definition as Record<string, unknown>)
					: parsed;
			importFileName = file.name;
		} catch (err) {
			importedPipeline = null;
			importFileName = '';
			importError = err instanceof Error ? err.message : 'Failed to parse JSON file';
		}
	}

	async function refreshValidation(): Promise<void> {
		if (!payload) {
			reviewValidation = { loading: false, valid: false, error: 'No pipeline configured yet' };
			return;
		}
		reviewValidation = { loading: true, valid: false, error: '' };
		const result = await validateAnalysis(payload);
		result.match(
			() => {
				reviewValidation = { loading: false, valid: true, error: '' };
			},
			(err) => {
				reviewValidation = { loading: false, valid: false, error: err.message };
			}
		);
	}

	async function handleCreate(): Promise<void> {
		creating = true;
		error = '';
		if (mode === 'template' || mode === 'ai') {
			if (!payload) {
				creating = false;
				return;
			}
			const result = await createAnalysis(payload);
			result.match(
				(analysis) => {
					goto(resolve(`/analysis/${analysis.id}`), { invalidateAll: true });
				},
				(err) => {
					error = err.message;
					creating = false;
				}
			);
			return;
		}
		if (mode === 'clone') {
			const result = await duplicateAnalysis(cloneSourceId, {
				name: name.trim() || `Copy of ${cloneSourceName}`,
				description: description.trim() || null
			});
			result.match(
				(analysis) => {
					goto(resolve(`/analysis/${analysis.id}`), { invalidateAll: true });
				},
				(err) => {
					error = err.message;
					creating = false;
				}
			);
			return;
		}
		if (mode === 'import' && importedPipeline) {
			const result = await importAnalysis({
				name: name.trim(),
				description: description.trim() || null,
				pipeline: importedPipeline,
				datasource_remap: datasourceRemap
			});
			result.match(
				(analysis) => {
					goto(resolve(`/analysis/${analysis.id}`), { invalidateAll: true });
				},
				(err) => {
					error = err.message;
					creating = false;
				}
			);
			return;
		}
		creating = false;
	}

	function updateOutput(
		index: number,
		field: 'filename' | 'namespace' | 'table_name' | 'build_mode',
		value: string
	): void {
		const tab = designTabs[index];
		if (!tab) return;
		if (field === 'filename') {
			tab.output.filename = value;
			return;
		}
		if (field === 'namespace') {
			tab.output.iceberg = {
				namespace: value,
				table_name: tab.output.iceberg?.table_name ?? slugify(tab.output.filename),
				branch: tab.output.iceberg?.branch ?? tab.datasource.config.branch
			};
			return;
		}
		if (field === 'table_name') {
			tab.output.iceberg = {
				namespace: tab.output.iceberg?.namespace ?? defaultOutputNamespace,
				table_name: value,
				branch: tab.output.iceberg?.branch ?? tab.datasource.config.branch
			};
			return;
		}
		tab.output.build_mode = value;
	}

	// Subscription: template-driven tabs must stay aligned with datasource selection and config edits.
	$effect(() => {
		if (mode !== 'template') return;
		synchronizeTemplateTabs(templateDetailQuery.data ?? null);
	});

	// Subscription: changing datasource selection after AI generation invalidates the generated draft.
	$effect(() => {
		if (mode !== 'ai') return;
		if (designTabs.length === 0) return;
		const currentIds = new Set(selectedDatasourceIds);
		const generatedIds = new Set(
			designTabs
				.map((tab) => (tab.datasource.analysis_tab_id ? null : tab.datasource.id))
				.filter((id): id is string => typeof id === 'string')
		);
		if (
			currentIds.size === generatedIds.size &&
			Array.from(currentIds).every((id) => generatedIds.has(id))
		)
			return;
		designTabs = [];
		aiExplanation = '';
	});

	// Subscription: entering review for pipeline modes should trigger server validation.
	$effect(() => {
		if (currentStepLabel !== 'Review') return;
		if (mode !== 'template' && mode !== 'ai') return;
		void refreshValidation();
	});

	// Subscription: configured AI providers should seed the provider/model pickers once loaded.
	$effect(() => {
		if (mode !== 'ai') return;
		if (!configuredProviders.length) return;
		if (!aiProvider) {
			aiProvider = configuredProviders[0]?.provider ?? null;
		}
		if (!aiModel) {
			aiModel =
				configuredProviders.find((provider) => provider.provider === aiProvider)?.default_model ??
				null;
		}
	});
</script>

<div
	class={css({
		marginX: 'auto',
		display: 'flex',
		maxWidth: '1200px',
		flexDirection: 'column',
		gap: '6',
		paddingX: '6',
		paddingY: '7'
	})}
>
	<header
		class={css({
			display: 'flex',
			flexDirection: 'column',
			gap: '4',
			borderBottomWidth: '1',
			paddingBottom: '5'
		})}
	>
		<div>
			<h1 class={css({ margin: '0', fontSize: '2xl', fontWeight: 'semibold' })}>New Analysis</h1>
			<p class={css({ marginTop: '2', marginBottom: '0', color: 'fg.tertiary', fontSize: 'sm' })}>
				Create from a template, generate with AI, clone an existing analysis, or import a pipeline
				definition.
			</p>
		</div>
		<div class={css({ display: 'flex', flexWrap: 'wrap', gap: '3' })}>
			{#each steps as stepLabel, index (stepLabel)}
				<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
					<div
						class={css({
							display: 'flex',
							height: '8',
							width: '8',
							alignItems: 'center',
							justifyContent: 'center',
							borderWidth: '1',
							fontSize: 'xs',
							fontWeight: 'semibold',
							...(step === index + 1
								? { backgroundColor: 'accent.secondary', color: 'fg.inverse' }
								: step > index + 1
									? { backgroundColor: 'bg.success', color: 'fg.success' }
									: { backgroundColor: 'bg.primary', color: 'fg.muted' })
						})}
					>
						{index + 1}
					</div>
					<span
						class={css({ fontSize: 'sm', color: step === index + 1 ? 'fg.primary' : 'fg.muted' })}
					>
						{stepLabel}
					</span>
				</div>
			{/each}
		</div>
	</header>

	{#if error}
		<Callout tone="error">{error}</Callout>
	{/if}

	<div class={css({ display: 'grid', gap: '6', lg: { gridTemplateColumns: '2fr 1fr' } })}>
		<div class={css({ display: 'flex', flexDirection: 'column', gap: '6' })}>
			{#if step === 1}
				<section class={css({ borderWidth: '1', backgroundColor: 'bg.primary', padding: '5' })}>
					<h2
						class={css({
							marginTop: '0',
							marginBottom: '4',
							fontSize: 'lg',
							fontWeight: 'semibold'
						})}
					>
						How do you want to start?
					</h2>
					<div
						class={css({
							display: 'grid',
							gap: '3',
							md: { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }
						})}
					>
						{#each [{ id: 'template', title: 'Template', body: 'Start from a built-in pipeline skeleton.' }, { id: 'ai', title: 'AI-assisted', body: 'Describe the analysis and generate the first draft.' }, { id: 'clone', title: 'Clone existing', body: 'Reuse an existing analysis safely with new outputs.' }, { id: 'import', title: 'Import JSON', body: 'Upload a pipeline definition and remap sources.' }] as option (option.id)}
							<button
								type="button"
								class={css({
									borderWidth: '1',
									padding: '4',
									textAlign: 'left',
									backgroundColor: mode === option.id ? 'bg.accent' : 'bg.primary',
									borderColor: mode === option.id ? 'border.accent' : 'border.primary',
									cursor: 'pointer'
								})}
								onclick={() => setMode(option.id as CreationMode)}
							>
								<div class={css({ fontWeight: 'semibold', marginBottom: '1' })}>{option.title}</div>
								<div class={css({ fontSize: 'sm', color: 'fg.tertiary' })}>{option.body}</div>
							</button>
						{/each}
					</div>

					<div class={css({ marginTop: '5', display: 'grid', gap: '4' })}>
						<label class={css({ display: 'grid', gap: '2' })}>
							<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}>Name</span>
							<input
								id="name"
								bind:value={name}
								class={css({
									borderWidth: '1',
									backgroundColor: 'bg.primary',
									paddingX: '3',
									paddingY: '2'
								})}
								placeholder={mode === 'clone'
									? 'A copy name will be suggested after you pick a source'
									: 'Sales ETL'}
							/>
						</label>
						<label class={css({ display: 'grid', gap: '2' })}>
							<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}>Description</span>
							<textarea
								id="description"
								rows="4"
								bind:value={description}
								class={css({
									borderWidth: '1',
									backgroundColor: 'bg.primary',
									paddingX: '3',
									paddingY: '2'
								})}
								placeholder="Optional context for collaborators and AI generation."
							></textarea>
						</label>
					</div>
				</section>
			{:else if mode === 'template' || mode === 'ai'}
				{#if step === 2}
					<section class={css({ borderWidth: '1', backgroundColor: 'bg.primary', padding: '5' })}>
						<h2
							class={css({
								marginTop: '0',
								marginBottom: '4',
								fontSize: 'lg',
								fontWeight: 'semibold'
							})}
						>
							Select Data Sources
						</h2>
						<DatasourcePicker
							{datasources}
							bind:selected={selectedDatasourceIds}
							mode="multi"
							label="Available datasources"
							onSelect={(id) => ensureDatasourceConfig(id)}
							onDeselect={(id) => removeDatasourceConfig(id)}
						/>
						<div class={css({ marginTop: '4', display: 'grid', gap: '3' })}>
							{#each selectedDatasources as datasource (datasource.id)}
								{@const currentConfig =
									datasourceConfigs[datasource.id] ?? defaultDatasourceConfig(datasource)}
								<div
									draggable="true"
									role="listitem"
									aria-label={`Selected datasource ${datasource.name}`}
									ondragstart={() => {
										draggedDatasourceId = datasource.id;
									}}
									ondragover={(event) => event.preventDefault()}
									ondrop={() => reorderDatasource(datasource.id)}
									class={css({
										display: 'grid',
										gap: '3',
										borderWidth: '1',
										padding: '4'
									})}
								>
									<div
										class={css({
											display: 'flex',
											flexWrap: 'wrap',
											justifyContent: 'space-between',
											gap: '3'
										})}
									>
										<div>
											<div class={css({ fontWeight: 'semibold' })}>{datasource.name}</div>
											<div class={css({ fontSize: 'sm', color: 'fg.tertiary' })}>
												{datasource.source_type} source
											</div>
										</div>
										<div class={css({ display: 'grid', gap: '2', minWidth: '200px' })}>
											<label class={css({ display: 'grid', gap: '1' })}>
												<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>Branch</span>
												<select
													class={css({
														borderWidth: '1',
														backgroundColor: 'bg.primary',
														padding: '2'
													})}
													value={currentConfig.branch}
													onchange={(event) => {
														datasourceConfigs[datasource.id] = {
															...currentConfig,
															branch: (event.currentTarget as HTMLSelectElement).value
														};
													}}
												>
													{#each getBranchOptions(datasource) as branch (branch)}
														<option value={branch}>{branch}</option>
													{/each}
												</select>
											</label>
										</div>
									</div>
									<div
										class={css({
											display: 'grid',
											gap: '2',
											md: { gridTemplateColumns: '1fr 1fr' }
										})}
									>
										<div class={css({ fontSize: 'sm', color: 'fg.tertiary' })}>
											Row count:
											{typeof datasource.schema_cache?.row_count === 'number'
												? datasource.schema_cache.row_count
												: 'Unknown'}
										</div>
										<div>
											<SnapshotPicker
												datasourceId={datasource.id}
												datasourceConfig={currentConfig}
												branch={currentConfig.branch}
												label="Snapshot"
												onConfigChange={(config) => {
													datasourceConfigs[datasource.id] = {
														...currentConfig,
														...(config as AnalysisTabDatasourceConfig)
													};
												}}
											/>
										</div>
									</div>
									{#if Array.isArray(datasource.schema_cache?.columns) && datasource.schema_cache.columns.length > 0}
										<div class={css({ display: 'flex', flexWrap: 'wrap', gap: '2' })}>
											{#each datasource.schema_cache.columns.slice(0, 8) as column (column.name)}
												<span
													class={css({
														borderWidth: '1',
														paddingX: '2',
														paddingY: '1',
														fontSize: 'xs',
														backgroundColor: 'bg.secondary'
													})}
												>
													{column.name}: {column.dtype}
												</span>
											{/each}
										</div>
									{/if}
								</div>
							{/each}
						</div>
					</section>
				{:else if step === 3}
					<section class={css({ borderWidth: '1', backgroundColor: 'bg.primary', padding: '5' })}>
						{#if mode === 'template'}
							<h2
								class={css({
									marginTop: '0',
									marginBottom: '4',
									fontSize: 'lg',
									fontWeight: 'semibold'
								})}
							>
								Choose Template
							</h2>
							{#if templatesQuery.isPending}
								<div class={spinner()}></div>
							{:else}
								<div
									class={css({
										display: 'grid',
										gap: '3',
										md: { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }
									})}
								>
									{#each templatesQuery.data ?? [] as template (template.id)}
										<button
											type="button"
											class={css({
												borderWidth: '1',
												padding: '4',
												textAlign: 'left',
												cursor: 'pointer',
												backgroundColor:
													selectedTemplateId === template.id ? 'bg.accent' : 'bg.primary',
												borderColor:
													selectedTemplateId === template.id ? 'border.accent' : 'border.primary'
											})}
											onclick={() => {
												selectedTemplateId = template.id;
											}}
										>
											<div class={css({ fontWeight: 'semibold', marginBottom: '1' })}>
												{template.name}
											</div>
											<div class={css({ fontSize: 'sm', color: 'fg.tertiary', marginBottom: '2' })}>
												{template.description}
											</div>
											<div class={css({ fontSize: 'xs', color: 'fg.muted' })}>
												{template.step_count} step{template.step_count === 1 ? '' : 's'}
											</div>
										</button>
									{/each}
								</div>
								{#if templateSummary}
									<div class={css({ marginTop: '4', borderTopWidth: '1', paddingTop: '4' })}>
										<div class={css({ fontWeight: 'semibold', marginBottom: '2' })}>Preview</div>
										<div
											class={css({
												display: 'flex',
												flexWrap: 'wrap',
												gap: '2',
												alignItems: 'center'
											})}
										>
											<span
												class={css({
													borderWidth: '1',
													paddingX: '2',
													paddingY: '1',
													fontSize: 'xs'
												})}
											>
												source
											</span>
											<span class={css({ color: 'fg.tertiary', fontSize: 'xs' })}>→</span>
											{#each templateDetailQuery.data?.steps ?? [] as stepPreview (stepPreview.type)}
												<span
													class={css({
														borderWidth: '1',
														paddingX: '2',
														paddingY: '1',
														fontSize: 'xs',
														backgroundColor: 'bg.secondary'
													})}
												>
													{stepPreview.type}
												</span>
												<span class={css({ color: 'fg.tertiary', fontSize: 'xs' })}>→</span>
											{/each}
											<span
												class={css({
													borderWidth: '1',
													paddingX: '2',
													paddingY: '1',
													fontSize: 'xs'
												})}
											>
												output
											</span>
										</div>
										{#if (templateDetailQuery.data?.required_input_columns?.length ?? 0) > 0}
											<div class={css({ marginTop: '3', display: 'grid', gap: '1' })}>
												<div
													class={css({
														fontSize: 'xs',
														fontWeight: 'semibold',
														color: 'fg.tertiary'
													})}
												>
													Required input columns
												</div>
												<div class={css({ display: 'flex', flexWrap: 'wrap', gap: '2' })}>
													{#each templateDetailQuery.data?.required_input_columns ?? [] as columnHint (columnHint)}
														<span
															class={css({
																borderWidth: '1',
																paddingX: '2',
																paddingY: '1',
																fontSize: 'xs',
																backgroundColor: 'bg.secondary'
															})}
														>
															{columnHint}
														</span>
													{/each}
												</div>
											</div>
										{/if}
									</div>
								{/if}
							{/if}
						{:else}
							<h2
								class={css({
									marginTop: '0',
									marginBottom: '4',
									fontSize: 'lg',
									fontWeight: 'semibold'
								})}
							>
								Describe Your Analysis
							</h2>
							<div class={css({ display: 'grid', gap: '4' })}>
								<textarea
									rows="6"
									bind:value={aiPrompt}
									class={css({ borderWidth: '1', backgroundColor: 'bg.primary', padding: '3' })}
									placeholder="Join orders with customers, filter cancelled orders, then build a monthly revenue report."
								></textarea>
								<div
									class={css({ display: 'grid', gap: '3', md: { gridTemplateColumns: '1fr 1fr' } })}
								>
									<label class={css({ display: 'grid', gap: '1' })}>
										<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>Provider</span>
										<select
											class={css({ borderWidth: '1', backgroundColor: 'bg.primary', padding: '2' })}
											bind:value={aiProvider}
										>
											{#each configuredProviders as provider (provider.provider)}
												<option value={provider.provider}>{provider.provider}</option>
											{/each}
										</select>
									</label>
									<label class={css({ display: 'grid', gap: '1' })}>
										<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>Model</span>
										<input
											class={css({ borderWidth: '1', backgroundColor: 'bg.primary', padding: '2' })}
											bind:value={aiModel}
										/>
									</label>
								</div>
								<button
									type="button"
									class={css({
										borderWidth: '1',
										backgroundColor: 'accent.primary',
										color: 'fg.inverse',
										paddingX: '4',
										paddingY: '2',
										width: 'fit-content'
									})}
									onclick={handleGenerate}
									disabled={generating ||
										!aiPrompt.trim() ||
										!name.trim() ||
										selectedDatasourceIds.length === 0}
								>
									{generating ? 'Generating...' : 'Generate Pipeline'}
								</button>
								{#if aiExplanation}
									<Callout tone="info">{aiExplanation}</Callout>
								{/if}
							</div>
						{/if}
					</section>
				{:else if step === 4}
					<section class={css({ borderWidth: '1', backgroundColor: 'bg.primary', padding: '5' })}>
						<h2
							class={css({
								marginTop: '0',
								marginBottom: '4',
								fontSize: 'lg',
								fontWeight: 'semibold'
							})}
						>
							Configure Outputs
						</h2>
						<div class={css({ display: 'grid', gap: '3' })}>
							{#each designTabs as tab, index (tab.id)}
								<div class={css({ borderWidth: '1', padding: '4', display: 'grid', gap: '3' })}>
									<div class={css({ fontWeight: 'semibold' })}>{tab.name}</div>
									<div
										class={css({
											display: 'grid',
											gap: '3',
											md: { gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }
										})}
									>
										<label class={css({ display: 'grid', gap: '1' })}>
											<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>Output name</span>
											<input
												class={css({
													borderWidth: '1',
													backgroundColor: 'bg.primary',
													padding: '2'
												})}
												bind:value={tab.output.filename}
											/>
										</label>
										<label class={css({ display: 'grid', gap: '1' })}>
											<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>Namespace</span>
											<input
												class={css({
													borderWidth: '1',
													backgroundColor: 'bg.primary',
													padding: '2'
												})}
												value={tab.output.iceberg?.namespace ?? ''}
												oninput={(event) =>
													updateOutput(
														index,
														'namespace',
														(event.currentTarget as HTMLInputElement).value
													)}
											/>
										</label>
										<label class={css({ display: 'grid', gap: '1' })}>
											<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>Table name</span>
											<input
												class={css({
													borderWidth: '1',
													backgroundColor: 'bg.primary',
													padding: '2'
												})}
												value={tab.output.iceberg?.table_name ?? ''}
												oninput={(event) =>
													updateOutput(
														index,
														'table_name',
														(event.currentTarget as HTMLInputElement).value
													)}
											/>
										</label>
										<label class={css({ display: 'grid', gap: '1' })}>
											<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>Build mode</span>
											<select
												class={css({
													borderWidth: '1',
													backgroundColor: 'bg.primary',
													padding: '2'
												})}
												value={tab.output.build_mode ?? 'full'}
												onchange={(event) =>
													updateOutput(
														index,
														'build_mode',
														(event.currentTarget as HTMLSelectElement).value
													)}
											>
												<option value="full">full</option>
												<option value="incremental">incremental</option>
												<option value="recreate">recreate</option>
											</select>
										</label>
									</div>
								</div>
							{/each}
						</div>
						{#if outputErrors.length > 0}
							<div class={css({ marginTop: '4' })}>
								<Callout tone="error">{outputErrors.join('. ')}</Callout>
							</div>
						{/if}
					</section>
				{:else}
					<section class={css({ borderWidth: '1', backgroundColor: 'bg.primary', padding: '5' })}>
						<h2
							class={css({
								marginTop: '0',
								marginBottom: '4',
								fontSize: 'lg',
								fontWeight: 'semibold'
							})}
						>
							Review
						</h2>
						<div class={css({ display: 'grid', gap: '4' })}>
							<div class={css({ display: 'grid', gap: '1' })}>
								<div><strong>Name:</strong> {name}</div>
								<div><strong>Sources:</strong> {selectedDatasourceIds.length}</div>
								<div><strong>Steps:</strong> {complexity.steps}</div>
								<div><strong>Complexity:</strong> {complexity.size}</div>
								<div><strong>Estimated output size:</strong> {estimatedOutputSize}</div>
							</div>
							<div class={css({ display: 'grid', gap: '3' })}>
								{#each designTabs as tab (tab.id)}
									<div class={css({ borderWidth: '1', padding: '4', display: 'grid', gap: '2' })}>
										<div class={css({ fontWeight: 'semibold' })}>{tab.name}</div>
										<div
											class={css({
												display: 'flex',
												flexWrap: 'wrap',
												gap: '2',
												alignItems: 'center'
											})}
										>
											<span
												class={css({
													borderWidth: '1',
													paddingX: '2',
													paddingY: '1',
													fontSize: 'xs'
												})}
											>
												{getDatasourceById(
													selectedDatasourceIds[
														Math.min(designTabs.indexOf(tab), selectedDatasourceIds.length - 1)
													]
												)?.name ?? 'datasource'}
											</span>
											<span class={css({ color: 'fg.tertiary', fontSize: 'xs' })}>→</span>
											{#each tab.steps as stepPreview (stepPreview.id)}
												<span
													class={css({
														borderWidth: '1',
														paddingX: '2',
														paddingY: '1',
														fontSize: 'xs',
														backgroundColor: 'bg.secondary'
													})}
												>
													{stepPreview.type}
												</span>
												<span class={css({ color: 'fg.tertiary', fontSize: 'xs' })}>→</span>
											{/each}
											<span
												class={css({
													borderWidth: '1',
													paddingX: '2',
													paddingY: '1',
													fontSize: 'xs'
												})}
											>
												{tab.output.iceberg?.namespace ?? defaultOutputNamespace}.{tab.output
													.iceberg?.table_name ?? tab.output.filename}
											</span>
										</div>
									</div>
								{/each}
							</div>
							{#if reviewValidation.loading}
								<div class={spinner()}></div>
							{:else if reviewValidation.error}
								<Callout tone="error">{reviewValidation.error}</Callout>
							{:else}
								<Callout tone="info">Validation passed.</Callout>
							{/if}
							{#if localPipelineErrors.length > 0}
								<Callout tone="error">{formatPipelineErrors(localPipelineErrors)}</Callout>
							{/if}
						</div>
					</section>
				{/if}
			{:else if mode === 'clone'}
				{#if step === 2}
					<section class={css({ borderWidth: '1', backgroundColor: 'bg.primary', padding: '5' })}>
						<h2
							class={css({
								marginTop: '0',
								marginBottom: '4',
								fontSize: 'lg',
								fontWeight: 'semibold'
							})}
						>
							Clone Existing Analysis
						</h2>
						<DatasourcePicker
							datasources={[]}
							selected={cloneSourceId}
							mode="single"
							modeSource="analysis"
							placeholder="Search analyses..."
							label="Available analyses"
							onSelect={(id, selectedName) => {
								cloneSourceId = id;
								cloneSourceName = selectedName;
								if (!name.trim() || name.startsWith('Copy of ')) {
									name = `Copy of ${selectedName}`;
								}
							}}
						/>
						<p class={css({ marginTop: '4', fontSize: 'sm', color: 'fg.tertiary' })}>
							Outputs will be regenerated and will not reuse the original analysis outputs.
						</p>
					</section>
				{:else}
					<section class={css({ borderWidth: '1', backgroundColor: 'bg.primary', padding: '5' })}>
						<h2
							class={css({
								marginTop: '0',
								marginBottom: '4',
								fontSize: 'lg',
								fontWeight: 'semibold'
							})}
						>
							Review Clone
						</h2>
						<div class={css({ display: 'grid', gap: '2' })}>
							<div><strong>Source:</strong> {cloneSourceName}</div>
							<div><strong>New name:</strong> {name || `Copy of ${cloneSourceName}`}</div>
							<div><strong>Description:</strong> {description || 'Reuse source description'}</div>
						</div>
					</section>
				{/if}
			{:else if step === 2}
				<section class={css({ borderWidth: '1', backgroundColor: 'bg.primary', padding: '5' })}>
					<h2
						class={css({
							marginTop: '0',
							marginBottom: '4',
							fontSize: 'lg',
							fontWeight: 'semibold'
						})}
					>
						Import Pipeline Definition
					</h2>
					<label class={css({ display: 'grid', gap: '2' })}>
						<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}>JSON file</span>
						<input type="file" accept="application/json" onchange={handleImportFile} />
					</label>
					{#if importFileName}
						<div class={css({ marginTop: '3', fontSize: 'sm', color: 'fg.tertiary' })}>
							Loaded: {importFileName}
						</div>
					{/if}
					{#if importError}
						<div class={css({ marginTop: '3' })}>
							<Callout tone="error">{importError}</Callout>
						</div>
					{/if}
					{#if importedPipeline}
						<div class={css({ marginTop: '4', display: 'grid', gap: '3' })}>
							<div class={css({ fontSize: 'sm', color: 'fg.tertiary' })}>
								Pipeline tabs: {Array.isArray(importedPipeline.tabs)
									? importedPipeline.tabs.length
									: 0}
							</div>
							{#if missingImportDatasourceIds.length > 0}
								<Callout tone="warn">
									Remap missing datasource references before creating the analysis.
								</Callout>
								{#each missingImportDatasourceIds as missingId (missingId)}
									<label class={css({ display: 'grid', gap: '1' })}>
										<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>
											Remap {missingId}
										</span>
										<select
											class={css({ borderWidth: '1', backgroundColor: 'bg.primary', padding: '2' })}
											bind:value={datasourceRemap[missingId]}
										>
											<option value="">Select datasource</option>
											{#each datasources as datasource (datasource.id)}
												<option value={datasource.id}>{datasource.name}</option>
											{/each}
										</select>
									</label>
								{/each}
							{/if}
						</div>
					{/if}
				</section>
			{:else}
				<section class={css({ borderWidth: '1', backgroundColor: 'bg.primary', padding: '5' })}>
					<h2
						class={css({
							marginTop: '0',
							marginBottom: '4',
							fontSize: 'lg',
							fontWeight: 'semibold'
						})}
					>
						Review Import
					</h2>
					<div class={css({ display: 'grid', gap: '2' })}>
						<div><strong>Name:</strong> {name}</div>
						<div><strong>File:</strong> {importFileName}</div>
						<div>
							<strong>Remapped datasources:</strong>
							{Object.keys(datasourceRemap).length}
						</div>
					</div>
				</section>
			{/if}
		</div>

		<aside class={css({ display: 'grid', gap: '4', alignContent: 'start' })}>
			<section class={css({ borderWidth: '1', backgroundColor: 'bg.primary', padding: '4' })}>
				<div class={css({ fontWeight: 'semibold', marginBottom: '2' })}>Summary</div>
				<div class={css({ display: 'grid', gap: '1', fontSize: 'sm', color: 'fg.tertiary' })}>
					<div>Mode: {mode}</div>
					<div>Step: {currentStepLabel}</div>
					<div>Selected sources: {selectedDatasourceIds.length}</div>
					<div>Draft tabs: {designTabs.length}</div>
					<div>Draft steps: {complexity.steps}</div>
				</div>
			</section>
			{#if templateSummary && mode === 'template'}
				<section class={css({ borderWidth: '1', backgroundColor: 'bg.primary', padding: '4' })}>
					<div class={css({ fontWeight: 'semibold', marginBottom: '2' })}>
						{templateSummary.name}
					</div>
					<div class={css({ fontSize: 'sm', color: 'fg.tertiary' })}>
						{templateSummary.description}
					</div>
				</section>
			{/if}
			{#if aiExplanation && mode === 'ai'}
				<section class={css({ borderWidth: '1', backgroundColor: 'bg.primary', padding: '4' })}>
					<div class={css({ fontWeight: 'semibold', marginBottom: '2' })}>AI Explanation</div>
					<div class={css({ fontSize: 'sm', color: 'fg.tertiary' })}>{aiExplanation}</div>
				</section>
			{/if}
		</aside>
	</div>

	<footer
		class={css({ display: 'flex', justifyContent: 'space-between', gap: '3', paddingTop: '2' })}
	>
		<div class={css({ display: 'flex', gap: '3' })}>
			{#if step > 1}
				<button
					type="button"
					class={css({
						borderWidth: '1',
						paddingX: '4',
						paddingY: '2',
						backgroundColor: 'bg.primary'
					})}
					onclick={prevStep}
				>
					Back
				</button>
			{/if}
			<a
				href={resolve('/')}
				class={css({
					borderWidth: '1',
					paddingX: '4',
					paddingY: '2',
					textDecoration: 'none',
					color: 'fg.primary',
					backgroundColor: 'bg.primary'
				})}
			>
				Cancel
			</a>
		</div>
		<div class={css({ display: 'flex', gap: '3' })}>
			{#if step < steps.length}
				<button
					type="button"
					class={css({
						borderWidth: '1',
						paddingX: '4',
						paddingY: '2',
						backgroundColor: 'accent.primary',
						color: 'fg.inverse'
					})}
					disabled={!canProceed()}
					onclick={nextStep}
				>
					Next
				</button>
			{:else}
				<button
					type="button"
					class={css({
						borderWidth: '1',
						paddingX: '4',
						paddingY: '2',
						backgroundColor: 'accent.primary',
						color: 'fg.inverse'
					})}
					disabled={creating ||
						(mode !== 'clone' &&
							mode !== 'import' &&
							(!reviewValidation.valid || outputErrors.length > 0))}
					onclick={handleCreate}
				>
					{creating ? 'Creating...' : mode === 'clone' ? 'Clone Analysis' : 'Create Analysis'}
				</button>
			{/if}
		</div>
	</footer>
</div>
