<script lang="ts">
	import { onDestroy } from 'svelte';
	import type { PipelineStep } from '$lib/types/analysis';
	import type { Schema } from '$lib/types/schema';
	import { schemaStore } from '$lib/stores/schema.svelte';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { configStore } from '$lib/stores/config.svelte';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { getStepSchema, throwIfAborted, type StepSchemaResponse } from '$lib/api/compute';
	import { track } from '$lib/utils/audit-log';
	import { normalizeConfig } from '$lib/utils/step-config-defaults';
	import { buildAnalysisPipelinePayload } from '$lib/utils/analysis-pipeline';
	import { cloneJson } from '$lib/utils/json';
	import { applySteps } from '$lib/utils/pipeline';
	import { hashPipeline } from '$lib/utils/hash';
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
	import DownloadConfig from '$lib/components/operations/DownloadConfig.svelte';
	import SampleConfig from '$lib/components/operations/SampleConfig.svelte';
	import LimitConfig from '$lib/components/operations/LimitConfig.svelte';
	import TopKConfig from '$lib/components/operations/TopKConfig.svelte';

	import UnpivotConfig from '$lib/components/operations/UnpivotConfig.svelte';
	import PlotConfig from '$lib/components/operations/PlotConfig.svelte';
	import NotificationConfig from '$lib/components/operations/NotificationConfig.svelte';
	import AIConfig from '$lib/components/operations/AIConfig.svelte';
	import UnionByNameConfig from '$lib/components/operations/UnionByNameConfig.svelte';
	import { getStepTypeConfig } from '$lib/components/pipeline/utils';
	import type { StepDraft } from '$lib/components/pipeline/step-draft';
	import PanelHeader from '$lib/components/ui/PanelHeader.svelte';
	import PanelFooter from '$lib/components/ui/PanelFooter.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { Settings2, X } from '@lucide/svelte';
	import { css, spinner, button } from '$lib/styles/panda';

	interface Props {
		step?: PipelineStep | null;
		schema: Schema | null;
		isLoadingSchema?: boolean;
		onClose?: () => void;
		onConfigApply?: () => void;
		readOnly?: boolean;
	}

	let {
		step = $bindable(null),
		schema,
		isLoadingSchema = false,
		onClose,
		onConfigApply,
		readOnly = false
	}: Props = $props();
	const stepLabel = $derived(step ? getStepTypeConfig(step.type).label : '');
	let fetchingPivotSchema = $state(false);
	let schemaAbortController: AbortController | null = null;

	function startSchemaRequest(): AbortController {
		schemaAbortController?.abort();
		const controller = new AbortController();
		schemaAbortController = controller;
		return controller;
	}

	function cloneConfig(
		config: Record<string, unknown> | null | undefined
	): Record<string, unknown> {
		const payload = config ?? {};
		return cloneJson(payload);
	}

	function draftFromStep(current: PipelineStep | null | undefined): Record<string, unknown> {
		if (!current) return {};
		return cloneConfig(
			normalizeConfig(current.type, (current.config as Record<string, unknown>) ?? {}) as Record<
				string,
				unknown
			>
		);
	}

	let draftStepId = $state<string | null>(step?.id ?? null);
	// One $state object, bound straight into the step form. A getter wrapper
	// lets the inputs mutate a copy while Apply still reads this object.
	let draftConfig = $state<StepDraft>(draftFromStep(step));
	const draftReady = $derived(step !== null && draftStepId === step.id);

	const inputSchema = $derived(
		step
			? (schemaStore.getInput(step.id) ?? { columns: [], row_count: null })
			: { columns: [], row_count: null }
	);
	const waitingForSelectedStepSchema = $derived(
		isLoadingSchema && inputSchema.columns.length === 0
	);

	const configFlags = $derived({
		smtpEnabled: configStore.smtpEnabled,
		telegramEnabled: configStore.telegramEnabled
	});
	const readOnlyConfigJson = $derived(JSON.stringify(draftConfig, null, 2));

	function applyBlockReason(stepType: string, config: Record<string, unknown>): string | null {
		if (stepType === 'download') {
			const filename = config.filename;
			if (typeof filename !== 'string' || filename.trim() === '') return 'Enter a filename';
		}
		if (stepType === 'with_columns') {
			const expressions = config.expressions;
			if (!Array.isArray(expressions) || expressions.length === 0) return 'Add an expression';
		}
		if (stepType === 'rename') {
			const mapping = config.column_mapping;
			if (
				mapping == null ||
				typeof mapping !== 'object' ||
				Array.isArray(mapping) ||
				Object.keys(mapping).length === 0
			) {
				return 'Add a rename';
			}
		}
		if (stepType === 'sample') {
			const fraction = config.fraction;
			if (
				typeof fraction !== 'number' ||
				!Number.isFinite(fraction) ||
				fraction <= 0 ||
				fraction > 1
			) {
				return 'Fraction must be greater than 0 and at most 1';
			}
		}
		return null;
	}

	const hasChanges = $derived(
		!!step &&
			(JSON.stringify(step.config) !== JSON.stringify(draftConfig) || step.is_applied === false)
	);
	const applyBlockedBecause = $derived(step ? applyBlockReason(step.type, draftConfig) : null);
	const canApply = $derived(!!step && hasChanges && applyBlockedBecause == null);

	function handleRefreshPivotSchema() {
		if (!step || step.type !== 'pivot') return;
		const config = draftConfig;
		if (!config || typeof config !== 'object') return;
		const columns = config['columns'];
		const index = config['index'];
		if (!(columns && Array.isArray(index) && index.length > 0)) return;

		const analysis = analysisStore.current;
		const datasourceId = analysisStore.activeTab?.datasource.id ?? null;
		if (!analysis?.id || !datasourceId) return;

		fetchingPivotSchema = true;

		const analysisPipeline = buildAnalysisPipelinePayload(
			analysis.id,
			analysisStore.tabs,
			datasourceStore.datasources
		);
		if (!analysisPipeline) {
			fetchingPivotSchema = false;
			return;
		}
		const controller = startSchemaRequest();

		getStepSchema(
			{
				analysis_id: analysis.id,
				analysis_pipeline: analysisPipeline,
				tab_id: analysisStore.activeTab?.id ?? null,
				target_step_id: step.id
			},
			{ signal: controller.signal }
		)
			.map((response: StepSchemaResponse) => {
				throwIfAborted(controller.signal);
				schemaStore.setPreviewSchema(step.id, response.columns, response.column_types);
				if (schemaAbortController === controller) fetchingPivotSchema = false;
			})
			.mapErr((error: unknown) => {
				if (controller.signal.aborted) return;
				const err = error instanceof Error ? error.message : String(error);
				track({
					event: 'schema_error',
					action: 'pivot_schema',
					target: step.id,
					meta: { message: err }
				});
				if (schemaAbortController === controller) fetchingPivotSchema = false;
			});
	}

	function handleApplyConfig() {
		if (readOnly) return;
		if (!step || !hasChanges || applyBlockReason(step.type, draftConfig)) return;
		analysisStore.updateStepConfig(step.id, cloneConfig(draftConfig));
		if (step.is_applied === false) {
			analysisStore.updateStep(step.id, { is_applied: true } as Partial<PipelineStep>);
		}
		onConfigApply?.();
		if (step.type === 'expression' || step.type === 'with_columns') {
			refreshStepSchema(step.id);
		}
	}

	function refreshStepSchema(stepId: string) {
		const analysis = analysisStore.current;
		if (!analysis?.id) return;
		const analysisPipeline = buildAnalysisPipelinePayload(
			analysis.id,
			analysisStore.tabs,
			datasourceStore.datasources
		);
		if (!analysisPipeline) return;
		const controller = startSchemaRequest();
		const pipelineHash = hashPipeline(applySteps(analysisStore.pipeline));
		getStepSchema(
			{
				analysis_id: analysis.id,
				analysis_pipeline: analysisPipeline,
				tab_id: analysisStore.activeTab?.id ?? null,
				target_step_id: stepId
			},
			{ signal: controller.signal }
		)
			.map((response: StepSchemaResponse) => {
				throwIfAborted(controller.signal);
				schemaStore.syncPreviewSchema(stepId, response, pipelineHash);
			})
			.mapErr((error: unknown) => {
				if (controller.signal.aborted) return;
				const err = error instanceof Error ? error.message : String(error);
				track({
					event: 'schema_error',
					action: 'apply_schema_refresh',
					target: stepId,
					meta: { message: err }
				});
			});
	}

	function handleCancelConfig() {
		if (readOnly) return;
		if (!step) return;
		draftConfig = cloneConfig(step.config as Record<string, unknown>);
	}

	onDestroy(() => {
		schemaAbortController?.abort();
	});
</script>

{#if step === null}
	<div
		class={[
			'step-config',
			css({
				boxSizing: 'border-box',
				display: 'flex',
				height: '100%',
				minHeight: '0',
				width: 'full',
				flexDirection: 'column',
				alignItems: 'center',
				justifyContent: 'center',
				overflowY: 'auto',
				backgroundColor: 'bg.primary',
				color: 'fg.primary'
			})
		]}
	>
		<div
			class={css({
				display: 'flex',
				flexDirection: 'column',
				alignItems: 'center',
				justifyContent: 'center',
				padding: '10',
				textAlign: 'center',
				color: 'fg.muted'
			})}
		>
			<div class={css({ marginBottom: '6', opacity: '0.3' })}><Settings2 size={40} /></div>
			<h3 class={css({ margin: '0', marginBottom: '3', fontSize: 'md', color: 'fg.primary' })}>
				No step selected
			</h3>
			<p class={css({ margin: '0', fontSize: 'xs', color: 'fg.muted' })}>
				Click on a pipeline step to configure it
			</p>
		</div>
	</div>
{:else}
	<div
		class={[
			'step-config',
			css({
				boxSizing: 'border-box',
				display: 'flex',
				height: '100%',
				minHeight: '0',
				width: 'full',
				flexDirection: 'column',
				overflowY: 'auto',
				backgroundColor: 'bg.primary',
				color: 'fg.primary'
			})
		]}
		data-step-config={step.type}
	>
		<PanelHeader>
			{#snippet title()}{stepLabel}{/snippet}
			{#snippet actions()}
				<button
					class={css({
						display: 'flex',
						height: 'row',
						width: 'row',
						cursor: 'pointer',
						alignItems: 'center',
						justifyContent: 'center',
						borderWidth: '0',
						backgroundColor: 'transparent',
						padding: '0',
						lineHeight: 'none',
						color: 'fg.muted',
						_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
					})}
					onclick={() => onClose?.()}
					type="button"
					title="Close"
				>
					<X size={14} />
				</button>
			{/snippet}
		</PanelHeader>

		<div
			class={css({
				flex: '1',
				overflowY: 'auto',
				backgroundColor: 'bg.primary',
				padding: '5'
			})}
		>
			{#if !draftReady}
				<div
					class={css({
						display: 'flex',
						flexDirection: 'column',
						alignItems: 'center',
						justifyContent: 'center',
						gap: '4',
						backgroundColor: 'bg.primary',
						padding: '10',
						textAlign: 'center',
						color: 'fg.tertiary'
					})}
				>
					<div class={spinner({ size: 'md' })}></div>
					<p class={css({ margin: '0', fontSize: 'xs' })}>Initializing config...</p>
				</div>
			{:else if !schema && !isLoadingSchema}
				<Callout tone="warn">
					<p>Schema not available. Please ensure the data source is loaded.</p>
					<button
						class={button({ variant: 'ghost', size: 'sm' })}
						onclick={() => onClose?.()}
						type="button">Close</button
					>
				</Callout>
			{:else if waitingForSelectedStepSchema}
				<div
					class={css({
						display: 'flex',
						flexDirection: 'column',
						alignItems: 'center',
						justifyContent: 'center',
						gap: '4',
						backgroundColor: 'bg.primary',
						padding: '10',
						textAlign: 'center',
						color: 'fg.tertiary'
					})}
				>
					<div class={spinner({ size: 'md' })}></div>
					<p class={css({ margin: '0', fontSize: 'xs' })}>Loading schema...</p>
				</div>
			{:else if readOnly}
				<div class={css({ display: 'flex', flexDirection: 'column', gap: '3' })}>
					<Callout tone="warn">This analysis is locked. Step configuration is read-only.</Callout>
					<pre
						class={css({
							margin: '0',
							overflowX: 'auto',
							borderWidth: '1',
							backgroundColor: 'bg.secondary',
							padding: '3',
							fontSize: 'xs',
							color: 'fg.primary'
						})}>
{readOnlyConfigJson}</pre>
				</div>
			{:else if step.type === 'filter'}
				<FilterConfig schema={inputSchema} bind:config={draftConfig} />
			{:else if step.type === 'select'}
				<SelectConfig schema={inputSchema} bind:config={draftConfig} />
			{:else if step.type === 'groupby'}
				<GroupByConfig schema={inputSchema} bind:config={draftConfig} />
			{:else if step.type === 'sort'}
				<SortConfig schema={inputSchema} bind:config={draftConfig} />
			{:else if step.type === 'rename'}
				<RenameConfig schema={inputSchema} bind:config={draftConfig} />
			{:else if step.type === 'drop'}
				<DropConfig schema={inputSchema} bind:config={draftConfig} />
			{:else if step.type === 'join'}
				<JoinConfig schema={inputSchema} bind:config={draftConfig} />
			{:else if step.type === 'expression'}
				<ExpressionConfig schema={inputSchema} bind:config={draftConfig} />
			{:else if step.type === 'with_columns'}
				<WithColumnsConfig schema={inputSchema} bind:config={draftConfig} />
			{:else if step.type === 'deduplicate'}
				<DeduplicateConfig schema={inputSchema} bind:config={draftConfig} />
			{:else if step.type === 'fill_null'}
				<FillNullConfig schema={inputSchema} bind:config={draftConfig} />
			{:else if step.type === 'explode'}
				<ExplodeConfig schema={inputSchema} bind:config={draftConfig} />
			{:else if step.type === 'pivot'}
				<PivotConfig
					schema={inputSchema}
					bind:config={draftConfig}
					onRefreshSchema={handleRefreshPivotSchema}
					isRefreshing={fetchingPivotSchema}
				/>
			{:else if step.type === 'timeseries'}
				<TimeSeriesConfig schema={inputSchema} bind:config={draftConfig} />
			{:else if step.type === 'string_transform'}
				<StringMethodsConfig schema={inputSchema} bind:config={draftConfig} />
			{:else if step.type === 'view'}
				<ViewConfig schema={inputSchema} bind:config={draftConfig} />
			{:else if step.type === 'download'}
				<DownloadConfig bind:config={draftConfig} />
			{:else if step.type === 'datasource'}
				<div class={css({ backgroundColor: 'bg.primary', padding: '10', textAlign: 'center' })}>
					<p class={css({ margin: '0', fontSize: 'xs', color: 'fg.muted' })}>
						Datasource options are set during upload.
					</p>
				</div>
			{:else if step.type === 'sample'}
				<SampleConfig bind:config={draftConfig} />
			{:else if step.type === 'limit'}
				<LimitConfig bind:config={draftConfig} />
			{:else if step.type === 'topk'}
				<TopKConfig schema={inputSchema} bind:config={draftConfig} />
			{:else if step.type === 'unpivot'}
				<UnpivotConfig schema={inputSchema} bind:config={draftConfig} />
			{:else if step.type === 'union_by_name'}
				<UnionByNameConfig schema={inputSchema} bind:config={draftConfig} />
			{:else if step.type === 'chart'}
				<PlotConfig schema={inputSchema} bind:config={draftConfig} />
			{:else if step.type === 'notification'}
				<NotificationConfig schema={inputSchema} bind:config={draftConfig} {configFlags} />
			{:else if step.type === 'ai'}
				<AIConfig schema={inputSchema} bind:config={draftConfig} />
			{:else}
				<div class={css({ backgroundColor: 'bg.primary', padding: '10', textAlign: 'center' })}>
					<p class={css({ margin: '0', marginBottom: '4', fontSize: 'xs', color: 'fg.muted' })}>
						Configuration for {step.type} is not yet implemented
					</p>
					<button
						class={css({
							cursor: 'pointer',
							borderWidth: '1',
							backgroundColor: 'transparent',
							paddingX: '5',
							paddingY: '2',
							fontFamily: 'mono',
							fontSize: 'xs',
							color: 'fg.secondary',
							_hover: { backgroundColor: 'bg.hover' }
						})}
						onclick={() => onClose?.()}
						type="button">Close</button
					>
				</div>
			{/if}
		</div>
		{#if !readOnly}
			<PanelFooter>
				<button
					class={css({
						flex: '1',
						cursor: 'pointer',
						borderWidth: '1',
						backgroundColor: 'transparent',
						paddingX: '4',
						paddingY: '2.5',
						fontFamily: 'mono',
						fontSize: 'xs',
						fontWeight: 'semibold',
						textTransform: 'uppercase',
						letterSpacing: 'wider',
						color: 'fg.secondary',
						_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' },
						_disabled: { cursor: 'not-allowed', opacity: '0.4' }
					})}
					onclick={handleCancelConfig}
					disabled={!hasChanges}
					title={hasChanges ? 'Discard edits in this step' : 'No edits to discard'}
					type="button"
				>
					Cancel
				</button>
				<button
					class={css({
						flex: '1',
						cursor: 'pointer',
						borderWidth: '1',
						backgroundColor: 'bg.accent',
						paddingX: '4',
						paddingY: '2.5',
						fontFamily: 'mono',
						fontSize: 'xs',
						fontWeight: 'semibold',
						textTransform: 'uppercase',
						letterSpacing: 'wider',
						color: 'accent.primary',
						_hover: { opacity: '0.9' },
						_disabled: {
							cursor: 'not-allowed',
							opacity: '1',
							backgroundColor: 'bg.muted',
							color: 'fg.muted'
						}
					})}
					onclick={handleApplyConfig}
					disabled={!canApply}
					title={applyBlockedBecause ??
						(hasChanges ? 'Apply configuration' : 'No changes to apply')}
					type="button"
				>
					Apply
				</button>
			</PanelFooter>
		{/if}
	</div>
{/if}
