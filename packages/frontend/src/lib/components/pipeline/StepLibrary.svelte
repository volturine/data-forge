<script lang="ts">
	import { drag, type DropTarget } from '#lib/stores/drag.svelte.js';
	import { css } from '#lib/styles/panda.js';
	import { getStepTypeConfig } from './utils';

	interface StepType {
		type: string;
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
	let pendingType = $state<string | null>(null);
	let pendingPointerType = $state<string | null>(null);

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
		pendingType = stepType;
		pendingPointerType = event.pointerType;

		// For touch inputs, require long press to prevent accidental drags
		if (event.pointerType === 'touch') {
			longPressTimer = window.setTimeout(() => {
				initiateDrag(event, stepType);
			}, longPressDelay);
			return;
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
		pendingType = null;
		pendingPointerType = null;
	}

	function handlePointerMove(event: PointerEvent) {
		// If we haven't started dragging yet, check if pointer moved too much (cancel long press)
		if (pointerStartX !== null && pointerStartY !== null && !dragging) {
			const deltaX = Math.abs(event.clientX - pointerStartX);
			const deltaY = Math.abs(event.clientY - pointerStartY);
			const moved = deltaX > dragThreshold || deltaY > dragThreshold;
			if (!moved) return;
			if (pendingPointerType === 'touch') {
				cancelLongPress();
				return;
			}
			if (pendingType) {
				initiateDrag(event, pendingType);
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
		{ type: 'filter', description: 'Filter rows by conditions' },
		{ type: 'select', description: 'Select specific columns' },
		{ type: 'groupby', description: 'Group and aggregate data' },
		{ type: 'sort', description: 'Sort rows by columns' },
		{ type: 'rename', description: 'Rename columns' },
		{ type: 'drop', description: 'Remove columns' },
		{ type: 'join', description: 'Join with another dataset' },
		{ type: 'expression', description: 'Create computed columns' },
		{ type: 'with_columns', description: 'Add/Update columns' },
		{ type: 'pivot', description: 'Reshape data wide' },
		{ type: 'unpivot', description: 'Reshape data long' },
		{ type: 'fill_null', description: 'Handle missing values' },
		{ type: 'deduplicate', description: 'Remove duplicate rows' },
		{ type: 'explode', description: 'Expand list columns' },
		{ type: 'timeseries', description: 'Date/time operations' },
		{ type: 'string_transform', description: 'Text manipulation' },
		{ type: 'sample', description: 'Random sample rows' },
		{ type: 'limit', description: 'Keep first N rows' },
		{ type: 'topk', description: 'Get top K rows by column' },
		{ type: 'chart', description: 'Visualize data inline' },
		{ type: 'notification', description: 'Send email or Telegram alert' },
		{ type: 'ai', description: 'Transform text using AI' },
		{ type: 'view', description: 'Preview data at this step' },
		{ type: 'union_by_name', description: 'Union rows from multiple datasources' },
		{ type: 'download', description: 'Download data in various formats' }
	];

	// Search/filter
	let search = $state('');
	const filtered = $derived.by(() => {
		const q = search.trim().toLowerCase();
		if (!q) return stepTypes;
		return stepTypes.filter(
			(s) =>
				getStepTypeConfig(s.type).label.toLowerCase().includes(q) ||
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
			class={css({
				color: 'fg.primary',
				borderWidth: '1',
				borderRadius: '0',
				paddingX: '3.5',
				paddingY: '2.25',
				transitionProperty: 'border-color',
				transitionDuration: '160ms',
				transitionTimingFunction: 'ease',
				_focus: { outline: 'none' },
				_focusVisible: { borderColor: 'border.accent' },
				_disabled: { opacity: '0.5', cursor: 'not-allowed', backgroundColor: 'bg.tertiary' },
				_placeholder: { color: 'fg.muted' },
				width: '100%',
				fontSize: 'xs',
				backgroundColor: 'bg.secondary'
			})}
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
			{@const stepConfig = getStepTypeConfig(stepType.type)}
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
				<stepConfig.icon
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
					<span class={css({ fontSize: 'xs', fontWeight: 'medium' })}>{stepConfig.label}</span>
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
