<script lang="ts">
	type OutputTab = {
		id: string;
		name: string;
		output: {
			output_datasource_id: string;
			format: string;
			filename: string;
			build_mode?: string;
			iceberg?: Record<string, unknown>;
		} & Record<string, unknown>;
		datasource?: {
			config?: {
				branch?: string;
			};
		};
	};
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
	import { css, cx, chip, input, label, row, rowBetween, muted } from '$lib/styles/panda';
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
		activeTab?: OutputTab | null;
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

	const outputConfig = $derived.by(() => {
		const tab = activeTab as (OutputTab & { datasource?: { config?: { branch?: string } } }) | null;
		const output = (tab?.output as Record<string, unknown> | null) ?? null;
		const icebergRaw = output?.iceberg as Record<string, unknown> | undefined;
		const defaultName = tab?.name ? tab.name.trim() : 'export';
		const tableName =
			(icebergRaw?.table_name as string) ||
			defaultName.replace(/\s+/g, '_').toLowerCase() ||
			'export';
		const branch =
			typeof icebergRaw?.branch === 'string'
				? icebergRaw.branch
				: (((tab?.datasource as Record<string, unknown>)?.config as { branch?: string } | undefined)
						?.branch ?? '');
		const namespace = (icebergRaw?.namespace as string) || 'outputs';
		return {
			format: 'parquet',
			filename: (output?.filename as string) || tableName,
			build_mode: (output?.build_mode as string) || 'full',
			iceberg: {
				namespace,
				table_name: tableName,
				branch
			},
			notification: (output?.notification as Record<string, unknown> | undefined) ?? null
		};
	});

	const branchValue = $derived(outputConfig.iceberg.branch);
	const branchOptions = $derived.by(() => {
		const branches = (outputDatasourceQuery.data?.config?.branches as string[] | undefined) ?? [];
		const cleaned = branches.map((branch) => branch.trim()).filter((branch) => branch.length > 0);
		const current = branchValue.trim();
		if (!current) return cleaned;
		if (cleaned.includes(current)) return cleaned;
		return [current, ...cleaned];
	});
	const idPrefix = $derived(`output-${analysisId ?? datasourceId ?? 'node'}`);

	const outputDatasourceId = $derived(activeTab?.output?.output_datasource_id ?? null);
	const outputDefaults = $derived.by(() => {
		const tab = activeTab;
		if (!tab) return null;
		const output = tab.output as Record<string, unknown> | null;
		const icebergRaw = output?.iceberg as Record<string, unknown> | undefined;
		const defaultName = tab.name ? tab.name.trim() : 'export';
		const tableName =
			(icebergRaw?.table_name as string) ||
			defaultName.replace(/\s+/g, '_').toLowerCase() ||
			'export';
		const namespace = (icebergRaw?.namespace as string) || 'outputs';
		const branch =
			typeof icebergRaw?.branch === 'string'
				? icebergRaw.branch
				: (((tab.datasource as Record<string, unknown>)?.config as { branch?: string } | undefined)
						?.branch ?? '');
		return {
			format: 'parquet',
			filename: (output?.filename as string) || tableName,
			build_mode: (output?.build_mode as string) || 'full',
			iceberg: {
				namespace,
				table_name: tableName,
				branch
			}
		};
	});
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
		const currentOutput = tab.output as Record<string, unknown>;
		const fallback = outputDefaults ?? {
			output_datasource_id: tab.output.output_datasource_id,
			format: 'parquet',
			filename: 'export',
			build_mode: 'full',
			iceberg: { namespace: 'outputs', table_name: 'export', branch: '' }
		};
		const nextOutput = { ...fallback, ...currentOutput, ...patch };
		analysisStore.updateTab(tab.id, { output: nextOutput as OutputTab['output'] });
	}

	function updateIcebergConfig(patch: Record<string, unknown>) {
		const current = outputConfig.iceberg ?? {};
		updateOutputConfig({ iceberg: { ...current, ...patch } });
	}

	function ensureOutputConfig(): void {
		return;
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
		const tab = activeTab;
		if (!tab) return;
		const output = (tab.output as Record<string, unknown>) ?? {};
		const iceberg = output.iceberg as Record<string, unknown> | undefined;
		const branch = next.trim();
		if (!branch) return;
		updateOutputConfig({ iceberg: { ...iceberg, branch } });
	}

	function toggleNotification() {
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

<div
	class={css({
		contentVisibility: 'auto',
		containIntrinsicSize: 'auto 200px',
		position: 'relative',
		width: '60%'
	})}
>
	<div
		class={css({
			borderWidth: '1',
			backgroundColor: 'bg.primary'
		})}
	>
		<!-- Header: icon + label + badge (mirrors DatasourceNode) -->
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'space-between',
				paddingX: '4',
				paddingY: '3',
				borderBottomWidth: '1'
			})}
		>
			<div class={cx(row, css({ gap: '2' }))}>
				<div
					class={css({
						display: 'flex',
						height: 'iconMd',
						width: 'iconMd',
						alignItems: 'center',
						justifyContent: 'center',
						backgroundColor: 'accent.primary',
						color: 'fg.inverse'
					})}
				>
					<Database size={12} />
				</div>
				<span
					class={css({
						fontSize: 'xs',
						fontWeight: '600',
						textTransform: 'uppercase',
						letterSpacing: 'wide'
					})}
				>
					output
				</span>
			</div>
			<span
				class={cx(
					chip({ tone: 'neutral' }),
					css({
						borderWidth: '1',
						letterSpacing: 'widest',
						color: 'fg.faint'
					})
				)}>sink</span
			>
		</div>

		<!-- Export Name (same info-row pattern as DatasourceNode tab name) -->
		<div
			class={css({
				marginX: '4',
				marginTop: '4',
				marginBottom: '3',
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'space-between',
				borderWidth: '1',
				backgroundColor: 'bg.secondary',
				paddingY: '2',
				paddingX: '3'
			})}
		>
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					gap: '2',
					fontSize: '2xs',
					textTransform: 'uppercase',
					letterSpacing: 'widest',
					color: 'fg.faint'
				})}
			>
				<Pencil size={11} class={css({ opacity: '0.5' })} />
				<span>Table name</span>
			</div>
			<div class={cx(row, css({ gap: '2' }))}>
				{#if editingName}
					<div class={cx(row, css({ gap: '1' }))}>
						<input
							class={cx(
								input(),
								css({
									minWidth: 'fieldSm',
									paddingX: '2',
									paddingY: '0.5',
									fontSize: 'sm'
								})
							)}
							id="output-node-name"
							bind:value={draftName}
							onkeydown={(e) => {
								if (e.key === 'Enter') commitNameEdit();
								if (e.key === 'Escape') cancelNameEdit();
							}}
							aria-label="Edit export name"
						/>
						<button
							class={css({
								display: 'inline-flex',
								height: 'iconMd',
								width: 'iconMd',
								cursor: 'pointer',
								alignItems: 'center',
								justifyContent: 'center',
								borderWidth: '1',
								color: 'success.fg',
								backgroundColor: 'bg.primary',
								padding: '0',
								lineHeight: '1',
								_hover: { backgroundColor: 'success.bg', color: 'fg.primary' }
							})}
							onclick={commitNameEdit}
							type="button"
							aria-label="Save"
						>
							<Check size={12} class={css({ flexShrink: '0' })} />
						</button>
						<button
							class={css({
								display: 'inline-flex',
								height: 'iconMd',
								width: 'iconMd',
								cursor: 'pointer',
								alignItems: 'center',
								justifyContent: 'center',
								borderWidth: '1',
								borderColor: 'error.border',
								color: 'error.fg',
								backgroundColor: 'bg.primary',
								padding: '0',
								lineHeight: '1',
								_hover: { backgroundColor: 'error.bg', color: 'fg.primary' }
							})}
							onclick={cancelNameEdit}
							type="button"
							aria-label="Cancel"
						>
							<X size={12} class={css({ flexShrink: '0' })} />
						</button>
					</div>
				{:else}
					<span class={css({ fontSize: 'sm', fontWeight: '500' })}>
						{outputConfig.iceberg.table_name}
					</span>
					<button
						class={css({
							display: 'inline-flex',
							height: 'iconMd',
							width: 'iconMd',
							cursor: 'pointer',
							alignItems: 'center',
							justifyContent: 'center',
							borderWidth: '1',
							color: 'fg.muted',
							backgroundColor: 'bg.primary',
							padding: '0',
							opacity: '0.5',
							lineHeight: '1',
							_hover: {
								backgroundColor: 'bg.tertiary',
								opacity: '1'
							}
						})}
						onclick={startNameEdit}
						type="button"
						aria-label="Edit export name"
					>
						<Pencil size={12} class={css({ flexShrink: '0' })} />
					</button>
				{/if}
			</div>
		</div>

		<!-- Output Details (mirrors DatasourceNode dataset card) -->
		<div class={css({ marginX: '4', marginBottom: '3' })}>
			<div
				class={css({
					marginBottom: '2',
					display: 'flex',
					alignItems: 'center',
					gap: '2',
					fontSize: 'xs',
					textTransform: 'uppercase',
					letterSpacing: 'wide',
					color: 'fg.muted'
				})}
			>
				<Database size={12} class={css({ opacity: '0.6' })} />
				<span>Output</span>
			</div>
			<div
				class={css({
					display: 'flex',
					flexDirection: 'column',
					gap: '2',
					borderWidth: '1',
					backgroundColor: 'bg.tertiary',
					padding: '3'
				})}
			>
				<div class={rowBetween}>
					<span class={css({ fontSize: 'sm', fontWeight: '600' })}>
						{outputConfig.iceberg.table_name}
					</span>
					<button
						type="button"
						class={css({
							display: 'flex',
							alignItems: 'center',
							gap: '1',
							borderWidth: '1',
							backgroundColor: 'bg.secondary',
							paddingX: '2',
							paddingY: '0.5',
							fontSize: '2xs',
							color: hidden ? 'fg.muted' : 'success.fg',
							_hover: { color: 'fg.primary' }
						})}
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
				<div
					class={css({
						display: 'grid',
						gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
						gap: '2',
						borderTopWidth: '1',
						paddingTop: '2'
					})}
				>
					<div
						class={cx(
							css({
								position: 'relative',
								display: 'flex',
								flexDirection: 'column',
								gap: '2',
								minWidth: 'inputSm'
							}),
							css({ position: 'relative' })
						)}
						bind:this={modeMenuRef}
					>
						<button
							type="button"
							class={cx(
								css({
									display: 'flex',
									alignItems: 'center',
									gap: '2',
									paddingX: '3',
									paddingY: '2',
									borderWidth: '1',
									backgroundColor: 'bg.secondary',
									cursor: 'pointer',
									justifyContent: 'space-between',
									fontSize: 'sm',
									_focusVisible: {
										outline: '2px solid {colors.accent.secondary}',
										outlineOffset: '2px'
									}
								}),
								css({ width: '100%' })
							)}
							onclick={() => (modeMenuOpen = !modeMenuOpen)}
							aria-expanded={modeMenuOpen}
							bind:this={modeTriggerRef}
						>
							<span
								class={css({
									flex: '1',
									textAlign: 'left',
									minWidth: '0',
									overflow: 'hidden',
									textOverflow: 'ellipsis',
									whiteSpace: 'nowrap'
								})}>{outputConfig.build_mode}</span
							>
							<ChevronDown size={14} class={muted} />
						</button>
						{#if modeMenuOpen}
							<div
								class={css({
									position: 'absolute',
									zIndex: 'dropdown',
									top: 'calc(100% + 6px)',
									left: '0',
									minWidth: '100%',
									width: '100%',
									maxWidth: '100%',
									backgroundColor: 'bg.primary',
									borderWidth: '1',
									padding: '2',
									display: 'flex',
									flexDirection: 'column',
									gap: '2'
								})}
								role="listbox"
							>
								<div
									class={css({
										display: 'flex',
										flexDirection: 'column',
										gap: '2',
										maxHeight: 'dropdown',
										overflowY: 'auto',
										overflowX: 'hidden',
										padding: '2',
										scrollbarWidth: 'thin',
										scrollbarColor: '{colors.border.primary} transparent'
									})}
								>
									{#each ['full', 'incremental', 'recreate'] as mode (mode)}
										<button
											type="button"
											class={cx(
												css({
													minWidth: '0',
													width: '100%',
													paddingX: '3',
													paddingY: '2',
													borderWidth: '1',
													borderColor: 'transparent',
													background: 'transparent',
													textAlign: 'left',
													display: 'flex',
													alignItems: 'center',
													justifyContent: 'flex-start',
													gap: '2',
													cursor: 'pointer',
													fontSize: 'sm',
													'& span': { minWidth: '0', overflowWrap: 'anywhere' },
													_hover: { backgroundColor: 'bg.hover' }
												}),
												outputConfig.build_mode === mode && css({ backgroundColor: 'bg.hover' })
											)}
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
		<div class={css({ marginX: '4', marginBottom: '3' })}>
			<button
				class={css({
					display: 'flex',
					width: '100%',
					cursor: 'pointer',
					alignItems: 'center',
					justifyContent: 'center',
					gap: '2',
					borderWidth: '1',
					backgroundColor: 'bg.secondary',
					paddingY: '2',
					paddingX: '3',
					fontSize: 'xs',
					fontWeight: '500',
					color: 'fg.secondary',
					_hover: {
						backgroundColor: 'bg.tertiary',
						'& svg': { opacity: '1' }
					},
					_disabled: { cursor: 'not-allowed', opacity: '0.5' }
				})}
				onclick={handleManualBuild}
				disabled={!analysisId || building}
				title="Run analysis build"
				type="button"
			>
				{#if building}
					<Loader size={14} class={css({ opacity: '0.7' })} />
					<span>building...</span>
				{:else}
					<Play size={14} class={css({ opacity: '0.7' })} />
					<span>build</span>
				{/if}
			</button>
		</div>

		<!-- Collapsible Sections -->
		<div
			class={css({
				display: 'flex',
				flexDirection: 'column',
				gap: '3',
				borderTopWidth: '1',
				paddingTop: '3',
				marginX: '4',
				marginBottom: '3'
			})}
		>
			<!-- Build Notification Section -->
			<div>
				<button
					type="button"
					class={css({
						display: 'flex',
						height: 'iconLg',
						width: '100%',
						cursor: 'pointer',
						alignItems: 'center',
						justifyContent: 'space-between',
						border: 'none',
						backgroundColor: 'transparent',
						padding: '0',
						fontSize: 'xs',
						color: 'fg.tertiary',
						_hover: { color: 'fg.primary' }
					})}
					onclick={() => (notifyOpen = !notifyOpen)}
				>
					<span class={cx(row, css({ gap: '2' }))}>
						{#if notifyOpen}
							<ChevronDown size={12} />
						{:else}
							<ChevronRight size={12} />
						{/if}
						<Bell size={12} />
						<span>Build Notification</span>
					</span>
					{#if notifyConfig.enabled}
						<span class={chip({ tone: 'accent' })}>
							{selectedCount}/{activeSubscribers.length}
						</span>
					{/if}
				</button>

				{#if notifyOpen}
					<div
						class={css({
							marginTop: '2',
							display: 'flex',
							flexDirection: 'column',
							gap: '2',
							paddingLeft: '5'
						})}
					>
						<label class={cx(label({ variant: 'checkbox' }), css({ gap: '2', fontSize: 'xs' }))}>
							<input
								name="notify_enabled"
								type="checkbox"
								checked={notifyConfig.enabled}
								onchange={toggleNotification}
							/>
							<span>Notify subscribers on build</span>
						</label>

						{#if notifyConfig.enabled}
							<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
								{#if !canTelegram}
									<div
										class={css({
											borderWidth: '1',
											borderColor: 'warning.border',
											backgroundColor: 'warning.bg',
											padding: '2',
											fontSize: '2xs',
											color: 'warning.fg'
										})}
									>
										Telegram not enabled. Enable bot in global settings.
									</div>
								{:else}
									<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
										<span
											class={css({
												fontSize: '2xs',
												textTransform: 'uppercase',
												color: 'fg.muted'
											})}
										>
											Recipients
										</span>
										<div
											class={css({
												maxHeight: 'colMd',
												overflowY: 'auto',
												borderWidth: '1',
												backgroundColor: 'bg.secondary'
											})}
										>
											{#if subscribersQuery.isPending}
												<div
													class={css({
														padding: '2',
														textAlign: 'center',
														fontSize: '2xs',
														color: 'fg.muted'
													})}
												>
													Loading...
												</div>
											{:else if subscribersQuery.isError}
												<div
													class={css({
														padding: '2',
														textAlign: 'center',
														fontSize: '2xs',
														color: 'error.fg'
													})}
												>
													Failed to load subscribers
												</div>
											{:else if activeSubscribers.length === 0}
												<div
													class={css({
														padding: '2',
														textAlign: 'center',
														fontSize: '2xs',
														color: 'fg.muted'
													})}
												>
													No subscribers. Users can subscribe via /subscribe in Telegram.
												</div>
											{:else}
												{#each activeSubscribers as sub (sub.id)}
													<div
														class={css({
															display: 'flex',
															alignItems: 'center',
															gap: '2',
															borderBottomWidth: '1',
															paddingX: '2',
															paddingY: '1.5',
															'&:last-child': { borderBottomWidth: '0' }
														})}
													>
														<span
															class={css({
																overflow: 'hidden',
																textOverflow: 'ellipsis',
																whiteSpace: 'nowrap',
																fontSize: 'xs',
																color: 'fg.primary'
															})}
														>
															{sub.title}
														</span>
														<span
															class={css({
																marginLeft: 'auto',
																flexShrink: '0',
																fontSize: '2xs',
																color: 'fg.muted'
															})}
														>
															{sub.chat_id}
														</span>
													</div>
												{/each}
											{/if}
										</div>
										<span class={css({ fontSize: '2xs', color: 'fg.muted' })}>
											All active subscribers receive build notifications.
										</span>
									</div>
								{/if}

								<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
									<label
										class={cx(label(), css({ fontSize: '2xs' }))}
										for={`${idPrefix}-notify-body`}
									>
										Message Template
									</label>
									<textarea
										class={cx(
											input(),
											css({
												backgroundColor: 'bg.secondary',
												paddingY: '1',
												paddingX: '2',
												fontSize: 'xs'
											})
										)}
										id={`${idPrefix}-notify-body`}
										rows="3"
										value={notifyConfig.body_template}
										oninput={(e) =>
											updateNotification({
												body_template: e.currentTarget.value
											})}
									></textarea>
									<span class={css({ fontSize: '2xs', color: 'fg.muted' })}>
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
					class={css({
						display: 'flex',
						height: 'iconLg',
						width: '100%',
						cursor: 'pointer',
						alignItems: 'center',
						justifyContent: 'space-between',
						border: 'none',
						backgroundColor: 'transparent',
						padding: '0',
						fontSize: 'xs',
						color: 'fg.tertiary',
						_hover: { color: 'fg.primary' }
					})}
					onclick={() => (healthOpen = !healthOpen)}
				>
					<span class={cx(row, css({ gap: '2' }))}>
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
							class={cx(
								css({ paddingX: '1.5', paddingY: '0.5', fontSize: '2xs' }),
								healthPassed === true &&
									css({ backgroundColor: 'success.bg', color: 'success.fg' }),
								healthPassed === false && css({ backgroundColor: 'error.bg', color: 'error.fg' }),
								healthPassed !== true &&
									healthPassed !== false &&
									css({ backgroundColor: 'accent.bg', color: 'accent.primary' })
							)}
						>
							{healthCount}
						</span>
					{/if}
				</button>

				{#if healthOpen}
					{#if canQueryOutput}
						<div
							class={css({
								marginTop: '2',
								borderWidth: '1',
								backgroundColor: 'bg.primary',
								padding: '2'
							})}
						>
							<HealthChecksManager datasourceId={outputDatasourceId ?? undefined} compact />
						</div>
					{:else}
						<div
							class={css({
								marginTop: '2',
								borderWidth: '1',
								borderStyle: 'dashed',
								padding: '3',
								textAlign: 'center',
								fontSize: 'xs',
								color: 'fg.tertiary'
							})}
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
					class={css({
						display: 'flex',
						height: 'iconLg',
						width: '100%',
						cursor: 'pointer',
						alignItems: 'center',
						justifyContent: 'space-between',
						border: 'none',
						backgroundColor: 'transparent',
						padding: '0',
						fontSize: 'xs',
						color: 'fg.tertiary',
						_hover: { color: 'fg.primary' }
					})}
					onclick={() => (scheduleOpen = !scheduleOpen)}
				>
					<span class={cx(row, css({ gap: '2' }))}>
						{#if scheduleOpen}
							<ChevronDown size={12} />
						{:else}
							<ChevronRight size={12} />
						{/if}
						<CalendarClock size={12} />
						<span>Schedules</span>
					</span>
					{#if scheduleCount > 0}
						<span class={chip({ tone: 'accent' })}>
							{enabledSchedules}/{scheduleCount}
						</span>
					{/if}
				</button>

				{#if scheduleOpen && canQueryOutput}
					<div
						class={css({
							marginTop: '2',
							borderWidth: '1',
							backgroundColor: 'bg.primary',
							padding: '2'
						})}
					>
						<ScheduleManager datasourceId={outputDatasourceId ?? undefined} compact />
					</div>
				{/if}
			</div>
		</div>

		{#if error}
			<div
				class={css({
					marginTop: '3',
					borderWidth: '1',
					borderColor: 'error.border',
					backgroundColor: 'error.bg',
					padding: '2',
					fontSize: 'xs',
					color: 'error.fg'
				})}
			>
				{error}
			</div>
		{/if}
	</div>
</div>
