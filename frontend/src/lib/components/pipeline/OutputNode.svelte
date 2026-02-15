<script lang="ts">
	import type { AnalysisTab } from '$lib/types/analysis';
	import type { Subscriber } from '$lib/api/settings';
	import { getSubscribers } from '$lib/api/settings';
	import { getDatasource, updateDatasource } from '$lib/api/datasource';
	import { buildAnalysis } from '$lib/api/compute';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { configStore } from '$lib/stores/config.svelte';
	import ScheduleManager from '$lib/components/common/ScheduleManager.svelte';
	import {
		Database,
		Bell,
		ChevronDown,
		ChevronRight,
		EyeOff,
		Loader,
		Search,
		Play
	} from 'lucide-svelte';

	interface Props {
		analysisId?: string;
		datasourceId?: string;
		activeTab?: AnalysisTab | null;
	}

	let { analysisId, datasourceId, activeTab = null }: Props = $props();

	const queryClient = useQueryClient();
	let toggling = $state(false);
	let building = $state(false);
	let error = $state<string | null>(null);
	let notifyOpen = $state(false);
	let search = $state('');
	let scheduleOpen = $state(false);
	const idPrefix = $derived(`output-${analysisId ?? datasourceId ?? 'node'}`);

	const outputDatasourceId = $derived(activeTab?.output_datasource_id ?? null);
	const outputDatasourceQuery = createQuery(() => ({
		queryKey: ['datasource', outputDatasourceId],
		queryFn: async () => {
			if (!outputDatasourceId) return null;
			const result = await getDatasource(outputDatasourceId);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		enabled: !!outputDatasourceId
	}));
	const hidden = $derived(outputDatasourceQuery.data?.is_hidden ?? true);

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
		const icebergRaw = (output.iceberg as Record<string, unknown> | undefined) ?? {};
		const defaultName = tab?.name ? tab.name.trim() : 'export';
		const tableName =
			(icebergRaw.table_name as string) ||
			defaultName.replace(/\s+/g, '_').toLowerCase() ||
			'export';
		return {
			datasource_type: 'iceberg',
			format: 'parquet',
			filename: (output.filename as string) || tableName,
			iceberg: {
				namespace: (icebergRaw.namespace as string) || 'exports',
				table_name: tableName
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

	function ensureOutputConfig(): void {
		const tab = activeTab;
		if (!tab) return;
		const base = (tab.datasource_config ?? {}) as Record<string, unknown>;
		const output = (base.output as Record<string, unknown> | undefined) ?? null;
		if (output) return;
		const defaultName = tab.name ? tab.name.trim() : 'export';
		const tableName = defaultName.replace(/\s+/g, '_').toLowerCase() || 'export';
		updateOutputConfig({
			datasource_type: 'iceberg',
			format: 'parquet',
			filename: tableName,
			iceberg: { namespace: 'exports', table_name: tableName }
		});
	}

	function toggleNotification() {
		ensureOutputConfig();
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
		ensureOutputConfig();
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
				queryClient.invalidateQueries({ queryKey: ['datasource', outputDatasourceId] });
				toggling = false;
			},
			(err) => {
				error = err.message;
				toggling = false;
			}
		);
	}

	async function handleManualBuild() {
		if (!analysisId || building) return;
		building = true;
		error = null;
		ensureOutputConfig();

		// Save analysis first so backend sees the latest output config
		const saveResult = await analysisStore.save();
		if (saveResult.isErr()) {
			error = saveResult.error.message;
			building = false;
			return;
		}

		const tabId = activeTab?.id;
		const result = await buildAnalysis(analysisId, tabId ?? undefined);
		result.match(
			(res) => {
				const failed = res.results.find((r) => r.status === 'failed');
				if (failed?.error) {
					error = failed.error;
				}
				queryClient.invalidateQueries({ queryKey: ['engine-runs', analysisId] });
				queryClient.invalidateQueries({ queryKey: ['datasource', outputDatasourceId] });
				queryClient.invalidateQueries({ queryKey: ['datasources'] });
				building = false;
			},
			(err) => {
				error = err.message;
				building = false;
			}
		);
	}
</script>

<div class="step-node relative w-[65%]">
	<div class="node-content border border-tertiary bg-primary p-3 shadow-sm">
		<!-- Row 1: Output Node badge + is_hidden toggle (far right) -->
		<div class="flex items-center justify-between gap-2">
			<span
				class="rounded-sm border border-tertiary bg-tertiary px-2 py-1 text-[10px] uppercase text-fg-muted"
			>
				Output Node
			</span>
			{#if outputDatasourceId}
				<button
					type="button"
					class="flex items-center gap-1 rounded-sm border border-tertiary px-1.5 py-0.5 text-[10px] transition-colors hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-50"
					class:text-fg-muted={hidden}
					class:text-success-fg={!hidden}
					onclick={toggleHidden}
					disabled={toggling}
					title={hidden
						? 'Hidden from other analyses — click to make visible'
						: 'Visible to other analyses — click to hide'}
				>
					{#if hidden}
						<EyeOff size={10} />
						<span>hidden</span>
					{:else}
						<Database size={10} />
						<span>visible</span>
					{/if}
				</button>
			{/if}
		</div>

		<!-- Row 2: table_name input + Build button -->
		<div class="mt-3 flex items-center gap-2 border-t border-tertiary pt-3">
			<input
				class="resource-input flex-1 border border-tertiary bg-secondary p-1 px-2 text-xs text-fg-primary"
				id={`${idPrefix}-iceberg-table`}
				value={outputConfig.iceberg.table_name}
				placeholder="Table name"
				oninput={(e) =>
					updateOutputConfig({
						iceberg: {
							...outputConfig.iceberg,
							table_name: e.currentTarget.value
						}
					})}
			/>
			<button
				class="flex items-center gap-1.5 border border-tertiary bg-secondary px-2 py-1 text-xs text-fg-primary transition-colors hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-50"
				onclick={handleManualBuild}
				disabled={!analysisId || building}
				title="Run analysis build"
				type="button"
			>
				{#if building}
					<Loader size={12} class="spin" />
					<span>Building...</span>
				{:else}
					<Play size={12} />
					<span>Build</span>
				{/if}
			</button>
		</div>

		<div class="mt-3 flex flex-col gap-3">
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
							<input type="checkbox" checked={notifyConfig.enabled} onchange={toggleNotification} />
							<span>Notify subscribers on build</span>
						</label>

						{#if notifyConfig.enabled}
							<div class="flex flex-col gap-2">
								{#if !canTelegram}
									<div class="border border-warning bg-warning-bg p-2 text-[10px] text-warning-fg">
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
										{'{{analysis_name}}'}, {'{{status}}'}, {'{{duration_ms}}'}, {'{{row_count}}'}
									</span>
								</div>
							</div>
						{/if}
					</div>
				{/if}
			</div>

			<!-- Schedule Section -->
			<div class="border-t border-tertiary pt-3">
				<button
					type="button"
					class="flex w-full cursor-pointer items-center gap-2 border-none bg-transparent p-0 text-xs text-fg-tertiary hover:text-fg-primary"
					onclick={() => (scheduleOpen = !scheduleOpen)}
				>
					{#if scheduleOpen}
						<ChevronDown size={12} />
					{:else}
						<ChevronRight size={12} />
					{/if}
					<Database size={12} />
					<span>Schedules</span>
				</button>

				{#if scheduleOpen && outputDatasourceId}
					<div class="mt-2 border border-tertiary bg-primary p-2">
						<ScheduleManager datasourceId={outputDatasourceId} compact />
					</div>
				{/if}
			</div>

			{#if error}
				<div class="mt-2 border border-error bg-error p-2 text-xs text-error">{error}</div>
			{/if}
		</div>
	</div>
</div>
