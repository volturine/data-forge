<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { listIcebergSnapshots } from '$lib/api/datasource';
	import { apiRequest } from '$lib/api/client';
	import { Trash2, ChevronDown, Clock } from '@lucide/svelte';
	import { SvelteMap } from 'svelte/reactivity';
	import { formatDateInput, formatDateTimeDisplay, formatTimeDisplay } from '$lib/utils/datetime';
	import { monthMeta, shiftMonthKey } from '$lib/utils/temporal';
	import { css, spinner } from '$lib/styles/panda';
	import { overlayStack } from '$lib/stores/overlay.svelte';
	import type { OverlayConfig } from '$lib/stores/overlay.svelte';

	interface Props {
		datasourceId: string;
		datasourceConfig: Record<string, unknown>;
		branch?: string | null;
		label?: string;
		persistOpen?: boolean;
		disabled?: boolean;
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
		disabled = false,
		onConfigChange,
		onUiChange,
		onSelect,
		showDelete = false,
		showBuildPreviews = false,
		branch = null
	}: Props = $props();

	const initialUi = untrack(
		() => (datasourceConfig.time_travel_ui as Record<string, unknown> | undefined) ?? {}
	);
	const startOpen = untrack(() =>
		persistOpen
			? Boolean(initialUi.open)
			: initialUi.open !== undefined
				? Boolean(initialUi.open)
				: false
	);
	let snapshotsOpen = $state(startOpen);
	let triggerRef = $state<HTMLButtonElement>();
	let popoverRef = $state<HTMLDivElement>();
	let popoverRect = $state({ left: 0, top: 0, width: 320 });
	let snapshotsLoading = $state(false);
	let snapshotsError = $state<string | null>(null);
	let snapshotsLoaded = $state(false);
	let snapshotMonth = $state(typeof initialUi.month === 'string' ? initialUi.month : '');
	let selectedDay = $state(typeof initialUi.day === 'string' ? initialUi.day : '');
	let snapshotList = $state<
		Array<{ id: string; timestamp: number; operation?: string | null; is_current?: boolean }>
	>([]);
	const timeTravelId = $derived(
		(datasourceConfig.time_travel_snapshot_id as string | null | undefined) ?? null
	);
	const timeTravelTs = $derived(
		datasourceConfig.time_travel_snapshot_timestamp_ms as number | null | undefined
	);
	const timeTravelLabel = $derived(
		timeTravelId && timeTravelTs ? formatSnapshotLabel(timeTravelTs) : null
	);
	let deleteConfirmId = $state<string | null>(null);
	let deleteLoading = $state(false);
	let deleteError = $state<string | null>(null);
	const filteredSnapshotList = $derived(snapshotList);
	const calendarDays = $derived.by(() => computeCalendarDays(snapshotMonth, filteredSnapshotList));
	const effectiveSelectedDay = $derived.by(() => {
		if (!selectedDay) return '';
		if (filteredSnapshotList.some((snap) => formatSnapshotKey(snap.timestamp) === selectedDay)) {
			return selectedDay;
		}
		return '';
	});
	const filteredSnapshots = $derived(
		effectiveSelectedDay
			? filteredSnapshotList.filter(
					(snap) => formatSnapshotKey(snap.timestamp) === effectiveSelectedDay
				)
			: []
	);
	const missingSnapshotId = $derived(
		timeTravelId && snapshotsLoaded && !snapshotList.some((snap) => snap.id === timeTravelId)
			? timeTravelId
			: null
	);

	const currentSnapshot = $derived(snapshotList.find((snap) => snap.is_current) ?? null);
	const isLatest = $derived.by(() => {
		if (!timeTravelId) return true;
		if (snapshotList.length === 0) return true;
		if (currentSnapshot && timeTravelId === currentSnapshot.id) return true;
		return false;
	});

	const overlayConfig = $derived<OverlayConfig>({
		onEscape: closeSnapshots,
		onOutsideClick: (target: Node) => {
			if (popoverRef?.contains(target)) return;
			if (triggerRef?.contains(target)) return;
			closeSnapshots();
		}
	});

	function formatSnapshotKey(timestampMs: number) {
		return formatDateInput(timestampMs);
	}

	function formatSnapshotLabel(timestampMs: number) {
		return formatDateTimeDisplay(timestampMs);
	}

	function formatSnapshotTime(timestampMs: number) {
		return formatTimeDisplay(timestampMs, {
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
		snapshotsLoaded = true;
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

	function computeCalendarDays(
		monthKey: string,
		snapshots: Array<{ timestamp: number }>
	): Array<{ key: string; day: number; count: number; inMonth: boolean }> {
		const meta = monthMeta(monthKey);
		if (!meta) return [];
		const days: Array<{ key: string; day: number; count: number; inMonth: boolean }> = [];

		for (let i = 0; i < meta.offset; i += 1) {
			days.push({ key: `blank-${monthKey}-${i}`, day: 0, count: 0, inMonth: false });
		}

		const counts = new SvelteMap<string, number>();
		for (const snap of snapshots) {
			const key = formatSnapshotKey(snap.timestamp);
			counts.set(key, (counts.get(key) ?? 0) + 1);
		}
		for (let day = 1; day <= meta.daysInMonth; day += 1) {
			const key = `${monthKey}-${String(day).padStart(2, '0')}`;
			const count = counts.get(key) ?? 0;
			days.push({ key, day, count, inMonth: true });
		}

		return days;
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
	}

	function loadSnapshots() {
		if (!datasourceId) return;
		snapshotsLoading = true;
		snapshotsError = null;
		snapshotsLoaded = false;
		snapshotList = [];
		getIcebergSnapshots(datasourceId).match(
			(result) => {
				buildSnapshotIndex(result.snapshots);
				snapshotsLoading = false;
			},
			(error) => {
				snapshotsError = error.message || 'Failed to load snapshots';
				snapshotsLoading = false;
				snapshotsLoaded = true;
				snapshotList = [];
			}
		);
	}

	onMount(() => {
		if (snapshotsOpen) loadSnapshots();
	});

	function getIcebergSnapshots(nextId: string) {
		const branchValue = branch ?? (datasourceConfig.branch as string | null | undefined) ?? null;
		return listIcebergSnapshots(nextId, {
			branch: branchValue,
			buildResultsOnly: showBuildPreviews
		});
	}

	function setSnapshot(snapshotId: string | null, timestampMs?: number) {
		const nextConfig = { ...datasourceConfig };
		if (snapshotId === null) {
			delete nextConfig.time_travel_snapshot_id;
			delete nextConfig.time_travel_snapshot_timestamp_ms;
		} else {
			nextConfig.time_travel_snapshot_id = snapshotId;
			if (timestampMs != null) {
				nextConfig.time_travel_snapshot_timestamp_ms = timestampMs;
			}
		}
		onConfigChange?.(nextConfig);
		onSelect?.(snapshotId, timestampMs);
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
		if (disabled) return;
		const next = !snapshotsOpen;
		snapshotsOpen = next;
		if (persistOpen) {
			updateUi({ open: next });
		}
		if (!next) return;
		updatePopoverPosition();
		if (!snapshotsLoading) {
			loadSnapshots();
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

	function shiftMonth(delta: number) {
		if (!snapshotMonth) return;
		selectMonth(shiftMonthKey(snapshotMonth, delta));
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
				if (persistOpen) {
					updateUi({ open: true });
				}
				loadSnapshots();
				if (timeTravelId === snapshotId) {
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
		class={[
			'engine-header',
			css({
				display: 'flex',
				width: '100%',
				cursor: disabled ? 'default' : 'pointer',
				alignItems: 'center',
				justifyContent: 'space-between',
				borderWidth: '1',
				backgroundColor: 'bg.secondary',
				padding: '2',
				paddingX: '3',
				_hover: disabled ? {} : { backgroundColor: 'bg.tertiary' },
				_disabled: { opacity: '0.7', cursor: 'default' }
			})
		]}
		onclick={toggleSnapshots}
		{disabled}
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
		<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
			{#if isLatest}
				<span
					class={css({
						borderWidth: '1',
						borderColor: 'border.accent',
						backgroundColor: 'bg.accent',
						paddingX: '1.5',
						paddingY: '0.5',
						fontSize: '2xs',
						textTransform: 'uppercase',
						color: 'accent.primary'
					})}
				>
					Latest
				</span>
			{:else}
				<span
					class={css({
						borderWidth: '1',
						backgroundColor: 'bg.tertiary',
						paddingX: '1.5',
						paddingY: '0.5',
						fontSize: '2xs',
						textTransform: 'uppercase',
						color: 'fg.muted',
						maxWidth: '120px',
						overflow: 'hidden',
						textOverflow: 'ellipsis',
						whiteSpace: 'nowrap'
					})}
					title={timeTravelId}
				>
					{timeTravelId}
				</span>
			{/if}
			<span
				class={css(
					{ color: 'fg.muted' },
					{ display: 'flex', alignItems: 'center' },
					snapshotsOpen && { transform: 'rotate(180deg)' }
				)}
			>
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
			use:overlayStack.action={overlayConfig}
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
					{#if isLatest}
						Selected: Latest{#if currentSnapshot}
							· #{currentSnapshot.id}{/if}
					{:else}
						Selected: #{timeTravelId}
						{#if timeTravelLabel}
							· {timeTravelLabel}
						{/if}
					{/if}
				</div>
				{#if !isLatest}
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
						borderColor: 'border.warning',
						backgroundColor: 'bg.warning',
						paddingX: '2',
						paddingY: '1',
						fontSize: '2xs',
						color: 'fg.warning'
					})}
				>
					Selected snapshot #{missingSnapshotId} no longer exists.
					<button
						class={css({
							marginLeft: '2',
							borderWidth: '1',
							borderColor: 'border.warning',
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
				<div class={css({ fontSize: 'xs', color: 'fg.error' })}>{deleteError}</div>
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
				<div class={css({ fontSize: 'xs', color: 'fg.error' })}>{snapshotsError}</div>
			{:else if filteredSnapshotList.length === 0}
				<div class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>No snapshots found.</div>
			{:else}
				<div class={css({ display: 'flex', gap: '2' })}>
					<div class={css({ display: 'flex', flex: '1', flexDirection: 'column', gap: '2' })}>
						<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
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
										class={css(
											{
												position: 'relative',
												height: 'rowXl',
												borderWidth: '1',
												backgroundColor: 'transparent',
												fontSize: 'xs'
											},
											day.count > 0
												? {
														backgroundColor: 'bg.muted',
														_hover: { backgroundColor: 'bg.hover' }
													}
												: { cursor: 'default', opacity: '0.4' },
											effectiveSelectedDay === day.key && { backgroundColor: 'bg.tertiary' }
										)}
										onclick={() => day.count > 0 && selectDay(day.key)}
										type="button"
									>
										<span
											class={day.count > 0
												? css({ color: 'fg.secondary' })
												: css({ color: 'fg.tertiary' })}>{day.day}</span
										>
										{#if day.count > 0}
											<span
												class={css({
													position: 'absolute',
													right: '1',
													top: '1',
													backgroundColor: 'bg.accent',
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
						{#if effectiveSelectedDay}
							{#each filteredSnapshots as snap (snap.id)}
								<div
									class={css(
										{
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
										},
										(timeTravelId === snap.id || (!timeTravelId && snap.is_current)) && {
											backgroundColor: 'bg.tertiary'
										}
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
											class={css(
												{ fontFamily: 'mono' },
												timeTravelId === snap.id
													? { color: 'fg.primary' }
													: { color: 'fg.secondary' }
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
													_hover: { color: 'fg.error' }
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
