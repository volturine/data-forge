<script lang="ts">
	import type { PipelineStep } from '$lib/types/analysis';
	import { drag, type DropTarget } from '$lib/stores/drag.svelte';
	import InlineDataTable from '$lib/components/viewers/InlineDataTable.svelte';
	import { Download, GripVertical } from 'lucide-svelte';
	import { exportData, downloadBlob, type ExportRequest } from '$lib/api/compute';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { getStepTypeConfig } from '$lib/components/pipeline/utils';

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

	let isExporting = $state(false);
	let exportError = $state<string | null>(null);
	let exportSuccess = $state<string | null>(null);

	let dragging = $state(false);
	let clickConsumed = $state(false);
	let longPressTimer = $state<number | null>(null);
	let pointerStartX = $state<number | null>(null);
	let pointerStartY = $state<number | null>(null);

	const longPressDelay = 180;
	const dragThreshold = 8;

	// Derived values from declarative config
	let stepConfig = $derived(getStepTypeConfig(step.type));
	let Icon = $derived(stepConfig.icon);
	let label = $derived(stepConfig.typeLabel);
	let summary = $derived(stepConfig.summary(step.config as Record<string, unknown>));
	let isApplied = $derived((step as PipelineStep & { is_applied?: boolean }).is_applied !== false);

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

	async function handleExport() {
		if (!datasourceId || isExporting) return;

		isExporting = true;
		exportError = null;
		exportSuccess = null;

		const format = (step.config.format as string) || 'csv';
		const filename = (step.config.filename as string) || 'export';
		const request = {
			analysis_id: analysisId,
			datasource_id: datasourceId,
			pipeline_steps: allSteps.map((s) => ({
				id: s.id,
				type: s.type,
				config: s.config,
				depends_on: s.depends_on
			})),
			target_step_id: step.id,
			format: format as ExportRequest['format'],
			filename,
			destination: 'download',
			datasource_config: analysisStore.activeTab?.datasource_config ?? null
		} as ExportRequest;

		exportData(request).match(
			(result) => {
				if (result instanceof Blob) {
					const ext =
						format === 'csv'
							? '.csv'
							: format === 'parquet'
								? '.parquet'
								: format === 'ndjson'
									? '.ndjson'
									: format === 'duckdb'
										? '.duckdb'
										: '.json';
					downloadBlob(result, `${filename}${ext}`);
					exportSuccess = `Downloaded ${filename}${ext}`;
				}
				isExporting = false;
			},
			(err) => {
				exportError = err.message;
				isExporting = false;
			}
		);
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

		{#if step.type === 'export' && datasourceId}
			<div class="mt-3 border-t border-tertiary pt-3">
				{#if exportError}
					<div class="mb-2 border border-error bg-error p-2 text-xs text-error">
						{exportError}
					</div>
				{/if}
				{#if exportSuccess}
					<div class="mb-2 border border-success bg-success-bg p-2 text-xs text-success-fg">
						{exportSuccess}
					</div>
				{/if}
				<button
					class="export-btn flex w-full cursor-pointer items-center justify-center gap-2 border-none px-3 py-2 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50 bg-accent text-bg-primary hover:opacity-90 hover:enabled:opacity-90"
					onclick={handleExport}
					disabled={isExporting}
					type="button"
				>
					{#if isExporting}
						<span class="spinner spinner-sm"></span>
						Exporting...
					{:else}
						<Download size={14} />
						Download
					{/if}
				</button>
			</div>
		{/if}

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
	</div>

	<div
		class="absolute left-1/2 -bottom-1 z-2 h-2 w-2 -translate-x-1/2 border-2 connector-dot"
	></div>
</div>
