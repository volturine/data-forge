<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import {
		getLineage,
		type LineageNode,
		type LineageResponse,
		type LineageMode,
		type NodeKind
	} from '$lib/api/lineage';
	import { listDatasources } from '$lib/api/datasource';
	import LineageGraph from '$lib/components/common/LineageGraph.svelte';
	import ScheduleManager from '$lib/components/common/ScheduleManager.svelte';
	import {
		Loader,
		X,
		Database,
		ChartColumn,
		ArrowRight,
		ArrowDown,
		LayoutGrid,
		RotateCcw,
		ZoomIn,
		ZoomOut,
		Layers,
		GitBranch
	} from 'lucide-svelte';
	import { css, button, toggleButton, chip } from '$lib/styles/panda';

	type LayoutMode = 'horizontal' | 'vertical' | 'grid';
	type LineageGraphApi = {
		resetLineageView: () => void;
		zoomInView: () => void;
		zoomOutView: () => void;
	};

	let selectedDatasourceId = $state<string>('');
	let selectedBranch = $state<string>('');
	let lineageMode = $state<LineageMode>('full');
	let internals = $state(false);

	const datasourcesQuery = createQuery(() => ({
		queryKey: ['datasources'],
		queryFn: async () => {
			const result = await listDatasources(true);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		}
	}));

	const outputDatasources = $derived(
		(datasourcesQuery.data ?? []).filter((ds) => ds.created_by === 'analysis')
	);

	const branchOptions = $derived.by(() => {
		const selected = outputDatasources.find((ds) => ds.id === selectedDatasourceId);
		const config = (selected?.config ?? {}) as Record<string, unknown>;
		const branches = config.branches as string[] | undefined;
		if (!branches || branches.length === 0) return ['master'];
		return branches;
	});

	const effectiveBranch = $derived(
		selectedDatasourceId ? selectedBranch || (branchOptions[0] ?? '') : ''
	);

	const query = createQuery(() => ({
		queryKey: ['lineage', selectedDatasourceId, effectiveBranch, lineageMode, internals],
		queryFn: async () => {
			const result = await getLineage({
				target: selectedDatasourceId || null,
				branch: effectiveBranch || null,
				mode: lineageMode,
				internals
			});
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		}
	}));

	const emptyLineage: LineageResponse = { nodes: [], edges: [] };
	const lineage = $derived(query.data ?? emptyLineage);

	let selectedNode = $state<LineageNode | null>(null);
	const panelWidth = 384;
	let layoutMode = $state<LayoutMode>('horizontal');
	let zoomPercent = $state(100);
	let graphRef = $state<LineageGraphApi | null>(null);

	function closePanel() {
		selectedNode = null;
	}

	const selectedRawId = $derived(
		selectedNode ? selectedNode.id.split(':').slice(1).join(':') : null
	);
	const selectedType = $derived(selectedNode?.type ?? null);

	function setLayout(mode: LayoutMode) {
		layoutMode = mode;
	}

	function zoomIn() {
		graphRef?.zoomInView();
	}

	function zoomOut() {
		graphRef?.zoomOutView();
	}

	function resetView() {
		graphRef?.resetLineageView();
	}

	function handleDatasourceChange(event: Event) {
		const target = event.currentTarget as HTMLSelectElement;
		selectedDatasourceId = target.value;
		selectedBranch = '';
	}

	function handleBranchChange(event: Event) {
		const target = event.currentTarget as HTMLSelectElement;
		selectedBranch = target.value;
	}

	const kindLabel: Record<NodeKind, string> = {
		source: 'Source',
		output: 'Output',
		internal: 'Internal',
		analysis: 'Analysis'
	};

	const modeOptions: Array<{ value: LineageMode; label: string }> = [
		{ value: 'full', label: 'Full' },
		{ value: 'upstream', label: 'Upstream' },
		{ value: 'downstream', label: 'Downstream' }
	];
</script>

<div class={css({ display: 'flex', height: '100%', flexDirection: 'column' })}>
	<header
		class={css({
			backgroundColor: 'bg.primary',
			paddingX: '6',
			paddingY: '3'
		})}
	>
		<h1 class={css({ margin: '0', fontSize: 'lg' })}>Data Lineage</h1>
	</header>

	<div
		class={css({
			display: 'grid',
			gridTemplateColumns: '384px minmax(0, 1fr)',
			gridTemplateRows: 'auto minmax(0, 1fr)',
			minHeight: '0',
			flex: '1',
			position: 'relative'
		})}
	>
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				gridColumn: '1 / -1',
				gridRow: '1',
				gap: '1',
				paddingX: '3',
				paddingY: '1.5',
				borderBottomWidth: '1',
				background: 'bg.primary',
				flexWrap: 'wrap'
			})}
		>
			<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
				<select
					class={css({
						width: 'full',
						color: 'fg.primary',
						backgroundColor: 'bg.primary',
						borderWidth: '1',
						borderRadius: '0',
						transitionProperty: 'border-color',
						transitionDuration: '160ms',
						transitionTimingFunction: 'ease',
						_focus: { outline: 'none' },
						_focusVisible: { borderColor: 'border.accent' },
						_disabled: { opacity: '0.5', cursor: 'not-allowed', backgroundColor: 'bg.tertiary' },
						_placeholder: { color: 'fg.muted' },
						fontSize: 'xs',
						paddingX: '2',
						paddingY: '1'
					})}
					id="lineage-ds"
					aria-label="Output datasource"
					value={selectedDatasourceId}
					onchange={handleDatasourceChange}
				>
					<option value="">Select output datasource</option>
					{#each outputDatasources as ds (ds.id)}
						<option value={ds.id}>{ds.name}</option>
					{/each}
				</select>
				<select
					class={css({
						width: 'full',
						color: 'fg.primary',
						backgroundColor: 'bg.primary',
						borderWidth: '1',
						borderRadius: '0',
						transitionProperty: 'border-color',
						transitionDuration: '160ms',
						transitionTimingFunction: 'ease',
						_focus: { outline: 'none' },
						_focusVisible: { borderColor: 'border.accent' },
						_disabled: { opacity: '0.5', cursor: 'not-allowed', backgroundColor: 'bg.tertiary' },
						_placeholder: { color: 'fg.muted' },
						fontSize: 'xs',
						paddingX: '2',
						paddingY: '1'
					})}
					id="lineage-branch"
					aria-label="Branch"
					value={effectiveBranch}
					onchange={handleBranchChange}
					disabled={!selectedDatasourceId}
				>
					{#if !selectedDatasourceId}
						<option value="">Select branch</option>
					{:else}
						{#each branchOptions as branch (branch)}
							<option value={branch}>{branch}</option>
						{/each}
					{/if}
				</select>
			</div>

			<div
				class={css({
					marginX: '2',
					height: 'iconSm',
					width: 'px',
					backgroundColor: 'bg.muted'
				})}
			></div>

			<div class={css({ display: 'flex', alignItems: 'center', gap: '0' })}>
				{#each modeOptions as opt, i (opt.value)}
					<button
						class={toggleButton({
							active: lineageMode === opt.value,
							radius: i === 0 ? 'left' : i === modeOptions.length - 1 ? 'right' : undefined
						})}
						onclick={() => {
							lineageMode = opt.value;
						}}
						title={`${opt.label} lineage`}
					>
						<span class={css({ fontSize: 'xs' })}>{opt.label}</span>
					</button>
				{/each}
			</div>

			<button
				class={button({ variant: internals ? 'primary' : 'ghost', size: 'sm' })}
				onclick={() => {
					internals = !internals;
				}}
				title="Toggle internal nodes"
				aria-pressed={internals}
			>
				<Layers size={14} />
				<span class={css({ fontSize: 'xs' })}>Internals</span>
			</button>

			<div
				class={css({
					marginX: '2',
					height: 'iconSm',
					width: 'px',
					backgroundColor: 'bg.muted'
				})}
			></div>

			<span class={css({ marginRight: '2', fontSize: 'xs', color: 'fg.muted' })}>Layout</span>
			<button
				class={layoutMode === 'horizontal'
					? button({ variant: 'primary', size: 'sm' })
					: button({ variant: 'ghost', size: 'sm' })}
				onclick={() => setLayout('horizontal')}
				title="Horizontal tree layout"
			>
				<ArrowRight size={14} />
				<span class={css({ fontSize: 'xs' })}>Horizontal</span>
			</button>
			<button
				class={layoutMode === 'vertical'
					? button({ variant: 'primary', size: 'sm' })
					: button({ variant: 'ghost', size: 'sm' })}
				onclick={() => setLayout('vertical')}
				title="Vertical tree layout"
			>
				<ArrowDown size={14} />
				<span class={css({ fontSize: 'xs' })}>Vertical</span>
			</button>
			<button
				class={layoutMode === 'grid'
					? button({ variant: 'primary', size: 'sm' })
					: button({ variant: 'ghost', size: 'sm' })}
				onclick={() => setLayout('grid')}
				title="Grid layout"
			>
				<LayoutGrid size={14} />
				<span class={css({ fontSize: 'xs' })}>Grid</span>
			</button>

			<div
				class={css({
					marginX: '2',
					height: 'iconSm',
					width: 'px',
					backgroundColor: 'bg.muted'
				})}
			></div>

			<button class={button({ variant: 'ghost', size: 'sm' })} onclick={zoomIn} title="Zoom in">
				<ZoomIn size={14} />
			</button>
			<button class={button({ variant: 'ghost', size: 'sm' })} onclick={zoomOut} title="Zoom out">
				<ZoomOut size={14} />
			</button>
			<button
				class={button({ variant: 'ghost', size: 'sm' })}
				onclick={resetView}
				title="Reset view"
			>
				<RotateCcw size={14} />
			</button>

			<span class={css({ marginLeft: 'auto', fontSize: 'xs', color: 'fg.muted' })}>
				{zoomPercent}%
			</span>
		</div>

		<aside
			class={css({
				gridColumn: '1',
				gridRow: '2',
				minHeight: '0',
				borderRightWidth: '1',
				background: 'bg.primary',
				boxShadow: 'popover',
				display: 'flex',
				flexDirection: 'column',
				zIndex: '10'
			})}
		>
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					gap: '3',
					borderBottomWidth: '1',
					paddingX: '4',
					paddingY: '3'
				})}
			>
				{#if selectedNode}
					<div class={css({ display: 'flex', alignItems: 'center', gap: '2', color: 'fg.muted' })}>
						{#if selectedType === 'datasource'}
							<Database size={16} />
						{:else}
							<ChartColumn size={16} />
						{/if}
					</div>
				{/if}
				<div class={css({ minWidth: '0', flex: '1' })}>
					<div
						class={css({
							fontSize: 'xs',
							textTransform: 'uppercase',
							letterSpacing: 'wide',
							color: 'fg.muted'
						})}
					>
						{selectedNode ? kindLabel[selectedNode.node_kind] : 'Details'}
					</div>
					<div
						class={css({
							textOverflow: 'ellipsis',
							overflow: 'hidden',
							whiteSpace: 'nowrap',
							fontSize: 'sm',
							fontWeight: 'semibold'
						})}
					>
						{selectedNode ? selectedNode.name : 'Select a node'}
					</div>
				</div>
				{#if selectedNode}
					<button
						class={css({
							borderWidth: '1',
							backgroundColor: 'transparent',
							color: 'fg.secondary',
							borderColor: 'transparent',
							fontSize: 'xs',
							padding: '1',
							'&:hover:not(:disabled)': { backgroundColor: 'bg.hover', color: 'fg.primary' }
						})}
						onclick={closePanel}
						title="Close panel"
						aria-label="Close panel"
					>
						<X size={14} />
					</button>
				{/if}
			</div>

			<div class={css({ flex: '1', overflowY: 'auto', padding: '4' })}>
				{#if selectedNode}
					<div
						class={css({ marginBottom: '4', display: 'flex', flexDirection: 'column', gap: '2' })}
					>
						<div
							class={css({
								display: 'flex',
								alignItems: 'center',
								justifyContent: 'space-between',
								fontSize: 'sm'
							})}
						>
							<span class={css({ color: 'fg.muted' })}>Kind</span>
							<span
								class={chip({ tone: selectedNode.node_kind === 'internal' ? 'neutral' : 'accent' })}
							>
								{kindLabel[selectedNode.node_kind]}
							</span>
						</div>
						{#if selectedNode.source_type}
							<div
								class={css({
									display: 'flex',
									alignItems: 'center',
									justifyContent: 'space-between',
									fontSize: 'sm'
								})}
							>
								<span class={css({ color: 'fg.muted' })}>Source</span>
								<span>{selectedNode.source_type}</span>
							</div>
						{/if}
						{#if selectedNode.status}
							<div
								class={css({
									display: 'flex',
									alignItems: 'center',
									justifyContent: 'space-between',
									fontSize: 'sm'
								})}
							>
								<span class={css({ color: 'fg.muted' })}>Status</span>
								<span>{selectedNode.status}</span>
							</div>
						{/if}
						{#if selectedNode.branch}
							<div
								class={css({
									display: 'flex',
									alignItems: 'center',
									justifyContent: 'space-between',
									fontSize: 'sm'
								})}
							>
								<span class={css({ color: 'fg.muted' })}>Branch</span>
								<div class={css({ display: 'flex', alignItems: 'center', gap: '1' })}>
									<GitBranch size={12} />
									<span>{selectedNode.branch}</span>
								</div>
							</div>
						{/if}
						<div
							class={css({
								display: 'flex',
								alignItems: 'center',
								justifyContent: 'space-between',
								fontSize: 'sm'
							})}
						>
							<span class={css({ color: 'fg.muted' })}>ID</span>
							<span
								class={css({
									textOverflow: 'ellipsis',
									overflow: 'hidden',
									whiteSpace: 'nowrap',
									paddingLeft: '4',
									fontSize: 'xs',
									color: 'fg.tertiary'
								})}
							>
								{selectedRawId}
							</span>
						</div>
					</div>

					{#if selectedType === 'datasource' && selectedRawId}
						<div class={css({ borderTopWidth: '1', paddingTop: '4' })}>
							<h3
								class={css({
									marginBottom: '3',
									fontSize: 'sm',
									fontWeight: 'semibold'
								})}
							>
								Schedules
							</h3>
							<ScheduleManager datasourceId={selectedRawId} compact />
						</div>
					{/if}
				{:else}
					<p class={css({ fontSize: 'sm', color: 'fg.tertiary' })}>
						Click a node to view details and schedules.
					</p>
				{/if}
			</div>
		</aside>

		<div
			class={css({
				gridColumn: '2',
				gridRow: '2',
				minHeight: '0',
				minWidth: '0',
				overflow: 'hidden',
				position: 'relative'
			})}
		>
			{#if query.isLoading}
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						height: '100%',
						justifyContent: 'center',
						gap: '2',
						color: 'fg.tertiary'
					})}
				>
					<Loader size={16} class={css({ animation: 'spin 1s linear infinite' })} />
					Loading lineage...
				</div>
			{:else if query.isError}
				<div
					data-testid="lineage-load-error"
					class={css({
						display: 'flex',
						alignItems: 'center',
						height: '100%',
						justifyContent: 'center'
					})}
				>
					<p class={css({ fontSize: 'sm', color: 'fg.error' })}>Failed to load lineage.</p>
				</div>
			{:else}
				<LineageGraph
					bind:this={graphRef}
					{lineage}
					showToolbar={false}
					bind:layoutMode
					bind:zoomPercent
					onnodeclick={(node) => {
						selectedNode = node;
					}}
					panelOffset={panelWidth}
				/>

				<!-- Legend -->
				<div
					class={css({
						position: 'absolute',
						bottom: '3',
						right: '3',
						display: 'flex',
						gap: '3',
						paddingX: '3',
						paddingY: '2',
						background: 'bg.primary',
						borderWidth: '1',
						fontSize: 'xs',
						color: 'fg.muted',
						zIndex: '5'
					})}
				>
					<div class={css({ display: 'flex', alignItems: 'center', gap: '1.5' })}>
						<div
							class={css({
								width: '3',
								height: '3',
								borderLeftWidth: '3',
								borderLeftColor: 'accent.primary'
							})}
						></div>
						<span>Source</span>
					</div>
					<div class={css({ display: 'flex', alignItems: 'center', gap: '1.5' })}>
						<div
							class={css({
								width: '3',
								height: '3',
								borderLeftWidth: '3',
								borderLeftColor: 'fg.success'
							})}
						></div>
						<span>Output</span>
					</div>
					<div class={css({ display: 'flex', alignItems: 'center', gap: '1.5' })}>
						<div
							class={css({
								width: '3',
								height: '3',
								borderLeftWidth: '3',
								borderLeftColor: 'fg.warning'
							})}
						></div>
						<span>Analysis</span>
					</div>
					{#if internals}
						<div class={css({ display: 'flex', alignItems: 'center', gap: '1.5' })}>
							<div
								class={css({
									width: '3',
									height: '3',
									borderWidth: '1',
									borderStyle: 'dashed',
									borderColor: 'fg.faint'
								})}
							></div>
							<span>Internal</span>
						</div>
					{/if}
				</div>
			{/if}
		</div>
	</div>
</div>
