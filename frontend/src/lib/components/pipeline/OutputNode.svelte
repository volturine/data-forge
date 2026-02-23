<script lang="ts">
	import type { AnalysisTab } from '$lib/types/analysis';
	import type { Subscriber } from '$lib/api/settings';
	import type { BuildResponse } from '$lib/api/compute';
	import { getSubscribers } from '$lib/api/settings';
	import { getDatasource, updateDatasource } from '$lib/api/datasource';
	import { buildAnalysisWithPayload } from '$lib/api/compute';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { configStore } from '$lib/stores/config.svelte';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { buildAnalysisPipelinePayload } from '$lib/utils/analysis-pipeline';
	import ScheduleManager from '$lib/components/common/ScheduleManager.svelte';
	import HealthChecksManager from '$lib/components/common/HealthChecksManager.svelte';
	import BranchPicker from '$lib/components/common/BranchPicker.svelte';
	import {
		Bell,
		CalendarClock,
		ChevronDown,
		ChevronRight,
		EyeOff,
		HeartPulse,
		Loader,
		Play,
		Database,
		Pencil,
		Check,
		X
	} from 'lucide-svelte';
	import { listHealthChecks, listHealthCheckResults } from '$lib/api/healthcheck';
	import { listSchedules } from '$lib/api/schedule';
	import { SvelteMap } from 'svelte/reactivity';

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
	let scheduleOpen = $state(false);
	let healthOpen = $state(false);
	let editingName = $state(false);
	let draftName = $state('');
	let modeMenuOpen = $state(false);
	let modeMenuRef = $state<HTMLElement>();
	let modeTriggerRef = $state<HTMLButtonElement>();

	const defaultBranch = $derived.by(() => {
		const current = analysisStore.current?.pipeline_definition ?? {};
		const branch = (current as Record<string, unknown>).output_branch as string | undefined;
		const next = branch ?? '';
		return next.trim().length > 0 ? next : 'master';
	});
	const branchValue = $derived.by(() => {
		const next = outputConfig.iceberg.branch ?? defaultBranch;
		return next.trim().length > 0 ? next : defaultBranch;
	});
	const branchOptions = $derived.by(() => {
		const branches = (outputDatasourceQuery.data?.config?.branches as string[] | undefined) ?? [];
		const cleaned = branches.map((branch) => branch.trim()).filter((branch) => branch.length > 0);
		const current = branchValue.trim();
		if (!current) return cleaned;
		if (cleaned.includes(current)) return cleaned;
		return [current, ...cleaned];
	});
	const idPrefix = $derived(`output-${analysisId ?? datasourceId ?? 'node'}`);

	const outputDatasourceId = $derived(activeTab?.output_datasource_id ?? null);
	const outputDatasource = $derived(
		outputDatasourceId ? (datasourceStore.getDatasource(outputDatasourceId) ?? null) : null
	);
	const canQueryOutput = $derived(!!outputDatasourceId && !!outputDatasource);

	const healthChecksQuery = createQuery(() => ({
		queryKey: ['healthchecks', outputDatasourceId],
		queryFn: async () => {
			if (!outputDatasourceId) return [];
			const result = await listHealthChecks(outputDatasourceId);
			if (result.isErr()) return [];
			return result.value;
		},
		enabled: canQueryOutput
	}));

	const healthResultsQuery = createQuery(() => ({
		queryKey: ['healthcheck-results', outputDatasourceId],
		queryFn: async () => {
			if (!outputDatasourceId) return [];
			const result = await listHealthCheckResults(outputDatasourceId, 50);
			if (result.isErr()) return [];
			return result.value;
		},
		enabled: canQueryOutput
	}));

	const healthCount = $derived(healthChecksQuery.data?.length ?? 0);
	const healthPassed = $derived.by(() => {
		const checks = healthChecksQuery.data ?? [];
		const results = healthResultsQuery.data ?? [];
		if (checks.length === 0) return null;
		const latest = new SvelteMap<string, boolean>();
		for (const r of results) {
			if (!latest.has(r.healthcheck_id)) {
				latest.set(r.healthcheck_id, r.passed);
			}
		}
		if (latest.size === 0) return null;
		const failed = [...latest.values()].filter((v) => !v).length;
		return failed === 0;
	});

	const schedulesQuery = createQuery(() => ({
		queryKey: ['schedules', outputDatasourceId],
		queryFn: async () => {
			if (!outputDatasourceId) return [];
			const result = await listSchedules(outputDatasourceId);
			if (result.isErr()) return [];
			return result.value;
		},
		enabled: canQueryOutput
	}));

	const scheduleCount = $derived(schedulesQuery.data?.length ?? 0);
	const enabledSchedules = $derived((schedulesQuery.data ?? []).filter((s) => s.enabled).length);

	const outputDatasourceQuery = createQuery(() => ({
		queryKey: ['datasource', outputDatasourceId],
		queryFn: async () => {
			if (!outputDatasourceId) return null;
			const result = await getDatasource(outputDatasourceId);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		enabled: canQueryOutput
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
		staleTime: 30_000,
		enabled: canTelegram
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
		const branch =
			typeof icebergRaw.branch === 'string' && icebergRaw.branch.trim().length > 0
				? icebergRaw.branch.trim()
				: defaultBranch;
		const namespace = typeof icebergRaw.namespace === 'string' ? icebergRaw.namespace : '';
		return {
			datasource_type: 'iceberg',
			format: 'parquet',
			filename: (output.filename as string) || tableName,
			build_mode: (output.build_mode as string) || 'full',
			iceberg: {
				namespace: namespace || 'outputs',
				table_name: tableName,
				branch
			},
			notification: (output.notification as Record<string, unknown> | undefined) ?? null
		};
	});

	const notifyConfig = $derived.by(() => {
		const n = outputConfig.notification;
		if (!n) {
			return {
				enabled: false,
				body_template:
					'Analysis: {{analysis_name}}\nStatus: {{status}}\nDuration: {{duration_ms}}ms\nRows: {{row_count}}'
			};
		}
		return {
			enabled: true,
			body_template:
				(n.body_template as string) ||
				'Analysis: {{analysis_name}}\nStatus: {{status}}\nDuration: {{duration_ms}}ms\nRows: {{row_count}}'
		};
	});

	const activeSubscribers = $derived(
		(subscribersQuery.data ?? []).filter((s: Subscriber) => s.is_active)
	);

	const selectedCount = $derived(activeSubscribers.length);

	function updateOutputConfig(patch: Record<string, unknown>) {
		const tab = activeTab;
		if (!tab) return;
		const next = { ...tab.datasource_config } as Record<string, unknown>;
		const currentOutput = (next.output as Record<string, unknown> | undefined) ?? {};
		next.output = { ...currentOutput, ...patch };
		analysisStore.updateTab(tab.id, { datasource_config: next });
	}

	function updateIcebergConfig(patch: Record<string, unknown>) {
		const current = outputConfig.iceberg ?? {};
		updateOutputConfig({ iceberg: { ...current, ...patch } });
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
			build_mode: 'full',
			iceberg: {
				namespace: 'outputs',
				table_name: tableName,
				branch: defaultBranch
			}
		});
	}

	function startNameEdit() {
		draftName = outputConfig.iceberg.table_name;
		editingName = true;
	}

	function commitNameEdit() {
		if (draftName.trim()) {
			updateIcebergConfig({ table_name: draftName.trim() });
		}
		editingName = false;
	}

	function cancelNameEdit() {
		editingName = false;
	}

	function applyGlobalBranchValue(next: string) {
		ensureOutputConfig();
		const tab = activeTab;
		if (!tab) return;
		const base = (tab.datasource_config ?? {}) as Record<string, unknown>;
		const output = (base.output as Record<string, unknown> | undefined) ?? {};
		const iceberg = (output.iceberg as Record<string, unknown> | undefined) ?? {};
		const trimmed = next.trim();
		const branch = trimmed.length > 0 ? trimmed : defaultBranch;
		analysisStore.setOutputBranch(branch);
		updateOutputConfig({ iceberg: { ...iceberg, branch } });
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

		const pipeline = buildAnalysisPipelinePayload(
			analysisId,
			analysisStore.tabs,
			datasourceStore.datasources
		);
		if (!pipeline) {
			error = 'Unable to build analysis payload.';
			building = false;
			return;
		}
		const result = await buildAnalysisWithPayload({
			analysis_pipeline: pipeline,
			tab_id: activeTab?.id ?? null
		});
		result.match(
			(res: BuildResponse) => {
				const failed = res.results.find(
					(r: BuildResponse['results'][number]) => r.status === 'failed'
				);
				if (failed?.error) {
					error = failed.error;
				}
				queryClient.invalidateQueries({ queryKey: ['engine-runs', analysisId] });
				queryClient.invalidateQueries({ queryKey: ['datasource', outputDatasourceId] });
				queryClient.invalidateQueries({ queryKey: ['datasources'] });
				void datasourceStore.loadDatasources();
				building = false;
			},
			(err: { message: string }) => {
				error = err.message;
				building = false;
			}
		);
	}

	// DOM: $derived can't close menu on outside click.
	$effect(() => {
		if (!modeMenuOpen) return;
		const handleOutside = (event: MouseEvent) => {
			const target = event.target as Node | null;
			if (!target) return;
			if (modeMenuRef?.contains(target)) return;
			if (modeTriggerRef?.contains(target)) return;
			modeMenuOpen = false;
		};
		window.addEventListener('mousedown', handleOutside, true);
		return () => {
			window.removeEventListener('mousedown', handleOutside, true);
		};
	});
</script>

<div class="step-node relative w-[60%]">
	<div class="node-content border border-tertiary bg-primary">
		<!-- Header: icon + label + badge (mirrors DatasourceNode) -->
		<div class="flex items-center justify-between px-4 py-3 border-b border-tertiary">
			<div class="flex items-center gap-2">
				<div class="flex h-5 w-5 items-center justify-center bg-accent text-bg-primary">
					<Database size={12} />
				</div>
				<span class="text-xs font-semibold uppercase tracking-wide">output</span>
			</div>
			<span
				class="border border-tertiary bg-tertiary px-1.5 py-0.5 text-[0.5625rem] uppercase tracking-widest text-fg-faint"
				>sink</span
			>
		</div>

		<!-- Export Name (same info-row pattern as DatasourceNode tab name) -->
		<div
			class="mx-4 mt-4 mb-3 flex items-center justify-between border border-tertiary bg-secondary p-2 px-3"
		>
			<div
				class="info-label flex items-center gap-2 text-[0.625rem] uppercase tracking-widest text-fg-faint"
			>
				<Pencil size={11} class="opacity-50" />
				<span>Table name</span>
			</div>
			<div class="flex items-center gap-2">
				{#if editingName}
					<div class="flex items-center gap-1">
						<input
							class="min-w-25 border border-tertiary bg-primary px-2 py-0.5 text-sm outline-none"
							bind:value={draftName}
							onkeydown={(e) => {
								if (e.key === 'Enter') commitNameEdit();
								if (e.key === 'Escape') cancelNameEdit();
							}}
							aria-label="Edit export name"
						/>
						<button
							class="icon-btn save inline-flex h-5 w-5 cursor-pointer items-center justify-center border border-accent-primary text-success bg-primary p-0 leading-none hover:bg-success hover:text-fg-primary"
							onclick={commitNameEdit}
							type="button"
							aria-label="Save"
						>
							<Check size={12} class="shrink-0" />
						</button>
						<button
							class="icon-btn cancel inline-flex h-5 w-5 cursor-pointer items-center justify-center border border-error text-error bg-primary p-0 leading-none hover:bg-error hover:text-fg-primary"
							onclick={cancelNameEdit}
							type="button"
							aria-label="Cancel"
						>
							<X size={12} class="shrink-0" />
						</button>
					</div>
				{:else}
					<span class="text-sm font-medium">{outputConfig.iceberg.table_name}</span>
					<button
						class="icon-btn edit inline-flex h-5 w-5 cursor-pointer items-center justify-center border border-tertiary text-fg-muted bg-primary p-0 opacity-50 leading-none hover:border-tertiary hover:text-fg-primary hover:bg-tertiary hover:opacity-100"
						onclick={startNameEdit}
						type="button"
						aria-label="Edit export name"
					>
						<Pencil size={12} class="shrink-0" />
					</button>
				{/if}
			</div>
		</div>

		<!-- Output Details (mirrors DatasourceNode dataset card) -->
		<div class="mx-4 mb-3">
			<div
				class="info-label mb-2 flex items-center gap-2 text-xs uppercase tracking-wide text-fg-muted"
			>
				<Database size={12} class="opacity-60" />
				<span>Output</span>
			</div>
			<div class="flex flex-col gap-2 border border-tertiary bg-tertiary p-3">
				<div class="flex items-center justify-between">
					<span class="text-sm font-semibold">{outputConfig.iceberg.table_name}</span>
					<button
						type="button"
						class="flex items-center gap-1 border border-tertiary bg-secondary px-2 py-0.5 text-[10px] hover:text-fg-primary"
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
				</div>
				<div class="grid grid-cols-2 gap-2 border-t border-tertiary pt-2">
					<div class="column-select relative" bind:this={modeMenuRef}>
						<button
							type="button"
							class="column-trigger w-full"
							onclick={() => (modeMenuOpen = !modeMenuOpen)}
							aria-expanded={modeMenuOpen}
							bind:this={modeTriggerRef}
						>
							<span class="column-label">{outputConfig.build_mode}</span>
							<ChevronDown size={14} class="chevron" />
						</button>
						{#if modeMenuOpen}
							<div class="column-menu" role="listbox">
								<div class="column-options">
									{#each ['full', 'incremental', 'recreate'] as mode (mode)}
										<button
											type="button"
											class="column-option"
											class:selected={outputConfig.build_mode === mode}
											onclick={() => {
												updateOutputConfig({ build_mode: mode });
												modeMenuOpen = false;
											}}
											role="option"
											aria-selected={outputConfig.build_mode === mode}
										>
											<span>{mode}</span>
										</button>
									{/each}
								</div>
							</div>
						{/if}
					</div>
					<BranchPicker
						branches={branchOptions}
						value={branchValue}
						placeholder="Branch"
						allowCreate={true}
						onChange={applyGlobalBranchValue}
					/>
				</div>
			</div>
		</div>

		<!-- Build Action -->
		<div class="mx-4 mb-3">
			<button
				class="flex w-full cursor-pointer items-center justify-center gap-2 border border-tertiary bg-secondary p-2 px-3 text-xs font-medium text-fg-secondary hover:border-accent-primary hover:bg-tertiary hover:text-fg-primary disabled:cursor-not-allowed disabled:opacity-50 [&:hover_svg]:opacity-100"
				onclick={handleManualBuild}
				disabled={!analysisId || building}
				title="Run analysis build"
				type="button"
			>
				{#if building}
					<Loader size={14} class="spin opacity-70" />
					<span>building...</span>
				{:else}
					<Play size={14} class="opacity-70" />
					<span>build</span>
				{/if}
			</button>
		</div>

		<!-- Collapsible Sections -->
		<div class="flex flex-col gap-3 border-t border-tertiary pt-3 mx-4 mb-3">
			<!-- Build Notification Section -->
			<div>
				<button
					type="button"
					class="flex h-6 w-full cursor-pointer items-center justify-between border-none bg-transparent p-0 text-xs text-fg-tertiary hover:text-fg-primary"
					onclick={() => (notifyOpen = !notifyOpen)}
				>
					<span class="flex items-center gap-2">
						{#if notifyOpen}
							<ChevronDown size={12} />
						{:else}
							<ChevronRight size={12} />
						{/if}
						<Bell size={12} />
						<span>Build Notification</span>
					</span>
					{#if notifyConfig.enabled}
						<span class="bg-accent-bg px-1.5 py-0.5 text-[10px] text-accent-primary">
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
										Telegram not enabled. Enable bot in global settings.
									</div>
								{:else}
									<div class="flex flex-col gap-1">
										<span class="text-[10px] uppercase text-fg-muted">Recipients</span>
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
											{:else}
												{#each activeSubscribers as sub (sub.id)}
													<div
														class="flex items-center gap-2 border-b border-tertiary px-2 py-1.5 last:border-b-0"
													>
														<span class="truncate text-xs text-fg-primary">{sub.title}</span>
														<span class="ml-auto shrink-0 text-[10px] text-fg-muted">
															{sub.chat_id}
														</span>
													</div>
												{/each}
											{/if}
										</div>
										<span class="text-[10px] text-fg-muted">
											All active subscribers receive build notifications.
										</span>
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
										&#123;&#123;analysis_name&#125;&#125;, &#123;&#123;status&#125;&#125;,
										&#123;&#123;duration_ms&#125;&#125;, &#123;&#123;row_count&#125;&#125;
									</span>
								</div>
							</div>
						{/if}
					</div>
				{/if}
			</div>

			<!-- Health Checks Section -->
			<div>
				<button
					type="button"
					class="flex h-6 w-full cursor-pointer items-center justify-between border-none bg-transparent p-0 text-xs text-fg-tertiary hover:text-fg-primary"
					onclick={() => (healthOpen = !healthOpen)}
				>
					<span class="flex items-center gap-2">
						{#if healthOpen}
							<ChevronDown size={12} />
						{:else}
							<ChevronRight size={12} />
						{/if}
						<HeartPulse size={12} />
						<span>Health Checks</span>
					</span>
					{#if healthCount > 0}
						<span
							class="px-1.5 py-0.5 text-[10px] {healthPassed === true
								? 'bg-success-bg text-success-fg'
								: healthPassed === false
									? 'bg-error-bg text-error-fg'
									: 'bg-accent-bg text-accent-primary'}"
						>
							{healthCount}
						</span>
					{/if}
				</button>

				{#if healthOpen}
					{#if canQueryOutput}
						<div class="mt-2 border border-tertiary bg-primary p-2">
							<HealthChecksManager datasourceId={outputDatasourceId ?? undefined} compact />
						</div>
					{:else}
						<div
							class="mt-2 border border-dashed border-tertiary p-3 text-center text-xs text-fg-tertiary"
						>
							Save this analysis to create an output datasource before adding health checks.
						</div>
					{/if}
				{/if}
			</div>

			<!-- Schedule Section -->
			<div>
				<button
					type="button"
					class="flex h-6 w-full cursor-pointer items-center justify-between border-none bg-transparent p-0 text-xs text-fg-tertiary hover:text-fg-primary"
					onclick={() => (scheduleOpen = !scheduleOpen)}
				>
					<span class="flex items-center gap-2">
						{#if scheduleOpen}
							<ChevronDown size={12} />
						{:else}
							<ChevronRight size={12} />
						{/if}
						<CalendarClock size={12} />
						<span>Schedules</span>
					</span>
					{#if scheduleCount > 0}
						<span class="bg-accent-bg px-1.5 py-0.5 text-[10px] text-accent-primary">
							{enabledSchedules}/{scheduleCount}
						</span>
					{/if}
				</button>

				{#if scheduleOpen && canQueryOutput}
					<div class="mt-2 border border-tertiary bg-primary p-2">
						<ScheduleManager datasourceId={outputDatasourceId ?? undefined} compact />
					</div>
				{/if}
			</div>
		</div>

		{#if error}
			<div class="mt-3 border border-error bg-error p-2 text-xs text-error">{error}</div>
		{/if}
	</div>
</div>
