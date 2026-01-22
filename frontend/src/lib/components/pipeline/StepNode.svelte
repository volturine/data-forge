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
		savedSteps?: PipelineStep[];
		saveStatus?: 'saved' | 'unsaved' | 'saving';
		onEdit: (id: string) => void;
		onDelete: (id: string) => void;
		onTouchMove: (stepId: string, target: DropTarget) => void;
	}

	let {
		step,
		index,
		analysisId,
		datasourceId,
		allSteps = [],
		savedSteps = [],
		saveStatus = 'saved',
		onEdit,
		onDelete,
		onTouchMove
	}: Props = $props();

	let isExporting = $state(false);
	let exportError = $state<string | null>(null);

	let dragPreviewEl = $state<HTMLImageElement | null>(null);
	let touchDragging = $state(false);
	let touchConsumed = $state(false);
	let pointerStartX = $state<number | null>(null);
	let pointerStartY = $state<number | null>(null);

	const longPressDelay = 180;
	const dragThreshold = 8;

	// Throttled for touch move
	let lastTouchMoveTime = $state(0);
	const touchMoveThrottleMs = 16;

	function throttledTouchMove(event: PointerEvent) {
		const now = performance.now();
		if (now - lastTouchMoveTime < touchMoveThrottleMs) return;
		lastTouchMoveTime = now;
		if (!touchDragging) return;
		const state = drag as typeof drag & {
			setPointer: (x: number, y: number) => void;
		};
		state.setPointer(event.clientX, event.clientY);
	}

	// Derived values from declarative config
	let stepConfig = $derived(stepTypes[step.type] || defaultStepType);
	let currentStepInfo = $derived({ label: stepConfig.label, icon: stepConfig.icon });
	let label = $derived(stepConfig.typeLabel);
	let summary = $derived(stepConfig.summary(step.config as Record<string, unknown>));
	let isSavedView = $derived(
		step.type === 'view' && savedSteps.some((item) => item.id === step.id)
	);

	// Is this node being dragged?
	let isDragging = $state(false);

	// Is another node being dragged (not this one)?
	let isOtherDragging = $derived(drag.active && drag.stepId !== step.id);

	function handleDragStart(event: DragEvent) {
		if (event.dataTransfer) {
			event.dataTransfer.setData('application/x-pipeline-step', step.id);
			event.dataTransfer.setData('text/plain', step.id);
			event.dataTransfer.effectAllowed = 'move';
			if (dragPreviewEl) {
				event.dataTransfer.setDragImage(dragPreviewEl, 0, 0);
			}
		}
		requestAnimationFrame(() => {
			isDragging = true;
			drag.startMove(step.id, step.type);
		});
	}

	function handleDragEnd() {
		isDragging = false;
		if (drag.active) {
			drag.end();
		}
	}

	function handleTouchClick(event: MouseEvent) {
		if (!touchConsumed) return;
		event.preventDefault();
		event.stopPropagation();
		touchConsumed = false;
	}

	function shouldStartTouch(event: PointerEvent) {
		return event.pointerType === 'touch';
	}

	function startLongPress(event: PointerEvent) {
		if (!shouldStartTouch(event)) return;
		const target = event.currentTarget as HTMLElement | null;
		const handle = target?.closest('[data-drag-handle]');
		if (!handle) return;
		pointerStartX = event.clientX;
		pointerStartY = event.clientY;
		window.setTimeout(() => {
			touchDragging = true;
			touchConsumed = true;
			isDragging = true;
			if (event.cancelable) {
				event.preventDefault();
			}
			const state = drag as typeof drag & {
				startMoveTouch: (
					stepId: string,
					type: string,
					pointerId: number,
					pointerX: number,
					pointerY: number
				) => void;
			};
			state.startMoveTouch(step.id, step.type, event.pointerId, event.clientX, event.clientY);
			if (event.currentTarget instanceof HTMLElement) {
				event.currentTarget.setPointerCapture(event.pointerId);
			}
		}, longPressDelay);
	}

	function handleTouchMove(event: PointerEvent) {
		if (!shouldStartTouch(event)) return;
		if (pointerStartX !== null && pointerStartY !== null) {
			const deltaX = Math.abs(event.clientX - pointerStartX);
			const deltaY = Math.abs(event.clientY - pointerStartY);
			const moved = deltaX > dragThreshold || deltaY > dragThreshold;
			if (moved && !touchDragging) {
				pointerStartX = null;
				pointerStartY = null;
				return;
			}
		}
		if (!touchDragging) return;
		throttledTouchMove(event);
		event.preventDefault();
	}

	function finishTouchDrag(event: PointerEvent) {
		if (!shouldStartTouch(event)) return;
		if (touchDragging && drag.active) {
			if (drag.target && drag.stepId && drag.valid) {
				onTouchMove(drag.stepId, drag.target);
			}
			drag.end();
		}
		const wasTouchDragging = touchDragging;
		touchDragging = false;
		touchConsumed = wasTouchDragging;
		isDragging = false;
		pointerStartX = null;
		pointerStartY = null;
		if (event.currentTarget instanceof HTMLElement) {
			event.currentTarget.releasePointerCapture(event.pointerId);
		}
	}

	$effect(() => {
		if (!touchDragging) return;
		document.body.classList.add('touch-dragging');
		return () => {
			document.body.classList.remove('touch-dragging');
		};
	});

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
	class="step-node"
	class:view-node={step.type === 'view'}
	class:greyed-out={isDragging}
	class:drag-target={isOtherDragging}
>
	<div class="connection-point top"></div>

	<div class="step-content" role="listitem">
		<div class="step-header">
			<!-- Drag handle (6-dot grip) -->
			<button
				class="drag-handle"
				class:touch-dragging={touchDragging}
				title="Drag to reorder"
				type="button"
				draggable="true"
				ondragstart={handleDragStart}
				ondragend={handleDragEnd}
				onpointerdown={startLongPress}
				onpointermove={handleTouchMove}
				onpointerup={finishTouchDrag}
				onpointercancel={finishTouchDrag}
				onclick={handleTouchClick}
				data-drag-handle="true"
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

			<span class="step-icon">{currentStepInfo.icon}</span>
			<span class="step-type">{label}</span>
			<span class="step-number">#{index + 1}</span>
		</div>

		<div class="step-summary">{summary}</div>

		<div class="step-actions">
			<button class="action-btn" onclick={() => onEdit(step.id)} type="button"> edit </button>
			<button class="action-btn danger" onclick={() => onDelete(step.id)} type="button">
				delete
			</button>
		</div>

		{#if step.type === 'export' && datasourceId}
			<div class="export-section">
				{#if exportError}
					<div class="export-error">{exportError}</div>
				{/if}
				<button class="export-btn" onclick={handleExport} disabled={isExporting} type="button">
					{#if isExporting}
						<span class="spinner"></span>
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

		{#if step.type === 'view' && datasourceId}
		<div class="view-preview expanded">
			{#if isSavedView}
				{#if saveStatus === 'unsaved'}
					<div class="preview-stale">Preview shows last saved state</div>
				{/if}
				{#if analysisId && datasourceId}
					<InlineDataTable
						{analysisId}
						{datasourceId}
						pipeline={savedSteps}
						stepId={step.id}
						rowLimit={typeof step.config?.rowLimit === 'number' ? step.config.rowLimit : 100}
					/>
				{/if}
			{:else}
				<div class="preview-pending">
					<div class="pending-dot"></div>
					<span>Save to preview data</span>
				</div>
			{/if}
		</div>
	{/if}
</div>

	<div class="connection-point bottom"></div>
</div>

<style>
	.step-node {
		position: relative;
		width: min(55%, 640px);
	}

	.step-node.view-node {
		max-width: 75%;
		width: 75%;
		min-width: 320px;
	}

	.step-node.greyed-out {
		opacity: 0.4;
		filter: grayscale(50%);
	}

	.connection-point {
		position: absolute;
		left: 50%;
		transform: translateX(-50%);
		width: 8px;
		height: 8px;
		background-color: var(--fg-muted);
		border: 2px solid var(--bg-primary);
		border-radius: 50%;
		z-index: 2;
	}

	.connection-point.top {
		top: -4px;
	}

	.connection-point.bottom {
		bottom: -4px;
	}

	.step-content {
		background-color: var(--bg-primary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		padding: var(--space-4);
		transition: all var(--transition);
		box-shadow: var(--card-shadow);
	}

	.step-content:hover {
		border-color: var(--border-tertiary);
		transform: translateY(-1px);
	}

	.step-header {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin-bottom: var(--space-3);
	}

	.drag-handle {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: var(--space-1);
		background: transparent;
		border: none;
		cursor: grab;
		opacity: 0.4;
		color: var(--fg-muted);
		border-radius: var(--radius-sm);
		transition:
			opacity 0.15s,
			background-color 0.15s;
		flex-shrink: 0;
		user-select: none;
		-webkit-user-select: none;
		appearance: none;
	}

	.drag-handle:hover {
		opacity: 1;
		background-color: var(--bg-hover);
	}

	.drag-handle:active {
		cursor: grabbing;
	}

	.drag-handle.touch-dragging {
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

	.step-icon {
		font-size: var(--text-base);
		flex-shrink: 0;
	}

	.step-type {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--fg-primary);
		font-family: var(--font-mono);
		flex: 1;
	}

	.step-number {
		font-size: var(--text-xs);
		color: var(--fg-muted);
		flex-shrink: 0;
	}

	.step-summary {
		padding: var(--space-2) var(--space-3);
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
		color: var(--fg-tertiary);
		margin-bottom: var(--space-3);
	}

	.step-actions {
		display: flex;
		gap: var(--space-2);
	}

	.view-preview {
		margin-top: var(--space-3);
		border-top: 1px solid var(--border-secondary);
		padding-top: var(--space-3);
	}

	.preview-pending {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-3);
		border: 1px dashed var(--border-secondary);
		border-radius: var(--radius-sm);
		background-color: var(--bg-tertiary);
		color: var(--fg-tertiary);
		font-size: var(--text-xs);
		font-weight: 600;
		letter-spacing: 0.02em;
		text-transform: uppercase;
	}

	.pending-dot {
		width: 8px;
		height: 8px;
		border-radius: 999px;
		background: var(--accent-primary);
		box-shadow: var(--accent-ring);
	}

	.preview-stale {
		margin-bottom: var(--space-2);
		padding: var(--space-2) var(--space-3);
		border: 1px dashed var(--warning-border);
		border-radius: var(--radius-sm);
		background-color: var(--warning-bg);
		color: var(--warning-fg);
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.action-btn {
		flex: 1;
		padding: var(--space-2);
		background-color: transparent;
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-weight: 500;
		color: var(--fg-secondary);
		transition: all var(--transition);
	}

	.action-btn:hover {
		background-color: var(--bg-hover);
		color: var(--fg-primary);
	}

	.action-btn.danger:hover {
		background-color: var(--error-bg);
		border-color: var(--error-border);
		color: var(--error-fg);
	}

	.export-section {
		margin-top: var(--space-3);
		padding-top: var(--space-3);
		border-top: 1px solid var(--border-primary);
	}

	.export-btn {
		width: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-3);
		background-color: var(--accent-primary);
		color: var(--bg-primary);
		border: none;
		border-radius: var(--radius-sm);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-weight: 500;
		cursor: pointer;
		transition: opacity var(--transition);
	}

	.export-btn:hover:not(:disabled) {
		opacity: 0.9;
	}

	.export-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.export-btn .spinner {
		width: 14px;
		height: 14px;
		border: 2px solid currentColor;
		border-top-color: transparent;
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	.export-error {
		padding: var(--space-2);
		margin-bottom: var(--space-2);
		background-color: var(--error-bg);
		color: var(--error-fg);
		border: 1px solid var(--error-border);
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	/* When another node is being dragged */
	.step-node.drag-target .step-content {
		border-style: dashed;
		border-color: var(--accent-primary);
		opacity: 0.7;
		transform: scale(0.98);
	}
</style>
