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
		},
		{
			type: 'pivot',
			label: 'Pivot',
			icon: '🔄',
			description: 'Reshape data wide'
		},
		{
			type: 'fill_null',
			label: 'Fill Null',
			icon: '🔧',
			description: 'Handle missing values'
		},
		{
			type: 'deduplicate',
			label: 'Deduplicate',
			icon: '🧹',
			description: 'Remove duplicate rows'
		},
		{
			type: 'explode',
			label: 'Explode',
			icon: '💥',
			description: 'Expand list columns'
		},
		{
			type: 'timeseries',
			label: 'Time Series',
			icon: '📅',
			description: 'Date/time operations'
		},
		{
			type: 'string_transform',
			label: 'String Transform',
			icon: '📝',
			description: 'Text manipulation'
		},
		{
			type: 'view',
			label: 'View',
			icon: '👁️',
			description: 'Preview data at this step'
		}
	];
</script>

<div class="step-library">
	<h3>Operations</h3>
	<div class="step-list">
		{#each stepTypes as stepType (stepType.type)}
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
		border-right: 1px solid var(--border-primary);
		padding: 1rem;
		background-color: var(--bg-tertiary);
	}

	h3 {
		margin-top: 0;
		margin-bottom: 1rem;
		font-size: 1.125rem;
		color: var(--fg-primary);
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
		background-color: var(--bg-primary);
		border: 1px solid var(--border-primary);
		border-radius: 6px;
		cursor: pointer;
		transition: all 0.2s;
		text-align: left;
	}

	.step-button:hover {
		border-color: var(--accent-primary);
		background-color: var(--bg-hover);
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
		color: var(--fg-primary);
		font-size: 0.875rem;
	}

	.step-description {
		font-size: 0.75rem;
		color: var(--fg-muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
</style>
