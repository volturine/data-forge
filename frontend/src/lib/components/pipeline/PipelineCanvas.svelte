<script lang="ts">
	import type { PipelineStep } from '$lib/types/analysis';
	import StepNode from './StepNode.svelte';
	import ConnectionLine from './ConnectionLine.svelte';

	interface Props {
		steps: PipelineStep[];
		onStepClick: (id: string) => void;
		onStepDelete: (id: string) => void;
	}

	let { steps, onStepClick, onStepDelete }: Props = $props();
</script>

<div class="pipeline-canvas">
	{#if steps.length === 0}
		<div class="empty-state">
			<div class="empty-icon">📊</div>
			<h3>No pipeline steps yet</h3>
			<p>Add operations from the library to build your data pipeline</p>
		</div>
	{:else}
		<div class="steps-container">
			{#each steps as step, i}
				{#if i > 0}
					<ConnectionLine
						fromStepIndex={i - 1}
						toStepIndex={i}
						totalSteps={steps.length}
					/>
				{/if}
				<StepNode {step} index={i} onEdit={onStepClick} onDelete={onStepDelete} />
			{/each}
		</div>
	{/if}
</div>

<style>
	.pipeline-canvas {
		flex: 1;
		padding: 2rem;
		background-color: #f8f9fa;
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
		color: #6c757d;
	}

	.empty-icon {
		font-size: 4rem;
		margin-bottom: 1rem;
		opacity: 0.5;
	}

	.empty-state h3 {
		margin: 0 0 0.5rem 0;
		font-size: 1.5rem;
		color: #495057;
	}

	.empty-state p {
		margin: 0;
		font-size: 1rem;
	}

	.steps-container {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0;
		max-width: 500px;
		margin: 0 auto;
	}
</style>
