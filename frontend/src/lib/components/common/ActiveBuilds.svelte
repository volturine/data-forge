<script lang="ts">
	import type { ActiveBuildSummary, BuildEvent, ProgressEvent } from '$lib/types/build-stream';
	import { connectBuildsListStream, connectBuildDetailStream } from '$lib/api/build-stream';
	import { BuildStreamStore } from '$lib/stores/build-stream.svelte';
	import BuildPreview from './BuildPreview.svelte';
	import {
		Loader,
		CheckCircle,
		XCircle,
		ChevronDown,
		ChevronRight,
		Radio,
		User
	} from 'lucide-svelte';
	import { css, cx, chip, spinner, tabButton } from '$lib/styles/panda';
	import { untrack } from 'svelte';

	interface Props {
		searchQuery?: string;
	}

	const { searchQuery = '' }: Props = $props();

	let builds = $state<ActiveBuildSummary[]>([]);
	let connected = $state(false);
	let error = $state<string | null>(null);
	let expandedId = $state<string | null>(null);
	let detailStores = $state(new Map<string, BuildStreamStore>());
	let statusFilter = $state<'all' | 'running' | 'completed' | 'failed'>('all');

	let connection: { close: () => void } | null = null;
	const rowClass = css({ display: 'flex', alignItems: 'center' });

	function progressToPercent(p: number): number {
		return Math.min(Math.max(Math.round(p * 100), 0), 100);
	}

	function starterLabel(build: ActiveBuildSummary): string | null {
		if (build.starter.display_name) return build.starter.display_name;
		if (build.starter.email) return build.starter.email;
		if (build.starter.user_id) return build.starter.user_id;
		if (build.starter.triggered_by) return build.starter.triggered_by;
		return null;
	}

	function applyProgressToSummary(buildId: string, event: BuildEvent): void {
		const idx = builds.findIndex((b) => b.build_id === buildId);
		if (idx < 0) return;
		const next = [...builds];
		const current = next[idx];

		if (event.type === 'progress') {
			const prog = event as ProgressEvent;
			next[idx] = { ...current, progress: prog.progress, current_step: prog.current_step };
		} else if (event.type === 'complete') {
			next[idx] = { ...current, status: 'completed', progress: event.progress };
		} else if (event.type === 'failed') {
			next[idx] = { ...current, status: 'failed', progress: event.progress };
		}
		builds = next;
	}

	function connect(): void {
		connection?.close();
		error = null;
		connection = connectBuildsListStream({
			onSnapshot: (snapshot) => {
				builds = snapshot;
				connected = true;
			},
			onEvent: (event) => {
				applyProgressToSummary(event.build_id, event);
			},
			onError: (msg) => {
				error = msg;
			},
			onClose: () => {
				connected = false;
			}
		});
	}

	function disconnect(): void {
		connection?.close();
		connection = null;
		for (const store of detailStores.values()) {
			store.close();
		}
		detailStores.clear();
	}

	function toggleExpand(buildId: string): void {
		if (expandedId === buildId) {
			const store = detailStores.get(buildId);
			store?.close();
			detailStores.delete(buildId);
			expandedId = null;
			return;
		}
		expandedId = buildId;
		if (!detailStores.has(buildId)) {
			const store = new BuildStreamStore();
			detailStores.set(buildId, store);
			const conn = connectBuildDetailStream(buildId, {
				onSnapshot: (build) => store.applySnapshot(build),
				onEvent: (event) => store.applyEvent(event),
				onError: (msg) => {
					store.error = msg;
				},
				onClose: () => {
					if (!store.done) store.status = 'disconnected';
				}
			});
			store['connection'] = conn;
		}
	}

	const filtered = $derived.by(() => {
		let result = builds;
		if (statusFilter !== 'all') {
			result = result.filter((b) => b.status === statusFilter);
		}
		if (!searchQuery) return result;
		const q = searchQuery.toLowerCase();
		return result.filter(
			(b) =>
				b.build_id.toLowerCase().includes(q) ||
				b.analysis_id.toLowerCase().includes(q) ||
				b.analysis_name.toLowerCase().includes(q) ||
				(b.current_step ?? '').toLowerCase().includes(q) ||
				(b.starter.display_name ?? '').toLowerCase().includes(q) ||
				(b.starter.email ?? '').toLowerCase().includes(q)
		);
	});

	const hasActive = $derived(filtered.length > 0);

	// WS lifecycle: connect on mount, disconnect on destroy
	$effect(() => {
		untrack(() => connect());
		return () => disconnect();
	});
</script>

<div
	class={css({ display: 'flex', flexDirection: 'column', gap: '3' })}
	data-testid="active-builds"
>
	<div class={cx(rowClass, css({ justifyContent: 'space-between' }))}>
		<div class={cx(rowClass, css({ gap: '2' }))}>
			<Radio size={14} class={css({ color: connected ? 'fg.success' : 'fg.muted' })} />
			<span class={css({ fontSize: 'sm', fontWeight: 'semibold' })}>Active Builds</span>
			{#if hasActive}
				<span class={chip({ tone: 'accent' })}>{filtered.length}</span>
			{/if}
		</div>
		{#if !connected && !error}
			<div class={cx(rowClass, css({ gap: '2', fontSize: 'xs', color: 'fg.muted' }))}>
				<div class={spinner({ size: 'sm' })}></div>
				Connecting...
			</div>
		{/if}
	</div>

	<div class={cx(rowClass, css({ gap: '1' }))} data-testid="active-builds-status-filter">
		<button
			type="button"
			class={tabButton({ active: statusFilter === 'all' })}
			onclick={() => (statusFilter = 'all')}
		>
			All
		</button>
		<button
			type="button"
			class={tabButton({ active: statusFilter === 'running' })}
			onclick={() => (statusFilter = 'running')}
		>
			Running
		</button>
		<button
			type="button"
			class={tabButton({ active: statusFilter === 'completed' })}
			onclick={() => (statusFilter = 'completed')}
		>
			Completed
		</button>
		<button
			type="button"
			class={tabButton({ active: statusFilter === 'failed' })}
			onclick={() => (statusFilter = 'failed')}
		>
			Failed
		</button>
	</div>

	{#if error}
		<div
			class={css({
				paddingX: '3',
				paddingY: '2',
				borderWidth: '1',
				borderColor: 'border.warning',
				backgroundColor: 'bg.warning',
				fontSize: 'xs',
				color: 'fg.warning'
			})}
		>
			Live build feed unavailable: {error}
		</div>
	{/if}

	{#if !hasActive}
		<div
			class={css({
				borderWidth: '1',
				borderStyle: 'dashed',
				padding: '4',
				textAlign: 'center',
				fontSize: 'sm',
				color: 'fg.muted'
			})}
		>
			No active builds
		</div>
	{:else}
		<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
			{#each filtered as build (build.build_id)}
				{@const isExpanded = expandedId === build.build_id}
				{@const pct = progressToPercent(build.progress)}
				{@const starter = starterLabel(build)}
				<div
					class={css({
						borderWidth: '1',
						overflow: 'hidden'
					})}
				>
					<button
						type="button"
						class={css({
							display: 'flex',
							width: '100%',
							alignItems: 'center',
							gap: '3',
							paddingX: '3',
							paddingY: '2.5',
							cursor: 'pointer',
							border: 'none',
							backgroundColor: isExpanded ? 'bg.secondary' : 'bg.primary',
							fontSize: 'sm',
							textAlign: 'left',
							_hover: { backgroundColor: 'bg.hover' }
						})}
						onclick={() => toggleExpand(build.build_id)}
						data-testid={`active-build-${build.build_id}`}
					>
						{#if isExpanded}
							<ChevronDown size={12} />
						{:else}
							<ChevronRight size={12} />
						{/if}

						{#if build.status === 'running'}
							<Loader
								size={14}
								class={css({ color: 'accent.primary', animation: 'spin 1s linear infinite' })}
							/>
						{:else if build.status === 'completed'}
							<CheckCircle size={14} class={css({ color: 'fg.success' })} />
						{:else}
							<XCircle size={14} class={css({ color: 'fg.error' })} />
						{/if}

						<span class={css({ fontFamily: 'mono', fontSize: 'xs' })}>
							{build.build_id.slice(0, 8)}
						</span>

						<span class={css({ fontSize: 'xs', color: 'fg.secondary' })}>
							{build.analysis_name}
						</span>

						{#if starter}
							<span
								class={cx(
									rowClass,
									css({ gap: '1', fontSize: 'xs', color: 'fg.muted', flexShrink: '0' })
								)}
								data-testid="build-starter"
							>
								<User size={10} />
								{starter}
							</span>
						{/if}

						<div class={css({ flex: '1', minWidth: '0' })}>
							{#if build.current_step}
								<span
									class={css({
										fontSize: 'xs',
										color: 'fg.muted',
										overflow: 'hidden',
										textOverflow: 'ellipsis',
										whiteSpace: 'nowrap'
									})}
								>
									{build.current_step}
								</span>
							{/if}
						</div>

						<div
							class={css({
								width: 'colNarrow',
								height: 'bar',
								backgroundColor: 'bg.tertiary',
								flexShrink: '0',
								position: 'relative',
								overflow: 'hidden'
							})}
						>
							<div
								class={css({
									position: 'absolute',
									top: '0',
									left: '0',
									bottom: '0',
									backgroundColor: 'accent.primary'
								})}
								style={`width: ${pct}%`}
							></div>
						</div>

						<span
							class={css({
								fontSize: 'xs',
								fontFamily: 'mono',
								color: 'fg.muted',
								flexShrink: '0'
							})}
						>
							{pct}%
						</span>
					</button>

					{#if isExpanded}
						{@const detailStore = detailStores.get(build.build_id)}
						{#if detailStore}
							<div class={css({ borderTopWidth: '1' })}>
								<BuildPreview store={detailStore} />
							</div>
						{/if}
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>
