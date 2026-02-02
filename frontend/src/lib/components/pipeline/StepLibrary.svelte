<script lang="ts">
	import { drag, type DropTarget } from '$lib/stores/drag.svelte';

	interface StepType {
		type: string;
		label: string;
		icon: string;
		description: string;
	}

	interface Props {
		onAddStep: (type: string) => void;
		onInsertStep: (type: string, target: DropTarget) => void;
	}

	let { onAddStep, onInsertStep }: Props = $props();

	let dragImageEl = $state<HTMLImageElement | null>(null);
	let dragging = $state(false);
	let clickConsumed = $state(false);
	let longPressTimer = $state<number | null>(null);
	let pointerStartX = $state<number | null>(null);
	let pointerStartY = $state<number | null>(null);

	const longPressDelay = 180;
	const dragThreshold = 8;

	function handleClick(stepType: string) {
		if (dragging || clickConsumed) {
			clickConsumed = false;
			return;
		}
		onAddStep(stepType);
	}

	function startDrag(event: PointerEvent, stepType: string) {
		const target = event.currentTarget as HTMLElement | null;
		const handle = target?.closest('[data-drag-handle]');
		if (!handle) return;

		pointerStartX = event.clientX;
		pointerStartY = event.clientY;

		// For touch inputs, require long press to prevent accidental drags
		if (event.pointerType === 'touch') {
			longPressTimer = window.setTimeout(() => {
				initiateDrag(event, stepType);
			}, longPressDelay);
		} else {
			// For mouse/trackpad, start drag immediately
			initiateDrag(event, stepType);
		}
	}

	function initiateDrag(event: PointerEvent, stepType: string) {
		dragging = true;
		clickConsumed = true;
		if (event.cancelable) {
			event.preventDefault();
		}
		drag.start(stepType, 'library', event.pointerId, event.clientX, event.clientY);
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
			if (drag.target && drag.type && drag.valid) {
				onInsertStep(drag.type, drag.target);
			}
			drag.end();
		}
		const wasDragging = dragging;
		dragging = false;
		clickConsumed = wasDragging;
		cancelLongPress();
	}

	const stepTypes: StepType[] = [
		{ type: 'filter', label: 'Filter', icon: '🔍', description: 'Filter rows by conditions' },
		{ type: 'select', label: 'Select', icon: '📋', description: 'Select specific columns' },
		{ type: 'groupby', label: 'Group By', icon: '📊', description: 'Group and aggregate data' },
		{ type: 'sort', label: 'Sort', icon: '↕️', description: 'Sort rows by columns' },
		{ type: 'rename', label: 'Rename', icon: '✏️', description: 'Rename columns' },
		{ type: 'drop', label: 'Drop', icon: '🗑️', description: 'Remove columns' },
		{ type: 'join', label: 'Join', icon: '🔗', description: 'Join with another dataset' },
		{ type: 'expression', label: 'Expression', icon: '🧮', description: 'Create computed columns' },
		{ type: 'with_columns', label: 'With Columns', icon: '🧮', description: 'Add/Update columns' },
		{ type: 'pivot', label: 'Pivot', icon: '🔄', description: 'Reshape data wide' },
		{ type: 'unpivot', label: 'Unpivot', icon: '🔃', description: 'Reshape data long' },
		{ type: 'fill_null', label: 'Fill Null', icon: '🔧', description: 'Handle missing values' },
		{ type: 'deduplicate', label: 'Deduplicate', icon: '🧹', description: 'Remove duplicate rows' },
		{ type: 'explode', label: 'Explode', icon: '💥', description: 'Expand list columns' },
		{ type: 'timeseries', label: 'Time Series', icon: '📅', description: 'Date/time operations' },
		{
			type: 'string_transform',
			label: 'String Transform',
			icon: '📝',
			description: 'Text manipulation'
		},
		{ type: 'sample', label: 'Sample', icon: '🎲', description: 'Random sample rows' },
		{ type: 'limit', label: 'Limit', icon: '✂️', description: 'Keep first N rows' },
		{ type: 'topk', label: 'Top K', icon: '🏆', description: 'Get top K rows by column' },
		{
			type: 'null_count',
			label: 'Null Count',
			icon: '❓',
			description: 'Count null values per column'
		},
		{
			type: 'value_counts',
			label: 'Value Counts',
			icon: '📊',
			description: 'Get value frequencies'
		},
		{ type: 'view', label: 'View', icon: '👁️', description: 'Preview data at this step' },
		{
			type: 'union_by_name',
			label: 'Union By Name',
			icon: '🧩',
			description: 'Union rows from multiple datasources'
		},
		{ type: 'export', label: 'Export', icon: '📤', description: 'Export data to file' }
	];

	// Quick insert selected type
	let selectedType = $state<string | null>(null);
</script>

<div class="step-library">
	<img class="drag-preview" alt="" bind:this={dragImageEl} />
	<h3>Operations</h3>
	<div class="step-list" role="list">
		{#each stepTypes as stepType (stepType.type)}
			<button
				class="step-button"
				class:dragging
				onclick={() => handleClick(stepType.type)}
				onpointerdown={(event) => startDrag(event, stepType.type)}
				onpointermove={handlePointerMove}
				onpointerup={finishDrag}
				onpointercancel={finishDrag}
				type="button"
				data-step={stepType.type}
				data-drag-handle="true"
			>
				<span class="step-icon" data-drag-handle="true">{stepType.icon}</span>
				<div class="step-info">
					<span class="step-label">{stepType.label}</span>
					<span class="step-description">{stepType.description}</span>
				</div>
			</button>
		{/each}
	</div>

	<div class="fallback-actions">
		<h4>Quick Insert</h4>
		<div class="fallback-controls">
			<select
				value={selectedType ?? ''}
				onchange={(event) => (selectedType = event.currentTarget.value || null)}
			>
				<option value="">Select operation...</option>
				{#each stepTypes as stepType (stepType.type)}
					<option value={stepType.type}>{stepType.label}</option>
				{/each}
			</select>
			<div class="fallback-buttons">
				<button
					type="button"
					disabled={!selectedType}
					onclick={() => {
						if (selectedType) {
							onAddStep(selectedType);
							selectedType = null;
						}
					}}
				>
					Add to end
				</button>
				<button
					type="button"
					disabled={!selectedType}
					onclick={() => {
						if (selectedType) {
							onInsertStep(selectedType, { index: 0, parentId: null, nextId: null });
							selectedType = null;
						}
					}}
				>
					Insert at start
				</button>
			</div>
		</div>
	</div>
</div>

<style>
	.step-library {
		width: var(--operations-panel-width, 280px);
		padding: var(--space-4) var(--space-3);
		background-color: var(--panel-bg);
		display: flex;
		flex-direction: column;
		overflow: hidden;
		gap: var(--space-3);
	}
	.drag-preview {
		position: fixed;
		top: -9999px;
		left: -9999px;
		width: 1px;
		height: 1px;
		opacity: 0;
		pointer-events: none;
	}
	h3 {
		margin-top: 0;
		margin-bottom: var(--space-3);
		font-size: var(--text-sm);
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--fg-primary);
		flex-shrink: 0;
	}
	.step-list {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		overflow-y: auto;
		overflow-x: hidden;
		flex: 1;
		min-height: 0;
	}
	.step-button {
		display: flex;
		align-items: center;
		justify-content: flex-start;
		gap: 0.75rem;
		padding: var(--space-3);
		background-color: transparent;
		border: 1px solid transparent;
		border-radius: 6px;
		cursor: grab;
		transition:
			background-color var(--transition),
			border-color var(--transition);
		text-align: left;
		position: relative;
	}
	.step-button::before {
		content: '';
		position: absolute;
		top: 6px;
		left: 6px;
		bottom: 6px;
		right: 6px;
		border-radius: 6px;
	}
	.step-button:hover {
		border-color: var(--border-secondary);
		background-color: var(--bg-hover);
	}
	.step-button:active {
		cursor: grabbing;
	}
	.step-button.dragging {
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
		font-size: 1.25rem;
		flex-shrink: 0;
	}
	.step-info {
		display: flex;
		flex-direction: column;
		gap: 0.125rem;
		align-items: flex-start;
		min-width: 0;
	}
	.step-label {
		font-weight: 600;
		color: var(--fg-primary);
		font-size: var(--text-sm);
	}
	.step-description {
		font-size: 0.75rem;
		color: var(--fg-muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.fallback-actions {
		margin-top: var(--space-4);
		padding-top: var(--space-3);
		border-top: 1px solid var(--panel-border);
		flex-shrink: 0;
	}
	.fallback-actions h4 {
		margin: 0 0 var(--space-2) 0;
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--fg-muted);
	}
	.fallback-controls {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.fallback-controls select {
		padding: 0.5rem;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background-color: var(--bg-secondary);
		color: var(--fg-primary);
	}
	.fallback-buttons {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2);
	}
	.fallback-controls button {
		padding: 0.5rem;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background-color: transparent;
		color: var(--fg-primary);
		cursor: pointer;
	}
	.fallback-controls button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
