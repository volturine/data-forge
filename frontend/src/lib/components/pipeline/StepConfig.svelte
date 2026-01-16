<script lang="ts">
	import type { PipelineStep } from '$lib/types/analysis';
	import type { Schema } from '$lib/types/schema';
	import FilterConfig from '$lib/components/operations/FilterConfig.svelte';
	import SelectConfig from '$lib/components/operations/SelectConfig.svelte';
	import GroupByConfig from '$lib/components/operations/GroupByConfig.svelte';
	import SortConfig from '$lib/components/operations/SortConfig.svelte';
	import RenameConfig from '$lib/components/operations/RenameConfig.svelte';
	import DropConfig from '$lib/components/operations/DropConfig.svelte';
	import JoinConfig from '$lib/components/operations/JoinConfig.svelte';
	import ExpressionConfig from '$lib/components/operations/ExpressionConfig.svelte';
	import DeduplicateConfig from '$lib/components/operations/DeduplicateConfig.svelte';
	import FillNullConfig from '$lib/components/operations/FillNullConfig.svelte';
	import ExplodeConfig from '$lib/components/operations/ExplodeConfig.svelte';
	import PivotConfig from '$lib/components/operations/PivotConfig.svelte';
	import TimeSeriesConfig from '$lib/components/operations/TimeSeriesConfig.svelte';
	import StringMethodsConfig from '$lib/components/operations/StringMethodsConfig.svelte';

	interface Props {
		step: PipelineStep | null;
		schema: Schema | null;
		onUpdateStep?: (stepId: string, config: Record<string, unknown>) => void;
		onClose?: () => void;
		onSave?: (config: Record<string, unknown>) => void;
		onCancel?: () => void;
	}

	let { step, schema, onUpdateStep, onClose, onSave, onCancel }: Props = $props();

	let nonNullSchema = $derived<Schema>(schema || { columns: [], row_count: null });

	function handleSave(config: unknown) {
		if (onSave) {
			onSave(config as Record<string, unknown>);
		} else if (onUpdateStep && step) {
			onUpdateStep(step.id, config as Record<string, unknown>);
			if (onClose) onClose();
		}
	}

	function handleCancel() {
		if (onCancel) {
			onCancel();
		} else if (onClose) {
			onClose();
		}
	}
</script>

{#if step === null}
	<div class="step-config empty">
		<div class="empty-message">
			<div class="empty-icon">⚙️</div>
			<h3>No step selected</h3>
			<p>Click on a pipeline step to configure it</p>
		</div>
	</div>
{:else}
	<div class="step-config">
		<div class="config-header">
			<h3>Configure Step</h3>
			<button class="close-button" onclick={handleCancel} type="button" title="Close">×</button>
		</div>

		<div class="config-body">
			{#if !schema}
				<div class="warning-message">
					<p>Schema not available. Please ensure the data source is loaded.</p>
					<button onclick={handleCancel} type="button">Close</button>
				</div>
			{:else if step.type === 'filter'}
				<FilterConfig schema={nonNullSchema} config={step.config as any} onSave={handleSave} />
			{:else if step.type === 'select'}
				<SelectConfig schema={nonNullSchema} config={step.config as any} onSave={handleSave} />
			{:else if step.type === 'groupby'}
				<GroupByConfig schema={nonNullSchema} config={step.config as any} onSave={handleSave} />
			{:else if step.type === 'sort'}
				<SortConfig schema={nonNullSchema} config={step.config as any} onSave={handleSave} />
			{:else if step.type === 'rename'}
				<RenameConfig schema={nonNullSchema} config={step.config as any} onSave={handleSave} />
			{:else if step.type === 'drop'}
				<DropConfig schema={nonNullSchema} config={step.config as any} onSave={handleSave} />
			{:else if step.type === 'join'}
				<JoinConfig schema={nonNullSchema} config={step.config as any} onSave={handleSave} />
			{:else if step.type === 'expression' || step.type === 'with_columns'}
				<ExpressionConfig schema={nonNullSchema} config={step.config as any} onSave={handleSave} />
			{:else if step.type === 'deduplicate'}
				<DeduplicateConfig schema={nonNullSchema} config={step.config as any} onSave={handleSave} />
			{:else if step.type === 'fill_null'}
				<FillNullConfig schema={nonNullSchema} config={step.config as any} onSave={handleSave} />
			{:else if step.type === 'explode'}
				<ExplodeConfig schema={nonNullSchema} config={step.config as any} onSave={handleSave} />
			{:else if step.type === 'pivot'}
				<PivotConfig schema={nonNullSchema} config={step.config as any} onSave={handleSave} />
			{:else if step.type === 'timeseries'}
				<TimeSeriesConfig schema={nonNullSchema} config={step.config as any} onSave={handleSave} />
			{:else if step.type === 'string_transform'}
				<StringMethodsConfig schema={nonNullSchema} config={step.config as any} onSave={handleSave} />
			{:else}
				<div class="not-implemented">
					<p>Configuration for {step.type} is not yet implemented</p>
					<button onclick={handleCancel} type="button">Close</button>
				</div>
			{/if}
		</div>
	</div>
{/if}

<style>
	.step-config {
		width: 400px;
		border-left: 1px solid #ddd;
		background-color: white;
		display: flex;
		flex-direction: column;
		overflow-y: auto;
	}

	.step-config.empty {
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.empty-message {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 2rem;
		color: #6c757d;
		text-align: center;
	}

	.empty-icon {
		font-size: 3rem;
		margin-bottom: 1rem;
		opacity: 0.5;
	}

	.empty-message h3 {
		margin: 0 0 0.5rem 0;
		font-size: 1.25rem;
		color: #495057;
	}

	.empty-message p {
		margin: 0;
		font-size: 0.875rem;
	}

	.config-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 1rem;
		border-bottom: 1px solid #ddd;
		background-color: #f8f9fa;
	}

	.config-header h3 {
		margin: 0;
		font-size: 1.125rem;
		color: #333;
	}

	.close-button {
		width: 32px;
		height: 32px;
		padding: 0;
		background-color: transparent;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		font-size: 1.5rem;
		line-height: 1;
		color: #6c757d;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.close-button:hover {
		background-color: #e9ecef;
		color: #333;
	}

	.config-body {
		flex: 1;
		overflow-y: auto;
	}

	.not-implemented {
		padding: 2rem;
		text-align: center;
	}

	.not-implemented p {
		margin: 0 0 1rem 0;
		color: #6c757d;
	}

	.not-implemented button {
		padding: 0.5rem 1.5rem;
		background-color: #6c757d;
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
	}

	.not-implemented button:hover {
		opacity: 0.9;
	}
</style>
