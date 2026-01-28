<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { Table, FileJson } from 'lucide-svelte';
	import { previewStepData, type StepPreviewResponse } from '$lib/api/compute';
	import DataTable from '$lib/components/viewers/DataTable.svelte';

	interface Props {
		datasourceId: string;
		datasourceName: string;
	}

	let { datasourceId, datasourceName }: Props = $props();

	let viewMode = $state<'data' | 'schema'>('data');

	const query = createQuery(() => ({
		queryKey: ['datasource-preview', datasourceId],
		queryFn: async (): Promise<StepPreviewResponse> => {
			const result = await previewStepData({
				analysis_id: '',
				datasource_id: datasourceId,
				pipeline_steps: [],
				target_step_id: 'source',
				row_limit: 100,
				page: 1
			});
			if (result.isErr()) {
				throw new Error(result.error.message);
			}
			return result.value;
		},
		staleTime: 30000,
		enabled: !!datasourceId
	}));

	const data = $derived(query.data);
	const isLoading = $derived(query.isLoading);
	const error = $derived(query.error);

	const schema = $derived(
		data
			? data.columns.map((name) => ({
					name,
					dtype: data.column_types?.[name] ?? 'unknown'
				}))
			: []
	);

	function getTypeCategory(dtype: string): string {
		const lower = dtype.toLowerCase();
		if (
			lower.includes('int') ||
			lower.includes('float') ||
			lower.includes('decimal') ||
			lower === 'f32' ||
			lower === 'f64' ||
			lower === 'i8' ||
			lower === 'i16' ||
			lower === 'i32' ||
			lower === 'i64' ||
			lower === 'u8' ||
			lower === 'u16' ||
			lower === 'u32' ||
			lower === 'u64'
		) {
			return 'numeric';
		}
		if (
			lower.includes('str') ||
			lower.includes('utf8') ||
			lower.includes('string') ||
			lower.includes('categorical')
		) {
			return 'string';
		}
		if (lower.includes('bool')) {
			return 'boolean';
		}
		if (lower.includes('date') || lower.includes('time') || lower.includes('duration')) {
			return 'temporal';
		}
		if (lower.includes('list') || lower.includes('array')) {
			return 'list';
		}
		if (lower.includes('struct') || lower.includes('object')) {
			return 'struct';
		}
		return 'other';
	}
</script>

<div class="preview-panel">
	<div class="preview-header">
		<h3>{datasourceName}</h3>
		<div class="view-toggle">
			<button
				class="toggle-btn"
				class:active={viewMode === 'data'}
				onclick={() => (viewMode = 'data')}
			>
				<Table size={14} />
				Data
			</button>
			<button
				class="toggle-btn"
				class:active={viewMode === 'schema'}
				onclick={() => (viewMode = 'schema')}
			>
				<FileJson size={14} />
				Schema
			</button>
		</div>
	</div>

	{#if viewMode === 'data'}
		{#if error}
			<div class="error-state">
				<p class="error-title">Failed to load preview</p>
				<p class="error-message">{error.message}</p>
			</div>
		{:else}
			<DataTable columns={data?.columns ?? []} data={data?.data ?? []} loading={isLoading} />
		{/if}
	{:else}
		<div class="schema-view">
			{#if isLoading}
				<div class="loading-state">Loading schema...</div>
			{:else if error}
				<div class="error-state">
					<p class="error-title">Failed to load schema</p>
					<p class="error-message">{error.message}</p>
				</div>
			{:else}
				<div class="schema-header">
					<span>Column</span>
					<span>Type</span>
				</div>
				{#each schema as column (column.name)}
					<div class="schema-row">
						<span class="col-name">{column.name}</span>
						<span class="type-badge {getTypeCategory(column.dtype)}">{column.dtype}</span>
					</div>
				{/each}
			{/if}
		</div>
	{/if}
</div>

<style>
	.preview-panel {
		background: var(--bg-primary);
		border-radius: var(--radius-md);
		overflow: hidden;
	}
	.preview-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 0.75rem 1rem;
		background: var(--bg-tertiary);
		border-bottom: 1px solid var(--border-primary);
	}
	.preview-header h3 {
		margin: 0;
		font-size: 0.875rem;
		font-weight: 600;
		color: var(--fg-primary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.view-toggle {
		display: flex;
		gap: 0.25rem;
		flex-shrink: 0;
	}
	.toggle-btn {
		display: flex;
		align-items: center;
		gap: 0.375rem;
		padding: 0.375rem 0.75rem;
		border: 1px solid transparent;
		border-radius: var(--radius-sm);
		background: transparent;
		color: var(--fg-tertiary);
		font-size: 0.75rem;
		font-weight: 500;
		cursor: pointer;
	}
	.toggle-btn:hover {
		background: var(--bg-hover);
		color: var(--fg-primary);
	}
	.toggle-btn.active {
		background: var(--accent-bg);
		color: var(--accent-fg);
		border-color: var(--accent-border);
	}
	.error-state {
		padding: var(--space-8);
		text-align: center;
	}
	.error-state .error-title {
		margin: 0 0 var(--space-2);
		color: var(--error-fg);
		font-weight: var(--font-semibold);
	}
	.error-state .error-message {
		margin: 0;
		font-size: var(--text-xs);
		color: var(--fg-tertiary);
	}
	.loading-state {
		padding: 2rem;
		text-align: center;
		color: var(--fg-tertiary);
	}
	.schema-view {
		max-height: 300px;
		overflow-y: auto;
	}
	.schema-header {
		display: grid;
		grid-template-columns: 1fr 1fr;
		padding: 0.5rem 1rem;
		background: var(--bg-tertiary);
		border-bottom: 1px solid var(--border-primary);
		font-size: 0.75rem;
		font-weight: 600;
		color: var(--fg-muted);
		position: sticky;
		top: 0;
	}
	.schema-row {
		display: grid;
		grid-template-columns: 1fr 1fr;
		padding: 0.5rem 1rem;
		border-bottom: 1px solid var(--border-primary);
	}
	.schema-row:hover {
		background: var(--bg-hover);
	}
	.schema-row:last-child {
		border-bottom: none;
	}
	.col-name {
		font-family: var(--font-mono);
		font-size: 0.8125rem;
		color: var(--fg-primary);
	}
	.type-badge {
		display: inline-block;
		padding: var(--space-1) var(--space-2);
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
		font-weight: var(--font-medium);
		font-family: var(--font-mono);
		border: 1px solid;
	}
	.type-badge.numeric {
		background: var(--info-bg);
		color: var(--info-fg);
		border-color: var(--info-border);
	}
	.type-badge.string {
		background: var(--success-bg);
		color: var(--success-fg);
		border-color: var(--success-border);
	}
	.type-badge.boolean {
		background: var(--warning-bg);
		color: var(--warning-fg);
		border-color: var(--warning-border);
	}
	.type-badge.temporal,
	.type-badge.list,
	.type-badge.struct,
	.type-badge.other {
		background: var(--bg-tertiary);
		color: var(--fg-tertiary);
		border-color: var(--border-primary);
	}
</style>
