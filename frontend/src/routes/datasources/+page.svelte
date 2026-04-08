<script lang="ts">
	import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { resolve } from '$app/paths';
	import { listDatasources, deleteDatasource, getDatasource } from '$lib/api/datasource';
	import {
		Plus,
		Trash2,
		Search,
		LoaderCircle,
		Eye,
		EyeOff,
		Upload,
		GitBranch
	} from 'lucide-svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import BranchPicker from '$lib/components/common/BranchPicker.svelte';
	import DatasourcePreview from '$lib/components/datasources/DatasourcePreview.svelte';
	import DatasourceConfigPanel from '$lib/components/datasources/DatasourceConfigPanel.svelte';
	import SnapshotPicker from '$lib/components/datasources/SnapshotPicker.svelte';
	import BuildComparisonPanel from '$lib/components/datasources/BuildComparisonPanel.svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { css, cx, spinner, button, chip, input } from '$lib/styles/panda';

	const queryClient = useQueryClient();

	let showHidden = $state(false);

	let selectedId = $state<string | null>(page.url.searchParams.get('id'));
	let showConfig = $state<string | null>(page.url.searchParams.get('id'));
	let deletingId = $state<string | null>(null);
	let mutatingId = $state<string | null>(null);
	let searchQuery = $state('');
	let showComparison = $state(false);

	const query = createQuery(() => ({
		queryKey: ['datasources', showHidden],
		queryFn: async () => {
			const result = await listDatasources(showHidden);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		}
	}));

	let snapshotConfig = $state<Record<string, unknown> | null>(null);
	let selectedBranch = $state<string | null>(null);

	const selectedDatasourceQuery = createQuery(() => ({
		queryKey: ['datasource', selectedId, selectedBranch ?? ''],
		queryFn: async () => {
			if (!selectedId) return null;
			const result = await getDatasource(selectedId);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		enabled: !!selectedId
	}));

	const deleteMutation = createMutation(() => ({
		mutationFn: async (id: string) => {
			const result = await deleteDatasource(id);
			if (result.isErr()) throw new Error(result.error.message);
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['datasources'] });
			if (selectedId === mutatingId) {
				selectDatasource(null);
			}
			mutatingId = null;
		}
	}));

	const datasources = $derived(query.data ?? []);
	const filteredDatasources = $derived(
		searchQuery
			? datasources.filter((d) => d.name.toLowerCase().includes(searchQuery.toLowerCase()))
			: datasources
	);
	const selectedDatasource = $derived(
		selectedDatasourceQuery.data ?? datasources.find((d) => d.id === selectedId) ?? null
	);

	function selectDatasource(id: string | null) {
		selectedId = id;
		showConfig = id;
		selectedBranch = id ? 'master' : null;
		showComparison = false;
		if (id) {
			const ds = datasources.find((d) => d.id === id);
			const config = (ds?.config ?? {}) as Record<string, unknown>;
			snapshotConfig = { ...config, branch: 'master' };
		} else {
			snapshotConfig = null;
		}
		const url = id ? `/datasources?id=${id}` : '/datasources';
		goto(resolve(url as '/'), { replaceState: true });
	}

	// $derived cannot write to $state — must imperatively merge server config while preserving active time-travel selection
	$effect(() => {
		const selected = selectedDatasource;
		if (!selectedId) return;
		if (!selected) return;
		if (snapshotConfig?.branch) return;
		const nextConfig = (selected.config ?? {}) as Record<string, unknown>;
		const nextBranch = selectedBranch ?? 'master';
		const travelId = snapshotConfig?.time_travel_snapshot_id as string | undefined;
		const travelTs = snapshotConfig?.time_travel_snapshot_timestamp_ms as number | undefined;
		const travelUi = snapshotConfig?.time_travel_ui as Record<string, unknown> | undefined;
		const merged = { ...nextConfig, branch: nextBranch } as Record<string, unknown>;
		if (travelId) merged.time_travel_snapshot_id = travelId;
		if (travelTs) merged.time_travel_snapshot_timestamp_ms = travelTs;
		if (travelUi) merged.time_travel_ui = travelUi;
		snapshotConfig = merged;
		selectedBranch = nextBranch;
	});

	function handleDelete(id: string) {
		deletingId = id;
	}

	function confirmDelete() {
		if (!deletingId) return;
		mutatingId = deletingId;
		deleteMutation.mutate(deletingId);
		deletingId = null;
	}

	function cancelDelete() {
		deletingId = null;
	}

	const deleteConfirmName = $derived.by(() => {
		if (!deletingId || !query.data) return '';
		const ds = query.data.find((d) => d.id === deletingId);
		return ds?.name ?? '';
	});

	function handleConfigSaved() {
		queryClient.invalidateQueries({ queryKey: ['datasources'] });
	}

	function handleSnapshotConfigChange(config: Record<string, unknown>) {
		snapshotConfig = config;
	}

	const branchOptions = $derived.by(() => {
		const config = (selectedDatasource?.config ?? {}) as Record<string, unknown>;
		const branches = (config.branches as string[] | undefined) ?? [];
		const cleaned = branches.map((branch) => branch.trim()).filter((branch) => branch.length > 0);
		const next = cleaned.includes('master') ? cleaned : ['master', ...cleaned];
		const active = activeBranch.trim();
		if (!active) return next;
		if (next.includes(active)) return next;
		return [active, ...next];
	});
	const activeBranch = $derived.by(() => {
		if (snapshotConfig && snapshotConfig.branch) return String(snapshotConfig.branch);
		return 'master';
	});
</script>

<div
	class={css({
		display: 'flex',
		height: '100%'
	})}
>
	<!-- Left Pane -->
	<aside
		class={css({
			width: 'datasourcePanel',
			borderRightWidth: '1',
			display: 'flex',
			flexDirection: 'column',
			backgroundColor: 'bg.primary',
			flexShrink: '0'
		})}
	>
		<!-- Header -->
		<header
			class={css({
				display: 'flex',
				flexDirection: 'column',
				gap: '2',
				paddingX: '4',
				paddingY: '3',
				height: 'fieldSm',
				boxSizing: 'border-box'
			})}
		>
			<div class={css({ display: 'flex', alignItems: 'center', justifyContent: 'space-between' })}>
				<h1 class={css({ fontSize: 'sm', fontWeight: 'semibold' })}>Data Sources</h1>
				<div class={css({ display: 'flex', alignItems: 'center', gap: '1' })}>
					<button
						class={css({
							display: 'inline-flex',
							alignItems: 'center',
							gap: '1',
							fontSize: 'xs',
							fontWeight: 'medium',
							paddingX: '2',
							paddingY: '1',
							backgroundColor: 'transparent',
							borderWidth: '1',
							color: showHidden ? 'accent.primary' : undefined
						})}
						title={showHidden
							? 'Hide auto-generated datasources'
							: 'Show auto-generated datasources'}
						onclick={() => (showHidden = !showHidden)}
					>
						{#if showHidden}
							<Eye size={14} />
						{:else}
							<EyeOff size={14} />
						{/if}
					</button>
					<a
						href={resolve('/datasources/new')}
						class={css({
							display: 'inline-flex',
							alignItems: 'center',
							gap: '1',
							fontSize: 'xs',
							fontWeight: 'medium',
							paddingX: '2',
							paddingY: '1',
							textDecoration: 'none',
							backgroundColor: 'accent.primary',
							color: 'fg.inverse',
							borderWidth: '1',
							borderColor: 'border.accent'
						})}
						data-sveltekit-reload
					>
						<Plus size={14} />
						Add
					</a>
				</div>
			</div>
			<div class={css({ position: 'relative' })}>
				<Search
					size={14}
					class={css({
						position: 'absolute',
						left: '2.5',
						top: '50%',
						transform: 'translateY(-50%)',
						color: 'fg.muted'
					})}
				/>
				<input
					type="text"
					id="ds-search"
					aria-label="Search datasources"
					placeholder="Search datasources..."
					class={cx(input({ variant: 'search' }), css({ paddingY: '1' }))}
					bind:value={searchQuery}
				/>
			</div>
		</header>

		<!-- Datasource List -->
		<div class={css({ flex: '1', overflowY: 'auto' })}>
			{#if query.isLoading}
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						height: '100%',
						justifyContent: 'center'
					})}
				>
					<div class={spinner()}></div>
				</div>
			{:else if query.isError}
				<Callout tone="error">
					Error: {query.error instanceof Error ? query.error.message : 'Unknown error'}
				</Callout>
			{:else if datasources.length === 0}
				<div class={css({ padding: '8', textAlign: 'center' })}>
					<p class={css({ fontSize: 'sm', color: 'fg.muted', marginBottom: '4' })}>
						No data sources yet.
					</p>
					<a
						href={resolve('/datasources/new')}
						class={css({
							display: 'inline-flex',
							alignItems: 'center',
							gap: '1',
							fontSize: 'sm',
							fontWeight: 'medium',
							paddingX: '3',
							paddingY: '2',
							textDecoration: 'none',
							backgroundColor: 'accent.primary',
							color: 'fg.inverse',
							borderWidth: '1'
						})}
						data-sveltekit-reload
					>
						Create your first data source
					</a>
				</div>
			{:else if filteredDatasources.length === 0}
				<div class={css({ padding: '8', textAlign: 'center', fontSize: 'sm', color: 'fg.muted' })}>
					No datasources match "{searchQuery}"
				</div>
			{:else}
				{#each filteredDatasources as datasource (datasource.id)}
					<div
						data-ds-row={datasource.name}
						class={css({
							borderBottomWidth: '1',
							...(selectedId === datasource.id
								? {
										backgroundColor: 'bg.accent',
										borderLeftWidth: '2'
									}
								: {})
						})}
					>
						<!-- Row -->
						<div
							class={css({
								display: 'flex',
								alignItems: 'center',
								justifyContent: 'space-between',
								paddingX: '3',
								paddingY: '2.5'
							})}
						>
							<button
								class={css({
									display: 'flex',
									alignItems: 'center',
									gap: '2',
									minWidth: '0',
									flex: '1',
									textAlign: 'left',
									backgroundColor: 'transparent',
									padding: '0',
									borderColor: 'transparent'
								})}
								onclick={() => selectDatasource(datasource.id)}
							>
								<span
									class={css({
										fontWeight: 'medium',
										textOverflow: 'ellipsis',
										overflow: 'hidden',
										whiteSpace: 'nowrap',
										fontSize: 'sm',
										color: selectedId === datasource.id ? 'accent.primary' : undefined
									})}
								>
									{datasource.name}
								</span>
								{#if datasource.created_by === 'analysis'}
									<span
										class={cx(chip({ tone: 'accent' }), css({ gap: '0.5', flexShrink: '0' }))}
										title="Created by analysis"
									>
										<GitBranch size={10} />
										Analysis
									</span>
								{:else}
									<span
										class={cx(chip({ tone: 'neutral' }), css({ gap: '0.5', flexShrink: '0' }))}
										title="Imported datasource"
									>
										<Upload size={10} />
										Import
									</span>
								{/if}
							</button>
							<div class={css({ display: 'flex', alignItems: 'center', flexShrink: '0' })}>
								<button
									class={css({
										padding: '1.5',
										backgroundColor: 'transparent',
										borderColor: 'transparent',
										transitionProperty: 'color, background-color',
										transitionTimingFunction: 'cubic-bezier(0.4, 0, 0.2, 1)',
										transitionDuration: '150ms',
										color: 'fg.muted',
										_hover: { color: 'fg.error', backgroundColor: 'bg.hover' }
									})}
									title="Delete"
									onclick={() => handleDelete(datasource.id)}
									disabled={deleteMutation.isPending && mutatingId === datasource.id}
								>
									{#if deleteMutation.isPending && mutatingId === datasource.id}
										<LoaderCircle size={14} class={css({ animation: 'spin 1s linear infinite' })} />
									{:else}
										<Trash2 size={14} />
									{/if}
								</button>
							</div>
						</div>

						<!-- Inline Config Panel -->
						{#if showConfig === datasource.id}
							<DatasourceConfigPanel {datasource} onSave={handleConfigSaved} />
						{/if}
					</div>
				{/each}
			{/if}
		</div>
	</aside>

	<!-- Right Pane -->
	<main class={css({ flex: '1', overflow: 'hidden' })}>
		{#if selectedDatasource}
			<div class={css({ height: '100%', display: 'flex', flexDirection: 'column' })}>
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						borderBottomWidth: '1',
						backgroundColor: 'bg.secondary',
						padding: '3',
						justifyContent: 'space-between',
						gap: '3'
					})}
				>
					<div class={css({ flex: '1', minWidth: '0' })}>
						{#if selectedDatasource.source_type === 'iceberg'}
							<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
								<div class={css({ flex: '1', minWidth: '0' })}>
									<SnapshotPicker
										datasourceId={selectedDatasource.id}
										datasourceConfig={snapshotConfig ?? selectedDatasource.config}
										label="Time Travel"
										branch={selectedBranch}
										showDelete
										showBuildPreviews={selectedDatasource.created_by === 'analysis'}
										onConfigChange={handleSnapshotConfigChange}
									/>
								</div>
								<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
									<GitBranch size={14} class={css({ color: 'fg.tertiary' })} />
									<BranchPicker
										branches={branchOptions}
										value={activeBranch}
										placeholder="Select branch"
										onChange={(value: string) => {
											selectedBranch = value;
											snapshotConfig = {
												...(snapshotConfig ?? selectedDatasource?.config ?? {}),
												branch: value
											} as Record<string, unknown>;
										}}
									/>
								</div>
								<button
									class={cx(
										button({ variant: 'ghost', size: 'sm' }),
										css({
											borderWidth: '1',
											fontSize: 'xs'
										})
									)}
									onclick={() => (showComparison = !showComparison)}
									aria-pressed={showComparison}
								>
									{#if showComparison}
										Hide comparison
									{:else}
										Compare builds
									{/if}
								</button>
							</div>
						{:else}
							<div class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>
								Time travel is available for Iceberg datasources.
							</div>
						{/if}
					</div>
				</div>
				<div class={css({ flex: '1', minHeight: '0', overflow: 'auto' })}>
					{#if showComparison}
						<BuildComparisonPanel datasource={selectedDatasource} />
					{:else}
						<DatasourcePreview
							datasourceId={selectedDatasource.id}
							datasource={selectedDatasource}
							datasourceConfig={snapshotConfig ?? selectedDatasource.config}
						/>
					{/if}
				</div>
			</div>
		{:else}
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					height: '100%',
					justifyContent: 'center',
					color: 'fg.muted',
					backgroundColor: 'bg.secondary'
				})}
			>
				<div class={css({ textAlign: 'center' })}>
					<p class={css({ fontSize: 'lg', fontWeight: 'medium', marginBottom: '2' })}>
						No datasource selected
					</p>
					<p class={css({ fontSize: 'sm' })}>Select a datasource from the list to preview</p>
				</div>
			</div>
		{/if}
	</main>
</div>

<ConfirmDialog
	show={deletingId !== null}
	heading="Delete Datasource"
	message={deleteConfirmName
		? `Are you sure you want to delete "${deleteConfirmName}"? This action cannot be undone.`
		: 'Are you sure you want to delete this datasource? This action cannot be undone.'}
	confirmText="Delete"
	cancelText="Cancel"
	onConfirm={confirmDelete}
	onCancel={cancelDelete}
/>
