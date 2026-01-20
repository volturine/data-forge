<script lang="ts">
	import type { PipelineStep } from '$lib/types/analysis';
	import { drag } from '$lib/stores/drag.svelte';
	import InlineDataTable from '$lib/components/viewers/InlineDataTable.svelte';
	import { Download, Save } from 'lucide-svelte';
	import { exportData, downloadBlob, type ExportRequest } from '$lib/api/compute';

	interface Props {
		step: PipelineStep;
		index: number;
		datasourceId?: string;
		allSteps?: PipelineStep[];
		savedSteps?: PipelineStep[];
		saveStatus?: 'saved' | 'unsaved' | 'saving';
		onEdit: (id: string) => void;
		onDelete: (id: string) => void;
	}

	let {
		step,
		index,
		datasourceId,
		allSteps = [],
		savedSteps = [],
		saveStatus = 'saved',
		onEdit,
		onDelete
	}: Props = $props();

	let isExporting = $state(false);
	let exportError = $state<string | null>(null);

	let dragPreviewEl = $state<HTMLDivElement | null>(null);

	const stepTypeInfo: Record<string, { label: string; icon: string }> = {
		filter: { label: 'Filter', icon: '🔍' },
		select: { label: 'Select', icon: '📋' },
		groupby: { label: 'Group By', icon: '📊' },
		sort: { label: 'Sort', icon: '↕️' },
		rename: { label: 'Rename', icon: '✏️' },
		drop: { label: 'Drop', icon: '🗑️' },
		join: { label: 'Join', icon: '🔗' },
		expression: { label: 'Expression', icon: '🧮' },
		with_columns: { label: 'With Columns', icon: '🧮' },
		pivot: { label: 'Pivot', icon: '🔄' },
		unpivot: { label: 'Unpivot', icon: '🔃' },
		fill_null: { label: 'Fill Null', icon: '🔧' },
		deduplicate: { label: 'Deduplicate', icon: '🧹' },
		explode: { label: 'Explode', icon: '💥' },
		timeseries: { label: 'Time Series', icon: '📅' },
		string_transform: { label: 'String Transform', icon: '📝' },
		sample: { label: 'Sample', icon: '🎲' },
		limit: { label: 'Limit', icon: '✂️' },
		topk: { label: 'Top K', icon: '🏆' },
		null_count: { label: 'Null Count', icon: '❓' },
		value_counts: { label: 'Value Counts', icon: '📊' },
		view: { label: 'View', icon: '👁️' },
		export: { label: 'Export', icon: '📤' }
	};

	const typeLabels: Record<string, string> = {
		filter: 'filter',
		select: 'select',
		groupby: 'group_by',
		sort: 'sort',
		rename: 'rename',
		drop: 'drop',
		join: 'join',
		expression: 'expression',
		with_columns: 'with_columns',
		deduplicate: 'deduplicate',
		fill_null: 'fill_null',
		explode: 'explode',
		pivot: 'pivot',
		timeseries: 'timeseries',
		string_transform: 'string',
		export: 'export'
	};

	function getConfigSummary(s: PipelineStep): string {
		switch (s.type) {
			case 'filter': {
				const conditions = s.config.conditions as Array<{
					column: string;
					operator: string;
					value: string;
				}>;
				if (!conditions || conditions.length === 0) return 'no conditions';
				return `${conditions.length} condition${conditions.length > 1 ? 's' : ''}`;
			}

			case 'select': {
				const columns = s.config.columns as string[];
				if (!columns || columns.length === 0) return 'no columns';
				return `${columns.length} column${columns.length > 1 ? 's' : ''}`;
			}

			case 'groupby': {
				const groupBy = s.config.groupBy as string[];
				const aggregations = s.config.aggregations as Array<unknown>;
				if (!groupBy || groupBy.length === 0) return 'not configured';
				return `${groupBy.length} key${groupBy.length > 1 ? 's' : ''}, ${aggregations?.length || 0} agg`;
			}

			case 'sort': {
				const sortRules = s.config as unknown as Array<{ column: string; descending: boolean }>;
				if (!Array.isArray(sortRules) || sortRules.length === 0) return 'not configured';
				return `${sortRules.length} column${sortRules.length > 1 ? 's' : ''}`;
			}

			case 'export': {
				const format = (s.config.format as string) || 'csv';
				const filename = (s.config.filename as string) || 'export';
				return `${filename}.${format}`;
			}

			default: {
				return 'click to configure';
			}
		}
	}

	let currentStepInfo = $derived(stepTypeInfo[step.type] || { label: step.type, icon: '⚙️' });
	let label = $derived(typeLabels[step.type] || step.type);
	let summary = $derived(getConfigSummary(step));

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

	async function handleExport() {
		if (!datasourceId || isExporting) return;

		isExporting = true;
		exportError = null;

		const format = (step.config.format as string) || 'csv';
		const filename = (step.config.filename as string) || 'export';
		const destination = (step.config.destination as string) || 'filesystem';

		try {
			const request: ExportRequest = {
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

			const result = await exportData(request);

			if (destination === 'download' && result instanceof Blob) {
				const ext = format === 'csv' ? '.csv' : format === 'parquet' ? '.parquet' : '.json';
				downloadBlob(result, `${filename}${ext}`);
			}
		} catch (err) {
			exportError = err instanceof Error ? err.message : 'Export failed';
		} finally {
			isExporting = false;
		}
	}
</script>

<div class="drag-preview" bind:this={dragPreviewEl}>
	<span class="preview-icon">{currentStepInfo.icon}</span>
	<span class="preview-name">{currentStepInfo.label}</span>
</div>

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
				title="Drag to reorder"
				type="button"
				draggable="true"
				ondragstart={handleDragStart}
				ondragend={handleDragEnd}
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

		{#if step.type === 'view' && datasourceId && savedSteps.length > 0}
			<div class="view-preview expanded">
				{#if saveStatus === 'unsaved'}
					<div class="preview-stale">Preview shows last saved state</div>
				{/if}
				<InlineDataTable
					{datasourceId}
					pipeline={savedSteps}
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
		transition: all var(--transition-fast);
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
		transition: all var(--transition-fast);
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
		transition: opacity var(--transition-fast);
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

	/* Hidden drag preview element - positioned off-screen */
	.drag-preview {
		position: fixed;
		top: -9999px;
		left: -9999px;
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-3);
		background: var(--bg-primary, #fff);
		border: 2px solid var(--border-primary, #ccc);
		border-radius: var(--radius-sm);
		font-size: var(--text-sm);
		white-space: nowrap;
		pointer-events: none;
		z-index: 9999;
		box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
		/* Use opacity 0 instead of display: none so browser can capture it */
		opacity: 0;
	}

	.preview-icon {
		font-size: var(--text-base);
	}

	.preview-name {
		font-weight: 500;
		color: var(--fg-primary);
	}
</style>
