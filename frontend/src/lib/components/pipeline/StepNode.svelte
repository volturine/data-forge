<script lang="ts">
	import type { PipelineStep } from '$lib/types/analysis';
	import { drag, type DropTarget } from '$lib/stores/drag.svelte';
	import InlineDataTable from '$lib/components/pipeline/InlineDataTable.svelte';
	import ChartPreview from '$lib/components/pipeline/ChartPreview.svelte';
	import { createQuery } from '@tanstack/svelte-query';
	import {
		previewStepData,
		getStepRowCount,
		type StepPreviewRequest,
		type StepPreviewResponse,
		type StepRowCountRequest
	} from '$lib/api/compute';
	import { applySteps } from '$lib/utils/pipeline';
	import { hashPipeline } from '$lib/utils/hash';
	import { GripVertical, Hash, RefreshCw } from 'lucide-svelte';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { getStepTypeConfig } from '$lib/components/pipeline/utils';
	import {
		buildAnalysisPipelinePayload,
		buildDatasourceConfig
	} from '$lib/utils/analysis-pipeline';
	import { SvelteMap } from 'svelte/reactivity';

	interface Props {
		step: PipelineStep;
		index: number;
		analysisId?: string;
		datasourceId?: string;
		allSteps?: PipelineStep[];
		onEdit: (id: string) => void;
		onDelete: (id: string) => void;
		onToggleApply: (id: string) => void;
		onTouchMove: (stepId: string, target: DropTarget) => void;
	}

	let {
		step,
		index,
		analysisId,
		datasourceId,
		allSteps = [],
		onEdit,
		onDelete,
		onToggleApply,
		onTouchMove
	}: Props = $props();

	const isChart = $derived(
		step.type === 'chart' || step.type === 'plot' || step.type.startsWith('plot_')
	);

	// Derived values from declarative config
	const stepConfig = $derived(getStepTypeConfig(step.type));
	const Icon = $derived(stepConfig.icon);
	const label = $derived(stepConfig.label);
	const summary = $derived(stepConfig.summary(step.config as Record<string, unknown>));
	const isApplied = $derived(
		(step as PipelineStep & { is_applied?: boolean }).is_applied !== false
	);

	// Chart preview query (only for chart/plot steps) — run after apply
	const chartPipeline = $derived(applySteps(allSteps));
	const chartPipelineKey = $derived(hashPipeline(chartPipeline));
	const chartDatasourceConfig = $derived.by(() => {
		if (!isChart) return {};
		return (
			buildDatasourceConfig({
				analysisId: analysisId ?? null,
				tab: analysisStore.activeTab ?? null,
				tabs: analysisStore.tabs,
				datasources: datasourceStore.datasources
			}) ??
			analysisStore.activeTab?.datasource_config ??
			{}
		);
	});
	const analysisPipeline = $derived.by(() => {
		if (!analysisId) return null;
		return buildAnalysisPipelinePayload(
			analysisId,
			analysisStore.tabs,
			datasourceStore.datasources
		);
	});

	const chartQuery = createQuery(() => ({
		queryKey: [
			'chart-preview',
			analysisId,
			datasourceId,
			step.id,
			chartPipelineKey,
			JSON.stringify(chartDatasourceConfig)
		],
		queryFn: async (): Promise<StepPreviewResponse> => {
			const resourceConfig = analysisStore.resourceConfig as unknown as Record<
				string,
				unknown
			> | null;
			const result = await previewStepData({
				analysis_pipeline: analysisPipeline,
				tab_id: analysisStore.activeTab?.id ?? null,
				target_step_id: step.id,
				row_limit: 5000,
				page: 1,
				resource_config: resourceConfig,
				datasource_config: chartDatasourceConfig
			} as unknown as StepPreviewRequest);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		staleTime: Infinity,
		gcTime: Infinity,
		refetchOnMount: false,
		enabled:
			isChart &&
			isApplied &&
			!!datasourceId &&
			!!analysisId &&
			!!analysisPipeline &&
			((step.config?.x_column as string | undefined) ?? '') !== ''
	}));

	const rowCounts = new SvelteMap<string, number>();
	const rowCountLoads = new SvelteMap<string, boolean>();
	const rowCountErrors = new SvelteMap<string, string>();

	const rowCountPipeline = $derived.by(() => applySteps(allSteps));
	const rowCountPipelineKey = $derived.by(() => hashPipeline(rowCountPipeline));
	const rowCountDatasourceConfig = $derived.by(() => {
		return (
			buildDatasourceConfig({
				analysisId: analysisId ?? null,
				tab: analysisStore.activeTab ?? null,
				tabs: analysisStore.tabs,
				datasources: datasourceStore.datasources
			}) ??
			analysisStore.activeTab?.datasource_config ??
			{}
		);
	});
	const rowCountKey = $derived.by(() => {
		const configKey = JSON.stringify(rowCountDatasourceConfig ?? {});
		return `${analysisId ?? ''}:${datasourceId ?? ''}:${step.id}:${rowCountPipelineKey}:${configKey}`;
	});
	const rowCount = $derived.by(() => rowCounts.get(rowCountKey) ?? null);
	const isLoadingRowCount = $derived.by(() => rowCountLoads.get(rowCountKey) ?? false);
	const rowCountError = $derived.by(() => rowCountErrors.get(rowCountKey) ?? null);
	const rowCountLabel = $derived.by(() => {
		if (rowCount === null) return '';
		return `${rowCount.toLocaleString()} rows`;
	});

	async function calculateRowCount() {
		if (!analysisId || !datasourceId) return;
		if (!analysisPipeline) return;
		if (isLoadingRowCount) return;
		rowCountLoads.set(rowCountKey, true);
		rowCountErrors.delete(rowCountKey);
		const result = await getStepRowCount({
			analysis_pipeline: analysisPipeline,
			tab_id: analysisStore.activeTab?.id ?? null,
			target_step_id: step.id,
			datasource_config: rowCountDatasourceConfig
		} as StepRowCountRequest);
		rowCountLoads.set(rowCountKey, false);
		if (result.isErr()) {
			rowCountErrors.set(rowCountKey, result.error.message);
			return;
		}
		rowCounts.set(rowCountKey, result.value.row_count);
		rowCountErrors.delete(rowCountKey);
	}

	let dragging = $state(false);
	let clickConsumed = $state(false);
	let longPressTimer = $state<number | null>(null);
	let pointerStartX = $state<number | null>(null);
	let pointerStartY = $state<number | null>(null);

	const longPressDelay = 180;
	const dragThreshold = 8;

	// Is this node being dragged?
	let isDragging = $state(false);

	// Is another node being dragged (not this one)?
	const isOtherDragging = $derived(drag.active && drag.stepId !== step.id);

	function handleClick(event: MouseEvent) {
		if (!clickConsumed) return;
		event.preventDefault();
		event.stopPropagation();
		clickConsumed = false;
	}

	function startDrag(event: PointerEvent) {
		const target = event.currentTarget as HTMLElement | null;
		const handle = target?.closest('[data-drag-handle]');
		if (!handle) return;

		pointerStartX = event.clientX;
		pointerStartY = event.clientY;

		// For touch inputs, require long press to prevent accidental drags
		if (event.pointerType === 'touch') {
			longPressTimer = window.setTimeout(() => {
				initiateDrag(event);
			}, longPressDelay);
		} else {
			// For mouse/trackpad, start drag immediately
			initiateDrag(event);
		}
	}

	function initiateDrag(event: PointerEvent) {
		dragging = true;
		clickConsumed = true;
		isDragging = true;
		if (event.cancelable) {
			event.preventDefault();
		}
		drag.startMove(step.id, step.type, event.pointerId, event.clientX, event.clientY);
		if (event.currentTarget instanceof HTMLElement) {
			event.currentTarget.setPointerCapture(event.pointerId);
			drag.setCapturedElement(event.currentTarget, event.pointerId);
		}
	}

	function cancelLongPress() {
		if (longPressTimer !== null) window.clearTimeout(longPressTimer);
		longPressTimer = null;
		pointerStartX = null;
		pointerStartY = null;
	}

	function handlePointerMove(event: PointerEvent) {
		// If we haven't started dragging yet, check if pointer moved too much (cancel long press)
		if (pointerStartX !== null && pointerStartY !== null && !dragging) {
			const deltaX = Math.abs(event.clientX - pointerStartX);
			const deltaY = Math.abs(event.clientY - pointerStartY);
			const moved = deltaX > dragThreshold || deltaY > dragThreshold;
			if (moved) {
				cancelLongPress();
				return;
			}
		}

		// If we're dragging, update pointer position
		if (!dragging) return;
		drag.setPointer(event.clientX, event.clientY);
		event.preventDefault();
	}

	function finishDrag(): void {
		if (dragging && drag.active) {
			if (drag.target && drag.stepId && drag.valid) {
				onTouchMove(drag.stepId, drag.target);
			}
			drag.end();
		}
		const wasDragging = dragging;
		dragging = false;
		clickConsumed = wasDragging;
		isDragging = false;
		cancelLongPress();
	}
</script>

<div
	class="step-node relative w-[60%]"
	class:view-node={step.type === 'view'}
	class:opacity-40={isDragging}
	class:grayscale-50={isDragging}
	class:drag-target={isOtherDragging}
>
	<div class="absolute left-1/2 -top-1 z-2 h-2 w-2 -translate-x-1/2 border-2 connector-dot"></div>

	<div class="step-content card-base border hover:border-tertiary" role="listitem">
		<div class="flex items-center gap-2 px-4 py-3 border-b border-tertiary">
			<button
				class="drag-handle flex shrink-0 cursor-grab items-center justify-center border-none bg-transparent p-0.5 opacity-30 select-none text-fg-muted hover:opacity-100 hover:bg-hover active:cursor-grabbing"
				class:dragging
				title="Drag to reorder"
				type="button"
				onpointerdown={startDrag}
				onpointermove={handlePointerMove}
				onpointerup={finishDrag}
				onpointercancel={finishDrag}
				onclick={handleClick}
				data-drag-handle="true"
			>
				<GripVertical size={14} />
			</button>

			<Icon size={13} class="shrink-0 text-fg-muted" />
			<span class="flex-1 text-xs font-semibold uppercase tracking-wide">{label}</span>
			<span class="shrink-0 text-[0.625rem] text-fg-faint">#{index + 1}</span>
		</div>

		<div class="px-4 py-3">
			<div
				class="step-summary px-3 py-2 text-[0.6875rem] bg-secondary text-fg-tertiary leading-relaxed"
				class:inactive={!isApplied}
			>
				{summary}
			</div>
		</div>

		<div class="flex gap-0 border-t border-tertiary">
			<button
				class="action-btn flex-1 cursor-pointer border-none bg-transparent py-2.5 font-medium uppercase tracking-widest text-[0.5625rem] text-fg-muted hover:bg-hover hover:text-fg-primary"
				class:inactive={!isApplied}
				onclick={() => onToggleApply(step.id)}
				type="button"
				title={isApplied ? 'Disable step' : 'Enable step'}
			>
				{isApplied ? 'disable' : 'enable'}
			</button>
			<div class="w-px bg-border-primary shrink-0"></div>
			<button
				class="action-btn flex-1 cursor-pointer border-none bg-transparent py-2.5 text-[0.5625rem] font-medium uppercase tracking-widest text-fg-muted hover:bg-hover hover:text-fg-primary"
				onclick={() => onEdit(step.id)}
				type="button"
			>
				edit
			</button>
			<div class="w-px bg-border-primary shrink-0"></div>
			<button
				class="action-btn danger flex-1 cursor-pointer border-none bg-transparent py-2.5 text-[0.5625rem] font-medium uppercase tracking-widest text-fg-muted hover:bg-error hover:text-error"
				onclick={() => onDelete(step.id)}
				type="button"
			>
				delete
			</button>
		</div>

		{#if step.type === 'view' && datasourceId && analysisId}
			<div class="border-t border-tertiary">
				<InlineDataTable
					{analysisId}
					{datasourceId}
					pipeline={allSteps}
					stepId={step.id}
					rowLimit={typeof step.config?.rowLimit === 'number' ? step.config.rowLimit : 100}
				/>
			</div>
		{/if}

		{#if isChart && datasourceId && analysisId}
			<div class="border-t border-tertiary">
				{#if !isApplied}
					<div
						class="chart-placeholder flex h-75 items-center justify-center text-[0.6875rem] text-fg-muted"
					>
						<Icon size={14} class="mr-2" />
						{#if ((step.config?.x_column as string | undefined) ?? '') === ''}
							<span>Configure chart to preview</span>
						{:else}
							<span>Apply to preview</span>
						{/if}
					</div>
				{:else if chartQuery.isFetching}
					<div class="flex items-center justify-center gap-2 py-5 text-[0.6875rem] text-fg-muted">
						<span class="spinner spinner-sm"></span>
						Loading chart...
					</div>
				{:else if chartQuery.error}
					<div class="border-t border-error bg-error p-3 text-xs text-error">
						{chartQuery.error.message}
					</div>
				{:else if chartQuery.data}
					<ChartPreview
						data={chartQuery.data.data}
						chartType={(step.config.chart_type as
							| 'bar'
							| 'horizontal_bar'
							| 'area'
							| 'heatgrid'
							| 'line'
							| 'pie'
							| 'histogram'
							| 'scatter'
							| 'boxplot') ?? 'bar'}
						config={step.config}
						metadata={chartQuery.data.metadata}
					/>
				{/if}
			</div>
		{/if}

		<div class="flex items-center px-4 py-2.5 border-t border-tertiary">
			{#if rowCount !== null}
				{#key `${rowCountKey}:${rowCount}`}
					<span class="flex items-center gap-1 text-[0.625rem] text-fg-faint">
						<Hash size={9} />
						{rowCountLabel}
					</span>
				{/key}
			{:else}
				<button
					class="calc-rows-btn flex cursor-pointer items-center gap-1 border border-tertiary bg-transparent text-fg-muted px-2 py-0.5 text-[0.5625rem] disabled:cursor-not-allowed disabled:opacity-70 hover:bg-hover hover:text-fg-primary"
					onclick={calculateRowCount}
					disabled={isLoadingRowCount}
					type="button"
					aria-label="Calculate row count"
				>
					{#if isLoadingRowCount}
						<RefreshCw size={9} class="spinning" />
						<span>counting...</span>
					{:else}
						<Hash size={9} />
						<span>count rows</span>
					{/if}
				</button>
			{/if}
		</div>
		{#if rowCountError}
			<div class="border-t border-error bg-error px-4 py-2 text-xs text-error">
				{rowCountError}
			</div>
		{/if}
	</div>

	<div
		class="absolute left-1/2 -bottom-1 z-2 h-2 w-2 -translate-x-1/2 border-2 connector-dot"
	></div>
</div>
