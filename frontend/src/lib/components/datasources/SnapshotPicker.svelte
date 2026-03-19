<script lang="ts">
	import { apiRequest } from '$lib/api/client';
	import { listEngineRuns, type EngineRun } from '$lib/api/engine-runs';
	import { buildSnapshotMap } from '$lib/utils/build-snapshot-map';
	import { Trash2, ChevronDown, Clock } from 'lucide-svelte';
	import { SvelteMap } from 'svelte/reactivity';
	import { css, cx, spinner, row, muted } from '$lib/styles/panda';

	interface Props {
		datasourceId: string;
		datasourceConfig: Record<string, unknown>;
		branch?: string | null;
		label?: string;
		persistOpen?: boolean;
		onConfigChange?: (config: Record<string, unknown>) => void;
		onUiChange?: (updates: { open?: boolean; month?: string; day?: string }) => void;
		onSelect?: (snapshotId: string | null, timestampMs?: number) => void;
		showDelete?: boolean;
		showBuildPreviews?: boolean;
	}

	let {
		datasourceId,
		datasourceConfig,
		label = 'Time Travel',
		persistOpen = false,
		onConfigChange,
		onUiChange,
		onSelect,
		showDelete = false,
		showBuildPreviews = false,
		branch = null
	}: Props = $props();

	let snapshotsOpen = $state(false);
	let hasOpened = $state(false);
	let triggerRef = $state<HTMLButtonElement>();
	let popoverRef = $state<HTMLDivElement>();
	let popoverRect = $state({ left: 0, top: 0, width: 320 });
	let snapshotsLoading = $state(false);
	let snapshotsError = $state<string | null>(null);
	let snapshotMonth = $state('');
	let selectedDay = $state('');
	let snapshotList = $state<
		Array<{ id: string; timestamp: number; operation?: string | null; is_current?: boolean }>
	>([]);
	let selectedSnapshotId = $state<string | null>(null);
	let selectedSnapshotLabel = $state<string | null>(null);
	let missingSnapshotId = $state<string | null>(null);
	let calendarDays = $state<Array<{ key: string; day: number; count: number; inMonth: boolean }>>(
		[]
	);
	let deleteConfirmId = $state<string | null>(null);
	let deleteLoading = $state(false);
	let deleteError = $state<string | null>(null);
	let buildRuns = $state<EngineRun[]>([]);
	const runSnapshotMap = $derived(buildSnapshotMap(buildRuns, toSnapshotRefs(snapshotList)));
	const filteredSnapshotList = $derived.by(() => {
		if (!showBuildPreviews) return snapshotList;
		const mapped = new SvelteMap<string, boolean>();
		for (const snap of runSnapshotMap.values()) {
			if (!snap) continue;
			mapped.set(snap, true);
		}
		return snapshotList.filter((snap) => mapped.has(snap.id));
	});
	const filteredSnapshots = $derived(
		selectedDay
			? filteredSnapshotList.filter((snap) => formatSnapshotKey(snap.timestamp) === selectedDay)
			: []
	);

	// Subscription: $derived can't sync state from config.
	$effect(() => {
		const ui = (datasourceConfig.time_travel_ui as Record<string, unknown>) ?? {};
		if (persistOpen && !hasOpened) {
			snapshotsOpen = (ui.open as boolean | undefined) ?? false;
			if (snapshotsOpen) hasOpened = true;
		}
		if (!persistOpen && ui.open !== undefined) {
			snapshotsOpen = Boolean(ui.open);
		}
		const nextMonth = ui.month as string | undefined;
		if (nextMonth !== undefined) snapshotMonth = nextMonth;
		const nextDay = ui.day as string | undefined;
		if (nextDay !== undefined) selectedDay = nextDay;
		const configSnapshot = datasourceConfig.snapshot_id as string | null | undefined;
		if (configSnapshot !== undefined) {
			selectedSnapshotId = configSnapshot ?? null;
		}
		const ts = datasourceConfig.snapshot_timestamp_ms as number | null;
		if (selectedSnapshotId && ts) {
			selectedSnapshotLabel = formatSnapshotLabel(ts);
		} else {
			selectedSnapshotLabel = null;
		}
		missingSnapshotId = selectedSnapshotId;
		if (snapshotsOpen && snapshotMonth) {
			buildCalendar(snapshotMonth);
		}
	});

	let lastDatasourceId = $state<string | null>(null);
	// Subscription: $derived can't reset snapshot state.
	$effect(() => {
		if (datasourceId === lastDatasourceId) return;
		lastDatasourceId = datasourceId;
		snapshotList = [];
		snapshotsError = null;
		snapshotsLoading = false;
		calendarDays = [];
		selectedDay = '';
		selectedSnapshotId = null;
		selectedSnapshotLabel = null;
		snapshotMonth = '';
		snapshotsOpen = false;
		hasOpened = false;
		deleteConfirmId = null;
		deleteLoading = false;
		deleteError = null;
		buildRuns = [];
	});

	function formatSnapshotKey(timestampMs: number) {
		const date = new Date(timestampMs);
		return date.toISOString().slice(0, 10);
	}

	function formatSnapshotLabel(timestampMs: number) {
		return new Date(timestampMs).toLocaleString();
	}

	function formatSnapshotTime(timestampMs: number) {
		return new Date(timestampMs).toLocaleTimeString([], {
			hour: '2-digit',
			minute: '2-digit',
			second: '2-digit'
		});
	}

	function buildSnapshotIndex(
		items: Array<{
			snapshot_id: string;
			timestamp_ms: number;
			operation?: string | null;
			is_current?: boolean | null;
		}>
	) {
		const list = items
			.map((snap) => ({
				id: snap.snapshot_id,
				timestamp: snap.timestamp_ms,
				operation: snap.operation,
				is_current: snap.is_current ?? false
			}))
			.sort((a, b) => b.timestamp - a.timestamp);
		snapshotList = list;
		if (selectedSnapshotId && list.some((snap) => snap.id === selectedSnapshotId)) {
			missingSnapshotId = null;
		}
		const monthSource = showBuildPreviews ? filteredSnapshotList : list;
		const monthOptions = Array.from(
			new Set(monthSource.map((snap) => formatSnapshotKey(snap.timestamp).slice(0, 7)))
		).sort((a, b) => (a > b ? -1 : 1));
		const persistedMonth = (datasourceConfig.time_travel_ui as Record<string, unknown>)?.month as
			| string
			| undefined;
		if (persistedMonth && monthOptions.includes(persistedMonth)) {
			selectMonth(persistedMonth);
			return;
		}
		if (!snapshotMonth && monthOptions.length) {
			selectMonth(monthOptions[0]);
		}
	}

	function buildCalendar(monthKey: string) {
		if (!monthKey) {
			calendarDays = [];
			return;
		}
		const [yearStr, monthStr] = monthKey.split('-');
		const year = Number(yearStr);
		const month = Number(monthStr) - 1;
		const first = new Date(year, month, 1);
		const startDay = (first.getDay() + 6) % 7;
		const daysInMonth = new Date(year, month + 1, 0).getDate();
		const days: Array<{ key: string; day: number; count: number; inMonth: boolean }> = [];

		for (let i = 0; i < startDay; i += 1) {
			days.push({ key: `blank-${monthKey}-${i}`, day: 0, count: 0, inMonth: false });
		}

		const counts = new SvelteMap<string, number>();
		for (const snap of filteredSnapshotList) {
			const key = formatSnapshotKey(snap.timestamp);
			counts.set(key, (counts.get(key) ?? 0) + 1);
		}
		for (let day = 1; day <= daysInMonth; day += 1) {
			const key = `${monthKey}-${String(day).padStart(2, '0')}`;
			const count = counts.get(key) ?? 0;
			days.push({ key, day, count, inMonth: true });
		}

		calendarDays = days;
	}

	function updateUi(updates: { open?: boolean; month?: string; day?: string }) {
		onUiChange?.(updates);
	}

	function selectDay(dayKey: string) {
		selectedDay = dayKey;
		updateUi({ day: dayKey });
	}

	function selectMonth(monthKey: string) {
		snapshotMonth = monthKey;
		selectedDay = '';
		updateUi({ month: monthKey, day: '' });
		buildCalendar(monthKey);
	}

	// Subscription: $derived can't clear day selection.
	$effect(() => {
		if (!snapshotsOpen) return;
		if (!filteredSnapshotList.length) return;
		if (!selectedDay) return;
		const hasMatch = filteredSnapshotList.some(
			(snap) => formatSnapshotKey(snap.timestamp) === selectedDay
		);
		if (hasMatch) return;
		selectedDay = '';
		updateUi({ day: '' });
	});

	// Subscription: $derived can't rebuild calendar.
	$effect(() => {
		if (!snapshotsOpen) return;
		if (!snapshotMonth) return;
		buildCalendar(snapshotMonth);
	});

	// Subscription: $derived can't select month on open.
	$effect(() => {
		if (!snapshotsOpen) return;
		const source = showBuildPreviews ? filteredSnapshotList : snapshotList;
		if (!source.length) {
			calendarDays = [];
			return;
		}
		const monthOptions = Array.from(
			new Set(source.map((snap) => formatSnapshotKey(snap.timestamp).slice(0, 7)))
		).sort((a, b) => (a > b ? -1 : 1));
		if (!monthOptions.length) return;
		if (snapshotMonth && monthOptions.includes(snapshotMonth)) return;
		selectMonth(monthOptions[0]);
	});

	function loadSnapshots() {
		if (!datasourceId) return;
		snapshotsLoading = true;
		snapshotsError = null;
		snapshotList = [];
		getIcebergSnapshots(datasourceId).match(
			(result) => {
				buildSnapshotIndex(result.snapshots);
				snapshotsLoading = false;
			},
			(error) => {
				snapshotsError = error.message || 'Failed to load snapshots';
				snapshotsLoading = false;
				snapshotList = [];
			}
		);
		if (showBuildPreviews) {
			loadBuildRuns();
		}
	}

	function loadBuildRuns() {
		if (!datasourceId) return;
		listEngineRuns({ datasource_id: datasourceId, limit: 50 }).match(
			(result) => {
				const branchValue =
					branch ?? (datasourceConfig.branch as string | null | undefined) ?? null;
				buildRuns = result.filter((run) => {
					if (!(run.kind === 'datasource_update' || run.kind === 'datasource_create')) return false;
					if (run.status !== 'success') return false;
					if (!branchValue) return true;
					const payload = run.request_json as Record<string, unknown>;
					const opts = payload.iceberg_options as Record<string, unknown> | undefined;
					const runBranch = opts?.branch as string | undefined;
					return runBranch === branchValue;
				});
			},
			() => {
				buildRuns = [];
			}
		);
	}

	function getIcebergSnapshots(nextId: string) {
		const branchValue = branch ?? (datasourceConfig.branch as string | null | undefined) ?? null;
		const suffix = branchValue ? `?branch=${encodeURIComponent(branchValue)}` : '';
		return apiRequest<{
			snapshots: Array<{
				snapshot_id: string;
				timestamp_ms: number;
				operation?: string | null;
				is_current?: boolean | null;
			}>;
		}>(`/v1/compute/iceberg/${nextId}/snapshots${suffix}`);
	}

	function setSnapshot(snapshotId: string | null, timestampMs?: number) {
		selectedSnapshotId = snapshotId;
		const nextConfig = { ...datasourceConfig };
		if (snapshotId === null) {
			delete nextConfig.snapshot_id;
			delete nextConfig.snapshot_timestamp_ms;
			selectedSnapshotLabel = null;
			missingSnapshotId = null;
		} else {
			nextConfig.snapshot_id = snapshotId;
			if (timestampMs) {
				nextConfig.snapshot_timestamp_ms = timestampMs;
				selectedSnapshotLabel = formatSnapshotLabel(timestampMs);
			}
			missingSnapshotId = null;
		}
		onConfigChange?.(nextConfig);
		onSelect?.(snapshotId, timestampMs);
	}

	function toSnapshotRefs(list: Array<{ id: string; timestamp: number }>) {
		return list.map((snap) => ({ snapshot_id: snap.id, timestamp_ms: snap.timestamp }));
	}

	function updatePopoverPosition() {
		const trigger = triggerRef;
		if (!trigger) return;
		const rect = trigger.getBoundingClientRect();
		const width = rect.width;
		let left = rect.left;
		const maxLeft = window.innerWidth - width - 8;
		if (left > maxLeft) left = Math.max(8, maxLeft);
		popoverRect = {
			left,
			top: rect.bottom + 8,
			width
		};
	}

	function applyPopoverPosition(
		node: HTMLElement | undefined,
		rect: { left: number; top: number; width: number }
	) {
		if (!node) return;
		node.style.setProperty('--popover-left', `${rect.left}px`);
		node.style.setProperty('--popover-top', `${rect.top}px`);
		node.style.setProperty('--popover-width', `${rect.width}px`);
	}

	function closeSnapshots() {
		if (!snapshotsOpen) return;
		snapshotsOpen = false;
		if (persistOpen) {
			updateUi({ open: false });
		}
	}

	function toggleSnapshots() {
		const next = !snapshotsOpen;
		snapshotsOpen = next;
		hasOpened = true;
		if (persistOpen) {
			updateUi({ open: next });
		}
		if (!next) return;
		updatePopoverPosition();
		if (!snapshotsLoading) {
			loadSnapshots();
		}
		if (snapshotMonth) {
			buildCalendar(snapshotMonth);
		}
		if (showBuildPreviews && !buildRuns.length) {
			loadBuildRuns();
		}
	}

	function portal(node: HTMLElement, rect: { left: number; top: number; width: number }) {
		document.body.appendChild(node);
		applyPopoverPosition(node, rect);
		return {
			update(next: { left: number; top: number; width: number }) {
				applyPopoverPosition(node, next);
			},
			destroy() {
				node.remove();
			}
		};
	}

	// DOM: $derived can't handle outside click.
	$effect(() => {
		if (!snapshotsOpen) return;
		const handleOutside = (event: MouseEvent) => {
			const target = event.target as Node | null;
			if (!target) return;
			if (popoverRef?.contains(target)) return;
			if (triggerRef?.contains(target)) return;
			closeSnapshots();
		};
		window.addEventListener('mousedown', handleOutside, true);
		return () => window.removeEventListener('mousedown', handleOutside, true);
	});

	function shiftMonth(delta: number) {
		const [yearStr, monthStr] = snapshotMonth.split('-');
		const year = Number(yearStr);
		const month = Number(monthStr) - 1 + delta;
		const next = new Date(year, month, 1);
		const nextKey = `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}`;
		selectMonth(nextKey);
	}

	function deleteSnapshot(snapshotId: string) {
		if (!showDelete) return;
		deleteLoading = true;
		deleteError = null;
		apiRequest<void>(`/v1/compute/iceberg/${datasourceId}/snapshots/${snapshotId}`, {
			method: 'DELETE'
		}).match(
			() => {
				deleteConfirmId = null;
				deleteLoading = false;
				snapshotsOpen = true;
				hasOpened = true;
				if (persistOpen) {
					updateUi({ open: true });
				}
				loadSnapshots();
				if (selectedSnapshotId === snapshotId) {
					setSnapshot(null);
				}
			},
			(err) => {
				deleteError = err.message || 'Failed to delete snapshot';
				deleteLoading = false;
			}
		);
	}
</script>

<div>
	<button
		class={cx(
			'engine-header',
			css({
				display: 'flex',
				width: '100%',
				cursor: 'pointer',
				alignItems: 'center',
				justifyContent: 'space-between',
				borderWidth: '1',
				backgroundColor: 'bg.secondary',
				padding: '2',
				paddingX: '3',
				_hover: { backgroundColor: 'bg.tertiary' }
			})
		)}
		onclick={toggleSnapshots}
		type="button"
		bind:this={triggerRef}
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
			<Clock size={12} />
			<span>{label}</span>
		</div>
		<div class={cx(row, css({ gap: '2' }))}>
			{#if selectedSnapshotId}
				<span
					class={css({
						borderWidth: '1',
						backgroundColor: 'bg.tertiary',
						paddingX: '1.5',
						paddingY: '0.5',
						fontSize: '2xs',
						textTransform: 'uppercase',
						color: 'fg.muted'
					})}
				>
					{selectedSnapshotId}
				</span>
			{:else}
				<span
					class={css({
						borderWidth: '1',
						borderColor: 'accent.primary',
						backgroundColor: 'accent.bg',
						paddingX: '1.5',
						paddingY: '0.5',
						fontSize: '2xs',
						textTransform: 'uppercase',
						color: 'accent.primary'
					})}
				>
					Latest
				</span>
			{/if}
			<span class={cx(muted, row, snapshotsOpen && css({ transform: 'rotate(180deg)' }))}>
				<ChevronDown size={12} />
			</span>
		</div>
	</button>

	{#if snapshotsOpen}
		<div
			class={css({
				left: 'var(--popover-left)',
				top: 'var(--popover-top)',
				width: 'var(--popover-width)',
				position: 'fixed',
				zIndex: 'overlay',
				borderWidth: '1',
				backgroundColor: 'bg.primary',
				padding: '2',
				boxShadow: 'sm',
				display: 'flex',
				flexDirection: 'column',
				gap: '2'
			})}
			bind:this={popoverRef}
			use:portal={popoverRect}
		>
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'space-between',
					borderWidth: '1',
					backgroundColor: 'bg.secondary',
					paddingX: '2',
					paddingY: '1'
				})}
			>
				<div class={css({ fontSize: 'xs', color: 'fg.muted', textAlign: 'left' })}>
					{#if selectedSnapshotId}
						Current: #{selectedSnapshotId}
						{#if selectedSnapshotLabel}
							· {selectedSnapshotLabel}
						{/if}
					{:else}
						Current: Latest
					{/if}
				</div>
				{#if selectedSnapshotId}
					<button
						class={css({
							borderWidth: '1',
							backgroundColor: 'bg.primary',
							paddingX: '2',
							paddingY: '1',
							fontSize: '2xs',
							textTransform: 'uppercase',
							color: 'fg.secondary'
						})}
						onclick={() => setSnapshot(null)}
						type="button"
					>
						Latest
					</button>
				{/if}
			</div>
			{#if missingSnapshotId}
				<div
					class={css({
						borderWidth: '1',
						borderColor: 'warning.border',
						backgroundColor: 'warning.bg',
						paddingX: '2',
						paddingY: '1',
						fontSize: '2xs',
						color: 'warning.fg'
					})}
				>
					Selected snapshot #{missingSnapshotId} no longer exists.
					<button
						class={css({
							marginLeft: '2',
							borderWidth: '1',
							borderColor: 'warning.border',
							backgroundColor: 'bg.primary',
							paddingX: '1.5',
							paddingY: '0.5'
						})}
						onclick={() => setSnapshot(null)}
						type="button"
					>
						Switch to latest
					</button>
				</div>
			{/if}

			{#if deleteError}
				<div class={css({ fontSize: 'xs', color: 'error.fg' })}>{deleteError}</div>
			{/if}

			{#if snapshotsLoading}
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						gap: '2',
						fontSize: 'xs',
						color: 'fg.tertiary'
					})}
				>
					<div class={spinner({ size: 'sm' })}></div>
					Loading snapshots...
				</div>
			{:else if snapshotsError}
				<div class={css({ fontSize: 'xs', color: 'error.fg' })}>{snapshotsError}</div>
			{:else if snapshotList.length === 0}
				<div class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>No snapshots found.</div>
			{:else}
				<div class={css({ display: 'flex', gap: '2' })}>
					<div class={css({ display: 'flex', flex: '1', flexDirection: 'column', gap: '2' })}>
						<div class={cx(row, css({ gap: '2' }))}>
							<button
								class={css({
									borderWidth: '1',
									backgroundColor: 'bg.secondary',
									paddingX: '2',
									paddingY: '1',
									fontSize: 'xs'
								})}
								onclick={() => shiftMonth(-1)}
								type="button"
							>
								←
							</button>
							<span
								class={css({
									fontSize: 'xs',
									fontFamily: 'mono',
									color: 'fg.secondary'
								})}>{snapshotMonth}</span
							>
							<button
								class={css({
									borderWidth: '1',
									backgroundColor: 'bg.secondary',
									paddingX: '2',
									paddingY: '1',
									fontSize: 'xs'
								})}
								onclick={() => shiftMonth(1)}
								type="button"
							>
								→
							</button>
						</div>

						<div
							class={css({
								display: 'grid',
								gridTemplateColumns: 'repeat(7, minmax(0, 1fr))',
								gap: '1',
								borderWidth: '1',
								padding: '2'
							})}
						>
							{#each ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'] as day (day)}
								<div class={css({ fontSize: '2xs', color: 'fg.tertiary', textAlign: 'center' })}>
									{day}
								</div>
							{/each}
							{#each calendarDays as day (day.key)}
								{#if day.inMonth}
									<button
										class={cx(
											css({
												position: 'relative',
												height: 'rowXl',
												borderWidth: '1',
												fontSize: 'xs',
												_hover: { backgroundColor: 'bg.tertiary' }
											}),
											selectedDay === day.key ? css({ backgroundColor: 'bg.tertiary' }) : ''
										)}
										onclick={() => selectDay(day.key)}
										type="button"
									>
										<span>{day.day}</span>
										{#if day.count > 0}
											<span
												class={css({
													position: 'absolute',
													right: '1',
													top: '1',
													backgroundColor: 'accent.bg',
													paddingX: '1',
													fontSize: '2xs',
													color: 'accent.primary'
												})}
											>
												{day.count}
											</span>
										{/if}
									</button>
								{:else}
									<div class={css({ height: 'rowXl' })}></div>
								{/if}
							{/each}
						</div>
					</div>
					<div
						class={css({
							width: 'listSm',
							maxHeight: 'previewMd',
							overflowY: 'auto',
							overflowX: 'hidden',
							borderWidth: '1'
						})}
					>
						{#if selectedDay}
							{#each filteredSnapshots as snap (snap.id)}
								<div
									class={cx(
										css({
											display: 'flex',
											width: '100%',
											alignItems: 'center',
											justifyContent: 'space-between',
											gap: '2',
											paddingX: '2',
											paddingY: '1',
											textAlign: 'left',
											fontSize: 'xs',
											_hover: { backgroundColor: 'bg.tertiary' }
										}),
										selectedSnapshotId === snap.id || (!selectedSnapshotId && snap.is_current)
											? css({ backgroundColor: 'bg.tertiary' })
											: ''
									)}
								>
									<button
										class={css({
											display: 'flex',
											flex: '1',
											alignItems: 'center',
											justifyContent: 'flex-start',
											gap: '2',
											backgroundColor: 'transparent',
											padding: '0',
											textAlign: 'left'
										})}
										onclick={() => setSnapshot(snap.id, snap.timestamp)}
										type="button"
									>
										<span
											class={cx(
												css({ fontFamily: 'mono' }),
												selectedSnapshotId === snap.id
													? css({ color: 'fg.primary' })
													: css({ color: 'fg.secondary' })
											)}
										>
											{formatSnapshotTime(snap.timestamp)}
										</span>
									</button>
									{#if showDelete && !snap.is_current}
										{#if deleteConfirmId === snap.id}
											<button
												class={css({
													borderWidth: '1',
													backgroundColor: 'bg.primary',
													paddingX: '1.5',
													paddingY: '0.5',
													fontSize: '2xs',
													textTransform: 'uppercase',
													color: 'fg.secondary'
												})}
												onclick={() => deleteSnapshot(snap.id)}
												disabled={deleteLoading}
												type="button"
											>
												{#if deleteLoading}...
												{:else}Confirm{/if}
											</button>
											<button
												class={css({
													marginLeft: '1',
													borderWidth: '1',
													backgroundColor: 'bg.primary',
													paddingX: '1.5',
													paddingY: '0.5',
													fontSize: '2xs',
													textTransform: 'uppercase',
													color: 'fg.secondary'
												})}
												onclick={() => (deleteConfirmId = null)}
												type="button"
											>
												Cancel
											</button>
										{:else}
											<button
												class={css({
													borderWidth: '1',
													backgroundColor: 'bg.primary',
													padding: '1',
													color: 'fg.tertiary',
													_hover: { color: 'error.fg' }
												})}
												onclick={() => (deleteConfirmId = snap.id)}
												type="button"
												aria-label="Delete snapshot"
											>
												<Trash2 size={12} />
											</button>
										{/if}
									{/if}
								</div>
							{/each}
						{:else}
							<div class={css({ padding: '2', fontSize: 'xs', color: 'fg.tertiary' })}>
								Select a day to view builds.
							</div>
						{/if}
					</div>
				</div>
			{/if}
		</div>
	{/if}
</div>
