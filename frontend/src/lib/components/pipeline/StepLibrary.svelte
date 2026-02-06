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

<div
	class="step-library flex w-full flex-col gap-3 overflow-hidden bg-panel-bg px-3 py-4"
>
	<img
		class="drag-preview pointer-events-none fixed -left-[9999px] -top-[9999px] h-px w-px opacity-0"
		alt=""
		bind:this={dragImageEl}
	/>
	<h3 class="m-0 mb-3 shrink-0 text-sm uppercase tracking-widest text-fg-primary">
		Operations
	</h3>
	<div
		class="step-list flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto overflow-x-hidden"
		role="list"
	>
		{#each stepTypes as stepType (stepType.type)}
			<button
				class="step-button relative flex cursor-grab items-center justify-start gap-3 rounded-md border border-transparent bg-transparent p-3 text-left transition-colors hover:border-border-secondary hover:bg-bg-hover"
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
				<span class="shrink-0 text-xl" data-drag-handle="true">{stepType.icon}</span>
				<div class="flex min-w-0 flex-col items-start gap-0.5">
					<span class="text-sm font-semibold text-fg-primary">{stepType.label}</span>
					<span class="truncate text-xs text-fg-muted">{stepType.description}</span>
				</div>
			</button>
		{/each}
	</div>

	<div class="mt-4 shrink-0 border-t border-panel-border pt-3">
		<h4 class="m-0 mb-2 text-xs uppercase tracking-wide text-fg-muted">
			Quick Insert
		</h4>
		<div class="flex flex-col gap-2">
			<select
				class="rounded-sm border border-panel-border bg-bg-secondary p-2 text-fg-primary"
				value={selectedType ?? ''}
				onchange={(event) => (selectedType = event.currentTarget.value || null)}
			>
				<option value="">Select operation...</option>
				{#each stepTypes as stepType (stepType.type)}
					<option value={stepType.type}>{stepType.label}</option>
				{/each}
			</select>
			<div class="grid grid-cols-2 gap-2">
				<button
					class="fallback-btn cursor-pointer rounded-sm border border-panel-border bg-transparent p-2 text-fg-primary transition-colors hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-50"
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
					class="fallback-btn cursor-pointer rounded-sm border border-panel-border bg-transparent p-2 text-fg-primary transition-colors hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-50"
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
</style>
