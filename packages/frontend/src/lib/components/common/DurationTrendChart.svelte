<script lang="ts">
	import type { DurationStatsResponse } from '$lib/api/engine-runs';
	import { formatDuration } from '$lib/utils/format-duration';
	import {
		isSuccessfulBuildStatus,
		trendDirectionLabel,
		trendTone
	} from '$lib/utils/duration-stats';
	import { css } from '$lib/styles/panda';

	interface Props {
		stats: DurationStatsResponse | null;
		loading?: boolean;
	}

	let { stats, loading = false }: Props = $props();

	const chartHeight = 96;
	const chartWidth = 320;
	const padX = 8;
	const padY = 8;

	const trend = $derived(stats?.trend ?? null);
	const direction = $derived(trend?.direction ?? 'insufficient_data');
	const tone = $derived(trendTone(direction));

	const points = $derived.by(() => {
		const runs = stats?.runs ?? [];
		const withDuration = runs
			.map((run, index) => ({ run, index, duration: run.duration_ms }))
			.filter(
				(item): item is { run: (typeof runs)[number]; index: number; duration: number } =>
					item.duration !== null && item.duration !== undefined && item.duration >= 0
			);
		if (withDuration.length === 0) return [];

		const maxDuration = Math.max(...withDuration.map((item) => item.duration), 1);
		const count = withDuration.length;
		return withDuration.map((item, i) => {
			const x = count === 1 ? chartWidth / 2 : padX + (i / (count - 1)) * (chartWidth - padX * 2);
			const y = chartHeight - padY - (item.duration / maxDuration) * (chartHeight - padY * 2);
			return {
				x,
				y,
				duration: item.duration,
				status: item.run.status,
				id: item.run.id,
				success: isSuccessfulBuildStatus(item.run.status)
			};
		});
	});

	const avgY = $derived.by(() => {
		if (!stats?.avg_duration_ms || points.length === 0) return null;
		const maxDuration = Math.max(...points.map((p) => p.duration), 1);
		return chartHeight - padY - (stats.avg_duration_ms / maxDuration) * (chartHeight - padY * 2);
	});

	const pathD = $derived.by(() => {
		if (points.length === 0) return '';
		return points
			.map(
				(point, index) => `${index === 0 ? 'M' : 'L'} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`
			)
			.join(' ');
	});
</script>

<div
	class={css({
		borderWidth: '1',
		borderColor: 'border.primary',
		backgroundColor: 'bg.secondary',
		padding: '3',
		display: 'flex',
		flexDirection: 'column',
		gap: '2'
	})}
	data-testid="duration-trend-chart"
>
	<div
		class={css({
			display: 'flex',
			alignItems: 'flex-start',
			justifyContent: 'space-between',
			gap: '3',
			flexWrap: 'wrap'
		})}
	>
		<div class={css({ display: 'flex', flexDirection: 'column', gap: '1', minWidth: '0' })}>
			<span class={css({ fontSize: 'sm', fontWeight: 'semibold' })}>Build length trend</span>
			{#if trend}
				<span
					class={css({
						fontSize: 'xs',
						fontWeight: 'medium',
						color:
							tone === 'success' ? 'fg.success' : tone === 'warning' ? 'fg.warning' : 'fg.secondary'
					})}
					data-testid="duration-trend-label"
					data-trend-direction={direction}
				>
					{trendDirectionLabel(direction)}
					{#if trend.change_pct !== null && direction !== 'insufficient_data'}
						({trend.change_pct > 0 ? '+' : ''}{trend.change_pct.toFixed(0)}% duration)
					{/if}
				</span>
			{/if}
		</div>
		{#if stats}
			<span
				class={css({
					fontSize: 'xs',
					color: 'fg.muted',
					textAlign: 'right',
					fontFamily: 'mono'
				})}
				data-testid="duration-trend-stats"
			>
				{#if stats.avg_duration_ms !== null}
					avg {formatDuration(stats.avg_duration_ms)}
				{/if}
				{#if stats.p50_duration_ms !== null}
					· p50 {formatDuration(stats.p50_duration_ms)}
				{/if}
				{#if stats.p95_duration_ms !== null}
					· p95 {formatDuration(stats.p95_duration_ms)}
				{/if}
			</span>
		{/if}
	</div>

	{#if trend}
		<p
			class={css({ fontSize: 'xs', color: 'fg.secondary', lineHeight: 'snug', margin: '0' })}
			data-testid="duration-trend-summary"
		>
			{trend.summary}
		</p>
		{#if trend.direction !== 'insufficient_data' && trend.older_avg_ms !== null && trend.recent_avg_ms !== null}
			<div
				class={css({
					display: 'flex',
					flexWrap: 'wrap',
					gap: '3',
					fontSize: '2xs',
					color: 'fg.muted',
					fontFamily: 'mono'
				})}
				data-testid="duration-trend-halves"
			>
				<span>
					Earlier ({trend.older_count}): {formatDuration(trend.older_avg_ms)}
				</span>
				<span>
					Recent ({trend.recent_count}): {formatDuration(trend.recent_avg_ms)}
				</span>
				<span>
					±{trend.threshold_pct}% band for “stable”
				</span>
			</div>
		{/if}
	{/if}

	{#if loading}
		<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>Loading duration stats…</span>
	{:else if points.length === 0}
		<span class={css({ fontSize: 'xs', color: 'fg.muted' })} data-testid="duration-trend-empty">
			No completed builds yet
		</span>
	{:else}
		<svg
			viewBox={`0 0 ${chartWidth} ${chartHeight}`}
			class={css({ width: '100%', maxWidth: 'md', height: 'auto' })}
			role="img"
			aria-label={trend?.summary ?? 'Build duration trend'}
			data-testid="duration-trend-svg"
		>
			{#if avgY !== null}
				<line
					x1={padX}
					y1={avgY}
					x2={chartWidth - padX}
					y2={avgY}
					stroke="currentColor"
					stroke-dasharray="4 3"
					class={css({ color: 'fg.faint' })}
					stroke-width="1"
				/>
			{/if}
			{#if pathD}
				<path
					d={pathD}
					fill="none"
					stroke="currentColor"
					stroke-width="1.5"
					class={css({ color: 'accent.primary' })}
				/>
			{/if}
			{#each points as point (point.id)}
				<circle
					cx={point.x}
					cy={point.y}
					r="3.5"
					class={css({
						fill: point.success ? 'fg.success' : 'fg.error'
					})}
					data-testid={`duration-trend-point-${point.id}`}
				>
					<title>{formatDuration(point.duration)} · {point.status}</title>
				</circle>
			{/each}
		</svg>
		<span class={css({ fontSize: '2xs', color: 'fg.faint' })}>
			Oldest → newest · dashed line is overall average · green/red dots by outcome
		</span>
	{/if}
</div>
