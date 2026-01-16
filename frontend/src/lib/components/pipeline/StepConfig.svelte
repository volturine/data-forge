<script lang="ts">
	import type { PipelineStep } from '$lib/types/analysis';
	import type { Schema, Column } from '$lib/types/schema';
	import type {
		FilterConfigData,
		SelectConfigData,
		GroupByConfigData,
		SortConfigData,
		RenameConfigData,
		DropConfigData,
		JoinConfigData,
		ExpressionConfigData,
		DeduplicateConfigData,
		FillNullConfigData,
		ExplodeConfigData,
		PivotConfigData,
		TimeSeriesConfigData,
		StringMethodsConfigData,
		ViewConfigData
	} from '$lib/types/operation-config';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { schemaCalculator } from '$lib/utils/schema';
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
	import ViewConfig from '$lib/components/operations/ViewConfig.svelte';

	interface Props {
		step: PipelineStep | null;
		schema: Schema | null;
		isLoadingSchema?: boolean;
		onClose?: () => void;
	}

	let { step, schema, isLoadingSchema = false, onClose }: Props = $props();

	let nonNullSchema = $derived<Schema>(schema || { columns: [], row_count: null });

	// Calculate the INPUT schema BEFORE the current step transformation
	let inputSchema = $derived.by(() => {
		if (!step) {
			return nonNullSchema;
		}

		// Get source schema from analysis store
		const sourceSchemas = analysisStore.sourceSchemas;
		if (!sourceSchemas.size) {
			// No source schema available - return empty schema
			return { columns: [], row_count: null };
		}

		const sourceSchema = sourceSchemas.values().next().value;
		if (!sourceSchema) {
			// No source schema available - return empty schema
			return { columns: [], row_count: null };
		}

		// Get all steps in the pipeline
		const allSteps = analysisStore.pipeline;

		// Find the current step's position
		const stepIndex = allSteps.findIndex((s) => s.id === step.id);
		if (stepIndex <= 0) {
			// This is the first step, use source schema
			return sourceSchema as Schema;
		}

		// Get steps before the current step
		const previousSteps = allSteps.slice(0, stepIndex);

		// Calculate schema after applying previous steps
		const calculatedInputSchema = schemaCalculator.calculatePipelineSchema(
			sourceSchema as Schema,
			previousSteps
		);

		return calculatedInputSchema || ({ columns: [], row_count: null } as Schema);
	});

	function handleClose() {
		if (onClose) {
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
			<button class="close-button" onclick={handleClose} type="button" title="Close">×</button>
		</div>

		<div class="config-body">
			{#if !schema && !isLoadingSchema}
				<div class="warning-message">
					<p>Schema not available. Please ensure the data source is loaded.</p>
					<button onclick={handleClose} type="button">Close</button>
				</div>
			{:else if isLoadingSchema}
				<div class="loading-message">
					<div class="spinner"></div>
					<p>Loading schema...</p>
				</div>
			{:else if step.type === 'filter'}
				<FilterConfig
					schema={inputSchema}
					bind:config={step.config as unknown as FilterConfigData}
				/>
			{:else if step.type === 'select'}
				<SelectConfig
					schema={inputSchema}
					bind:config={step.config as unknown as SelectConfigData}
				/>
			{:else if step.type === 'groupby'}
				<GroupByConfig
					schema={inputSchema}
					bind:config={step.config as unknown as GroupByConfigData}
				/>
			{:else if step.type === 'sort'}
				<SortConfig schema={inputSchema} bind:config={step.config as unknown as SortConfigData} />
			{:else if step.type === 'rename'}
				<RenameConfig
					schema={inputSchema}
					bind:config={step.config as unknown as RenameConfigData}
				/>
			{:else if step.type === 'drop'}
				<DropConfig schema={inputSchema} bind:config={step.config as unknown as DropConfigData} />
			{:else if step.type === 'join'}
				<JoinConfig schema={inputSchema} bind:config={step.config as unknown as JoinConfigData} />
			{:else if step.type === 'expression' || step.type === 'with_columns'}
				<ExpressionConfig
					schema={inputSchema}
					bind:config={step.config as unknown as ExpressionConfigData}
				/>
			{:else if step.type === 'deduplicate'}
				<DeduplicateConfig
					schema={inputSchema}
					bind:config={step.config as unknown as DeduplicateConfigData}
				/>
			{:else if step.type === 'fill_null'}
				<FillNullConfig
					schema={inputSchema}
					bind:config={step.config as unknown as FillNullConfigData}
				/>
			{:else if step.type === 'explode'}
				<ExplodeConfig
					schema={inputSchema}
					bind:config={step.config as unknown as ExplodeConfigData}
				/>
			{:else if step.type === 'pivot'}
				<PivotConfig
					schema={inputSchema}
					bind:config={step.config as unknown as PivotConfigData}
				/>
			{:else if step.type === 'timeseries'}
				<TimeSeriesConfig
					schema={inputSchema}
					bind:config={step.config as unknown as TimeSeriesConfigData}
				/>
			{:else if step.type === 'string_transform'}
				<StringMethodsConfig
					schema={inputSchema}
					bind:config={step.config as unknown as StringMethodsConfigData}
				/>
			{:else if step.type === 'view'}
				<ViewConfig schema={inputSchema} bind:config={step.config as unknown as ViewConfigData} />
			{:else}
				<div class="not-implemented">
					<p>Configuration for {step.type} is not yet implemented</p>
					<button onclick={handleClose} type="button">Close</button>
				</div>
			{/if}
		</div>
	</div>
{/if}

<style>
	.step-config {
		width: 400px;
		border-left: 1px solid var(--border-primary);
		background-color: var(--bg-primary);
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
		color: var(--fg-muted);
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
		color: var(--fg-secondary);
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
		border-bottom: 1px solid var(--border-primary);
		background-color: var(--bg-tertiary);
	}

	.config-header h3 {
		margin: 0;
		font-size: 1.125rem;
		color: var(--fg-primary);
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
		color: var(--fg-muted);
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.close-button:hover {
		background-color: var(--bg-hover);
		color: var(--fg-primary);
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
		color: var(--fg-muted);
	}

	.not-implemented button {
		padding: 0.5rem 1.5rem;
		background-color: var(--accent-primary);
		color: var(--bg-primary);
		border: none;
		border-radius: 4px;
		cursor: pointer;
	}

	.not-implemented button:hover {
		opacity: 0.9;
	}

	.loading-message {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 2rem;
		color: var(--fg-muted);
		text-align: center;
		gap: var(--space-3);
	}

	.loading-message .spinner {
		width: 24px;
		height: 24px;
		border: 2px solid var(--border-primary);
		border-top-color: var(--accent-primary);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
</style>
