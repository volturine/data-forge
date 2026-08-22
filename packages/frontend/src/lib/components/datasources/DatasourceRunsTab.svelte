<script lang="ts">
	import { resolve } from '$app/paths';
	import {
		CircleAlert,
		CircleCheck,
		CircleX,
		Download,
		Eye,
		EyeOff,
		Loader,
		RefreshCw,
		Save
	} from '@lucide/svelte';
	import type { BuildRunSummary } from '$lib/types/build-stream';
	import {
		buildLifecycleStatusLabel,
		buildLifecycleStatusTone,
		engineRunDisplayKind,
		engineRunKindLabel
	} from '$lib/types/build-stream';
	import type { PaginatedStatus } from '$lib/stores/paginated-store.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { formatDateDisplay, toEpochDisplay } from '$lib/utils/datetime';
	import { css, chip, emptyText } from '$lib/styles/panda';

	type DatasourceRunRow = {
		id: string;
		kind: string;
		status: BuildRunSummary['status'];
		durationMs: number | null;
		createdAt: string;
		builtTag: boolean;
	};

	interface Props {
		datasourceId: string;
		builds: BuildRunSummary[];
		status: PaginatedStatus;
		error: string | null;
		showPreviews?: boolean;
		onTogglePreviews: () => void;
	}

	let {
		datasourceId,
		builds,
		status,
		error,
		showPreviews = false,
		onTogglePreviews
	}: Props = $props();

	const filteredRuns = $derived.by((): DatasourceRunRow[] => {
		const buildRows = builds.map((run: BuildRunSummary) => ({
			id: run.build_id,
			kind: run.current_kind ?? 'build',
			status: run.status,
			durationMs: run.elapsed_ms,
			createdAt: run.started_at,
			builtTag:
				run.current_output_id === datasourceId || run.result_json?.datasource_id === datasourceId
		}));
		const rows = buildRows.filter((run) => showPreviews || run.kind !== 'preview');
		return rows.sort(
			(left, right) => toEpochDisplay(right.createdAt) - toEpochDisplay(left.createdAt)
		);
	});

	function formatDuration(ms: number | null): string {
		if (ms === null) return '-';
		if (ms < 1000) return `${ms}ms`;
		return `${(ms / 1000).toFixed(2)}s`;
	}

	function runStatusLabel(status: DatasourceRunRow['status']): string {
		return buildLifecycleStatusLabel(status);
	}

	function runStatusTone(
		status: DatasourceRunRow['status']
	): 'success' | 'active' | 'warning' | 'error' {
		return buildLifecycleStatusTone(status);
	}
</script>

<div class={css({ display: 'flex', flexDirection: 'column', gap: '3' })}>
	<button
		class={css({
			borderWidth: '1',
			backgroundColor: 'transparent',
			color: 'fg.secondary',
			borderColor: 'transparent',
			fontSize: 'xs',
			paddingX: '2',
			paddingY: '1',
			width: 'fit-content',
			'&:hover:not(:disabled)': { backgroundColor: 'bg.hover', color: 'fg.primary' }
		})}
		onclick={onTogglePreviews}
		aria-pressed={showPreviews}
	>
		{#if showPreviews}
			<EyeOff size={12} />
			Hide previews
		{:else}
			<Eye size={12} />
			Show previews
		{/if}
	</button>
	{#if status === 'connecting'}
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				flexDirection: 'column',
				justifyContent: 'center',
				gap: '3',
				paddingY: '8',
				color: 'fg.muted'
			})}
		>
			<Loader size={24} class={css({ animation: 'spin 1s linear infinite' })} />
			<p class={css({ fontSize: 'sm' })}>Loading runs...</p>
		</div>
	{:else if status === 'error'}
		<Callout tone="error">
			<div class={css({ display: 'flex', alignItems: 'flex-start', gap: '3' })}>
				<CircleAlert size={20} />
				<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
					<p class={css({ margin: '0', fontWeight: 'semibold' })}>Failed to load runs</p>
					<p class={css({ margin: '0', fontSize: 'sm', opacity: '0.8' })}>
						{error ?? 'Unknown error'}
					</p>
				</div>
			</div>
		</Callout>
	{:else if filteredRuns.length === 0}
		<div class={emptyText({ size: 'panel' })}>
			<p class={css({ margin: '0' })}>No runs associated with this datasource.</p>
			<p class={css({ margin: '0', marginTop: '1', color: 'fg.tertiary' })}>
				Runs will appear here when this datasource is onboarded, rebuilt from source, or used in
				analyses.
			</p>
		</div>
	{:else}
		<div
			class={css({
				borderWidth: '1'
			})}
		>
			<div
				class={css({
					display: 'grid',
					gridTemplateColumns: '1fr 80px 80px 100px',
					alignItems: 'center',
					columnGap: '2',
					backgroundColor: 'bg.tertiary',
					paddingX: '3',
					paddingY: '2',
					fontSize: 'xs',
					fontWeight: 'semibold',
					textTransform: 'uppercase',
					letterSpacing: 'wide',
					color: 'fg.muted',
					borderBottomWidth: '1'
				})}
			>
				<span>Type</span>
				<span>Status</span>
				<span>Duration</span>
				<span>Created</span>
			</div>
			{#each filteredRuns as run, index (run.id)}
				{@const displayKind = engineRunDisplayKind(run.kind)}
				<div
					class={css(
						{
							display: 'grid',
							gridTemplateColumns: '1fr 80px 80px 100px',
							alignItems: 'center',
							columnGap: '2',
							paddingX: '3',
							paddingY: '2'
						},
						index > 0 && { borderTopWidth: '1' }
					)}
				>
					<div class={css({ display: 'flex', alignItems: 'center', gap: '2', fontSize: 'xs' })}>
						{#if displayKind === 'preview'}
							<Eye size={14} class={css({ flexShrink: '0', color: 'accent.primary' })} />
						{:else if displayKind === 'build'}
							<Save size={14} class={css({ flexShrink: '0', color: 'accent.primary' })} />
						{:else if displayKind === 'row_count'}
							<RefreshCw size={14} class={css({ flexShrink: '0', color: 'fg.secondary' })} />
						{:else}
							<Download size={14} class={css({ flexShrink: '0', color: 'fg.success' })} />
						{/if}
						<span>{engineRunKindLabel(run.kind)}</span>
						{#if run.builtTag}
							<span
								class={chip({ tone: 'accent' })}
								title="This datasource was produced by this run"
							>
								BUILT
							</span>
						{/if}
					</div>
					<div class={css({ display: 'flex', alignItems: 'center', gap: '1.5', fontSize: 'xs' })}>
						{#if runStatusTone(run.status) === 'success'}
							<CircleCheck size={14} class={css({ color: 'fg.success' })} />
							<span class={css({ color: 'fg.success' })}>{runStatusLabel(run.status)}</span>
						{:else if runStatusTone(run.status) === 'active'}
							<Loader
								size={14}
								class={css({ color: 'accent.primary', animation: 'spin 1s linear infinite' })}
							/>
							<span class={css({ color: 'accent.primary' })}>{runStatusLabel(run.status)}</span>
						{:else if runStatusTone(run.status) === 'warning'}
							<CircleX size={14} class={css({ color: 'fg.warning' })} />
							<span class={css({ color: 'fg.warning' })}>{runStatusLabel(run.status)}</span>
						{:else}
							<CircleX size={14} class={css({ color: 'fg.error' })} />
							<span class={css({ color: 'fg.error' })}>{runStatusLabel(run.status)}</span>
						{/if}
					</div>
					<span
						class={css({
							fontSize: 'xs',
							fontFamily: 'mono',
							color: 'fg.secondary'
						})}
					>
						{formatDuration(run.durationMs)}
					</span>
					<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>
						{formatDateDisplay(run.createdAt)}
					</span>
				</div>
			{/each}
		</div>
		{#if filteredRuns.length >= 50}
			<p class={css({ fontSize: 'xs', color: 'fg.tertiary', textAlign: 'center' })}>
				Showing last 50 runs.
				<a
					href="{resolve('/monitoring')}?datasource_id={datasourceId}"
					class={css({ color: 'accent.primary', _hover: { textDecoration: 'underline' } })}
				>
					View all runs
				</a>
			</p>
		{/if}
	{/if}
</div>
