<script lang="ts">
	import type { PipelineStep } from '$lib/types/analysis';
	import type { DataSource } from '$lib/types/datasource';
	import { drag, type DropTarget } from '$lib/stores/drag.svelte';
	import { LayoutGrid } from 'lucide-svelte';
	import StepNode from './StepNode.svelte';
	import ConnectionLine from './ConnectionLine.svelte';
	import DatasourceNode from './DatasourceNode.svelte';

	interface Props {
		steps: PipelineStep[];
		analysisId?: string;
		datasourceId?: string;
		datasource?: DataSource | null;
		tabName?: string;
		onStepClick: (id: string) => void;
		onStepDelete: (id: string) => void;
		onStepToggle: (id: string) => void;
		onInsertStep: (type: string, target: DropTarget) => void;
		onMoveStep: (stepId: string, target: DropTarget) => void;
		onChangeDatasource?: () => void;
		onRenameTab?: (name: string) => void;
	}

	let {
		steps,
		analysisId,
		datasourceId,
		datasource = null,
		tabName: _tabName,
		onStepClick,
		onStepDelete,
		onStepToggle,
		onInsertStep,
		onMoveStep,
		onChangeDatasource: _onChangeDatasource,
		onRenameTab: _onRenameTab
	}: Props = $props();

	// Derived: whether we can accept drops
	let canDrop = $derived(drag.active);

	// Derived: current hovered target index
	let hoverIndex = $derived(drag.target?.index ?? null);

	function getParentId(index: number): string | null {
		if (index <= 0) return null;
		return steps[index - 1]?.id ?? null;
	}

	function getNextId(index: number): string | null {
		return steps[index]?.id ?? null;
	}

	function buildTarget(index: number): DropTarget {
		const parentId = index === 0 ? null : getParentId(index);
		const nextId = index < steps.length ? getNextId(index) : null;
		return { index, parentId, nextId };
	}

	function shouldShowInsert(index: number): boolean {
		if (!drag.isReorder || !drag.stepId) return true;
		const currentIndex = steps.findIndex((step) => step.id === drag.stepId);
		if (currentIndex === -1) return true;
		return index !== currentIndex && index !== currentIndex + 1;
	}

	function isValidTarget(index: number): boolean {
		// For reorder operations, check if we're dropping on ourselves
		if (drag.isReorder && drag.stepId) {
			const currentIndex = steps.findIndex((s) => s.id === drag.stepId);
			// Can't drop on self (same position or adjacent)
			if (index === currentIndex || index === currentIndex + 1) {
				return false;
			}
		}

		const nextId = index < steps.length ? getNextId(index) : null;
		if (!nextId) return true;

		// For reorder, the next step might be the one we're moving
		if (drag.isReorder && nextId === drag.stepId) {
			return true;
		}

		const nextStep = steps.find((s) => s.id === nextId);
		if (!nextStep) return true;
		const deps = nextStep.depends_on ?? [];
		// Valid if no dependencies or single dependency matching expected parent
		if (deps.length === 0) return true;
		if (deps.length > 1) return false;
		const parentId = index === 0 ? null : getParentId(index);
		return deps[0] === parentId;
	}

	function handleDragEnter(event: DragEvent, index: number) {
		if (!drag.active) return;
		event.preventDefault();
		const target = buildTarget(index);
		const valid = isValidTarget(index);
		drag.setTarget(target, valid);
	}

	function handleDragOver(event: DragEvent) {
		if (drag.active) {
			event.preventDefault();
			if (event.dataTransfer) {
				event.dataTransfer.dropEffect = drag.isReorder ? 'move' : 'copy';
			}
		}
	}

	function handleDragLeave(event: DragEvent) {
		const related = event.relatedTarget as Node | null;
		const current = event.currentTarget as Node;
		if (!related || !current.contains(related)) {
			drag.clearTarget();
		}
	}

	function handleDrop(event: DragEvent, index: number) {
		event.preventDefault();
		if (!drag.active) return;

		const target = buildTarget(index);
		const valid = isValidTarget(index);

		if (!valid) {
			drag.end();
			return;
		}

		if (drag.isReorder && drag.stepId) {
			// Moving existing step
			onMoveStep(drag.stepId, target);
		} else if (drag.isInsert && drag.type) {
			// Inserting new step from library
			onInsertStep(drag.type, target);
		}

		drag.end();
	}

	function resolveTargetFromPoint(x: number, y: number): DropTarget | null {
		const zones = Array.from(document.querySelectorAll<HTMLElement>('.insert-zone'));
		const entries = zones
			.map((zone) => {
				const raw = zone.dataset.index;
				const index = raw ? Number(raw) : Number.NaN;
				const rect = zone.getBoundingClientRect();
				return {
					index,
					rect,
					center: rect.top + rect.height / 2
				};
			})
			.filter((item) => Number.isFinite(item.index));

		const entry = entries.find((item) => y >= item.rect.top && y <= item.rect.bottom);
		if (entry) return buildTarget(entry.index);

		const sorted = entries
			.filter((item) => Number.isFinite(item.center))
			.sort((a, b) => a.center - b.center);

		const fallback = sorted.find((item) => y < item.center) ?? sorted.at(-1);
		if (!fallback) return null;

		return buildTarget(fallback.index);
	}

	$effect(() => {
		if (!drag.active) return;
		if (drag.pointerX === null || drag.pointerY === null) return;
		const target = resolveTargetFromPoint(drag.pointerX, drag.pointerY);
		if (!target) {
			drag.clearTarget();
			return;
		}
		const valid = isValidTarget(target.index);
		drag.setTarget(target, valid);
	});

	// Auto-scroll when dragging near edges
	const scrollThreshold = 60;
	const scrollSpeed = 15;

	function autoScroll(canvasEl: HTMLElement, pointerY: number) {
		canvasEl.getBoundingClientRect();
		const viewportHeight = window.innerHeight;

		// Check if pointer is near the bottom of the viewport
		if (pointerY > viewportHeight - scrollThreshold) {
			canvasEl.scrollTop += scrollSpeed;
		}

		// Check if pointer is near the top of the viewport
		if (pointerY < scrollThreshold) {
			canvasEl.scrollTop -= scrollSpeed;
		}
	}

	$effect(() => {
		if (!drag.active) return;
		if (drag.pointerY === null) return;

		const canvas = document.querySelector('.pipeline-canvas') as HTMLElement | null;
		if (!canvas) return;

		const handleScroll = () => {
			if (!drag.active || drag.pointerY === null) return;
			autoScroll(canvas, drag.pointerY);
		};

		const intervalId = window.setInterval(handleScroll, 16);
		return () => window.clearInterval(intervalId);
	});
</script>

<div
	class="pipeline-canvas flex-1 overflow-y-auto p-6"
	style="background-color: var(--bg-secondary); background-image: repeating-linear-gradient(90deg, rgba(0, 0, 0, 0.04) 0, rgba(0, 0, 0, 0.04) 1px, transparent 1px, transparent 64px), linear-gradient(180deg, transparent 0%, var(--bg-tertiary) 100%); min-height: 400px;"
>
	{#if steps.length === 0 && !datasource}
		<div
			class="empty-state flex min-h-[400px] h-full flex-col items-center justify-center text-center"
			style="color: var(--fg-muted);"
		>
			<LayoutGrid size={32} strokeWidth={1.5} class="mb-4" style="color: var(--fg-faint);" />
			<h3 class="m-0 mb-2 text-base font-semibold" style="color: var(--fg-secondary);">
				No pipeline steps
			</h3>
			<p class="m-0 text-sm" style="color: var(--fg-muted);">
				Drag operations from the library and drop here
			</p>
			<div
				class="insert-zone empty-drop flex w-full cursor-default flex-col items-center py-2 transition-all"
				class:ready={canDrop}
				class:active={hoverIndex === 0}
				class:invalid={hoverIndex === 0 && !drag.valid}
				role="button"
				tabindex="0"
				data-index="0"
				ondragenter={(e) => handleDragEnter(e, 0)}
				ondragover={handleDragOver}
				ondragleave={handleDragLeave}
				ondrop={(e) => handleDrop(e, 0)}
			>
				{#if steps.length > 0 || canDrop}
					<ConnectionLine
						fromStepIndex={-1}
						toStepIndex={0}
						totalSteps={steps.length + 1}
						highlighted={hoverIndex === 0}
					/>
				{/if}

				{#if canDrop}
					<div
						class="my-2 flex min-h-7 w-[min(55%,480px)] shrink-0 items-center justify-center rounded-md border-2 border-dashed px-4 py-2 text-center transition-all border-[var(--fg-faint)] bg-transparent hover:border-[var(--fg-muted)] hover:bg-[var(--bg-hover)]"
						class:!border-[var(--fg-primary)]={hoverIndex === 0}
						class:!bg-[var(--bg-tertiary)]={hoverIndex === 0}
						class:!border-[var(--error-border)]={hoverIndex === 0 && !drag.valid}
						class:!bg-[var(--error-bg)]={hoverIndex === 0 && !drag.valid}
					>
						{#if hoverIndex === 0}
							<span class="font-mono text-sm font-medium lowercase text-[var(--fg-primary)]"
								>{drag.type ?? 'step'}</span
							>
						{/if}
					</div>
					<ConnectionLine
						fromStepIndex={-1}
						toStepIndex={0}
						totalSteps={steps.length + 1}
						highlighted={hoverIndex === 0}
					/>
				{/if}
			</div>
		</div>
	{:else}
		<div class="steps-container mx-auto flex w-full max-w-full flex-col items-center" role="list">
			<DatasourceNode
				{datasource}
				{analysisId}
				tabName={_tabName}
				onChangeDatasource={_onChangeDatasource}
				onRenameTab={_onRenameTab}
			/>
			{#if shouldShowInsert(0)}
				<div
					class="insert-zone flex w-full cursor-default flex-col items-center py-2 transition-all"
					class:ready={canDrop}
					class:active={hoverIndex === 0}
					class:invalid={hoverIndex === 0 && !drag.valid}
					role="button"
					tabindex="0"
					data-index="0"
					ondragenter={(e) => handleDragEnter(e, 0)}
					ondragover={handleDragOver}
					ondragleave={handleDragLeave}
					ondrop={(e) => handleDrop(e, 0)}
				>
					<ConnectionLine
						fromStepIndex={-1}
						toStepIndex={0}
						totalSteps={steps.length + 1}
						highlighted={hoverIndex === 0}
					/>
					{#if canDrop}
						<div
							class="my-2 flex min-h-7 w-[min(55%,480px)] shrink-0 items-center justify-center rounded-md border-2 border-dashed px-4 py-2 text-center transition-all border-[var(--fg-faint)] bg-transparent hover:border-[var(--fg-muted)] hover:bg-[var(--bg-hover)]"
							class:!border-[var(--fg-primary)]={hoverIndex === 0}
							class:!bg-[var(--bg-tertiary)]={hoverIndex === 0}
							class:!border-[var(--error-border)]={hoverIndex === 0 && !drag.valid}
							class:!bg-[var(--error-bg)]={hoverIndex === 0 && !drag.valid}
						>
							{#if hoverIndex === 0}
								<span class="font-mono text-sm font-medium lowercase text-[var(--fg-primary)]"
									>{drag.type ?? 'step'}</span
								>
							{/if}
						</div>
						{#if steps.length > 0}
							<ConnectionLine
								fromStepIndex={-1}
								toStepIndex={0}
								totalSteps={steps.length + 1}
								highlighted={hoverIndex === 0}
							/>
						{/if}
					{/if}
				</div>
			{:else if steps.length > 0}
				<div class="insert-spacer flex items-center justify-center py-2" aria-hidden="true">
					<ConnectionLine fromStepIndex={-1} toStepIndex={0} totalSteps={steps.length} />
				</div>
			{/if}
			{#each steps as step, i (step.id)}
				<StepNode
					{step}
					index={i}
					{analysisId}
					{datasourceId}
					allSteps={steps}
					onEdit={onStepClick}
					onDelete={onStepDelete}
					onToggleApply={onStepToggle}
					onTouchMove={onMoveStep}
				/>
				<!-- Connection + Drop zone after each step -->
				{#if i < steps.length - 1 || canDrop}
					{#if shouldShowInsert(i + 1)}
						<div
							class="insert-zone flex w-full cursor-default flex-col items-center py-2 transition-all"
							class:ready={canDrop}
							class:active={hoverIndex === i + 1}
							class:invalid={hoverIndex === i + 1 && !drag.valid}
							role="button"
							tabindex="0"
							data-index={i + 1}
							ondragenter={(e) => handleDragEnter(e, i + 1)}
							ondragover={handleDragOver}
							ondragleave={handleDragLeave}
							ondrop={(e) => handleDrop(e, i + 1)}
						>
							{#if i < steps.length - 1 || !drag.isReorder || drag.stepId !== step.id}
								<ConnectionLine
									fromStepIndex={i}
									toStepIndex={i + 1}
									totalSteps={steps.length}
									highlighted={hoverIndex === i + 1}
								/>
							{/if}
							{#if canDrop}
								<div
									class="my-2 flex min-h-7 w-[min(55%,480px)] shrink-0 items-center justify-center rounded-md border-2 border-dashed px-4 py-2 text-center transition-all border-[var(--fg-faint)] bg-transparent hover:border-[var(--fg-muted)] hover:bg-[var(--bg-hover)]"
									class:!border-[var(--fg-primary)]={hoverIndex === i + 1}
									class:!bg-[var(--bg-tertiary)]={hoverIndex === i + 1}
									class:!border-[var(--error-border)]={hoverIndex === i + 1 && !drag.valid}
									class:!bg-[var(--error-bg)]={hoverIndex === i + 1 && !drag.valid}
								>
									{#if hoverIndex === i + 1}
										<span class="font-mono text-sm font-medium lowercase text-[var(--fg-primary)]"
											>{drag.type ?? 'step'}</span
										>
									{/if}
								</div>
								{#if i < steps.length - 1}
									<ConnectionLine
										fromStepIndex={i}
										toStepIndex={i + 1}
										totalSteps={steps.length}
										highlighted={hoverIndex === i + 1}
									/>
								{/if}
							{/if}
						</div>
					{:else if i < steps.length - 1 || !drag.isReorder || drag.stepId !== step.id}
						<div class="insert-spacer flex items-center justify-center py-2" aria-hidden="true">
							<ConnectionLine fromStepIndex={i} toStepIndex={i + 1} totalSteps={steps.length} />
						</div>
					{/if}
				{/if}
			{/each}
		</div>
	{/if}
</div>

<style>
	:global(body.touch-dragging) .pipeline-canvas {
		overflow: hidden;
		touch-action: none;
	}

	.insert-zone.ready {
		cursor: pointer;
	}

	.insert-zone.ready:hover :global(.connection-line) {
		color: var(--accent-primary);
	}
</style>
