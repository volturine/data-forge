<script lang="ts">
	import type { PipelineStep } from '$lib/types/analysis';
	import { drag, type DropTarget } from '$lib/stores/drag.svelte';
	import InlineDataTable from '$lib/components/viewers/InlineDataTable.svelte';
	import ChartPreview from '$lib/components/viewers/ChartPreview.svelte';
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
	let stepConfig = $derived(getStepTypeConfig(step.type));
	let Icon = $derived(stepConfig.icon);
	let label = $derived(stepConfig.label);
	let summary = $derived(stepConfig.summary(step.config as Record<string, unknown>));
	let isApplied = $derived((step as PipelineStep & { is_applied?: boolean }).is_applied !== false);

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
	let isOtherDragging = $derived(drag.active && drag.stepId !== step.id);

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
	class="step-node relative w-[65%]"
	class:view-node={step.type === 'view'}
	class:opacity-40={isDragging}
	class:grayscale-50={isDragging}
	class:drag-target={isOtherDragging}
>
	<div class="absolute left-1/2 -top-1 z-2 h-2 w-2 -translate-x-1/2 border-2 connector-dot"></div>

	<div class="step-content card-base border p-4 hover:border-tertiary" role="listitem">
		<div class="mb-3 flex items-center gap-2">
			<!-- Drag handle (6-dot grip) -->
			<button
				class="drag-handle flex shrink-0 cursor-grab items-center justify-center border-none bg-transparent p-1 opacity-40 select-none text-fg-muted hover:opacity-100 hover:bg-hover active:cursor-grabbing"
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
				<GripVertical size={16} />
			</button>

			<Icon size={14} class="shrink-0" />
			<span class="flex-1 text-sm font-semibold">{label}</span>
			<span class="shrink-0 text-xs text-fg-muted">#{index + 1}</span>
		</div>

		<div
			class="step-summary mb-3 px-3 py-2 text-xs bg-tertiary text-fg-tertiary"
			class:inactive={!isApplied}
		>
			{summary}
		</div>

		<div class="flex gap-2">
			<button
				class="action-btn flex-1 cursor-pointer border border-tertiary bg-transparent p-2 font-medium uppercase tracking-widest text-[0.625rem] text-fg-secondary hover:bg-hover hover:text-fg-primary"
				class:inactive={!isApplied}
				onclick={() => onToggleApply(step.id)}
				type="button"
				title={isApplied ? 'Disable step' : 'Enable step'}
			>
				{isApplied ? 'disable' : 'enable'}
			</button>
			<button
				class="action-btn flex-1 cursor-pointer border border-tertiary bg-transparent p-2 text-xs font-medium text-fg-secondary hover:bg-hover hover:text-fg-primary"
				onclick={() => onEdit(step.id)}
				type="button"
			>
				edit
			</button>
			<button
				class="action-btn danger flex-1 cursor-pointer border border-tertiary bg-transparent p-2 text-xs font-medium text-fg-secondary hover:bg-error hover:border-error hover:text-error"
				onclick={() => onDelete(step.id)}
				type="button"
			>
				delete
			</button>
		</div>

		{#if step.type === 'view' && datasourceId && analysisId}
			<div class="mt-3 border-t border-tertiary pt-3">
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
			<div class="mt-3 border-t border-tertiary pt-3">
				{#if !isApplied}
					<div
						class="chart-placeholder flex h-50 items-center justify-center text-xs text-fg-muted"
					>
						<Icon size={16} class="mr-2" />
						{#if ((step.config?.x_column as string | undefined) ?? '') === ''}
							<span>Configure chart to preview</span>
						{:else}
							<span>Apply to preview</span>
						{/if}
					</div>
				{:else if chartQuery.isFetching}
					<div class="flex items-center justify-center gap-2 py-4 text-xs text-fg-muted">
						<span class="spinner spinner-sm"></span>
						Loading chart...
					</div>
				{:else if chartQuery.error}
					<div class="border border-error bg-error p-2 text-xs text-error">
						{chartQuery.error.message}
					</div>
				{:else if chartQuery.data}
					<ChartPreview
						data={chartQuery.data.data}
						chartType={(step.config.chart_type as
							| 'bar'
							| 'line'
							| 'pie'
							| 'histogram'
							| 'scatter'
							| 'boxplot') ?? 'bar'}
						config={step.config}
					/>
				{/if}
			</div>
		{/if}

		<div class="mt-3 border-t border-tertiary pt-3">
			{#if rowCount !== null}
				{#key `${rowCountKey}:${rowCount}`}
					<span class="flex items-center gap-1 text-xs text-fg-muted">
						<Hash size={10} />
						{rowCountLabel}
					</span>
				{/key}
			{:else}
				<button
					class="calc-rows-btn flex cursor-pointer items-center gap-1 border border-tertiary bg-secondary text-fg-muted px-2 py-0.5 text-[10px] disabled:cursor-not-allowed disabled:opacity-70 hover:border-tertiary hover:text-fg-primary"
					onclick={calculateRowCount}
					disabled={isLoadingRowCount}
					type="button"
					aria-label="Calculate row count"
				>
					{#if isLoadingRowCount}
						<RefreshCw size={10} class="spinning" />
						<span>counting...</span>
					{:else}
						<Hash size={10} />
						<span>count rows</span>
					{/if}
				</button>
			{/if}
		</div>
		{#if rowCountError}
			<div class="mt-2 border border-error bg-error p-2 text-xs text-error">
				{rowCountError}
			</div>
		{/if}
	</div>

	<div
		class="absolute left-1/2 -bottom-1 z-2 h-2 w-2 -translate-x-1/2 border-2 connector-dot"
	></div>
</div>
