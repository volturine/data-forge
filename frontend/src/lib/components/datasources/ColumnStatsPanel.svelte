<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { ChartColumn, X } from 'lucide-svelte';
	import { getColumnStats } from '$lib/api/datasource';
	import type { HistogramBin } from '$lib/api/datasource';
	import PanelHeader from '$lib/components/ui/PanelHeader.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { useNamespace } from '$lib/stores/namespace.svelte';
	import { css } from '$lib/styles/panda';

	interface Props {
		datasourceId: string;
		columnName: string | null;
		open: boolean;
		datasourceConfig?: Record<string, unknown> | null;
		onClose: () => void;
	}

	let { datasourceId, columnName, open, datasourceConfig = null, onClose }: Props = $props();

	const ns = useNamespace();

	const query = createQuery(() => ({
		queryKey: ['column-stats', ns.value, datasourceId, columnName, datasourceConfig ?? null],
		queryFn: async () => {
			if (!columnName) {
				throw new Error('Column name required');
			}
			const result = await getColumnStats(datasourceId, columnName, {
				sample: true,
				datasource: datasourceConfig ? { config: datasourceConfig } : undefined
			});
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		enabled: open && !!columnName && !!datasourceId && !ns.switching,
		staleTime: 30000
	}));

	const stats = $derived(query.data ?? null);
	const loading = $derived(query.isLoading);
	const error = $derived(query.error);

	const histMax = $derived(stats?.histogram ? Math.max(...stats.histogram.map((b) => b.count)) : 0);

	const topMax = $derived(
		stats?.top_values ? Math.max(...stats.top_values.map((v) => Number(v.count ?? 0))) : 0
	);

	function fmt(value: number | null | undefined): string {
		if (value === null || value === undefined) return '-';
		return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2);
	}

	function barPct(count: number, max: number): number {
		if (max === 0) return 0;
		return (count / max) * 100;
	}

	function histLabel(bin: HistogramBin): string {
		return `${fmt(bin.start)} – ${fmt(bin.end)}`;
	}
</script>

{#if open}
	<div
		class={css({ position: 'absolute', insetInline: '0', bottom: '0', zIndex: '40' })}
		data-testid="column-stats-panel"
	>
		<div
			class={css({
				borderTopWidth: '1',
				backgroundColor: 'bg.primary'
			})}
		>
			<PanelHeader>
				{#snippet title()}
					<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
						<ChartColumn size={16} />
						<h3 class={css({ margin: '0', fontSize: 'xs', fontWeight: 'semibold' })}>
							Column Stats
						</h3>
						{#if columnName}
							<span class={css({ fontSize: 'xs', color: 'fg.muted', fontFamily: 'mono' })}
								>{columnName}</span
							>
						{/if}
						{#if stats}
							<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>({stats.dtype})</span>
						{/if}
					</div>
				{/snippet}
				{#snippet actions()}
					<button
						class={css({
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'center',
							borderWidth: '1',
							backgroundColor: 'transparent',
							paddingX: '2',
							paddingY: '1',
							fontSize: 'xs',
							color: 'fg.secondary',
							_hover: { backgroundColor: 'bg.hover' },
							transition: 'color 160ms, background-color 160ms'
						})}
						onclick={onClose}
						type="button"
						data-testid="column-stats-close"
					>
						<X size={14} />
					</button>
				{/snippet}
			</PanelHeader>

			<div class={css({ height: 'listLg', overflowY: 'auto', padding: '5' })}>
				{#if loading}
					<div class={css({ fontSize: 'sm', color: 'fg.muted' })}>Computing stats...</div>
				{:else if error}
					<Callout tone="error">
						{error instanceof Error ? error.message : 'Failed to load stats'}
					</Callout>
				{:else if stats}
					<div class={css({ display: 'flex', gap: '6' })}>
						<!-- Left: Core metrics -->
						<div class={css({ minWidth: 'list', flexShrink: '0' })}>
							<!-- Overview section -->
							<div class={css({ marginBottom: '4' })}>
								<div
									class={css({
										fontSize: '2xs',
										fontWeight: 'semibold',
										textTransform: 'uppercase',
										letterSpacing: 'wider',
										color: 'fg.muted',
										marginBottom: '1.5'
									})}
								>
									Overview
								</div>
								<div
									class={css({
										display: 'flex',
										justifyContent: 'space-between',
										alignItems: 'baseline',
										paddingY: '0.5'
									})}
								>
									<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>Rows</span>
									<span
										class={css({
											fontSize: 'xs',
											fontWeight: 'semibold',
											fontFamily: 'mono'
										})}>{stats.count.toLocaleString()}</span
									>
								</div>
								<div
									class={css({
										display: 'flex',
										justifyContent: 'space-between',
										alignItems: 'baseline',
										paddingY: '0.5'
									})}
								>
									<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>Nulls</span>
									<span
										class={css({
											fontSize: 'xs',
											fontWeight: 'semibold',
											fontFamily: 'mono'
										})}
									>
										{stats.null_count.toLocaleString()}
									</span>
								</div>
								<div
									class={css({
										height: 'barTall',
										backgroundColor: 'bg.tertiary',
										borderWidth: '1',
										marginTop: '1',
										overflow: 'hidden'
									})}
								>
									<div
										class={css({
											height: '100%',
											backgroundColor: 'accent.primary',
											transition: 'width 300ms ease'
										})}
										style="width: {Math.min(stats.null_percentage, 100)}%"
									></div>
								</div>
								<div class={css({ fontSize: 'xs', color: 'fg.muted', marginTop: '0.5' })}>
									{fmt(stats.null_percentage)}% null
								</div>
								{#if stats.unique !== null && stats.unique !== undefined}
									<div
										class={css({
											display: 'flex',
											justifyContent: 'space-between',
											alignItems: 'baseline',
											paddingY: '0.5',
											marginTop: '1'
										})}
									>
										<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>Unique</span>
										<span
											class={css({
												fontSize: 'xs',
												fontWeight: 'semibold',
												fontFamily: 'mono'
											})}>{stats.unique.toLocaleString()}</span
										>
									</div>
								{/if}
							</div>

							<!-- Numeric stats -->
							{#if stats.mean !== null && stats.mean !== undefined}
								<div class={css({ marginBottom: '4' })}>
									<div
										class={css({
											fontSize: '2xs',
											fontWeight: 'semibold',
											textTransform: 'uppercase',
											letterSpacing: 'wider',
											color: 'fg.muted',
											marginBottom: '1.5'
										})}
									>
										Distribution
									</div>
									<div
										class={css({
											display: 'flex',
											justifyContent: 'space-between',
											alignItems: 'baseline',
											paddingY: '0.5'
										})}
									>
										<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>Mean</span>
										<span
											class={css({
												fontSize: 'xs',
												fontWeight: 'semibold',
												fontFamily: 'mono'
											})}>{fmt(stats.mean)}</span
										>
									</div>
									{#if stats.median !== null && stats.median !== undefined}
										<div
											class={css({
												display: 'flex',
												justifyContent: 'space-between',
												alignItems: 'baseline',
												paddingY: '0.5'
											})}
										>
											<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>Median</span>
											<span
												class={css({
													fontSize: 'xs',
													fontWeight: 'semibold',
													fontFamily: 'mono'
												})}>{fmt(stats.median)}</span
											>
										</div>
									{/if}
									{#if stats.std !== null && stats.std !== undefined}
										<div
											class={css({
												display: 'flex',
												justifyContent: 'space-between',
												alignItems: 'baseline',
												paddingY: '0.5'
											})}
										>
											<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>Std Dev</span>
											<span
												class={css({
													fontSize: 'xs',
													fontWeight: 'semibold',
													fontFamily: 'mono'
												})}>{fmt(stats.std)}</span
											>
										</div>
									{/if}
									<div
										class={css({
											display: 'flex',
											justifyContent: 'space-between',
											alignItems: 'baseline',
											paddingY: '0.5'
										})}
									>
										<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>Min</span>
										<span
											class={css({
												fontSize: 'xs',
												fontWeight: 'semibold',
												fontFamily: 'mono'
											})}>{stats.min}</span
										>
									</div>
									{#if stats.q25 !== null && stats.q25 !== undefined}
										<div
											class={css({
												display: 'flex',
												justifyContent: 'space-between',
												alignItems: 'baseline',
												paddingY: '0.5'
											})}
										>
											<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>Q25</span>
											<span
												class={css({
													fontSize: 'xs',
													fontWeight: 'semibold',
													fontFamily: 'mono'
												})}>{fmt(stats.q25)}</span
											>
										</div>
									{/if}
									{#if stats.q75 !== null && stats.q75 !== undefined}
										<div
											class={css({
												display: 'flex',
												justifyContent: 'space-between',
												alignItems: 'baseline',
												paddingY: '0.5'
											})}
										>
											<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>Q75</span>
											<span
												class={css({
													fontSize: 'xs',
													fontWeight: 'semibold',
													fontFamily: 'mono'
												})}>{fmt(stats.q75)}</span
											>
										</div>
									{/if}
									<div
										class={css({
											display: 'flex',
											justifyContent: 'space-between',
											alignItems: 'baseline',
											paddingY: '0.5'
										})}
									>
										<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>Max</span>
										<span
											class={css({
												fontSize: 'xs',
												fontWeight: 'semibold',
												fontFamily: 'mono'
											})}>{stats.max}</span
										>
									</div>
								</div>
							{/if}

							<!-- Datetime stats -->
							{#if stats.mean === null && stats.min !== null && stats.min !== undefined && typeof stats.min === 'string'}
								<div class={css({ marginBottom: '4' })}>
									<div
										class={css({
											fontSize: '2xs',
											fontWeight: 'semibold',
											textTransform: 'uppercase',
											letterSpacing: 'wider',
											color: 'fg.muted',
											marginBottom: '1.5'
										})}
									>
										Range
									</div>
									<div
										class={css({
											display: 'flex',
											justifyContent: 'space-between',
											alignItems: 'baseline',
											paddingY: '0.5'
										})}
									>
										<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>Min</span>
										<span
											class={css({
												fontSize: 'xs',
												fontWeight: 'semibold',
												fontFamily: 'mono'
											})}>{stats.min}</span
										>
									</div>
									<div
										class={css({
											display: 'flex',
											justifyContent: 'space-between',
											alignItems: 'baseline',
											paddingY: '0.5'
										})}
									>
										<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>Max</span>
										<span
											class={css({
												fontSize: 'xs',
												fontWeight: 'semibold',
												fontFamily: 'mono'
											})}>{stats.max}</span
										>
									</div>
								</div>
							{/if}

							<!-- Boolean stats -->
							{#if stats.true_count !== null && stats.true_count !== undefined}
								{@const total = stats.true_count + (stats.false_count ?? 0)}
								{@const truePct = total > 0 ? (stats.true_count / total) * 100 : 0}
								<div class={css({ marginBottom: '4' })}>
									<div
										class={css({
											fontSize: '2xs',
											fontWeight: 'semibold',
											textTransform: 'uppercase',
											letterSpacing: 'wider',
											color: 'fg.muted',
											marginBottom: '1.5'
										})}
									>
										Boolean Distribution
									</div>
									<div
										class={css({
											height: 'dot',
											backgroundColor: 'bg.tertiary',
											borderWidth: '1',
											overflow: 'hidden'
										})}
									>
										<div
											class={css({
												height: '100%',
												backgroundColor: 'accent.primary',
												transition: 'width 300ms ease'
											})}
											style="width: {truePct}%"
										></div>
									</div>
									<div
										class={css({
											display: 'flex',
											justifyContent: 'space-between',
											fontSize: 'xs',
											marginTop: '1'
										})}
									>
										<span class={css({ color: 'accent.primary' })}
											>True: {stats.true_count.toLocaleString()}</span
										>
										<span class={css({ color: 'fg.muted' })}
											>False: {(stats.false_count ?? 0).toLocaleString()}</span
										>
									</div>
								</div>
							{/if}

							<!-- String length stats -->
							{#if stats.min_length !== null && stats.min_length !== undefined}
								<div class={css({ marginBottom: '4' })}>
									<div
										class={css({
											fontSize: '2xs',
											fontWeight: 'semibold',
											textTransform: 'uppercase',
											letterSpacing: 'wider',
											color: 'fg.muted',
											marginBottom: '1.5'
										})}
									>
										String Lengths
									</div>
									<div
										class={css({
											display: 'flex',
											justifyContent: 'space-between',
											alignItems: 'baseline',
											paddingY: '0.5'
										})}
									>
										<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>Min</span>
										<span
											class={css({
												fontSize: 'xs',
												fontWeight: 'semibold',
												fontFamily: 'mono'
											})}>{stats.min_length}</span
										>
									</div>
									<div
										class={css({
											display: 'flex',
											justifyContent: 'space-between',
											alignItems: 'baseline',
											paddingY: '0.5'
										})}
									>
										<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>Avg</span>
										<span
											class={css({
												fontSize: 'xs',
												fontWeight: 'semibold',
												fontFamily: 'mono'
											})}>{fmt(stats.avg_length)}</span
										>
									</div>
									<div
										class={css({
											display: 'flex',
											justifyContent: 'space-between',
											alignItems: 'baseline',
											paddingY: '0.5'
										})}
									>
										<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>Max</span>
										<span
											class={css({
												fontSize: 'xs',
												fontWeight: 'semibold',
												fontFamily: 'mono'
											})}>{stats.max_length}</span
										>
									</div>
								</div>
							{/if}
						</div>

						<!-- Right: Visualizations -->
						<div class={css({ flex: '1', minWidth: '0' })}>
							<!-- Histogram for numeric columns -->
							{#if stats.histogram && stats.histogram.length > 1}
								<div class={css({ marginBottom: '4' })}>
									<div
										class={css({
											fontSize: '2xs',
											fontWeight: 'semibold',
											textTransform: 'uppercase',
											letterSpacing: 'wider',
											color: 'fg.muted',
											marginBottom: '1.5'
										})}
									>
										Distribution
									</div>
									<div
										class={css({
											display: 'flex',
											alignItems: 'flex-end',
											gap: 'px',
											height: 'fieldMd'
										})}
									>
										{#each stats.histogram as bin (bin.start)}
											<div
												class={css({
													flex: '1',
													height: '100%',
													display: 'flex',
													alignItems: 'flex-end',
													cursor: 'default'
												})}
												title="{histLabel(bin)}: {bin.count.toLocaleString()}"
											>
												<div
													class={css({
														width: '100%',
														backgroundColor: 'accent.primary',
														opacity: '0.7',
														minHeight: 'px',
														transition: 'height 300ms ease',
														_groupHover: { opacity: '1' }
													})}
													style="height: {barPct(bin.count, histMax)}%"
												></div>
											</div>
										{/each}
									</div>
									<div
										class={css({
											display: 'flex',
											justifyContent: 'space-between',
											fontSize: 'xs',
											color: 'fg.muted',
											marginTop: '1'
										})}
									>
										<span>{fmt(stats.histogram[0].start)}</span>
										<span>{fmt(stats.histogram[stats.histogram.length - 1].end)}</span>
									</div>
								</div>
							{/if}

							<!-- Top values for string columns -->
							{#if stats.top_values && stats.top_values.length > 0}
								<div class={css({ marginBottom: '4' })}>
									<div
										class={css({
											fontSize: '2xs',
											fontWeight: 'semibold',
											textTransform: 'uppercase',
											letterSpacing: 'wider',
											color: 'fg.muted',
											marginBottom: '1.5'
										})}
									>
										Top Values
									</div>
									<div class={css({ display: 'flex', flexDirection: 'column', gap: '1.5' })}>
										{#each stats.top_values as item, i (i)}
											{@const val = String(item[stats.column] ?? '')}
											{@const cnt = Number(item.count ?? 0)}
											<div class={css({ display: 'flex', flexDirection: 'column', gap: '0.5' })}>
												<div
													class={css({
														display: 'flex',
														justifyContent: 'space-between',
														alignItems: 'baseline'
													})}
												>
													<span
														class={css({
															fontSize: 'xs',
															fontFamily: 'mono',
															overflow: 'hidden',
															textOverflow: 'ellipsis',
															whiteSpace: 'nowrap',
															maxWidth: 'listSm'
														})}
														title={val}>{val}</span
													>
													<span class={css({ fontSize: 'xs', color: 'fg.muted' })}
														>{cnt.toLocaleString()}</span
													>
												</div>
												<div
													class={css({
														height: 'barTall',
														backgroundColor: 'bg.tertiary',
														borderWidth: '1',
														overflow: 'hidden'
													})}
												>
													<div
														class={css({
															height: '100%',
															backgroundColor: 'accent.primary',
															opacity: '0.7',
															transition: 'width 300ms ease'
														})}
														style="width: {barPct(cnt, topMax)}%"
													></div>
												</div>
											</div>
										{/each}
									</div>
								</div>
							{/if}
						</div>
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}
