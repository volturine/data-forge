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
		savedSteps?: PipelineStep[];
		saveStatus?: 'saved' | 'unsaved' | 'saving';
		analysisId?: string;
		datasourceId?: string;
		previewDatasourceId?: string;
		datasource?: DataSource | null;
		tabName?: string;
		onStepClick: (id: string) => void;
		onStepDelete: (id: string) => void;
		onInsertStep: (type: string, target: DropTarget) => void;
		onMoveStep: (stepId: string, target: DropTarget) => void;
		onChangeDatasource?: () => void;
		onRenameTab?: (name: string) => void;
	}

	let {
		steps,
		savedSteps = [],
		saveStatus = 'saved',
		analysisId,
		datasourceId,
		previewDatasourceId,
		datasource = null,
		tabName: _tabName,
		onStepClick,
		onStepDelete,
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
		const state = drag as typeof drag & {
			touchActive: boolean;
			pointerX: number | null;
			pointerY: number | null;
		};
		if (!state.active) return;
		if (!state.touchActive) return;
		if (state.pointerX === null || state.pointerY === null) return;
		const target = resolveTargetFromPoint(state.pointerX, state.pointerY);
		if (!target) {
			state.clearTarget();
			return;
		}
		const valid = isValidTarget(target.index);
		state.setTarget(target, valid);
	});
</script>

<div class="pipeline-canvas">
	{#if steps.length === 0 && !datasource}
		<div class="empty-state">
			<LayoutGrid size={32} strokeWidth={1.5} />
			<h3>No pipeline steps</h3>
			<p>Drag operations from the library and drop here</p>
			<div
				class="insert-zone empty-drop"
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
						class="drop-slot"
						class:active={hoverIndex === 0}
						class:invalid={hoverIndex === 0 && !drag.valid}
					>
						{#if hoverIndex === 0}
							<span class="slot-label">{drag.type ?? 'step'}</span>
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
		<div class="steps-container" role="list">
			<DatasourceNode
				{datasource}
				tabName={_tabName}
				onChangeDatasource={_onChangeDatasource}
				onRenameTab={_onRenameTab}
			/>
			{#if shouldShowInsert(0)}
				<div
					class="insert-zone"
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
							class="drop-slot"
							class:active={hoverIndex === 0}
							class:invalid={hoverIndex === 0 && !drag.valid}
						>
							{#if hoverIndex === 0}
								<span class="slot-label">{drag.type ?? 'step'}</span>
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
				<div class="insert-spacer" aria-hidden="true">
					<ConnectionLine fromStepIndex={-1} toStepIndex={0} totalSteps={steps.length} />
				</div>
			{/if}
		{#each steps as step, i (step.id)}
			<StepNode
				{step}
				index={i}
				{analysisId}
				datasourceId={previewDatasourceId ?? datasourceId}
				allSteps={steps}
				{savedSteps}
				{saveStatus}
				onEdit={onStepClick}
				onDelete={onStepDelete}
				onTouchMove={onMoveStep}
			/>
				<!-- Connection + Drop zone after each step -->
				{#if i < steps.length - 1 || canDrop}
					{#if shouldShowInsert(i + 1)}
						<div
							class="insert-zone"
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
									class="drop-slot"
									class:active={hoverIndex === i + 1}
									class:invalid={hoverIndex === i + 1 && !drag.valid}
								>
									{#if hoverIndex === i + 1}
										<span class="slot-label">{drag.type ?? 'step'}</span>
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
						<div class="insert-spacer" aria-hidden="true">
							<ConnectionLine fromStepIndex={i} toStepIndex={i + 1} totalSteps={steps.length} />
						</div>
					{/if}
				{/if}
			{/each}
		</div>
	{/if}
</div>

<style>
	.pipeline-canvas {
		flex: 1;
		padding: var(--space-6);
		background-color: var(--bg-secondary);
		background-image:
			repeating-linear-gradient(
				90deg,
				rgba(0, 0, 0, 0.04) 0,
				rgba(0, 0, 0, 0.04) 1px,
				transparent 1px,
				transparent 64px
			),
			linear-gradient(180deg, transparent 0%, var(--bg-tertiary) 100%);
		overflow-y: auto;
		min-height: 400px;
	}

	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100%;
		min-height: 400px;
		color: var(--fg-muted);
		text-align: center;
	}

	.empty-state :global(svg) {
		color: var(--fg-faint);
		margin-bottom: var(--space-4);
	}

	.empty-state h3 {
		margin: 0 0 var(--space-2) 0;
		font-size: var(--text-base);
		font-weight: 600;
		color: var(--fg-secondary);
	}

	.empty-state p {
		margin: 0;
		font-size: var(--text-sm);
		color: var(--fg-muted);
	}

	.steps-container {
		display: flex;
		flex-direction: column;
		align-items: center;
		width: 100%;
		max-width: 100%;
		margin: 0 auto;
	}

	/* Insert zone - wraps connection line and drop area */
	.insert-zone {
		display: flex;
		flex-direction: column;
		align-items: center;
		width: 100%;
		cursor: default;
		transition: all var(--transition);
		padding: var(--space-2) 0;
	}

	.insert-spacer {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: var(--space-2) 0;
	}

	/* Ensure connection lines never stretch */
	.insert-zone :global(.connection-line),
	.insert-spacer :global(.connection-line) {
		flex-shrink: 0;
	}

	.insert-zone.ready {
		cursor: pointer;
	}

	.insert-zone.ready:hover :global(.connection-line) {
		color: var(--accent-primary);
	}

	/* Drop slot - always visible during drag, highlights on hover */
	.drop-slot {
		width: min(55%, 480px);
		padding: var(--space-2) var(--space-4);
		background-color: transparent;
		border: 2px dashed var(--fg-faint);
		border-radius: var(--radius-md);
		text-align: center;
		min-height: 28px;
		display: flex;
		align-items: center;
		justify-content: center;
		transition: all var(--transition);
		margin: var(--space-2) 0;
		flex-shrink: 0;
	}

	.drop-slot:hover {
		border-color: var(--fg-muted);
		background-color: var(--bg-hover);
	}

	.drop-slot.active {
		border-color: var(--fg-primary);
		background-color: var(--bg-tertiary);
	}

	.drop-slot.invalid {
		border-color: var(--error-border);
		background-color: var(--error-bg);
	}

	.slot-label {
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--fg-primary);
		text-transform: lowercase;
	}

	.drop-slot.invalid .slot-label {
		color: var(--error-fg);
	}

	@keyframes fadeIn {
		from {
			opacity: 0;
			transform: scale(0.95);
		}
		to {
			opacity: 1;
			transform: scale(1);
		}
	}
</style>
