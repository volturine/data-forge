<script lang="ts">
	import { drag, type DropTarget } from '$lib/stores/drag.svelte';

	interface StepType {
		type: string;
		label: string;
		icon: string;
		description: string;
	}

	interface Props {
		onAddStep: (type: string) => void;
		onInsertStep: (type: string, target: DropTarget) => void;
	}

	let { onAddStep, onInsertStep }: Props = $props();

	// Track if we're dragging to prevent click from firing
	let isDragging = $state(false);

	function handleDragStart(event: DragEvent, stepType: string) {
		isDragging = true;
		if (event.dataTransfer) {
			event.dataTransfer.setData('application/x-pipeline-step', stepType);
			event.dataTransfer.effectAllowed = 'copy';
		}
		drag.start(stepType, 'library');
	}

	function handleDragEnd() {
		// Small delay to prevent click from firing after drag
		setTimeout(() => {
			isDragging = false;
		}, 0);
		drag.end();
	}

	function handleClick(stepType: string) {
		// Don't add step if we were dragging
		if (isDragging) return;
		onAddStep(stepType);
	}

	const stepTypes: StepType[] = [
		{ type: 'filter', label: 'Filter', icon: '🔍', description: 'Filter rows by conditions' },
		{ type: 'select', label: 'Select', icon: '📋', description: 'Select specific columns' },
		{ type: 'groupby', label: 'Group By', icon: '📊', description: 'Group and aggregate data' },
		{ type: 'sort', label: 'Sort', icon: '↕️', description: 'Sort rows by columns' },
		{ type: 'rename', label: 'Rename', icon: '✏️', description: 'Rename columns' },
		{ type: 'drop', label: 'Drop', icon: '🗑️', description: 'Remove columns' },
		{ type: 'join', label: 'Join', icon: '🔗', description: 'Join with another dataset' },
		{ type: 'expression', label: 'Expression', icon: '🧮', description: 'Create computed columns' },
		{ type: 'pivot', label: 'Pivot', icon: '🔄', description: 'Reshape data wide' },
		{ type: 'unpivot', label: 'Unpivot', icon: '🔃', description: 'Reshape data long' },
		{ type: 'fill_null', label: 'Fill Null', icon: '🔧', description: 'Handle missing values' },
		{ type: 'deduplicate', label: 'Deduplicate', icon: '🧹', description: 'Remove duplicate rows' },
		{ type: 'explode', label: 'Explode', icon: '💥', description: 'Expand list columns' },
		{ type: 'timeseries', label: 'Time Series', icon: '📅', description: 'Date/time operations' },
		{
			type: 'string_transform',
			label: 'String Transform',
			icon: '📝',
			description: 'Text manipulation'
		},
		{ type: 'sample', label: 'Sample', icon: '🎲', description: 'Random sample rows' },
		{ type: 'limit', label: 'Limit', icon: '✂️', description: 'Keep first N rows' },
		{ type: 'topk', label: 'Top K', icon: '🏆', description: 'Get top K rows by column' },
		{
			type: 'null_count',
			label: 'Null Count',
			icon: '❓',
			description: 'Count null values per column'
		},
		{
			type: 'value_counts',
			label: 'Value Counts',
			icon: '📊',
			description: 'Get value frequencies'
		},
		{ type: 'view', label: 'View', icon: '👁️', description: 'Preview data at this step' }
	];

	// Quick insert selected type
	let selectedType = $state<string | null>(null);
</script>

<div class="step-library">
	<h3>Operations</h3>
	<div class="step-list" role="list">
		{#each stepTypes as stepType (stepType.type)}
			<button
				class="step-button"
				onclick={() => handleClick(stepType.type)}
				ondragstart={(event) => handleDragStart(event, stepType.type)}
				ondragend={handleDragEnd}
				type="button"
				draggable="true"
				data-step={stepType.type}
			>
				<span class="step-icon">{stepType.icon}</span>
				<div class="step-info">
					<span class="step-label">{stepType.label}</span>
					<span class="step-description">{stepType.description}</span>
				</div>
			</button>
		{/each}
	</div>

	<div class="fallback-actions">
		<h4>Quick Insert</h4>
		<div class="fallback-controls">
			<select
				value={selectedType ?? ''}
				onchange={(event) => (selectedType = event.currentTarget.value || null)}
			>
				<option value="">Select operation...</option>
				{#each stepTypes as stepType (stepType.type)}
					<option value={stepType.type}>{stepType.label}</option>
				{/each}
			</select>
			<div class="fallback-buttons">
				<button
					type="button"
					disabled={!selectedType}
					onclick={() => {
						if (selectedType) {
							onAddStep(selectedType);
							selectedType = null;
						}
					}}
				>
					Add to end
				</button>
				<button
					type="button"
					disabled={!selectedType}
					onclick={() => {
						if (selectedType) {
							onInsertStep(selectedType, { index: 0, parentId: null, nextId: null });
							selectedType = null;
						}
					}}
				>
					Insert at start
				</button>
			</div>
		</div>
	</div>
</div>

<style>
	.step-library {
		width: 240px;
		border-right: 1px solid var(--border-primary);
		padding: 1rem;
		background-color: var(--bg-tertiary);
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	h3 {
		margin-top: 0;
		margin-bottom: 1rem;
		font-size: 1.125rem;
		color: var(--fg-primary);
		flex-shrink: 0;
	}

	.step-list {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		overflow-y: auto;
		flex: 1;
		min-height: 0;
	}

	.step-button {
		display: flex;
		align-items: center;
		justify-content: flex-start;
		gap: 0.75rem;
		padding: 0.75rem;
		background-color: var(--bg-primary);
		border: 1px solid var(--border-primary);
		border-radius: 6px;
		cursor: grab;
		transition: all 0.2s;
		text-align: left;
	}

	.step-button:hover {
		border-color: var(--accent-primary);
		background-color: var(--bg-hover);
		transform: translateX(4px);
	}

	.step-button:active {
		cursor: grabbing;
	}

	.step-icon {
		font-size: 1.5rem;
		flex-shrink: 0;
	}

	.step-info {
		display: flex;
		flex-direction: column;
		gap: 0.125rem;
		align-items: flex-start;
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

	.fallback-actions {
		margin-top: var(--space-4);
		padding-top: var(--space-3);
		border-top: 1px solid var(--border-primary);
		flex-shrink: 0;
	}

	.fallback-actions h4 {
		margin: 0 0 var(--space-2) 0;
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--fg-muted);
	}

	.fallback-controls {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.fallback-controls select {
		padding: 0.5rem;
		border: 1px solid var(--form-control-border);
		border-radius: var(--radius-sm);
		background-color: var(--form-control-bg);
		color: var(--fg-primary);
	}

	.fallback-buttons {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2);
	}

	.fallback-controls button {
		padding: 0.5rem;
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		background-color: var(--bg-primary);
		color: var(--fg-primary);
		cursor: pointer;
	}

	.fallback-controls button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
