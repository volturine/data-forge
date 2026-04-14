<script lang="ts">
	import { drag, type DropTarget } from '$lib/stores/drag.svelte';
	import { css, cx, input } from '$lib/styles/panda';

	interface StepType {
		type: string;
		label: string;
		icon: typeof Funnel;
		description: string;
	}

	interface Props {
		onAddStep: (type: string) => void;
		onInsertStep: (type: string, target: DropTarget) => void;
		readOnly?: boolean;
	}

	let { onAddStep, onInsertStep, readOnly = false }: Props = $props();

	let dragImageEl = $state<HTMLImageElement | null>(null);
	let dragging = $state(false);
	let clickConsumed = $state(false);
	let longPressTimer = $state<number | null>(null);
	let pointerStartX = $state<number | null>(null);
	let pointerStartY = $state<number | null>(null);

	const longPressDelay = 180;
	const dragThreshold = 8;

	function handleClick(stepType: string) {
		if (readOnly) return;
		if (dragging || clickConsumed) {
			clickConsumed = false;
			return;
		}
		onAddStep(stepType);
	}

	function startDrag(event: PointerEvent, stepType: string) {
		if (readOnly) return;
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
			return;
		}
		// For mouse/trackpad, start drag immediately
		initiateDrag(event, stepType);
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
		ChartColumn,
		Bomb,
		Brush,
		Calculator,
		Calendar,
		Dices,
		Eye,
		Funnel,
		LayoutGrid,
		Link,
		Pencil,
		Repeat,
		Repeat2,
		Scissors,
		Trophy,
		Type,
		Wrench,
		ListChecks,
		Trash2,
		ChartColumnIncreasing,
		Bell,
		Sparkles,
		Download
	} from 'lucide-svelte';

	const stepTypes: StepType[] = [
		{ type: 'filter', label: 'Filter', icon: Funnel, description: 'Filter rows by conditions' },
		{ type: 'select', label: 'Select', icon: ListChecks, description: 'Select specific columns' },
		{
			type: 'groupby',
			label: 'Group By',
			icon: ChartColumn,
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
			type: 'chart',
			label: 'Chart',
			icon: ChartColumnIncreasing,
			description: 'Visualize data inline'
		},
		{
			type: 'notification',
			label: 'Notify',
			icon: Bell,
			description: 'Send email or Telegram alert'
		},
		{ type: 'ai', label: 'AI', icon: Sparkles, description: 'Transform text using AI' },
		{ type: 'view', label: 'View', icon: Eye, description: 'Preview data at this step' },
		{
			type: 'union_by_name',
			label: 'Union By Name',
			icon: LayoutGrid,
			description: 'Union rows from multiple datasources'
		},
		{
			type: 'download',
			label: 'Download',
			icon: Download,
			description: 'Download data in various formats'
		}
	];

	// Search/filter
	let search = $state('');
	const filtered = $derived.by(() => {
		const q = search.trim().toLowerCase();
		if (!q) return stepTypes;
		return stepTypes.filter(
			(s) =>
				s.label.toLowerCase().includes(q) ||
				s.type.toLowerCase().includes(q) ||
				s.description.toLowerCase().includes(q)
		);
	});
</script>

<div
	class={css({
		display: 'flex',
		height: '100%',
		minHeight: '0',
		width: '100%',
		flexDirection: 'column',
		overflow: 'hidden',
		backgroundColor: 'bg.primary',
		contain: 'content'
	})}
>
	<img
		class={css({
			pointerEvents: 'none',
			position: 'fixed',
			left: '-2500px',
			top: '-2500px',
			height: 'px',
			width: 'px',
			opacity: '0'
		})}
		alt=""
		bind:this={dragImageEl}
	/>
	<div class={css({ flexShrink: '0', paddingX: '5', paddingTop: '5', paddingBottom: '3' })}>
		<h3
			class={css({
				margin: '0',
				marginBottom: '3',
				fontSize: 'xs',
				fontWeight: 'semibold',
				textTransform: 'uppercase',
				letterSpacing: 'widest',
				color: 'fg.muted'
			})}
		>
			Operations
		</h3>
		<input
			type="text"
			placeholder="Search operations..."
			bind:value={search}
			class={cx(
				input(),
				css({
					width: '100%',
					fontSize: 'xs',
					backgroundColor: 'bg.secondary'
				})
			)}
		/>
	</div>
	<div
		class={css({
			display: 'flex',
			minHeight: '0',
			flex: '1',
			flexDirection: 'column',
			gap: '0',
			overflowY: 'auto',
			overflowX: 'hidden',
			paddingX: '3',
			paddingBottom: '3'
		})}
		role="list"
	>
		{#each filtered as stepType (stepType.type)}
			<button
				class={css({
					position: 'relative',
					display: 'flex',
					cursor: readOnly ? 'not-allowed' : 'grab',
					alignItems: 'center',
					justifyContent: 'flex-start',
					gap: '3',
					borderWidth: '1',
					borderColor: 'transparent',
					backgroundColor: 'transparent',
					paddingX: '3',
					paddingY: '2.5',
					textAlign: 'left',
					_hover: { backgroundColor: 'bg.hover' },
					_active: { cursor: readOnly ? 'not-allowed' : 'grabbing' },
					...(dragging ? { userSelect: 'none', WebkitUserSelect: 'none', touchAction: 'none' } : {})
				})}
				onclick={() => handleClick(stepType.type)}
				onpointerdown={(event) => startDrag(event, stepType.type)}
				onpointermove={handlePointerMove}
				onpointerup={finishDrag}
				onpointercancel={finishDrag}
				type="button"
				data-step={stepType.type}
				data-drag-handle="true"
				disabled={readOnly}
			>
				<stepType.icon
					size={15}
					class={css({ flexShrink: '0', color: 'fg.muted' })}
					data-drag-handle="true"
				/>
				<div
					class={css({
						display: 'flex',
						minWidth: '0',
						flexDirection: 'column',
						alignItems: 'flex-start',
						gap: '0'
					})}
				>
					<span class={css({ fontSize: 'xs', fontWeight: 'medium' })}>{stepType.label}</span>
					<span
						class={css({
							overflow: 'hidden',
							textOverflow: 'ellipsis',
							whiteSpace: 'nowrap',
							fontSize: '2xs',
							color: 'fg.faint'
						})}>{stepType.description}</span
					>
				</div>
			</button>
		{/each}
	</div>
</div>
