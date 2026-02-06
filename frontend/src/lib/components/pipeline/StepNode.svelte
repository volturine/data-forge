<script lang="ts">
	import type { PipelineStep } from '$lib/types/analysis';
	import { drag, type DropTarget } from '$lib/stores/drag.svelte';
	import InlineDataTable from '$lib/components/viewers/InlineDataTable.svelte';
	import { Download, Save } from 'lucide-svelte';
	import { exportData, downloadBlob, type ExportRequest } from '$lib/api/compute';
	import { defaultStepType, stepTypes } from '$lib/components/pipeline/utils';

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

	let dragging = $state(false);
	let clickConsumed = $state(false);
	let longPressTimer = $state<number | null>(null);
	let pointerStartX = $state<number | null>(null);
	let pointerStartY = $state<number | null>(null);

	const longPressDelay = 180;
	const dragThreshold = 8;

	// Derived values from declarative config
	let stepConfig = $derived(stepTypes[step.type] || defaultStepType);
	let currentStepInfo = $derived({ label: stepConfig.label, icon: stepConfig.icon });
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

		const format = (step.config.format as string) || 'csv';
		const filename = (step.config.filename as string) || 'export';
		const destination = (step.config.destination as string) || 'filesystem';

		const request: ExportRequest = {
			analysis_id: analysisId,
			datasource_id: datasourceId,
			pipeline_steps: allSteps.map((s) => ({
				id: s.id,
				type: s.type,
				config: s.config,
				depends_on: s.depends_on
			})),
			target_step_id: step.id,
			format: format as 'csv' | 'parquet' | 'json',
			filename,
			destination: destination as 'download' | 'filesystem'
		};

		exportData(request).match(
			(result) => {
				if (destination === 'download' && result instanceof Blob) {
					const ext = format === 'csv' ? '.csv' : format === 'parquet' ? '.parquet' : '.json';
					downloadBlob(result, `${filename}${ext}`);
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
	class:greyed-out={isDragging}
	class:drag-target={isOtherDragging}
>
	<div
		class="absolute left-1/2 -top-1 z-[2] h-2 w-2 -translate-x-1/2 rounded-full"
		style="background-color: var(--fg-muted); border: 2px solid var(--bg-primary);"
	></div>

	<div
		class="step-content rounded-sm border p-4 transition-all"
		role="listitem"
		style="background-color: var(--bg-primary); border-color: var(--border-primary); box-shadow: var(--card-shadow);"
	>
		<div class="mb-3 flex items-center gap-2">
			<!-- Drag handle (6-dot grip) -->
			<button
				class="drag-handle flex shrink-0 cursor-grab items-center justify-center rounded-sm border-none bg-transparent p-1 opacity-40 transition-all select-none"
				class:dragging
				title="Drag to reorder"
				type="button"
				onpointerdown={startDrag}
				onpointermove={handlePointerMove}
				onpointerup={finishDrag}
				onpointercancel={finishDrag}
				onclick={handleClick}
				data-drag-handle="true"
				style="color: var(--fg-muted);"
			>
				<svg width="10" height="16" viewBox="0 0 10 16" fill="currentColor">
					<circle cx="2" cy="2" r="1.5" />
					<circle cx="8" cy="2" r="1.5" />
					<circle cx="2" cy="8" r="1.5" />
					<circle cx="8" cy="8" r="1.5" />
					<circle cx="2" cy="14" r="1.5" />
					<circle cx="8" cy="14" r="1.5" />
				</svg>
			</button>

			<span class="shrink-0 text-base">{currentStepInfo.icon}</span>
			<span class="flex-1 text-sm font-semibold">{label}</span>
			<span class="shrink-0 text-xs" style="color: var(--fg-muted);">#{index + 1}</span>
		</div>

		<div
			class="step-summary mb-3 rounded-sm px-3 py-2 text-xs"
			class:inactive={!isApplied}
			style="background-color: var(--bg-tertiary); color: var(--fg-tertiary);"
		>
			{summary}
		</div>

		<div class="flex gap-2">
			<button
				class="action-btn flex-1 cursor-pointer rounded-sm border bg-transparent p-2 text-xs font-medium uppercase tracking-widest transition-all"
				class:inactive={!isApplied}
				onclick={() => onToggleApply(step.id)}
				type="button"
				title={isApplied ? 'Disable step' : 'Enable step'}
				style="border-color: var(--border-primary); color: var(--fg-secondary); font-size: 0.625rem;"
			>
				{isApplied ? 'disable' : 'enable'}
			</button>
			<button
				class="action-btn flex-1 cursor-pointer rounded-sm border bg-transparent p-2 text-xs font-medium transition-all"
				onclick={() => onEdit(step.id)}
				type="button"
				style="border-color: var(--border-primary); color: var(--fg-secondary);"
			>
				edit
			</button>
			<button
				class="action-btn danger flex-1 cursor-pointer rounded-sm border bg-transparent p-2 text-xs font-medium transition-all"
				onclick={() => onDelete(step.id)}
				type="button"
				style="border-color: var(--border-primary); color: var(--fg-secondary);"
			>
				delete
			</button>
		</div>

		{#if step.type === 'export' && datasourceId}
			<div class="mt-3 border-t pt-3" style="border-color: var(--border-primary);">
				{#if exportError}
					<div
						class="mb-2 rounded-sm border p-2 text-xs"
						style="background-color: var(--error-bg); color: var(--error-fg); border-color: var(--error-border);"
					>
						{exportError}
					</div>
				{/if}
				<button
					class="export-btn flex w-full cursor-pointer items-center justify-center gap-2 rounded-sm border-none px-3 py-2 text-xs font-medium transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
					onclick={handleExport}
					disabled={isExporting}
					type="button"
					style="background-color: var(--accent-primary); color: var(--bg-primary);"
				>
					{#if isExporting}
						<span class="spinner spinner-sm"></span>
						Exporting...
					{:else if step.config.destination === 'download'}
						<Download size={14} />
						Download
					{:else}
						<Save size={14} />
						Save
					{/if}
				</button>
			</div>
		{/if}

		{#if step.type === 'view' && datasourceId && analysisId}
			<div class="mt-3 border-t pt-3" style="border-color: var(--border-secondary);">
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
		class="absolute left-1/2 -bottom-1 z-[2] h-2 w-2 -translate-x-1/2 rounded-full"
		style="background-color: var(--fg-muted); border: 2px solid var(--bg-primary);"
	></div>
</div>

<style>
	.step-node.view-node {
		width: 85%;
		min-width: 320px;
	}

	.step-node.greyed-out {
		opacity: 0.4;
		filter: grayscale(50%);
	}

	.step-content:hover {
		border-color: var(--border-tertiary);
		transform: translateY(-1px);
	}

	.drag-handle:hover {
		opacity: 1;
		background-color: var(--bg-hover);
	}

	.drag-handle:active {
		cursor: grabbing;
	}

	.drag-handle.dragging {
		user-select: none;
		-webkit-user-select: none;
		-webkit-touch-callout: none;
		touch-action: none;
	}

	:global(body.touch-dragging) {
		user-select: none;
		-webkit-user-select: none;
		-webkit-touch-callout: none;
	}

	.step-summary.inactive {
		background-color: var(--bg-secondary) !important;
		color: var(--fg-muted) !important;
		border: 1px dashed var(--border-primary);
	}

	.action-btn:hover {
		background-color: var(--bg-hover);
		color: var(--fg-primary);
	}

	.action-btn.inactive {
		border-style: dashed;
		color: var(--fg-muted);
	}

	.action-btn.inactive:hover {
		background-color: var(--bg-tertiary);
		color: var(--fg-secondary);
	}

	.action-btn.danger:hover {
		background-color: var(--error-bg);
		border-color: var(--error-border);
		color: var(--error-fg);
	}

	.export-btn:hover:not(:disabled) {
		opacity: 0.9;
	}

	.step-node.drag-target .step-content {
		border-style: dashed;
		border-color: var(--accent-primary);
		opacity: 0.7;
		transform: scale(0.98);
	}
</style>
