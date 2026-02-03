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

		<div class="step-summary" class:inactive={!isApplied}>{summary}</div>

		<div class="step-actions">
			<button
				class="action-btn apply-toggle"
				class:inactive={!isApplied}
				onclick={() => onToggleApply(step.id)}
				type="button"
				title={isApplied ? 'Disable step' : 'Enable step'}
			>
				{isApplied ? 'disable' : 'enable'}
			</button>
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
						<span class="spinner-sm"></span>
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
			<div class="view-preview expanded">
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

	.step-icon {
		font-size: var(--text-base);
		flex-shrink: 0;
	}
	.step-type {
		font-size: var(--text-sm);
		font-weight: 600;
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
	.step-summary.inactive {
		background-color: var(--bg-secondary);
		color: var(--fg-muted);
		border: 1px dashed var(--border-primary);
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

	.action-btn {
		flex: 1;
		padding: var(--space-2);
		background-color: transparent;
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: var(--text-xs);
		font-weight: 500;
		color: var(--fg-secondary);
		transition: all var(--transition);
	}
	.action-btn:hover {
		background-color: var(--bg-hover);
		color: var(--fg-primary);
	}
	.action-btn.apply-toggle {
		text-transform: uppercase;
		letter-spacing: 0.08em;
		font-size: 0.625rem;
	}
	.action-btn.apply-toggle.inactive {
		border-style: dashed;
		color: var(--fg-muted);
	}
	.action-btn.apply-toggle.inactive:hover {
		background-color: var(--bg-tertiary);
		color: var(--fg-secondary);
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

	.export-error {
		padding: var(--space-2);
		margin-bottom: var(--space-2);
		background-color: var(--error-bg);
		color: var(--error-fg);
		border: 1px solid var(--error-border);
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
	}

	.step-node.drag-target .step-content {
		border-style: dashed;
		border-color: var(--accent-primary);
		opacity: 0.7;
		transform: scale(0.98);
	}
</style>
