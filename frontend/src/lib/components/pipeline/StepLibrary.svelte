<script lang="ts">
	interface StepType {
		type: string;
		label: string;
		icon: string;
		description: string;
	}


	interface InsertTarget {
		index: number;
		parentId: string | null;
		nextId: string | null;
		valid: boolean;
	}

	interface Props {
		onAddStep: (type: string) => void;
		onInsertStep: (type: string, target: InsertTarget) => void;
		onBranchStep: (type: string, parentId: string | null) => void;
		onDragStart: (type: string) => void;
		onDragEnd: () => void;
		selectedType: string | null;
		onSelectType: (type: string | null) => void;
	}

	let { onAddStep, onInsertStep, onBranchStep, onDragStart, onDragEnd, selectedType, onSelectType }: Props =
		$props();

	function handleDragStart(event: DragEvent, stepType: string) {
		if (event.dataTransfer) {
			event.dataTransfer.setData('text/plain', stepType);
			event.dataTransfer.effectAllowed = 'move';
		}
		onDragStart(stepType);
	}

	function handleDragEnd() {
		onDragEnd();
	}

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
			type: 'unpivot',
			label: 'Unpivot',
			icon: '🔃',
			description: 'Reshape data long'
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
			type: 'sample',
			label: 'Sample',
			icon: '🎲',
			description: 'Random sample rows'
		},
		{
			type: 'limit',
			label: 'Limit',
			icon: '✂️',
			description: 'Keep first N rows'
		},
		{
			type: 'topk',
			label: 'Top K',
			icon: '🏆',
			description: 'Get top K rows by column'
		},
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
	<div class="step-list" ondragend={handleDragEnd}>
		{#each stepTypes as stepType (stepType.type)}
			<button
				class="step-button"
				onclick={() => onAddStep(stepType.type)}
				ondragstart={(event) => handleDragStart(event, stepType.type)}
				ondragend={handleDragEnd}
				type="button"
				draggable="true"
				data-step="{stepType.type}"
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
			<select value={selectedType ?? ''} onchange={(event) => onSelectType(event.currentTarget.value || null)}>
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
							onBranchStep(selectedType, null);
							onSelectType(null);
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
							const target: InsertTarget = {
								index: 0,
								parentId: null,
								nextId: null,
								valid: true
							};
							onInsertStep(selectedType, target);
							onSelectType(null);
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

	.fallback-actions {
		margin-top: var(--space-4);
		padding-top: var(--space-3);
		border-top: 1px solid var(--border-primary);
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
