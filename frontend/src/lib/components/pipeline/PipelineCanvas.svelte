<script lang="ts">
	import type { PipelineStep } from '$lib/types/analysis';
	import StepNode from './StepNode.svelte';
	import ConnectionLine from './ConnectionLine.svelte';

	interface DropTarget {
		index: number;
		parentId: string | null;
		nextId: string | null;
		valid: boolean;
	}

	interface Props {
		steps: PipelineStep[];
		datasourceId?: string;
		onStepClick: (id: string) => void;
		onStepDelete: (id: string) => void;
		onInsertStep: (type: string, target: DropTarget) => void;
		onBranchStep: (type: string, parentId: string) => void;
		selectedType: string | null;
	}

	let {
		steps,
		datasourceId,
		onStepClick,
		onStepDelete,
		onInsertStep,
		onBranchStep,
		selectedType
	}: Props = $props();

	let draggedType = $state<string | null>(null);
	let activeTarget = $state<DropTarget | null>(null);

	function getParentId(indexValue: number): string | null {
		if (indexValue <= 0) {
			return null;
		}
		const prev = steps[indexValue - 1];
		return prev ? prev.id : null;
	}

	function getNextId(indexValue: number): string | null {
		const next = steps[indexValue];
		return next ? next.id : null;
	}

	function buildTarget(indexValue: number): DropTarget {
		const parentId = indexValue === 0 ? null : getParentId(indexValue);
		const nextId = indexValue < steps.length ? getNextId(indexValue) : null;
		const nextStep = nextId ? steps.find((item) => item.id === nextId) : null;
		const nextDeps = nextStep?.depends_on ?? [];
		const valid = nextDeps.length <= 1 && (nextDeps.length === 0 || nextDeps[0] === parentId);
		return { index: indexValue, parentId, nextId, valid };
	}

	function handleDragStart(type: string) {
		draggedType = type;
	}

	function handleDragEnd() {
		draggedType = null;
		activeTarget = null;
	}


	function handleDrop(event: DragEvent | null, indexValue: number) {
		const type = draggedType ?? selectedType ?? event?.dataTransfer?.getData('text/plain') ?? null;
		if (!type) {
			return;
		}
		const target = buildTarget(indexValue);
		activeTarget = target;
		if (!target.valid) {
			return;
		}
		onInsertStep(type, target);
		handleDragEnd();
	}

	function handleDragOver(event: DragEvent, indexValue: number) {
		const type = draggedType ?? event.dataTransfer?.getData('text/plain') ?? null;
		if (!type) {
			return;
		}
		draggedType = type;
		event.preventDefault();
		const target = buildTarget(indexValue);
		activeTarget = target;
	}

	function handleBranch(type: string, parentId: string) {
		onBranchStep(type, parentId);
		handleDragEnd();
	}
</script>

<div class="pipeline-canvas">
	{#if steps.length === 0}
		<div class="empty-state">
			<svg
				width="32"
				height="32"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="1.5"
			>
				<rect x="3" y="3" width="18" height="18" rx="1" />
				<path d="M3 9h18M9 3v18" />
			</svg>
			<h3>No pipeline steps</h3>
			<p>Add operations from the library to build your pipeline</p>
		</div>
	{:else}
		<div class="steps-container">
			{#if steps.length > 0}
					<div
						class="drop-target"
						ondragover={(event) => handleDragOver(event, 0)}
						ondrop={(event) => handleDrop(event, 0)}
						class:active={activeTarget?.index === 0}
						class:invalid={activeTarget?.index === 0 && activeTarget && !activeTarget.valid}
						data-label="Start"
						onclick={() => handleDrop(null, 0)}
					></div>

			{/if}
			{#each steps as step, i (step.id)}
				{#if i > 0}
					<ConnectionLine fromStepIndex={i - 1} toStepIndex={i} totalSteps={steps.length} />
				{/if}
				<StepNode
					{step}
					index={i}
					{datasourceId}
					allSteps={steps}
					onEdit={onStepClick}
					onDelete={onStepDelete}
					onDragStart={handleDragStart}
					onDragEnd={handleDragEnd}
					onBranch={handleBranch}
				/>
				<div
					class="drop-target"
					ondragover={(event) => handleDragOver(event, i + 1)}
					ondrop={(event) => handleDrop(event, i + 1)}
					class:active={activeTarget?.index === i + 1}
					class:invalid={activeTarget?.index === i + 1 && activeTarget && !activeTarget.valid}
					data-label="After {step.type}"
					onclick={() => handleDrop(null, i + 1)}
				></div>
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

	.empty-state svg {
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
		max-width: 400px;
		margin: 0 auto;
	}

	.drop-target {
		width: min(75%, 480px);
		height: 36px;
		display: flex;
		align-items: center;
		justify-content: center;
		border: 1px dashed transparent;
		border-radius: var(--radius-sm);
		color: var(--fg-muted);
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.08em;
		transition: all var(--transition-fast);
	}

	.drop-target::after {
		content: attr(data-label);
	}

	.drop-target.active {
		border-color: var(--accent-primary);
		background-color: var(--accent-soft);
		color: var(--accent-primary);
	}

	.drop-target.invalid {
		border-color: var(--error-border);
		background-color: var(--error-bg);
		color: var(--error-fg);
		cursor: not-allowed;
	}

	.drop-target:hover {
		border-color: var(--border-secondary);
		background-color: var(--bg-hover);
	}

</style>
