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
		datasourceId?: string;
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
		datasourceId,
		datasource = null,
		tabName,
		onStepClick,
		onStepDelete,
		onInsertStep,
		onMoveStep,
		onChangeDatasource,
		onRenameTab
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
</script>

<div class="pipeline-canvas">
	{#if steps.length === 0 && !datasource}
		<div class="empty-state">
			<LayoutGrid size={32} strokeWidth={1.5} />
			<h3>No pipeline steps</h3>
			<p>Drag operations from the library and drop here</p>
			<!-- svelte-ignore a11y_consider_explicit_label -->
			<div
				class="drop-target empty-drop"
				class:ready={canDrop}
				class:active={hoverIndex === 0}
				role="button"
				tabindex="0"
				ondragenter={(e) => handleDragEnter(e, 0)}
				ondragover={handleDragOver}
				ondragleave={handleDragLeave}
				ondrop={(e) => handleDrop(e, 0)}
				data-label={canDrop ? 'Drop here to add first step' : ''}
			></div>
		</div>
	{:else}
		<div class="steps-container" role="list">
			<!-- Datasource node (non-removable root) -->
			{#if datasource}
				<DatasourceNode {datasource} {tabName} {onChangeDatasource} {onRenameTab} />
			{/if}

			<!-- Connection + Drop zone before first step (after datasource) -->
			<!-- svelte-ignore a11y_consider_explicit_label -->
			<div
				class="insert-zone"
				class:ready={canDrop}
				class:active={hoverIndex === 0}
				class:invalid={hoverIndex === 0 && !drag.valid}
				role="button"
				tabindex="0"
				ondragenter={(e) => handleDragEnter(e, 0)}
				ondragover={handleDragOver}
				ondragleave={handleDragLeave}
				ondrop={(e) => handleDrop(e, 0)}
			>
				<ConnectionLine fromStepIndex={-1} toStepIndex={0} totalSteps={steps.length + 1} highlighted={hoverIndex === 0} />
				{#if hoverIndex === 0 && canDrop}
					<div class="insert-preview" class:invalid={!drag.valid}>
						<span class="insert-label">{drag.type ?? 'step'}</span>
					</div>
					<ConnectionLine fromStepIndex={-1} toStepIndex={0} totalSteps={steps.length + 1} highlighted />
				{/if}
			</div>

			{#each steps as step, i (step.id)}
				<StepNode
					{step}
					index={i}
					{datasourceId}
					allSteps={steps}
					onEdit={onStepClick}
					onDelete={onStepDelete}
				/>
				<!-- Connection + Drop zone after each step -->
				<!-- svelte-ignore a11y_consider_explicit_label -->
				<div
					class="insert-zone"
					class:ready={canDrop}
					class:active={hoverIndex === i + 1}
					class:invalid={hoverIndex === i + 1 && !drag.valid}
					role="button"
					tabindex="0"
					ondragenter={(e) => handleDragEnter(e, i + 1)}
					ondragover={handleDragOver}
					ondragleave={handleDragLeave}
					ondrop={(e) => handleDrop(e, i + 1)}
				>
					<ConnectionLine fromStepIndex={i} toStepIndex={i + 1} totalSteps={steps.length} highlighted={hoverIndex === i + 1} />
					{#if hoverIndex === i + 1 && canDrop}
						<div class="insert-preview" class:invalid={!drag.valid}>
							<span class="insert-label">{drag.type ?? 'step'}</span>
						</div>
						<ConnectionLine fromStepIndex={i} toStepIndex={i + 1} totalSteps={steps.length} highlighted />
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.pipeline-canvas {
		flex: 1;
		padding: var(--space-6);
		background-color: var(--bg-secondary);
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
		gap: 0;
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
		transition: all var(--transition-fast);
	}

	.insert-zone.ready {
		cursor: pointer;
	}

	.insert-zone.ready:hover :global(.connection-line) {
		color: var(--accent-primary);
	}

	/* Insert preview - shows where the node will be inserted */
	.insert-preview {
		width: min(55%, 480px);
		padding: var(--space-3) var(--space-4);
		background-color: var(--accent-soft);
		border: 2px dashed var(--accent-primary);
		border-radius: var(--radius-md);
		text-align: center;
		animation: fadeIn 0.15s ease-out;
	}

	.insert-preview.invalid {
		background-color: var(--error-bg);
		border-color: var(--error-border);
	}

	.insert-preview.invalid .insert-label {
		color: var(--error-fg);
	}

	.insert-label {
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--accent-primary);
		text-transform: lowercase;
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

	.drop-target {
		width: min(55%, 480px);
		height: 8px;
		display: flex;
		align-items: center;
		justify-content: center;
		border: 1px dashed transparent;
		border-radius: var(--radius-sm);
		color: var(--fg-faint);
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.08em;
		transition: all var(--transition-fast);
		background: transparent;
		cursor: default;
		margin: -4px 0;
	}

	.drop-target::after {
		content: attr(data-label);
	}

	.drop-target.ready {
		height: 24px;
		margin: 0;
		border-color: var(--border-secondary);
		color: var(--fg-muted);
		cursor: pointer;
	}

	.drop-target.ready:hover {
		height: 32px;
		border-color: var(--accent-primary);
		background-color: var(--bg-hover);
		color: var(--accent-primary);
	}

	.drop-target.active {
		height: 32px;
		margin: 0;
		border-color: var(--accent-primary);
		background-color: var(--accent-soft);
		color: var(--accent-primary);
	}

	.drop-target.empty-drop {
		width: 100%;
		max-width: 400px;
		height: 80px;
		margin-top: var(--space-4);
		border-style: dashed;
		border-color: var(--border-secondary);
	}

	.drop-target.empty-drop.ready {
		border-color: var(--accent-primary);
	}
</style>
