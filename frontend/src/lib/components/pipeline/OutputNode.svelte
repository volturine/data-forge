<script lang="ts">
	import type { AnalysisTab, PipelineStep } from '$lib/types/analysis';
	import type { DataSource } from '$lib/types/datasource';
	import { exportData, type ExportRequest } from '$lib/api/compute';
	import { useQueryClient } from '@tanstack/svelte-query';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { Database, Check } from 'lucide-svelte';

	interface Props {
		steps: PipelineStep[];
		analysisId?: string;
		datasourceId?: string;
		activeTab?: AnalysisTab | null;
		datasource?: DataSource | null;
	}

	let { steps, analysisId, datasourceId, activeTab = null, datasource = null }: Props = $props();

	const queryClient = useQueryClient();
	let exporting = $state(false);
	let error = $state<string | null>(null);
	let success = $state<string | null>(null);
	const idPrefix = $derived(() => `output-${analysisId ?? datasourceId ?? 'node'}`);

	let outputConfig = $derived.by(() => {
		const tab = activeTab;
		const sourceName = datasource?.name ?? tab?.name ?? 'analysis_output';
		const baseName = `${sourceName}_out`;
		const base = (tab?.datasource_config ?? {}) as Record<string, unknown>;
		const output = (base.output as Record<string, unknown> | undefined) ?? {};
		return {
			datasource_type: (output.datasource_type as string) || 'iceberg',
			format: (output.format as string) || 'parquet',
			filename: (output.filename as string) || baseName,
			iceberg: (output.iceberg as Record<string, unknown> | undefined) ?? {
				namespace: 'exports',
				table_name: baseName
			},
			duckdb: (output.duckdb as Record<string, unknown> | undefined) ?? {
				table_name: 'data'
			}
		};
	});

	function updateOutputConfig(patch: Record<string, unknown>) {
		const tab = activeTab;
		if (!tab) return;
		const next = { ...(tab.datasource_config ?? {}) } as Record<string, unknown>;
		const currentOutput = (next.output as Record<string, unknown> | undefined) ?? {};
		next.output = { ...currentOutput, ...patch };
		analysisStore.updateTab(tab.id, { datasource_config: next });
	}

	async function handleExport() {
		if (!datasourceId || !analysisId || exporting) return;
		exporting = true;
		error = null;
		success = null;

		const format = outputConfig.datasource_type === 'file' ? outputConfig.format : undefined;
		const filename = outputConfig.filename;
		const request = {
			analysis_id: analysisId,
			datasource_id: datasourceId,
			pipeline_steps: steps.map((s) => ({
				id: s.id,
				type: s.type,
				config: s.config,
				depends_on: s.depends_on
			})),
			target_step_id: steps.length ? (steps[steps.length - 1]?.id ?? 'source') : 'source',
			format,
			filename,
			destination: 'datasource',
			datasource_type: outputConfig.datasource_type,
			iceberg_options:
				outputConfig.datasource_type === 'iceberg'
					? {
							namespace: outputConfig.iceberg.namespace,
							table_name: outputConfig.iceberg.table_name
						}
					: undefined,
			duckdb_options:
				outputConfig.datasource_type === 'duckdb'
					? {
							table_name: outputConfig.duckdb.table_name
						}
					: undefined,
			datasource_config: analysisStore.activeTab?.datasource_config ?? null
		} as unknown as ExportRequest;

		exportData(request).match(
			(result) => {
				if (result instanceof Blob) {
					exporting = false;
					return;
				}
				const response = result as import('$lib/api/compute').ExportResponse & {
					datasource_name?: string | null;
				};
				success = `Saved output: ${response.datasource_name ?? response.filename}`;
				queryClient.invalidateQueries({ queryKey: ['datasources'] });
				exporting = false;
			},
			(err) => {
				error = err.message;
				exporting = false;
			}
		);
	}
</script>

<div class="step-node relative w-[65%]">
	<div class="node-content border border-tertiary bg-primary p-3 shadow-sm">
		<div class="flex items-center justify-between gap-2">
			<div class="flex items-center gap-2">
				<span
					class="rounded-sm border border-tertiary bg-tertiary px-2 py-1 text-[10px] uppercase text-fg-muted"
				>
					Output
				</span>
				<span class="text-sm font-medium">Analysis Output</span>
			</div>
		</div>

		<div class="mt-3 border-t border-tertiary pt-3">
			<div class="flex flex-col gap-3">
				<div class="flex items-center gap-2">
					<label class="text-xs text-fg-muted" for={`${idPrefix}-destination`}>Destination</label>
					<select
						class="resource-input border border-tertiary bg-secondary text-fg-primary p-1 px-2 text-xs"
						id={`${idPrefix}-destination`}
						value={outputConfig.datasource_type}
						onchange={(e) => updateOutputConfig({ datasource_type: e.currentTarget.value })}
					>
						<option value="iceberg">Iceberg</option>
						<option value="duckdb">DuckDB</option>
						<option value="file">File</option>
					</select>
				</div>

				{#if outputConfig.datasource_type === 'iceberg'}
					<div class="grid grid-cols-2 gap-2">
						<div class="flex flex-col gap-1">
							<label
								class="text-[10px] uppercase text-fg-muted"
								for={`${idPrefix}-iceberg-namespace`}
							>
								Namespace
							</label>
							<input
								class="resource-input border border-tertiary bg-secondary text-fg-primary p-1 px-2 text-xs"
								id={`${idPrefix}-iceberg-namespace`}
								value={outputConfig.iceberg.namespace}
								oninput={(e) =>
									updateOutputConfig({
										iceberg: {
											...outputConfig.iceberg,
											namespace: e.currentTarget.value
										}
									})}
							/>
						</div>
						<div class="flex flex-col gap-1">
							<label class="text-[10px] uppercase text-fg-muted" for={`${idPrefix}-iceberg-table`}>
								Table
							</label>
							<input
								class="resource-input border border-tertiary bg-secondary text-fg-primary p-1 px-2 text-xs"
								id={`${idPrefix}-iceberg-table`}
								value={outputConfig.iceberg.table_name}
								oninput={(e) =>
									updateOutputConfig({
										iceberg: {
											...outputConfig.iceberg,
											table_name: e.currentTarget.value
										}
									})}
							/>
						</div>
					</div>
				{:else if outputConfig.datasource_type === 'duckdb'}
					<div class="flex flex-col gap-1">
						<label class="text-[10px] uppercase text-fg-muted" for={`${idPrefix}-duckdb-table`}>
							Table
						</label>
						<input
							class="resource-input border border-tertiary bg-secondary text-fg-primary p-1 px-2 text-xs"
							id={`${idPrefix}-duckdb-table`}
							value={outputConfig.duckdb.table_name}
							oninput={(e) =>
								updateOutputConfig({
									duckdb: { ...outputConfig.duckdb, table_name: e.currentTarget.value }
								})}
						/>
					</div>
				{:else}
					<div class="grid grid-cols-2 gap-2">
						<div class="flex flex-col gap-1">
							<label class="text-[10px] uppercase text-fg-muted" for={`${idPrefix}-file-name`}>
								Filename
							</label>
							<input
								class="resource-input border border-tertiary bg-secondary text-fg-primary p-1 px-2 text-xs"
								id={`${idPrefix}-file-name`}
								value={outputConfig.filename}
								oninput={(e) => updateOutputConfig({ filename: e.currentTarget.value })}
							/>
						</div>
						<div class="flex flex-col gap-1">
							<label class="text-[10px] uppercase text-fg-muted" for={`${idPrefix}-file-format`}>
								Format
							</label>
							<select
								class="resource-input border border-tertiary bg-secondary text-fg-primary p-1 px-2 text-xs"
								id={`${idPrefix}-file-format`}
								value={outputConfig.format}
								onchange={(e) => updateOutputConfig({ format: e.currentTarget.value })}
							>
								<option value="csv">CSV</option>
								<option value="parquet">Parquet</option>
								<option value="json">JSON</option>
								<option value="ndjson">NDJSON</option>
								<option value="duckdb">DuckDB</option>
							</select>
						</div>
					</div>
				{/if}

				<div class="flex items-center justify-between gap-2 border-t border-tertiary pt-3">
					<div class="flex items-center gap-2 text-xs text-fg-tertiary">
						<Database size={14} />
						<span>Output datasource</span>
					</div>
					<button
						class="export-btn flex items-center gap-2 border-none px-3 py-2 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50 bg-accent text-bg-primary hover:opacity-90 hover:enabled:opacity-90"
						onclick={handleExport}
						disabled={exporting}
						type="button"
					>
						{#if exporting}
							<span class="spinner spinner-sm"></span>
							Saving...
						{:else}
							<Database size={14} />
							Save Output
						{/if}
					</button>
				</div>

				{#if error}
					<div class="mt-2 border border-error bg-error p-2 text-xs text-error">{error}</div>
				{/if}
				{#if success}
					<div class="mt-2 border border-success bg-success-bg p-2 text-xs text-success-fg">
						<Check size={12} class="inline-block mr-1" />
						{success}
					</div>
				{/if}
			</div>
		</div>
	</div>
</div>
