<script lang="ts">
	import type { PipelineStep } from '$lib/types/analysis';
	import StepNode from './StepNode.svelte';
	import ConnectionLine from './ConnectionLine.svelte';

	interface Props {
		steps: PipelineStep[];
		datasourceId?: string;
		onStepClick: (id: string) => void;
		onStepDelete: (id: string) => void;
	}

	let { steps, datasourceId, onStepClick, onStepDelete }: Props = $props();
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
				/>
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
</style>
