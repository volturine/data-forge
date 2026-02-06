<script lang="ts">
	import type { PipelineStep } from '$lib/types/analysis';
	import type { Schema } from '$lib/types/schema';
	import type {
		FilterConfigData,
		SelectConfigData,
		GroupByConfigData,
		SortConfigData,
		RenameConfigData,
		DropConfigData,
		JoinConfigData,
		ExpressionConfigData,
		DeduplicateConfigData,
		FillNullConfigData,
		ExplodeConfigData,
		PivotConfigData,
		TimeSeriesConfigData,
		StringMethodsConfigData,
		ViewConfigData,
		SampleConfigData,
		LimitConfigData,
		TopKConfigData,
		ValueCountsConfigData,
		UnpivotConfigData
	} from '$lib/types/operation-config';
	import { schemaStore } from '$lib/stores/schema.svelte';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { getStepSchema, type StepSchemaResponse } from '$lib/api/compute';
	import { normalizeConfig } from '$lib/utils/step-config-defaults';
	import FilterConfig from '$lib/components/operations/FilterConfig.svelte';
	import SelectConfig from '$lib/components/operations/SelectConfig.svelte';
	import GroupByConfig from '$lib/components/operations/GroupByConfig.svelte';
	import SortConfig from '$lib/components/operations/SortConfig.svelte';
	import RenameConfig from '$lib/components/operations/RenameConfig.svelte';
	import DropConfig from '$lib/components/operations/DropConfig.svelte';
	import JoinConfig from '$lib/components/operations/JoinConfig.svelte';
	import ExpressionConfig from '$lib/components/operations/ExpressionConfig.svelte';
	import WithColumnsConfig from '$lib/components/operations/WithColumnsConfig.svelte';
	import DeduplicateConfig from '$lib/components/operations/DeduplicateConfig.svelte';
	import FillNullConfig from '$lib/components/operations/FillNullConfig.svelte';
	import ExplodeConfig from '$lib/components/operations/ExplodeConfig.svelte';
	import PivotConfig from '$lib/components/operations/PivotConfig.svelte';
	import TimeSeriesConfig from '$lib/components/operations/TimeSeriesConfig.svelte';
	import StringMethodsConfig from '$lib/components/operations/StringMethodsConfig.svelte';
	import ViewConfig from '$lib/components/operations/ViewConfig.svelte';
	import SampleConfig from '$lib/components/operations/SampleConfig.svelte';
	import LimitConfig from '$lib/components/operations/LimitConfig.svelte';
	import TopKConfig from '$lib/components/operations/TopKConfig.svelte';
	import NullCountConfig from '$lib/components/operations/NullCountConfig.svelte';
	import ValueCountsConfig from '$lib/components/operations/ValueCountsConfig.svelte';
	import UnpivotConfig from '$lib/components/operations/UnpivotConfig.svelte';
	import ExportConfig from '$lib/components/operations/ExportConfig.svelte';
	import UnionByNameConfig from '$lib/components/operations/UnionByNameConfig.svelte';

	type WithColumnsConfigShape = {
		expressions: Array<{
			name: string;
			type: 'literal' | 'column' | 'udf';
			value?: string | number | null;
			column?: string | null;
			args?: string[] | null;
			code?: string | null;
		}>;
	};

	interface Props {
		step?: PipelineStep | null;
		schema: Schema | null;
		isLoadingSchema?: boolean;
		onClose?: () => void;
		onConfigApply?: () => void;
	}

	let {
		step = $bindable(null),
		schema,
		isLoadingSchema = false,
		onClose,
		onConfigApply
	}: Props = $props();
	let fetchingPivotSchema = $state(false);
	let draftStepId = $state<string | null>(null);
	let draftConfig = $state<Record<string, unknown>>({});

	let inputSchema = $derived(
		step
			? (schemaStore.getInput(step.id) ?? { columns: [], row_count: null })
			: { columns: [], row_count: null }
	);

	function cloneConfig(
		config: Record<string, unknown> | null | undefined
	): Record<string, unknown> {
		const payload = config ?? {};
		return JSON.parse(JSON.stringify(payload)) as Record<string, unknown>;
	}

	$effect(() => {
		if (!step) {
			draftStepId = null;
			draftConfig = {};
			return;
		}
		if (draftStepId === step.id) return;
		draftStepId = step.id;
		const normalizedConfig = normalizeConfig(
			step.type,
			(step.config as Record<string, unknown>) ?? {}
		) as Record<string, unknown>;
		draftConfig = cloneConfig(normalizedConfig);
	});

	const hasChanges = $derived(
		!!step &&
			(JSON.stringify(step.config) !== JSON.stringify(draftConfig) ||
				(step as PipelineStep & { is_applied?: boolean }).is_applied === false)
	);

	function handleRefreshPivotSchema() {
		if (!step || step.type !== 'pivot') return;
		const config = draftConfig;
		if (!config || typeof config !== 'object') return;
		const columns = config.columns;
		const index = config.index;
		if (!(columns && Array.isArray(index) && index.length > 0)) return;

		const analysis = analysisStore.current;
		const datasourceId = analysisStore.activeTab?.datasource_id;
		if (!analysis?.id || !datasourceId) return;

		fetchingPivotSchema = true;

		const pipelineSteps = analysisStore.pipeline.map((s) => {
			if (s.id !== step.id) {
				return {
					id: s.id,
					type: s.type,
					config: s.config,
					depends_on: s.depends_on
				};
			}
			return {
				id: s.id,
				type: s.type,
				config: draftConfig,
				depends_on: s.depends_on
			};
		});

		getStepSchema({
			analysis_id: analysis.id,
			datasource_id: datasourceId,
			pipeline_steps: pipelineSteps,
			target_step_id: step.id
		})
			.map((response: StepSchemaResponse) => {
				schemaStore.setPreviewSchema(step.id, response.columns, response.column_types);
				fetchingPivotSchema = false;
			})
			.mapErr((error: unknown) => {
				console.error('Failed to fetch pivot schema:', error);
				fetchingPivotSchema = false;
			});
	}

	function handleApplyConfig() {
		if (!step) return;
		analysisStore.updateStepConfig(step.id, cloneConfig(draftConfig));
		if ((step as PipelineStep & { is_applied?: boolean }).is_applied === false) {
			analysisStore.updateStep(step.id, { is_applied: true } as Partial<PipelineStep> & {
				is_applied: boolean;
			});
		}
		onConfigApply?.();
	}

	function handleCancelConfig() {
		if (!step) return;
		draftConfig = cloneConfig(step.config as Record<string, unknown>);
	}
</script>

{#if step === null}
	<div
		class="step-config box-border flex w-full flex-col items-center justify-center overflow-y-auto bg-panel-bg text-fg-primary"
	>
		<div
			class="flex flex-col items-center justify-center p-6 text-center text-fg-muted"
		>
			<div class="mb-4 text-4xl opacity-50">⚙️</div>
			<h3 class="m-0 mb-2 text-lg text-fg-primary">No step selected</h3>
			<p class="m-0 text-sm">Click on a pipeline step to configure it</p>
		</div>
	</div>
{:else}
	<div
		class="step-config box-border flex w-full flex-col overflow-y-auto bg-panel-bg text-fg-primary"
	>
		<div
			class="config-header relative flex items-center justify-between bg-panel-bg p-4 shadow-[inset_0_-1px_0_var(--panel-border),inset_0_-3px_0_var(--panel-border),inset_0_-5px_0_var(--panel-border)]"
		>
			<h3
				class="m-0 text-sm font-semibold uppercase tracking-widest text-fg-primary"
			>
				Configure Step
			</h3>
			<button
				class="close-button flex h-8 w-8 cursor-pointer items-center justify-center rounded-sm border-none bg-transparent p-0 text-2xl leading-none text-fg-muted transition-all hover:bg-bg-hover hover:text-fg-primary"
				onclick={() => onClose?.()}
				type="button"
				title="Close">×</button
			>
		</div>

		<div class="config-body flex-1 overflow-y-auto bg-panel-bg p-3">
			{#if !schema && !isLoadingSchema}
				<div class="warning-message">
					<p>Schema not available. Please ensure the data source is loaded.</p>
					<button onclick={() => onClose?.()} type="button">Close</button>
				</div>
			{:else if isLoadingSchema}
				<div
					class="flex flex-col items-center justify-center gap-3 bg-panel-bg p-6 text-center text-fg-tertiary"
				>
					<div class="spinner-md"></div>
					<p class="m-0">Loading schema...</p>
				</div>
			{:else if step.type === 'filter'}
				<FilterConfig
					schema={inputSchema}
					bind:config={draftConfig as unknown as FilterConfigData}
				/>
			{:else if step.type === 'select'}
				<SelectConfig
					schema={inputSchema}
					bind:config={draftConfig as unknown as SelectConfigData}
				/>
			{:else if step.type === 'groupby'}
				<GroupByConfig
					schema={inputSchema}
					bind:config={draftConfig as unknown as GroupByConfigData}
				/>
			{:else if step.type === 'sort'}
				<SortConfig schema={inputSchema} bind:config={draftConfig as unknown as SortConfigData} />
			{:else if step.type === 'rename'}
				<RenameConfig
					schema={inputSchema}
					bind:config={draftConfig as unknown as RenameConfigData}
				/>
			{:else if step.type === 'drop'}
				<DropConfig schema={inputSchema} bind:config={draftConfig as unknown as DropConfigData} />
			{:else if step.type === 'join'}
				<JoinConfig schema={inputSchema} bind:config={draftConfig as unknown as JoinConfigData} />
			{:else if step.type === 'expression'}
				<ExpressionConfig
					schema={inputSchema}
					bind:config={draftConfig as unknown as ExpressionConfigData}
				/>
			{:else if step.type === 'with_columns'}
				<WithColumnsConfig
					schema={inputSchema}
					bind:config={draftConfig as unknown as WithColumnsConfigShape}
				/>
			{:else if step.type === 'deduplicate'}
				<DeduplicateConfig
					schema={inputSchema}
					bind:config={draftConfig as unknown as DeduplicateConfigData}
				/>
			{:else if step.type === 'fill_null'}
				<FillNullConfig
					schema={inputSchema}
					bind:config={draftConfig as unknown as FillNullConfigData}
				/>
			{:else if step.type === 'explode'}
				<ExplodeConfig
					schema={inputSchema}
					bind:config={draftConfig as unknown as ExplodeConfigData}
				/>
			{:else if step.type === 'pivot'}
				<PivotConfig
					schema={inputSchema}
					bind:config={draftConfig as unknown as PivotConfigData}
					onRefreshSchema={handleRefreshPivotSchema}
					isRefreshing={fetchingPivotSchema}
				/>
			{:else if step.type === 'timeseries'}
				<TimeSeriesConfig
					schema={inputSchema}
					bind:config={draftConfig as unknown as TimeSeriesConfigData}
				/>
			{:else if step.type === 'string_transform'}
				<StringMethodsConfig
					schema={inputSchema}
					bind:config={draftConfig as unknown as StringMethodsConfigData}
				/>
			{:else if step.type === 'view'}
				<ViewConfig schema={inputSchema} bind:config={draftConfig as unknown as ViewConfigData} />
			{:else if step.type === 'datasource'}
				<div class="bg-panel-bg p-6 text-center">
					<p class="m-0 mb-3 text-fg-tertiary">
						Datasource options are set during upload.
					</p>
				</div>
			{:else if step.type === 'sample'}
				<SampleConfig bind:config={draftConfig as unknown as SampleConfigData} />
			{:else if step.type === 'limit'}
				<LimitConfig bind:config={draftConfig as unknown as LimitConfigData} />
			{:else if step.type === 'topk'}
				<TopKConfig schema={inputSchema} bind:config={draftConfig as unknown as TopKConfigData} />
			{:else if step.type === 'null_count'}
				<NullCountConfig bind:config={draftConfig as unknown as Record<string, never>} />
			{:else if step.type === 'value_counts'}
				<ValueCountsConfig
					schema={inputSchema}
					bind:config={draftConfig as unknown as ValueCountsConfigData}
				/>
			{:else if step.type === 'unpivot'}
				<UnpivotConfig
					schema={inputSchema}
					bind:config={draftConfig as unknown as UnpivotConfigData}
				/>
			{:else if step.type === 'union_by_name'}
				<UnionByNameConfig
					schema={inputSchema}
					bind:config={draftConfig as unknown as { sources: string[]; allow_missing: boolean }}
				/>
			{:else if step.type === 'export'}
				<ExportConfig
					bind:config={
						draftConfig as unknown as { format?: string; filename?: string; destination?: string }
					}
				/>
			{:else}
				<div class="bg-panel-bg p-6 text-center">
					<p class="m-0 mb-3 text-fg-tertiary">
						Configuration for {step.type} is not yet implemented
					</p>
					<button
						class="cursor-pointer rounded-sm border-none bg-accent-primary px-5 py-2 font-mono text-bg-primary"
						onclick={() => onClose?.()}
						type="button">Close</button
					>
				</div>
			{/if}
		</div>
		<div
			class="flex gap-2 border-t border-panel-border bg-panel-bg p-3"
		>
			<button
				class="action-button cancel flex-1 cursor-pointer rounded-sm border border-border-primary bg-transparent px-3 py-2 font-mono text-sm font-semibold text-fg-primary transition-all hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
				onclick={handleCancelConfig}
				disabled={!hasChanges}
				type="button"
			>
				Cancel
			</button>
			<button
				class="action-button apply flex-1 cursor-pointer rounded-sm border border-accent-primary bg-accent-primary px-3 py-2 font-mono text-sm font-semibold text-bg-primary transition-all hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
				onclick={handleApplyConfig}
				disabled={!hasChanges}
				type="button"
			>
				Apply Changes
			</button>
		</div>
	</div>
{/if}

<style>
	.step-config,
	.step-config :global(*) {
		box-sizing: border-box;
	}
</style>
