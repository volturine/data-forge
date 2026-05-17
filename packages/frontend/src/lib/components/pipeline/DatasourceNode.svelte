<script lang="ts">
	import type { DataSource } from '$lib/types/datasource';
	import type { AnalysisTab, AnalysisTabDatasource } from '$lib/types/analysis';
	import { createQuery } from '@tanstack/svelte-query';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { getDatasource } from '$lib/api/datasource';
	import { schemaStore } from '$lib/stores/schema.svelte';
	import { track } from '$lib/utils/audit-log';
	import {
		Copy,
		FileText,
		Database,
		Layers,
		Snowflake,
		GitMerge,
		PanelLeft,
		Pencil,
		RefreshCw,
		Check,
		X,
		Cpu,
		ChevronDown
	} from 'lucide-svelte';
	import { drag } from '$lib/stores/drag.svelte';
	import FileTypeBadge from '$lib/components/common/FileTypeBadge.svelte';
	import BranchPicker from '$lib/components/common/BranchPicker.svelte';
	import SnapshotPicker from '$lib/components/datasources/SnapshotPicker.svelte';
	import type { SourceType } from '$lib/utils/file-types';
	import { css } from '$lib/styles/panda';

	interface Props {
		datasource: DataSource | null;
		datasourceLabel?: string | null;
		tabName?: string;
		analysisId?: string;
		activeTab?: AnalysisTab | null;
		onChangeDatasource?: () => void;
		onRenameTab?: (name: string) => void;
		onDuplicateTab?: () => void;
		readOnly?: boolean;
	}

	let {
		datasource,
		datasourceLabel = null,
		tabName,
		analysisId,
		activeTab: activeTabRaw,
		onChangeDatasource,
		onRenameTab,
		onDuplicateTab,
		readOnly = false
	}: Props = $props();

	const activeTab = $derived(activeTabRaw);

	let isEditing = $state(false);
	let draftName = $state('');

	// Engine config - simple state bound to store
	let engineExpanded = $state(false);

	// Use defaults from store (fetched by analysis page on load)
	const defaults = $derived(analysisStore.engineDefaults);

	// Threads: show effective value (default when not overridden)
	const threadsOverride = $derived(analysisStore.resourceConfig?.max_threads ?? 0);
	const effectiveThreads = $derived(threadsOverride || defaults?.max_threads || 0);
	const isUsingDefaultThreads = $derived(threadsOverride === 0);
	function setThreads(value: number) {
		if (readOnly) return;
		const current = analysisStore.resourceConfig ?? {};
		// If set to the default value, treat as "use default" (store undefined)
		const defaultThreads = defaults?.max_threads ?? 0;
		const storeValue = value === defaultThreads ? undefined : value || undefined;
		analysisStore.setResourceConfig({ ...current, max_threads: storeValue });
	}

	// Memory: show effective value (default when not overridden)
	const memoryGbOverride = $derived(
		Math.floor((analysisStore.resourceConfig?.max_memory_mb ?? 0) / 1024)
	);
	const effectiveMemoryGb = $derived(
		memoryGbOverride || Math.floor((defaults?.max_memory_mb ?? 0) / 1024)
	);
	const isUsingDefaultMemory = $derived(memoryGbOverride === 0);
	function setMemoryGb(value: number) {
		if (readOnly) return;
		const current = analysisStore.resourceConfig ?? {};
		// If set to the default value, treat as "use default" (store undefined)
		const defaultMemoryGb = Math.floor((defaults?.max_memory_mb ?? 0) / 1024);
		const storeValue = value === defaultMemoryGb ? undefined : value ? value * 1024 : undefined;
		analysisStore.setResourceConfig({ ...current, max_memory_mb: storeValue });
	}

	const standardMemoryOptions = [1, 2, 4, 8, 16, 32, 64];
	// Include the default/effective value in options if not already present
	const memoryOptions = $derived.by(() => {
		const val = effectiveMemoryGb;
		if (val && !standardMemoryOptions.includes(val)) {
			return [...standardMemoryOptions, val].sort((a, b) => a - b);
		}
		return standardMemoryOptions;
	});

	const isIceberg = $derived(datasource?.source_type === 'iceberg');
	const datasourceQuery = createQuery(() => ({
		queryKey: ['datasource', datasource?.id ?? null, datasource?.config?.branch ?? ''],
		queryFn: async () => {
			if (!datasource?.id) return null;
			const result = await getDatasource(datasource.id);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		enabled: !!datasource?.id
	}));
	const resolvedDatasource = $derived(datasourceQuery.data ?? datasource);
	const outputId = $derived(activeTab?.output.result_id ?? null);
	const isOutputSource = $derived(activeTab?.datasource?.id === outputId && !!outputId);
	function ensureBranch(
		config: AnalysisTabDatasource['config'] | null | undefined,
		fallback: string
	): AnalysisTabDatasource['config'] {
		const branch = fallback.trim();
		return { ...(config ?? { branch }), branch };
	}

	function updateTimeTravelUi(updates: { open?: boolean; month?: string; day?: string }) {
		if (readOnly) return;
		const active = activeTab;
		if (!active) return;
		const branch = active.datasource.config.branch;
		const nextConfig = ensureBranch(active?.datasource?.config, branch ?? '');
		const currentUi = nextConfig.time_travel_ui ?? {};
		nextConfig.time_travel_ui = { ...currentUi, ...updates };
		const tab = active;
		analysisStore.updateTab(active.id, {
			datasource: {
				...(tab?.datasource ?? {}),
				config: nextConfig
			}
		});
	}

	function updateSnapshotConfig(nextConfig: Record<string, unknown>) {
		if (readOnly) return;
		const active = activeTab;
		if (!active) return;
		const branch = active.datasource.config.branch;
		const config = ensureBranch(
			{
				...nextConfig,
				branch:
					typeof nextConfig.branch === 'string' && nextConfig.branch.trim()
						? nextConfig.branch
						: branch
			},
			branch ?? ''
		);
		const tab = active;
		analysisStore.updateTab(active.id, {
			datasource: {
				...(tab?.datasource ?? {}),
				config
			}
		});
		analysisStore.setActiveTab(active.id);
	}

	function handleSnapshotSelect(snapshotId: string | null, timestampMs?: number) {
		schemaStore.reset();
		track({
			event: 'analysis_time_travel',
			action: snapshotId ? 'set_snapshot' : 'set_latest',
			target: datasource?.id ?? '',
			meta: {
				snapshot_id: snapshotId,
				snapshot_timestamp_ms: timestampMs
			}
		});
	}

	function startEdit() {
		if (readOnly) return;
		if (!onRenameTab) return;
		isEditing = true;
		draftName = tabName ?? datasourceLabel ?? datasource?.name ?? '';
	}

	function cancelEdit() {
		isEditing = false;
	}

	function commitEdit() {
		if (readOnly) {
			cancelEdit();
			return;
		}
		if (!onRenameTab) {
			cancelEdit();
			return;
		}
		const next = draftName.trim();
		if (!next) {
			cancelEdit();
			return;
		}
		onRenameTab(next);
		isEditing = false;
	}

	const analysisSourceId = $derived(resolvedDatasource?.created_by_analysis_id ?? null);
	const isDerived = $derived(!!activeTab?.datasource?.analysis_tab_id);
	type DatasourceBadgeType = SourceType | 'analysis' | 'derived';
	function getDatasourceBranches(ds: DataSource | null | undefined): string[] {
		const raw = ds?.config?.branches;
		if (!Array.isArray(raw)) return [];
		return raw.filter((branch): branch is string => typeof branch === 'string' && !!branch.trim());
	}
	function getDatasourceFilePath(ds: DataSource | null | undefined): string {
		const path = ds?.config?.file_path;
		return typeof path === 'string' ? path : '';
	}
	const sourceType = $derived(
		(isDerived
			? 'derived'
			: analysisSourceId
				? 'analysis'
				: (resolvedDatasource?.source_type ?? 'file')) as DatasourceBadgeType
	);
	const isDragActive = $derived(drag.active);
	const snapshotConfig = $derived(activeTab?.datasource?.config ?? {});
	const snapshotBranch = $derived.by((): string | null => {
		const branch = activeTab?.datasource?.config?.branch;
		return typeof branch === 'string' ? branch : null;
	});
	const branchValue = $derived(activeTab?.datasource?.config?.branch ?? '');

	function applyBranchValue(next: string) {
		if (readOnly) return;
		const active = activeTab;
		if (!active) return;
		if (!next.trim()) return;
		const config = ensureBranch(active?.datasource?.config, next);
		const tab = active;
		analysisStore.updateTab(active.id, {
			datasource: {
				...(tab?.datasource ?? {}),
				config
			}
		});
		analysisStore.setActiveTab(active.id);
	}
</script>

<div class={css({ position: 'relative', width: '60%' })}>
	<div
		class={[
			'node-content',
			css({
				backgroundColor: 'bg.primary',
				borderWidth: '1'
			}),
			isDragActive &&
				css({
					borderStyle: 'dashed',
					opacity: '0.85'
				})
		]}
	>
		<!-- Header with icon and badge -->
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
			<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
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
					{#if sourceType === 'file'}
						<FileText size={12} />
					{:else if sourceType === 'database'}
						<Database size={12} />
					{:else if sourceType === 'iceberg'}
						<Snowflake size={12} />
					{:else if sourceType === 'analysis'}
						<Layers size={12} />
					{:else if sourceType === 'derived'}
						<GitMerge size={12} />
					{:else}
						<FileText size={12} />
					{/if}
				</div>
				<span
					class={css({
						fontSize: 'xs',
						fontWeight: 'semibold',
						textTransform: 'uppercase',
						letterSpacing: 'wide'
					})}
				>
					source
				</span>
			</div>
			<button
				class={css({
					display: 'inline-flex',
					alignItems: 'center',
					justifyContent: 'center',
					gap: '1',
					borderWidth: '1',
					borderColor: 'border.primary',
					backgroundColor: 'bg.primary',
					color: 'fg.muted',
					paddingX: '1.5',
					paddingY: '0',
					minHeight: 'iconMd',
					fontSize: '3xs',
					fontWeight: 'medium',
					lineHeight: 'normal',
					textTransform: 'uppercase',
					letterSpacing: 'widest',
					cursor: 'pointer',
					_hover: {
						color: 'fg.primary',
						backgroundColor: 'bg.hover'
					}
				})}
				onclick={onDuplicateTab}
				disabled={readOnly || !onDuplicateTab}
				type="button"
				title="Duplicate tab"
				aria-label="Duplicate tab"
			>
				<Copy size={9} class={css({ display: 'block', flexShrink: '0' })} />
				<span
					class={css({
						display: 'inline-flex',
						alignItems: 'center',
						lineHeight: '1',
						transform: 'translateY(1px)'
					})}>copy</span
				>
			</button>
		</div>

		<!-- Tab Section -->
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
				<PanelLeft size={11} class={css({ opacity: '0.5' })} />
				<span>Tab name</span>
			</div>
			<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
				{#if isEditing}
					<div class={css({ display: 'flex', alignItems: 'center', gap: '1' })}>
						<input
							class={css({
								width: 'full',
								color: 'fg.primary',
								borderWidth: '1',
								borderRadius: '0',
								transitionProperty: 'border-color',
								transitionDuration: '160ms',
								transitionTimingFunction: 'ease',
								_focus: { outline: 'none' },
								_focusVisible: { borderColor: 'border.accent' },
								_disabled: {
									opacity: '0.5',
									cursor: 'not-allowed',
									backgroundColor: 'bg.tertiary'
								},
								_placeholder: { color: 'fg.muted' },
								minWidth: 'fieldSm',
								paddingX: '2',
								paddingY: '0.5',
								fontSize: 'sm'
							})}
							id="ds-node-name"
							bind:value={draftName}
							onkeydown={(e) => {
								if (e.key === 'Enter') commitEdit();
								if (e.key === 'Escape') cancelEdit();
							}}
							aria-label="Edit tab name"
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
								borderColor: 'border.accent',
								color: 'fg.success',
								backgroundColor: 'bg.primary',
								padding: '0',
								lineHeight: '1',
								_hover: { backgroundColor: 'bg.success', color: 'fg.primary' }
							})}
							onclick={commitEdit}
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
								borderColor: 'border.error',
								color: 'fg.error',
								backgroundColor: 'bg.primary',
								padding: '0',
								lineHeight: '1',
								_hover: { backgroundColor: 'bg.error', color: 'fg.primary' }
							})}
							onclick={cancelEdit}
							type="button"
							aria-label="Cancel"
						>
							<X size={12} class={css({ flexShrink: '0' })} />
						</button>
					</div>
				{:else}
					<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}
						>{tabName ?? datasourceLabel ?? datasource?.name ?? 'Untitled'}</span
					>
					{#if onRenameTab && !readOnly}
						<button
							class={css({
								display: 'inline-flex',
								height: 'iconMd',
								width: 'iconMd',
								cursor: 'pointer',
								alignItems: 'center',
								justifyContent: 'center',
								borderWidth: '1',
								borderColor: 'border.primary',
								backgroundColor: 'bg.primary',
								color: 'fg.muted',
								padding: '0',
								lineHeight: '1',
								_hover: {
									color: 'fg.primary',
									backgroundColor: 'bg.tertiary',
									opacity: '1'
								}
							})}
							onclick={startEdit}
							type="button"
							aria-label="Edit tab name"
						>
							<Pencil size={12} class={css({ flexShrink: '0' })} />
						</button>
					{/if}
				{/if}
			</div>
		</div>

		<!-- Dataset Section -->
		<div class={css({ marginX: '4', marginBottom: '3' })}>
			<div
				class={css({
					marginBottom: '2',
					display: 'flex',
					alignItems: 'center',
					gap: '2',
					fontSize: '2xs',
					textTransform: 'uppercase',
					letterSpacing: 'widest',
					color: 'fg.faint'
				})}
			>
				<Database size={11} class={css({ opacity: '0.5' })} />
				<span>Dataset</span>
			</div>
			{#if datasource || datasourceLabel}
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
					<div
						class={css({ display: 'flex', alignItems: 'center', justifyContent: 'space-between' })}
					>
						<div class={css({ fontSize: 'sm', fontWeight: 'semibold' })}>
							{datasourceLabel ?? datasource?.name}
						</div>
						<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
							{#if datasource}
								{#if isDerived}
									<FileTypeBadge sourceType="derived" size="sm" showIcon={true} />
								{:else if datasource.source_type === 'file'}
									<FileTypeBadge
										path={getDatasourceFilePath(datasource)}
										size="sm"
										showIcon={true}
									/>
								{:else if datasource.source_type === 'analysis'}
									{@const badgeSource = sourceType as SourceType}
									<FileTypeBadge sourceType={badgeSource} size="sm" showIcon={true} />
								{:else}
									<FileTypeBadge
										sourceType={datasource.source_type as 'database' | 'iceberg'}
										size="sm"
										showIcon={true}
									/>
								{/if}
							{:else}
								{@const badgeSource = sourceType as SourceType}
								<FileTypeBadge sourceType={badgeSource} size="sm" showIcon={true} />
							{/if}
						</div>
					</div>
					{#if isIceberg && datasource}
						<div
							class={css({
								borderTopWidth: '1',
								display: 'flex',
								alignItems: 'flex-start',
								gap: '2',
								paddingTop: '2'
							})}
						>
							<div class={css({ minWidth: '0', flex: '1' })}>
								<SnapshotPicker
									datasourceId={datasource.id}
									datasourceConfig={snapshotConfig}
									label="Time Travel"
									persistOpen
									disabled={readOnly}
									branch={snapshotBranch}
									showBuildPreviews={!isOutputSource}
									onConfigChange={updateSnapshotConfig}
									onUiChange={updateTimeTravelUi}
									onSelect={handleSnapshotSelect}
								/>
							</div>
							<div class={css({ minWidth: 'colMd', flexShrink: '0' })}>
								<BranchPicker
									branches={getDatasourceBranches(resolvedDatasource)}
									value={branchValue}
									placeholder="master"
									disabled={readOnly}
									onChange={applyBranchValue}
								/>
							</div>
						</div>
					{/if}
				</div>
			{:else}
				<div
					class={css({
						borderWidth: '1',
						borderStyle: 'dashed',
						padding: '3',
						textAlign: 'center'
					})}
				>
					<span class={css({ fontSize: 'xs', color: 'fg.muted' })}> No datasource connected </span>
				</div>
			{/if}
		</div>

		<!-- Engine Resources Section -->
		{#if analysisId}
			<div
				class={css({
					marginX: '4',
					marginBottom: '3',
					overflow: 'hidden',
					borderWidth: '1'
				})}
			>
				<button
					class={[
						'engine-header',
						css({
							display: 'flex',
							width: '100%',
							cursor: 'pointer',
							alignItems: 'center',
							justifyContent: 'space-between',
							border: 'none',
							backgroundColor: 'bg.secondary',
							paddingY: '2',
							paddingX: '3',
							_hover: { backgroundColor: 'bg.tertiary' }
						})
					]}
					onclick={() => (engineExpanded = !engineExpanded)}
					type="button"
				>
					<div
						class={css({
							display: 'flex',
							alignItems: 'center',
							gap: '2',
							fontSize: 'xs',
							textTransform: 'uppercase',
							letterSpacing: 'wide',
							color: 'fg.muted'
						})}
					>
						<Cpu size={12} />
						<span>Engine</span>
					</div>
					<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
						<span
							class={css({
								fontSize: '2xs',
								color: 'fg.secondary'
							})}
						>
							{effectiveThreads} threads, {effectiveMemoryGb}GB
						</span>
						<span
							class={css(
								{ color: 'fg.muted' },
								{ display: 'flex', alignItems: 'center' },
								engineExpanded && { transform: 'rotate(180deg)' }
							)}
						>
							<ChevronDown size={12} />
						</span>
					</div>
				</button>

				{#if engineExpanded}
					<div
						class={css({
							borderTopWidth: '1',
							display: 'flex',
							flexDirection: 'column',
							gap: '2',
							backgroundColor: 'bg.primary',
							padding: '3'
						})}
					>
						<div class={css({ display: 'flex', alignItems: 'center', gap: '3' })}>
							<label
								for="threads-input"
								class={css({
									display: 'block',
									fontWeight: 'medium',
									color: 'fg.secondary',
									marginBottom: '1.5',
									textTransform: 'none',
									letterSpacing: 'normal',
									minWidth: 'labelSm',
									fontSize: 'xs'
								})}
							>
								Threads
							</label>
							<input
								id="threads-input"
								class={css({
									width: 'full',
									color: 'fg.primary',
									borderWidth: '1',
									borderRadius: '0',
									transitionProperty: 'border-color',
									transitionDuration: '160ms',
									transitionTimingFunction: 'ease',
									_focus: { outline: 'none' },
									_focusVisible: { borderColor: 'border.accent' },
									_disabled: {
										opacity: '0.5',
										cursor: 'not-allowed'
									},
									_placeholder: { color: 'fg.muted' },
									flex: '1',
									backgroundColor: 'bg.secondary',
									paddingY: '1',
									paddingX: '2',
									fontSize: 'xs'
								})}
								type="number"
								min="1"
								max="64"
								value={effectiveThreads}
								onchange={(e) => setThreads(parseInt(e.currentTarget.value) || 0)}
								disabled={readOnly}
							/>
							{#if isUsingDefaultThreads}
								<span
									class={css({
										minWidth: 'labelXs',
										fontSize: '3xs',
										fontStyle: 'italic',
										color: 'fg.tertiary'
									})}
								>
									(default)
								</span>
							{/if}
						</div>
						<div class={css({ display: 'flex', alignItems: 'center', gap: '3' })}>
							<label
								for="memory-select"
								class={css({
									display: 'block',
									fontWeight: 'medium',
									color: 'fg.secondary',
									marginBottom: '1.5',
									textTransform: 'none',
									letterSpacing: 'normal',
									minWidth: 'labelSm',
									fontSize: 'xs'
								})}
							>
								Memory
							</label>
							<select
								id="memory-select"
								class={css({
									width: 'full',
									color: 'fg.primary',
									borderWidth: '1',
									borderRadius: '0',
									transitionProperty: 'border-color',
									transitionDuration: '160ms',
									transitionTimingFunction: 'ease',
									_focus: { outline: 'none' },
									_focusVisible: { borderColor: 'border.accent' },
									_disabled: {
										opacity: '0.5',
										cursor: 'not-allowed'
									},
									_placeholder: { color: 'fg.muted' },
									flex: '1',
									backgroundColor: 'bg.secondary',
									paddingY: '1',
									paddingX: '2',
									fontSize: 'xs'
								})}
								value={effectiveMemoryGb}
								onchange={(e) => setMemoryGb(parseInt(e.currentTarget.value) || 0)}
								disabled={readOnly}
							>
								{#each memoryOptions as gb (gb)}
									<option value={gb}>{gb} GB</option>
								{/each}
							</select>
							{#if isUsingDefaultMemory}
								<span
									class={css({
										minWidth: 'labelXs',
										fontSize: '3xs',
										fontStyle: 'italic',
										color: 'fg.tertiary'
									})}
								>
									(default)
								</span>
							{/if}
						</div>
					</div>
				{/if}
			</div>
		{/if}

		<!-- Action Button -->
		{#if onChangeDatasource}
			<button
				class={[
					'change-source-btn',
					css({
						marginX: '4',
						marginBottom: '4',
						display: 'flex',
						width: 'calc(100% - 2rem)',
						cursor: 'pointer',
						alignItems: 'center',
						justifyContent: 'center',
						gap: '2',
						borderWidth: '1',
						borderColor: 'border.primary',
						backgroundColor: 'bg.secondary',
						color: 'fg.muted',
						paddingY: '2',
						paddingX: '3',
						fontSize: 'xs2',
						fontWeight: 'medium',
						_hover: {
							backgroundColor: 'bg.tertiary',
							color: 'fg.primary',
							borderColor: 'border.primary',
							'& svg': { opacity: '1' }
						}
					})
				]}
				onclick={onChangeDatasource}
				type="button"
				disabled={readOnly}
			>
				<RefreshCw size={14} class={css({ opacity: '0.7' })} />
				<span>change source</span>
			</button>
		{/if}
	</div>
</div>
