<script lang="ts">
	import type { PipelineStep } from '$lib/types/analysis';
	import { InlineDataTable } from '$lib/components/viewers';

	interface Props {
		step: PipelineStep;
		index: number;
		datasourceId?: string;
		allSteps?: PipelineStep[];
		onEdit: (id: string) => void;
		onDelete: (id: string) => void;
	}

	let { step, index, datasourceId, allSteps = [], onEdit, onDelete }: Props = $props();

	const typeLabels: Record<string, string> = {
		filter: 'filter',
		select: 'select',
		groupby: 'group_by',
		sort: 'sort',
		rename: 'rename',
		drop: 'drop',
		join: 'join',
		expression: 'expression',
		with_columns: 'with_columns',
		deduplicate: 'deduplicate',
		fill_null: 'fill_null',
		explode: 'explode',
		pivot: 'pivot',
		timeseries: 'timeseries',
		string_transform: 'string'
	};

	function getConfigSummary(step: PipelineStep): string {
		switch (step.type) {
			case 'filter': {
				const conditions = step.config.conditions as Array<{
					column: string;
					operator: string;
					value: string;
				}>;
				if (!conditions || conditions.length === 0) return 'no conditions';
				return `${conditions.length} condition${conditions.length > 1 ? 's' : ''}`;
			}

			case 'select': {
				const columns = step.config.columns as string[];
				if (!columns || columns.length === 0) return 'no columns';
				return `${columns.length} column${columns.length > 1 ? 's' : ''}`;
			}

			case 'groupby': {
				const groupBy = step.config.groupBy as string[];
				const aggregations = step.config.aggregations as Array<unknown>;
				if (!groupBy || groupBy.length === 0) return 'not configured';
				return `${groupBy.length} key${groupBy.length > 1 ? 's' : ''}, ${aggregations?.length || 0} agg`;
			}

			case 'sort': {
				const sortRules = step.config as unknown as Array<{ column: string; descending: boolean }>;
				if (!Array.isArray(sortRules) || sortRules.length === 0) return 'not configured';
				return `${sortRules.length} column${sortRules.length > 1 ? 's' : ''}`;
			}

			default: {
				return 'click to configure';
			}
		}
	}

	let label = $derived(typeLabels[step.type] || step.type);
	let summary = $derived(getConfigSummary(step));
</script>

<div class="step-node" class:view-node={step.type === 'view'}>
	<div class="connection-point top"></div>

	<div class="step-content">
		<div class="step-header">
			<span class="step-type">{label}</span>
			<span class="step-number">#{index + 1}</span>
		</div>

		<div class="step-summary">{summary}</div>

		<div class="step-actions">
			<button class="action-btn" onclick={() => onEdit(step.id)} type="button"> edit </button>
			<button class="action-btn danger" onclick={() => onDelete(step.id)} type="button">
				delete
			</button>
		</div>

		{#if step.type === 'view' && datasourceId && allSteps.length > 0}
			<div class="view-preview expanded">
				<InlineDataTable
					{datasourceId}
					pipeline={allSteps}
					stepId={step.id}
					rowLimit={typeof step.config?.rowLimit === 'number' ? step.config.rowLimit : 100}
				/>
			</div>
		{/if}
	</div>

	<div class="connection-point bottom"></div>
</div>

<style>
	.step-node {
		position: relative;
		width: 100%;
	}

	.step-node.view-node {
		max-width: none;
		width: 75%;
		min-width: 600px;
	}

	.connection-point {
		position: absolute;
		left: 50%;
		transform: translateX(-50%);
		width: 8px;
		height: 8px;
		background-color: var(--fg-muted);
		border: 2px solid var(--bg-primary);
		border-radius: 50%;
		z-index: 2;
	}

	.connection-point.top {
		top: -4px;
	}

	.connection-point.bottom {
		bottom: -4px;
	}

	.step-content {
		background-color: var(--bg-primary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		padding: var(--space-4);
		transition: all var(--transition-fast);
		box-shadow: var(--card-shadow);
	}

	.step-content:hover {
		border-color: var(--border-tertiary);
		transform: translateY(-1px);
	}

	.step-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: var(--space-3);
	}

	.step-type {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--fg-primary);
		font-family: var(--font-mono);
	}

	.step-number {
		font-size: var(--text-xs);
		color: var(--fg-muted);
	}

	.step-summary {
		padding: var(--space-2) var(--space-3);
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
		color: var(--fg-tertiary);
		margin-bottom: var(--space-3);
	}

	.step-actions {
		display: flex;
		gap: var(--space-2);
	}

	.view-preview {
		margin-top: var(--space-3);
		border-top: 1px solid var(--border-primary);
		padding-top: var(--space-3);
		width: 100%;
		overflow-y: auto;
	}

	.action-btn {
		flex: 1;
		padding: var(--space-2);
		background-color: transparent;
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-weight: 500;
		color: var(--fg-secondary);
		transition: all var(--transition-fast);
	}

	.action-btn:hover {
		background-color: var(--bg-hover);
		color: var(--fg-primary);
	}

	.action-btn.danger:hover {
		background-color: var(--error-bg);
		border-color: var(--error-border);
		color: var(--error-fg);
	}
</style>
