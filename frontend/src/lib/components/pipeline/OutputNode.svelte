<script lang="ts">
	import type { AnalysisTab } from '$lib/types/analysis';
	import type { DataSource } from '$lib/types/datasource';
	import type { Subscriber } from '$lib/api/settings';
	import { getSubscribers } from '$lib/api/settings';
	import { updateDatasource } from '$lib/api/datasource';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { configStore } from '$lib/stores/config.svelte';
	import { Database, Bell, ChevronDown, ChevronRight, Eye, EyeOff, Search } from 'lucide-svelte';

	interface Props {
		analysisId?: string;
		datasourceId?: string;
		activeTab?: AnalysisTab | null;
		datasource?: DataSource | null;
	}

	let { analysisId, datasourceId, activeTab = null, datasource = null }: Props = $props();

	const queryClient = useQueryClient();
	let toggling = $state(false);
	let error = $state<string | null>(null);
	let notifyOpen = $state(false);
	let search = $state('');
	const idPrefix = $derived(`output-${analysisId ?? datasourceId ?? 'node'}`);

	const hidden = $derived(datasource?.is_hidden ?? true);
	const outputDatasourceId = $derived(activeTab?.output_datasource_id ?? null);
	const canTelegram = $derived(configStore.telegramEnabled);

	const subscribersQuery = createQuery(() => ({
		queryKey: ['telegram-subscribers'],
		queryFn: async () => {
			const result = await getSubscribers();
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		staleTime: 30_000
	}));

	const outputConfig = $derived.by(() => {
		const tab = activeTab;
		const base = (tab?.datasource_config ?? {}) as Record<string, unknown>;
		const output = (base.output as Record<string, unknown> | undefined) ?? {};
		return {
			datasource_type: (output.datasource_type as string) || 'iceberg',
			format: (output.format as string) || 'parquet',
			filename: (output.filename as string) || 'export',
			iceberg: (output.iceberg as Record<string, unknown> | undefined) ?? {
				namespace: 'exports',
				table_name: 'export'
			},
			duckdb: (output.duckdb as Record<string, unknown> | undefined) ?? {
				table_name: 'data'
			},
			notification: (output.notification as Record<string, unknown> | undefined) ?? null
		};
	});

	const notifyConfig = $derived.by(() => {
		const n = outputConfig.notification;
		if (!n) {
			return {
				enabled: false,
				excluded_recipients: [] as string[],
				body_template:
					'Analysis: {{analysis_name}}\nStatus: {{status}}\nDuration: {{duration_ms}}ms\nRows: {{row_count}}'
			};
		}
		return {
			enabled: true,
			excluded_recipients: (n.excluded_recipients as string[] | undefined) ?? [],
			body_template:
				(n.body_template as string) ||
				'Analysis: {{analysis_name}}\nStatus: {{status}}\nDuration: {{duration_ms}}ms\nRows: {{row_count}}'
		};
	});

	const activeSubscribers = $derived(
		(subscribersQuery.data ?? []).filter((s: Subscriber) => s.is_active)
	);

	const filtered = $derived.by(() => {
		const q = search.toLowerCase().trim();
		if (!q) return activeSubscribers;
		return activeSubscribers.filter(
			(s: Subscriber) => s.title.toLowerCase().includes(q) || s.chat_id.toLowerCase().includes(q)
		);
	});

	const selectedCount = $derived(
		activeSubscribers.length - notifyConfig.excluded_recipients.length
	);

	function updateOutputConfig(patch: Record<string, unknown>) {
		const tab = activeTab;
		if (!tab) return;
		const next = { ...(tab.datasource_config ?? {}) } as Record<string, unknown>;
		const currentOutput = (next.output as Record<string, unknown> | undefined) ?? {};
		next.output = { ...currentOutput, ...patch };
		analysisStore.updateTab(tab.id, { datasource_config: next });
	}

	function toggleNotification() {
		if (notifyConfig.enabled) {
			updateOutputConfig({ notification: null });
			return;
		}
		updateOutputConfig({
			notification: {
				method: 'telegram',
				excluded_recipients: [],
				body_template:
					'Analysis: {{analysis_name}}\nStatus: {{status}}\nDuration: {{duration_ms}}ms\nRows: {{row_count}}'
			}
		});
	}

	function updateNotification(patch: Record<string, unknown>) {
		const current = outputConfig.notification ?? {};
		updateOutputConfig({ notification: { ...current, ...patch } });
	}

	function toggleSubscriber(chatId: string) {
		const excluded = [...notifyConfig.excluded_recipients];
		const idx = excluded.indexOf(chatId);
		if (idx >= 0) {
			excluded.splice(idx, 1);
		} else {
			excluded.push(chatId);
		}
		updateNotification({ excluded_recipients: excluded });
	}

	function isIncluded(chatId: string): boolean {
		return !notifyConfig.excluded_recipients.includes(chatId);
	}

	async function toggleHidden() {
		if (!outputDatasourceId || toggling) return;
		toggling = true;
		const result = await updateDatasource(outputDatasourceId, { is_hidden: !hidden });
		result.match(
			() => {
				queryClient.invalidateQueries({ queryKey: ['datasources'] });
				toggling = false;
			},
			(err) => {
				error = err.message;
				toggling = false;
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

				<!-- Build Notification Section -->
				<div class="border-t border-tertiary pt-3">
					<button
						type="button"
						class="flex w-full cursor-pointer items-center gap-2 border-none bg-transparent p-0 text-xs text-fg-tertiary hover:text-fg-primary"
						onclick={() => (notifyOpen = !notifyOpen)}
					>
						{#if notifyOpen}
							<ChevronDown size={12} />
						{:else}
							<ChevronRight size={12} />
						{/if}
						<Bell size={12} />
						<span>Build Notification</span>
						{#if notifyConfig.enabled}
							<span
								class="ml-auto rounded-sm bg-accent-bg px-1.5 py-0.5 text-[10px] text-accent-primary"
							>
								{selectedCount}/{activeSubscribers.length}
							</span>
						{/if}
					</button>

					{#if notifyOpen}
						<div class="mt-2 flex flex-col gap-2 pl-5">
							<label class="flex cursor-pointer items-center gap-2 text-xs">
								<input
									type="checkbox"
									checked={notifyConfig.enabled}
									onchange={toggleNotification}
								/>
								<span>Notify subscribers on build</span>
							</label>

							{#if notifyConfig.enabled}
								<div class="flex flex-col gap-2">
									{#if !canTelegram}
										<div
											class="border border-warning bg-warning-bg p-2 text-[10px] text-warning-fg"
										>
											Telegram not configured. Set bot token in global settings.
										</div>
									{:else}
										<!-- Subscriber Picker -->
										<div class="flex flex-col gap-1">
											<span class="text-[10px] uppercase text-fg-muted">Recipients</span>
											<div class="relative">
												<Search
													size={12}
													class="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-fg-muted"
												/>
												<input
													class="resource-input w-full border border-tertiary bg-secondary py-1 pl-7 pr-2 text-xs text-fg-primary"
													placeholder="Search subscribers..."
													value={search}
													oninput={(e) => (search = e.currentTarget.value)}
												/>
											</div>
											<div class="max-h-32 overflow-y-auto border border-tertiary bg-secondary">
												{#if subscribersQuery.isPending}
													<div class="p-2 text-center text-[10px] text-fg-muted">Loading...</div>
												{:else if subscribersQuery.isError}
													<div class="p-2 text-center text-[10px] text-error">
														Failed to load subscribers
													</div>
												{:else if activeSubscribers.length === 0}
													<div class="p-2 text-center text-[10px] text-fg-muted">
														No subscribers. Users can subscribe via /subscribe in Telegram.
													</div>
												{:else if filtered.length === 0}
													<div class="p-2 text-center text-[10px] text-fg-muted">No matches</div>
												{:else}
													{#each filtered as sub (sub.id)}
														<label
															class="flex cursor-pointer items-center gap-2 border-b border-tertiary px-2 py-1.5 last:border-b-0 hover:bg-tertiary"
														>
															<input
																type="checkbox"
																checked={isIncluded(sub.chat_id)}
																onchange={() => toggleSubscriber(sub.chat_id)}
															/>
															<span class="truncate text-xs text-fg-primary">
																{sub.title}
															</span>
															<span class="ml-auto shrink-0 text-[10px] text-fg-muted">
																{sub.chat_id}
															</span>
														</label>
													{/each}
												{/if}
											</div>
										</div>
									{/if}

									<div class="flex flex-col gap-1">
										<label
											class="text-[10px] uppercase text-fg-muted"
											for={`${idPrefix}-notify-body`}
										>
											Message Template
										</label>
										<textarea
											class="resource-input border border-tertiary bg-secondary p-1 px-2 text-xs text-fg-primary"
											id={`${idPrefix}-notify-body`}
											rows="3"
											value={notifyConfig.body_template}
											oninput={(e) =>
												updateNotification({
													body_template: e.currentTarget.value
												})}
										></textarea>
										<span class="text-[10px] text-fg-muted">
											{'{{analysis_name}}'}, {'{{status}}'}, {'{{duration_ms}}'},
											{'{{row_count}}'}
										</span>
									</div>
								</div>
							{/if}
						</div>
					{/if}
				</div>

				<!-- Output Datasource Section -->
				<div class="flex flex-col gap-2 border-t border-tertiary pt-3">
					<div class="flex items-center gap-2 text-xs text-fg-tertiary">
						<Database size={14} />
						<span>Output datasource</span>
					</div>

					{#if outputDatasourceId}
						<button
							type="button"
							class="flex w-full cursor-pointer items-center gap-2 border border-tertiary bg-secondary px-2 py-1.5 text-xs disabled:cursor-not-allowed disabled:opacity-50"
							onclick={toggleHidden}
							disabled={toggling}
							title={hidden
								? 'Datasource is hidden from datasources page'
								: 'Datasource is visible on datasources page'}
						>
							{#if hidden}
								<EyeOff size={12} class="text-fg-muted" />
								<span class="text-fg-muted">Hidden</span>
							{:else}
								<Eye size={12} class="text-success-fg" />
								<span class="text-success-fg">Visible</span>
							{/if}
							<span class="ml-auto text-[10px] text-fg-tertiary">
								{hidden ? 'Not shown on datasources page' : 'Shown on datasources page'}
							</span>
						</button>
					{/if}
				</div>

				{#if error}
					<div class="mt-2 border border-error bg-error p-2 text-xs text-error">{error}</div>
				{/if}
			</div>
		</div>
	</div>
</div>
