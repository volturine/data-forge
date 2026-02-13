<script lang="ts">
	import { drag, type DropTarget } from '$lib/stores/drag.svelte';

	interface StepType {
		type: string;
		label: string;
		icon: typeof Filter;
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

	import {
		ArrowUpDown,
		BarChart3,
		Bomb,
		Brush,
		Calculator,
		Calendar,
		CircleHelp,
		Dices,
		Eye,
		Filter,
		LayoutGrid,
		Link,
		Pencil,
		Repeat,
		Repeat2,
		Scissors,
		Trophy,
		Type,
		Upload,
		Wrench,
		ListChecks,
		Trash2
	} from 'lucide-svelte';

	const stepTypes: StepType[] = [
		{ type: 'filter', label: 'Filter', icon: Filter, description: 'Filter rows by conditions' },
		{ type: 'select', label: 'Select', icon: ListChecks, description: 'Select specific columns' },
		{
			type: 'groupby',
			label: 'Group By',
			icon: BarChart3,
			description: 'Group and aggregate data'
		},
		{ type: 'sort', label: 'Sort', icon: ArrowUpDown, description: 'Sort rows by columns' },
		{ type: 'rename', label: 'Rename', icon: Pencil, description: 'Rename columns' },
		{ type: 'drop', label: 'Drop', icon: Trash2, description: 'Remove columns' },
		{ type: 'join', label: 'Join', icon: Link, description: 'Join with another dataset' },
		{
			type: 'expression',
			label: 'Expression',
			icon: Calculator,
			description: 'Create computed columns'
		},
		{
			type: 'with_columns',
			label: 'With Columns',
			icon: Calculator,
			description: 'Add/Update columns'
		},
		{ type: 'pivot', label: 'Pivot', icon: Repeat, description: 'Reshape data wide' },
		{ type: 'unpivot', label: 'Unpivot', icon: Repeat2, description: 'Reshape data long' },
		{ type: 'fill_null', label: 'Fill Null', icon: Wrench, description: 'Handle missing values' },
		{
			type: 'deduplicate',
			label: 'Deduplicate',
			icon: Brush,
			description: 'Remove duplicate rows'
		},
		{ type: 'explode', label: 'Explode', icon: Bomb, description: 'Expand list columns' },
		{
			type: 'timeseries',
			label: 'Time Series',
			icon: Calendar,
			description: 'Date/time operations'
		},
		{
			type: 'string_transform',
			label: 'String Transform',
			icon: Type,
			description: 'Text manipulation'
		},
		{ type: 'sample', label: 'Sample', icon: Dices, description: 'Random sample rows' },
		{ type: 'limit', label: 'Limit', icon: Scissors, description: 'Keep first N rows' },
		{ type: 'topk', label: 'Top K', icon: Trophy, description: 'Get top K rows by column' },
		{
			type: 'null_count',
			label: 'Null Count',
			icon: CircleHelp,
			description: 'Count null values per column'
		},
		{
			type: 'value_counts',
			label: 'Value Counts',
			icon: BarChart3,
			description: 'Get value frequencies'
		},
		{ type: 'view', label: 'View', icon: Eye, description: 'Preview data at this step' },
		{
			type: 'union_by_name',
			label: 'Union By Name',
			icon: LayoutGrid,
			description: 'Union rows from multiple datasources'
		},
		{ type: 'export', label: 'Export', icon: Upload, description: 'Download data' }
	];

	// Quick insert selected type
	let selectedType = $state<string | null>(null);
</script>

<div
	class="step-library flex h-full min-h-0 w-full flex-col gap-3 overflow-hidden bg-primary px-3 py-4"
>
	<img
		class="drag-preview pointer-events-none fixed -left-2500 -top-2500 h-px w-px opacity-0"
		alt=""
		bind:this={dragImageEl}
	/>
	<h3 class="m-0 mb-3 shrink-0 text-sm uppercase tracking-widest text-fg-primary">Operations</h3>
	<div
		class="step-list flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto overflow-x-hidden"
		role="list"
	>
		{#each stepTypes as stepType (stepType.type)}
			<button
				class="step-button relative flex cursor-grab items-center justify-start gap-3 border border-transparent bg-transparent p-3 text-left hover:border-tertiary hover:bg-bg-hover"
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
				<stepType.icon size={18} class="shrink-0" data-drag-handle="true" />
				<div class="flex min-w-0 flex-col items-start gap-0.5">
					<span class="text-sm font-semibold text-fg-primary">{stepType.label}</span>
					<span class="truncate text-xs text-fg-muted">{stepType.description}</span>
				</div>
			</button>
		{/each}
	</div>

	<div class="mt-4 shrink-0 border-t border-tertiary pt-3">
		<h4 class="m-0 mb-2 text-xs uppercase tracking-wide text-fg-muted">Quick Insert</h4>
		<div class="flex flex-col gap-2">
			<select
				class="rounded-sm border border-tertiary bg-bg-secondary p-2 text-fg-primary"
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
					class="fallback-btn cursor-pointer border border-tertiary bg-transparent p-2 text-fg-primary hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-50"
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
					class="fallback-btn cursor-pointer border border-tertiary bg-transparent p-2 text-fg-primary hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-50"
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
