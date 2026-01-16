<script lang="ts">
	interface StepType {
		type: string;
		label: string;
		icon: string;
		description: string;
	}

	interface Props {
		onAddStep: (type: string) => void;
	}

	let { onAddStep }: Props = $props();

	const stepTypes: StepType[] = [
		{
			type: 'filter',
			label: 'Filter',
			icon: '🔍',
			description: 'Filter rows by conditions'
		},
		{
			type: 'select',
			label: 'Select',
			icon: '📋',
			description: 'Select specific columns'
		},
		{
			type: 'groupby',
			label: 'Group By',
			icon: '📊',
			description: 'Group and aggregate data'
		},
		{
			type: 'sort',
			label: 'Sort',
			icon: '↕️',
			description: 'Sort rows by columns'
		},
		{
			type: 'rename',
			label: 'Rename',
			icon: '✏️',
			description: 'Rename columns'
		},
		{
			type: 'drop',
			label: 'Drop',
			icon: '🗑️',
			description: 'Remove columns'
		},
		{
			type: 'join',
			label: 'Join',
			icon: '🔗',
			description: 'Join with another dataset'
		},
		{
			type: 'expression',
			label: 'Expression',
			icon: '🧮',
			description: 'Create computed columns'
		}
	];
</script>

<div class="step-library">
	<h3>Operations</h3>
	<div class="step-list">
		{#each stepTypes as stepType}
			<button class="step-button" onclick={() => onAddStep(stepType.type)} type="button">
				<span class="step-icon">{stepType.icon}</span>
				<div class="step-info">
					<span class="step-label">{stepType.label}</span>
					<span class="step-description">{stepType.description}</span>
				</div>
			</button>
		{/each}
	</div>
</div>

<style>
	.step-library {
		width: 240px;
		border-right: 1px solid #ddd;
		padding: 1rem;
		background-color: #f8f9fa;
	}

	h3 {
		margin-top: 0;
		margin-bottom: 1rem;
		font-size: 1.125rem;
		color: #333;
	}

	.step-list {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.step-button {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.75rem;
		background-color: white;
		border: 1px solid #ddd;
		border-radius: 6px;
		cursor: pointer;
		transition: all 0.2s;
		text-align: left;
	}

	.step-button:hover {
		border-color: #007bff;
		background-color: #f0f8ff;
		transform: translateX(4px);
	}

	.step-icon {
		font-size: 1.5rem;
		flex-shrink: 0;
	}

	.step-info {
		display: flex;
		flex-direction: column;
		gap: 0.125rem;
		min-width: 0;
	}

	.step-label {
		font-weight: 600;
		color: #333;
		font-size: 0.875rem;
	}

	.step-description {
		font-size: 0.75rem;
		color: #6c757d;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
</style>
