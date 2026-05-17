<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { compareDatasourceSnapshots, listIcebergSnapshots } from '$lib/api/datasource';
	import type { SnapshotCompareResponse } from '$lib/api/datasource';
	import type { DataSource } from '$lib/types/datasource';
	import type { ActiveBuildSummary } from '$lib/types/build-stream';
	import DataTable from '$lib/components/common/DataTable.svelte';
	import { GitCompareArrows, RefreshCw, X, Plus, Minus, Search } from 'lucide-svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { buildSnapshotMap } from '$lib/utils/build-snapshot-map';
	import { BuildsStore } from '$lib/stores/builds.svelte';
	import { css, button } from '$lib/styles/panda';

	interface Props {
		datasource: DataSource;
	}

	let { datasource }: Props = $props();

	const selected = new SvelteSet<string>();
	let comparison = $state<SnapshotCompareResponse | null>(null);
	let comparing = $state(false);
	let compareError = $state<string | null>(null);
	let runSearch = $state('');
	let rowLimit = $state(100);

	const engineRunsStore = new BuildsStore();
	// Network: fetch datasource build history when the datasource changes.
	$effect(() => {
		engineRunsStore.load({ datasource_id: datasource.id, limit: 50 });
		return () => engineRunsStore.close();
	});

	const snapshotsQuery = createQuery(() => ({
		queryKey: ['iceberg-snapshots', datasource.id],
		queryFn: async () => {
			const result = await listIcebergSnapshots(datasource.id);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value.snapshots;
		},
		enabled: datasource.source_type === 'iceberg'
	}));

	const runs = $derived(
		engineRunsStore.builds.filter(
			(run) => run.current_kind === 'build' && run.status === 'completed'
		)
	);

	const visibleRuns = $derived.by(() => {
		const q = runSearch.trim().toLowerCase();
		if (!q) return runs;
		return runs.filter((run) => {
			const created = formatDate(run.started_at).toLowerCase();
			return (
				run.build_id.toLowerCase().includes(q) ||
				(run.current_kind ?? '').toLowerCase().includes(q) ||
				created.includes(q)
			);
		});
	});

	const selectedRuns = $derived.by(() => {
		const list = Array.from(selected).map((id) => runs.find((run) => run.build_id === id) ?? null);
		return list.filter((run): run is ActiveBuildSummary => run !== null);
	});

	const runA = $derived(selectedRuns[0] ?? null);
	const runB = $derived(selectedRuns[1] ?? null);
	const canCompare = $derived(selected.size === 2);

	const snapshots = $derived(snapshotsQuery.data ?? []);

	const runSnapshotMap = $derived(buildSnapshotMap(runs, snapshots));
	const snapshotA = $derived(runA ? (runSnapshotMap.get(runA.build_id) ?? null) : null);
	const snapshotB = $derived(runB ? (runSnapshotMap.get(runB.build_id) ?? null) : null);

	function toggleSelect(id: string) {
		if (selected.has(id)) {
			selected.delete(id);
			resetComparison();
			return;
		}
		if (selected.size >= 2) return;
		selected.add(id);
		resetComparison();
	}

	async function runComparison() {
		const snapA = snapshotA;
		const snapB = snapshotB;
		if (!snapA || !snapB) return;
		comparing = true;
		compareError = null;
		const result = await compareDatasourceSnapshots(datasource.id, snapA, snapB, rowLimit);
		if (result.isOk()) {
			comparison = result.value;
			comparing = false;
			return;
		}
		compareError = result.error.message;
		comparing = false;
	}

	function closeComparison() {
		selected.clear();
		resetComparison();
	}

	function resetComparison() {
		comparison = null;
		compareError = null;
	}

	function formatDate(isoDate: string): string {
		const date = new Date(isoDate);
		return date.toLocaleString();
	}

	function formatDelta(val: number): string {
		if (val === 0) return '0';
		const sign = val > 0 ? '+' : '';
		return `${sign}${val}`;
	}

	function rowDeltaClass(val: number): string {
		if (val === 0) return css({ color: 'fg.muted' });
		return val > 0 ? css({ color: 'fg.success' }) : css({ color: 'fg.error' });
	}

	function nullDeltaClass(val: number): string {
		if (val === 0) return css({ color: 'fg.muted' });
		return val > 0 ? css({ color: 'fg.error' }) : css({ color: 'fg.success' });
	}

	function uniqueDeltaClass(val: number): string {
		if (val === 0) return css({ color: 'fg.muted' });
		return val > 0 ? css({ color: 'fg.success' }) : css({ color: 'fg.error' });
	}

	function previewColumns(preview: SnapshotCompareResponse['preview_a'] | null) {
		return preview?.columns ?? [];
	}

	function previewData(preview: SnapshotCompareResponse['preview_a'] | null) {
		return preview?.data ?? [];
	}

	function previewTypes(preview: SnapshotCompareResponse['preview_a'] | null) {
		return preview?.column_types ?? {};
	}

	const combinedStats = $derived.by(() => {
		if (!comparison) return [];
		const statsA = new Map(comparison.stats_a.map((s) => [s.column, s]));
		const statsB = new Map(comparison.stats_b.map((s) => [s.column, s]));
		const allCols = new Set([...statsA.keys(), ...statsB.keys()]);
		return Array.from(allCols)
			.sort()
			.map((col) => {
				const a = statsA.get(col);
				const b = statsB.get(col);
				const nullA = a?.null_count;
				const nullB = b?.null_count;
				const uniqueA = a?.unique_count;
				const uniqueB = b?.unique_count;

				let nullDelta: number | null = null;
				if (typeof nullA === 'number' && typeof nullB === 'number') {
					nullDelta = nullB - nullA;
				}

				let uniqueDelta: number | null = null;
				if (typeof uniqueA === 'number' && typeof uniqueB === 'number') {
					uniqueDelta = uniqueB - uniqueA;
				}

				return {
					column: col,
					// Show A -> B if types differ, otherwise just Type
					type:
						a?.dtype === b?.dtype ? (a?.dtype ?? '-') : `${a?.dtype ?? '-'} → ${b?.dtype ?? '-'}`,
					null_a: nullA ?? '-',
					null_b: nullB ?? '-',
					null_delta: nullDelta,
					unique_a: uniqueA ?? '-',
					unique_b: uniqueB ?? '-',
					unique_delta: uniqueDelta,
					min_a: a?.min ?? '-',
					min_b: b?.min ?? '-',
					max_a: a?.max ?? '-',
					max_b: b?.max ?? '-'
				};
			});
	});
</script>

<div
	class={css({
		borderWidth: '1',
		backgroundColor: 'bg.primary',
		display: 'flex',
		flexDirection: 'column',
		minHeight: '0'
	})}
>
	<div
		class={css({
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'space-between',
			borderBottomWidth: '1',
			backgroundColor: 'bg.tertiary',
			paddingX: '4',
			paddingY: '3'
		})}
	>
		<h3
			class={css({
				margin: '0',
				display: 'flex',
				alignItems: 'center',
				gap: '2',
				fontSize: 'sm',
				fontWeight: 'medium'
			})}
		>
			<GitCompareArrows size={16} class={css({ color: 'accent.primary' })} />
			Build Comparison
		</h3>
		{#if comparison}
			<button class={button({ variant: 'ghost', size: 'sm' })} onclick={closeComparison}>
				<X size={14} />
			</button>
		{/if}
	</div>

	{#if datasource.source_type !== 'iceberg'}
		<div class={css({ padding: '4', fontSize: 'sm', color: 'fg.tertiary' })}>
			Snapshot comparison is only available for Iceberg datasources.
		</div>
	{:else}
		<div
			class={[
				css({
					flex: '1',
					minHeight: '0',
					padding: '4',
					overflow: 'auto',
					display: 'flex',
					flexDirection: 'column',
					gap: '4',
					contain: 'content'
				}),
				'datasource-comparison-scroll'
			]}
		>
			<div
				class={css({
					display: 'grid',
					gap: '3',
					md: { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }
				})}
			>
				<div
					class={css({
						borderWidth: '1',
						padding: '3'
					})}
				>
					<div
						class={css({
							marginBottom: '2',
							fontSize: 'xs',
							fontWeight: 'medium',
							color: 'fg.muted'
						})}
					>
						Select builds
					</div>
					{#if engineRunsStore.status === 'connecting'}
						<div class={css({ fontSize: 'sm', color: 'fg.tertiary' })}>Loading runs...</div>
					{:else if engineRunsStore.status === 'error'}
						<div class={css({ fontSize: 'sm', color: 'fg.error' })}>
							{engineRunsStore.error ?? 'Failed to load runs'}
						</div>
					{:else if runs.length === 0}
						<p class={css({ fontSize: 'sm', color: 'fg.tertiary' })}>
							No successful datasource builds recorded.
						</p>
					{:else}
						<div class={css({ display: 'flex', flexDirection: 'column', gap: '3' })}>
							<div class={css({ position: 'relative' })}>
								<Search
									size={12}
									class={css({
										position: 'absolute',
										left: '2.5',
										top: '50%',
										translate: '0 -50%',
										color: 'fg.muted'
									})}
								/>
								<input
									type="text"
									id="bcp-search"
									aria-label="Search builds"
									placeholder="Search builds by ID or date..."
									class={css({
										width: 'full',
										fontSize: 'xs',
										color: 'fg.primary',
										borderWidth: '1',
										borderRadius: '0',
										paddingLeft: '8',
										paddingRight: '2',
										paddingY: '1.5',
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
										_placeholder: { color: 'fg.muted' }
									})}
									bind:value={runSearch}
								/>
							</div>
							{#if visibleRuns.length === 0}
								<p class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>
									No builds match your search.
								</p>
							{:else}
								<div
									class={[
										css({
											maxHeight: 'previewXl',
											display: 'flex',
											flexDirection: 'column',
											gap: '2',
											overflowY: 'auto',
											contain: 'content'
										}),
										'datasource-comparison-scroll'
									]}
								>
									{#each visibleRuns as run (run.build_id)}
										<button
											class={css(
												{
													display: 'flex',
													width: '100%',
													alignItems: 'flex-start',
													justifyContent: 'space-between',
													borderWidth: '1',
													backgroundColor: 'transparent',
													paddingX: '3',
													paddingY: '2',
													textAlign: 'left',
													fontSize: 'sm',
													_hover: { backgroundColor: 'bg.hover' }
												},
												selected.has(run.build_id) && {
													backgroundColor: 'bg.accent',
													color: 'accent.primary'
												}
											)}
											onclick={() => toggleSelect(run.build_id)}
										>
											<div class={css({ minWidth: '0' })}>
												<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
													<span class={css({ fontFamily: 'mono', fontSize: 'xs' })}
														>{run.build_id.slice(0, 8)}...</span
													>
													<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}
														>{run.current_kind ?? ''}</span
													>
												</div>
												<div class={css({ fontSize: 'xs', color: 'fg.muted' })}>
													{formatDate(run.started_at)}
												</div>
											</div>
											<div class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>
												{runSnapshotMap.get(run.build_id) ? 'snapshot mapped' : 'missing snapshot'}
											</div>
										</button>
									{/each}
								</div>
							{/if}
						</div>
					{/if}
				</div>
				<div
					class={css({
						borderWidth: '1',
						padding: '3'
					})}
				>
					<div
						class={css({
							marginBottom: '2',
							fontSize: 'xs',
							fontWeight: 'medium',
							color: 'fg.muted'
						})}
					>
						Selected builds
					</div>
					<div
						class={css({
							display: 'flex',
							flexDirection: 'column',
							gap: '2',
							fontSize: 'sm'
						})}
					>
						<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
							<GitCompareArrows size={14} class={css({ color: 'fg.muted' })} />
							<span>{selected.size}/2 builds selected</span>
						</div>
						{#if selectedRuns.length === 0}
							<p class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>
								Select two builds to compare.
							</p>
						{:else}
							<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
								{#each selectedRuns as run (run.build_id)}
									<div
										class={css({
											display: 'flex',
											alignItems: 'center',
											justifyContent: 'space-between',
											borderWidth: '1',
											backgroundColor: 'bg.secondary',
											paddingX: '3',
											paddingY: '2',
											fontSize: 'xs'
										})}
									>
										<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
											<span class={css({ fontFamily: 'mono' })}>{run.build_id.slice(0, 8)}...</span>
											<span class={css({ color: 'fg.tertiary' })}>{run.current_kind ?? ''}</span>
										</div>
										<button
											class={css({
												borderStyle: 'none',
												backgroundColor: 'transparent',
												color: 'fg.tertiary',
												_hover: { color: 'fg.primary' }
											})}
											onclick={() => toggleSelect(run.build_id)}
											title="Remove selection"
										>
											<X size={12} />
										</button>
									</div>
								{/each}
								{#if selectedRuns.length < 2}
									<p class={css({ fontSize: '2xs', color: 'fg.tertiary' })}>
										Select one more build.
									</p>
								{/if}
							</div>
							<button
								class={button({ variant: 'primary', size: 'sm' })}
								disabled={!canCompare || comparing || !snapshotA || !snapshotB}
								onclick={runComparison}
							>
								{#if comparing}
									<RefreshCw size={13} class={css({ animation: 'spin 1s linear infinite' })} />
								{/if}
								Compare snapshots
							</button>
							{#if compareError}
								<div class={css({ fontSize: 'xs', color: 'fg.error' })}>{compareError}</div>
							{/if}
							{#if !snapshotA || !snapshotB}
								<div class={css({ fontSize: 'xs', color: 'fg.warning' })}>
									Snapshot mapping missing for one or both builds.
								</div>
							{/if}
						{/if}
					</div>
				</div>
			</div>

			{#if comparison}
				<div class={css({ borderWidth: '1' })}>
					<div
						class={css({
							display: 'grid',
							gap: '4',
							borderBottomWidth: '1',
							padding: '4',
							md: { gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }
						})}
					>
						<div
							class={css({
								borderWidth: '1',
								padding: '3',
								textAlign: 'center'
							})}
						>
							<div class={css({ fontSize: 'xs', color: 'fg.muted' })}>Row Count A</div>
							<div class={css({ marginTop: '1', fontFamily: 'mono', fontSize: 'lg' })}>
								{comparison.row_count_a}
							</div>
						</div>
						<div
							class={css({
								borderWidth: '1',
								padding: '3',
								textAlign: 'center'
							})}
						>
							<div class={css({ fontSize: 'xs', color: 'fg.muted' })}>Row Count B</div>
							<div class={css({ marginTop: '1', fontFamily: 'mono', fontSize: 'lg' })}>
								{comparison.row_count_b}
							</div>
						</div>
						<div
							class={css({
								borderWidth: '1',
								padding: '3',
								textAlign: 'center'
							})}
						>
							<div class={css({ fontSize: 'xs', color: 'fg.muted' })}>Row Count Delta</div>
							<div
								class={[
									css({ marginTop: '1', fontFamily: 'mono', fontSize: 'lg' }),
									rowDeltaClass(comparison.row_count_delta)
								]}
							>
								{formatDelta(comparison.row_count_delta)}
							</div>
						</div>
					</div>
					<div class={css({ padding: '4' })}>
						<h4
							class={css({
								marginBottom: '2',
								fontSize: 'sm',
								fontWeight: 'medium',
								color: 'fg.secondary'
							})}
						>
							Schema Changes
						</h4>
						{#if comparison.schema_diff.length > 0}
							<div
								class={css({
									borderWidth: '1'
								})}
							>
								<table class={css({ width: '100%', borderCollapse: 'collapse', fontSize: 'sm' })}>
									<thead>
										<tr class={css({ backgroundColor: 'bg.tertiary' })}>
											<th
												class={css({
													borderBottomWidth: '1',
													paddingX: '3',
													paddingY: '1.5',
													textAlign: 'left',
													fontWeight: 'medium'
												})}>Column</th
											>
											<th
												class={css({
													borderBottomWidth: '1',
													paddingX: '3',
													paddingY: '1.5',
													textAlign: 'left',
													fontWeight: 'medium'
												})}>Change</th
											>
											<th
												class={css({
													borderBottomWidth: '1',
													paddingX: '3',
													paddingY: '1.5',
													textAlign: 'left',
													fontWeight: 'medium'
												})}>Type A</th
											>
											<th
												class={css({
													borderBottomWidth: '1',
													paddingX: '3',
													paddingY: '1.5',
													textAlign: 'left',
													fontWeight: 'medium'
												})}>Type B</th
											>
										</tr>
									</thead>
									<tbody>
										{#each comparison.schema_diff as diff (diff.column)}
											<tr>
												<td
													class={css({
														borderBottomWidth: '1',
														paddingX: '3',
														paddingY: '1.5',
														fontFamily: 'mono',
														fontSize: 'xs'
													})}>{diff.column}</td
												>
												<td
													class={css({
														borderBottomWidth: '1',
														paddingX: '3',
														paddingY: '1.5'
													})}
												>
													{#if diff.status === 'added'}
														<span
															class={css({
																display: 'inline-flex',
																alignItems: 'center',
																gap: '1',
																fontSize: 'xs',
																color: 'fg.success'
															})}
														>
															<Plus size={12} /> Added
														</span>
													{:else if diff.status === 'removed'}
														<span
															class={css({
																display: 'inline-flex',
																alignItems: 'center',
																gap: '1',
																fontSize: 'xs',
																color: 'fg.error'
															})}
														>
															<Minus size={12} /> Removed
														</span>
													{:else}
														<span
															class={css({
																display: 'inline-flex',
																alignItems: 'center',
																gap: '1',
																fontSize: 'xs',
																color: 'fg.warning'
															})}
														>
															<RefreshCw size={12} /> Changed
														</span>
													{/if}
												</td>
												<td
													class={css({
														borderBottomWidth: '1',
														paddingX: '3',
														paddingY: '1.5',
														fontFamily: 'mono',
														fontSize: 'xs',
														color: 'fg.muted'
													})}
												>
													{diff.type_a ?? '-'}
												</td>
												<td
													class={css({
														borderBottomWidth: '1',
														paddingX: '3',
														paddingY: '1.5',
														fontFamily: 'mono',
														fontSize: 'xs',
														color: 'fg.muted'
													})}
												>
													{diff.type_b ?? '-'}
												</td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						{:else}
							<div
								class={css({
									borderWidth: '1',
									backgroundColor: 'bg.tertiary',
									padding: '4',
									textAlign: 'center',
									fontSize: 'sm',
									color: 'fg.tertiary'
								})}
							>
								No schema changes detected
							</div>
						{/if}
					</div>

					<div class={css({ padding: '4' })}>
						<h4
							class={css({
								marginBottom: '2',
								fontSize: 'sm',
								fontWeight: 'medium',
								color: 'fg.secondary'
							})}
						>
							Column Statistics
						</h4>
						<div
							class={css({
								borderWidth: '1'
							})}
						>
							<div
								class={[
									css({ maxHeight: 'listTall', overflow: 'auto', contain: 'content' }),
									'datasource-comparison-scroll'
								]}
							>
								<table class={css({ width: '100%', borderCollapse: 'collapse', fontSize: 'sm' })}>
									<thead
										class={css({
											position: 'sticky',
											top: '0',
											zIndex: '10',
											backgroundColor: 'bg.tertiary'
										})}
									>
										<tr>
											<th
												class={css({
													borderBottomWidth: '1',
													paddingX: '3',
													paddingY: '1.5',
													textAlign: 'left',
													fontWeight: 'medium'
												})}>Column</th
											>
											<th
												class={css({
													borderBottomWidth: '1',
													paddingX: '3',
													paddingY: '1.5',
													textAlign: 'left',
													fontWeight: 'medium'
												})}>Type</th
											>
											<th
												class={css({
													borderBottomWidth: '1',
													paddingX: '3',
													paddingY: '1.5',
													textAlign: 'left',
													fontWeight: 'medium'
												})}>Null Count (A → B)</th
											>
											<th
												class={css({
													borderBottomWidth: '1',
													paddingX: '3',
													paddingY: '1.5',
													textAlign: 'left',
													fontWeight: 'medium'
												})}>Unique Count (A → B)</th
											>
											<th
												class={css({
													borderBottomWidth: '1',
													paddingX: '3',
													paddingY: '1.5',
													textAlign: 'left',
													fontWeight: 'medium'
												})}>Min (A → B)</th
											>
											<th
												class={css({
													borderBottomWidth: '1',
													paddingX: '3',
													paddingY: '1.5',
													textAlign: 'left',
													fontWeight: 'medium'
												})}>Max (A → B)</th
											>
										</tr>
									</thead>
									<tbody>
										{#each combinedStats as stat (stat.column)}
											<tr>
												<td
													class={css({
														borderBottomWidth: '1',
														paddingX: '3',
														paddingY: '1.5',
														fontFamily: 'mono',
														fontSize: 'xs',
														fontWeight: 'medium'
													})}
												>
													{stat.column}
												</td>
												<td
													class={css({
														borderBottomWidth: '1',
														paddingX: '3',
														paddingY: '1.5',
														fontFamily: 'mono',
														fontSize: 'xs',
														color: 'fg.muted'
													})}
												>
													{stat.type}
												</td>
												<td
													class={css({
														borderBottomWidth: '1',
														paddingX: '3',
														paddingY: '1.5',
														fontFamily: 'mono',
														fontSize: 'xs'
													})}
												>
													<div class={css({ display: 'flex', alignItems: 'baseline', gap: '2' })}>
														<span class={css({ color: 'fg.muted' })}>{stat.null_a}</span>
														<span class={css({ color: 'fg.tertiary' })}>→</span>
														<span>{stat.null_b}</span>
														{#if stat.null_delta !== null}
															<span
																class={[
																	css({ marginLeft: '1', fontSize: '2xs' }),
																	nullDeltaClass(stat.null_delta)
																]}
															>
																({formatDelta(stat.null_delta)})
															</span>
														{/if}
													</div>
												</td>
												<td
													class={css({
														borderBottomWidth: '1',
														paddingX: '3',
														paddingY: '1.5',
														fontFamily: 'mono',
														fontSize: 'xs'
													})}
												>
													<div class={css({ display: 'flex', alignItems: 'baseline', gap: '2' })}>
														<span class={css({ color: 'fg.muted' })}>{stat.unique_a}</span>
														<span class={css({ color: 'fg.tertiary' })}>→</span>
														<span>{stat.unique_b}</span>
														{#if stat.unique_delta !== null}
															<span
																class={[
																	css({ marginLeft: '1', fontSize: '2xs' }),
																	uniqueDeltaClass(stat.unique_delta)
																]}
															>
																({formatDelta(stat.unique_delta)})
															</span>
														{/if}
													</div>
												</td>
												<td
													class={css({
														borderBottomWidth: '1',
														paddingX: '3',
														paddingY: '1.5',
														fontFamily: 'mono',
														fontSize: 'xs',
														color: 'fg.muted'
													})}
												>
													{#if stat.min_a === stat.min_b}
														{stat.min_b}
													{:else}
														<span class={css({ color: 'fg.tertiary' })}>{stat.min_a}</span>
														<span class={css({ marginX: '1' })}>→</span>
														<span>{stat.min_b}</span>
													{/if}
												</td>
												<td
													class={css({
														borderBottomWidth: '1',
														paddingX: '3',
														paddingY: '1.5',
														fontFamily: 'mono',
														fontSize: 'xs',
														color: 'fg.muted'
													})}
												>
													{#if stat.max_a === stat.max_b}
														{stat.max_b}
													{:else}
														<span class={css({ color: 'fg.tertiary' })}>{stat.max_a}</span>
														<span class={css({ marginX: '1' })}>→</span>
														<span>{stat.max_b}</span>
													{/if}
												</td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						</div>
					</div>
					<div
						class={css({
							display: 'grid',
							gap: '4',
							padding: '4',
							md: { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }
						})}
					>
						<div
							class={css({
								borderWidth: '1'
							})}
						>
							<div
								class={css({
									borderBottomWidth: '1',
									backgroundColor: 'bg.tertiary',
									paddingX: '3',
									paddingY: '2',
									fontSize: 'xs',
									fontWeight: 'medium',
									color: 'fg.muted'
								})}
							>
								Snapshot A preview
							</div>
							<div
								class={[
									css({ height: 'listLg', contain: 'content' }),
									'datasource-comparison-scroll'
								]}
							>
								<DataTable
									columns={previewColumns(comparison.preview_a)}
									data={previewData(comparison.preview_a)}
									columnTypes={previewTypes(comparison.preview_a)}
									fillContainer
									showHeader
								/>
							</div>
						</div>
						<div
							class={css({
								borderWidth: '1'
							})}
						>
							<div
								class={css({
									borderBottomWidth: '1',
									backgroundColor: 'bg.tertiary',
									paddingX: '3',
									paddingY: '2',
									fontSize: 'xs',
									fontWeight: 'medium',
									color: 'fg.muted'
								})}
							>
								Snapshot B preview
							</div>
							<div
								class={[
									css({ height: 'listLg', contain: 'content' }),
									'datasource-comparison-scroll'
								]}
							>
								<DataTable
									columns={previewColumns(comparison.preview_b)}
									data={previewData(comparison.preview_b)}
									columnTypes={previewTypes(comparison.preview_b)}
									fillContainer
									showHeader
								/>
							</div>
						</div>
					</div>
				</div>
			{:else if selected.size > 0}
				<div
					class={css({
						borderWidth: '1',
						padding: '4',
						fontSize: 'sm',
						color: 'fg.tertiary'
					})}
				>
					Select two builds to enable snapshot comparison.
				</div>
			{/if}
		</div>
	{/if}
</div>
