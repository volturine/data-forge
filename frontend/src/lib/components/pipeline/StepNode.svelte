<script lang="ts">
	import type { PipelineStep } from '$lib/types/analysis';

	interface Props {
		step: PipelineStep;
		index: number;
		onEdit: (id: string) => void;
		onDelete: (id: string) => void;
	}

	let { step, index, onEdit, onDelete }: Props = $props();

	const typeIcons: Record<string, string> = {
		filter: '🔍',
		select: '📋',
		groupby: '📊',
		sort: '↕️',
		rename: '✏️',
		drop: '🗑️',
		join: '🔗',
		expression: '🧮'
	};

	const typeLabels: Record<string, string> = {
		filter: 'Filter',
		select: 'Select',
		groupby: 'Group By',
		sort: 'Sort',
		rename: 'Rename',
		drop: 'Drop',
		join: 'Join',
		expression: 'Expression'
	};

	const typeColors: Record<string, string> = {
		filter: '#17a2b8',
		select: '#28a745',
		groupby: '#ffc107',
		sort: '#6f42c1',
		rename: '#fd7e14',
		drop: '#dc3545',
		join: '#20c997',
		expression: '#007bff'
	};

	function getConfigSummary(step: PipelineStep): string {
		switch (step.type) {
			case 'filter':
				const conditions = step.config.conditions as Array<{
					column: string;
					operator: string;
					value: string;
				}>;
				if (!conditions || conditions.length === 0) return 'No conditions';
				return `${conditions.length} condition${conditions.length > 1 ? 's' : ''}`;

			case 'select':
				const columns = step.config.columns as string[];
				if (!columns || columns.length === 0) return 'No columns selected';
				return `${columns.length} column${columns.length > 1 ? 's' : ''}`;

			case 'groupby':
				const groupBy = step.config.groupBy as string[];
				const aggregations = step.config.aggregations as Array<unknown>;
				if (!groupBy || groupBy.length === 0) return 'No grouping';
				return `Group by ${groupBy.length}, ${aggregations?.length || 0} agg${aggregations?.length !== 1 ? 's' : ''}`;

			case 'sort':
				const sortRules = step.config as unknown as Array<{ column: string; descending: boolean }>;
				if (!Array.isArray(sortRules) || sortRules.length === 0) return 'No sort rules';
				return `Sort by ${sortRules.length} column${sortRules.length > 1 ? 's' : ''}`;

			default:
				return 'Not configured';
		}
	}

	let icon = $derived(typeIcons[step.type] || '❓');
	let label = $derived(typeLabels[step.type] || step.type);
	let color = $derived(typeColors[step.type] || '#6c757d');
	let summary = $derived(getConfigSummary(step));
</script>

<div class="step-node">
	<div class="connection-point top"></div>

	<div class="step-content">
		<div class="step-header">
			<div class="step-badge" style="background-color: {color};">
				<span class="step-icon">{icon}</span>
				<span class="step-type">{label}</span>
			</div>
			<span class="step-number">#{index + 1}</span>
		</div>

		<div class="step-summary">
			{summary}
		</div>

		<div class="step-actions">
			<button class="action-btn edit-btn" onclick={() => onEdit(step.id)} type="button">
				Edit
			</button>
			<button class="action-btn delete-btn" onclick={() => onDelete(step.id)} type="button">
				Delete
			</button>
		</div>
	</div>

	<div class="connection-point bottom"></div>
</div>

<style>
	.step-node {
		position: relative;
		width: 100%;
		max-width: 400px;
	}

	.connection-point {
		position: absolute;
		left: 50%;
		transform: translateX(-50%);
		width: 12px;
		height: 12px;
		background-color: #007bff;
		border: 2px solid white;
		border-radius: 50%;
		box-shadow: 0 0 0 2px #007bff;
		z-index: 2;
	}

	.connection-point.top {
		top: -6px;
	}

	.connection-point.bottom {
		bottom: -6px;
	}

	.step-content {
		background-color: white;
		border: 2px solid #ddd;
		border-radius: 8px;
		padding: 1rem;
		box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
		transition: all 0.2s;
	}

	.step-content:hover {
		border-color: #007bff;
		box-shadow: 0 4px 8px rgba(0, 123, 255, 0.2);
	}

	.step-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 0.75rem;
	}

	.step-badge {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.375rem 0.75rem;
		border-radius: 6px;
		color: white;
		font-weight: 600;
		font-size: 0.875rem;
	}

	.step-icon {
		font-size: 1.125rem;
	}

	.step-type {
		text-transform: uppercase;
		letter-spacing: 0.025em;
	}

	.step-number {
		font-size: 0.75rem;
		color: #6c757d;
		font-weight: 500;
	}

	.step-summary {
		padding: 0.75rem;
		background-color: #f8f9fa;
		border-radius: 4px;
		font-size: 0.875rem;
		color: #495057;
		margin-bottom: 0.75rem;
		min-height: 2.5rem;
		display: flex;
		align-items: center;
	}

	.step-actions {
		display: flex;
		gap: 0.5rem;
	}

	.action-btn {
		flex: 1;
		padding: 0.5rem;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		font-weight: 500;
		font-size: 0.875rem;
		transition: opacity 0.2s;
	}

	.action-btn:hover {
		opacity: 0.85;
	}

	.edit-btn {
		background-color: #007bff;
		color: white;
	}

	.delete-btn {
		background-color: #dc3545;
		color: white;
	}
</style>
