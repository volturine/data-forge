<script lang="ts">
	import { apiRequest } from '$lib/api/client';
	import { listEngineRuns, type EngineRun } from '$lib/api/engine-runs';
	import { buildSnapshotMap } from '$lib/utils/build-snapshot-map';
	import { Trash2, ChevronDown, Clock } from 'lucide-svelte';
	import { SvelteMap } from 'svelte/reactivity';

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
	const runSnapshotMap = $derived.by(() =>
		buildSnapshotMap(buildRuns, toSnapshotRefs(snapshotList))
	);
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
		class="engine-header flex w-full cursor-pointer items-center justify-between border border-tertiary bg-secondary p-2 px-3 hover:bg-tertiary"
		onclick={toggleSnapshots}
		type="button"
		bind:this={triggerRef}
	>
		<div class="flex items-center gap-2 text-xs uppercase tracking-wide text-fg-muted">
			<Clock size={12} />
			<span>{label}</span>
		</div>
		<div class="flex items-center gap-2">
			{#if selectedSnapshotId}
				<span
					class="border border-tertiary bg-tertiary px-1.5 py-0.5 text-[10px] uppercase text-fg-muted"
				>
					{selectedSnapshotId}
				</span>
			{:else}
				<span
					class="border border-accent-primary bg-accent-bg px-1.5 py-0.5 text-[10px] uppercase text-accent-primary"
				>
					Latest
				</span>
			{/if}
			<span class="chevron flex items-center text-fg-muted" class:expanded={snapshotsOpen}>
				<ChevronDown size={12} />
			</span>
		</div>
	</button>

	{#if snapshotsOpen}
		<div
			class="snapshot-picker__popover fixed z-overlay border border-tertiary bg-primary p-2 shadow flex flex-col gap-2"
			bind:this={popoverRef}
			use:portal={popoverRect}
		>
			<div class="flex items-center justify-between border border-tertiary bg-secondary px-2 py-1">
				<div class="text-xs text-fg-muted text-left">
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
						class="border border-tertiary bg-primary px-2 py-1 text-[10px] uppercase text-fg-secondary"
						onclick={() => setSnapshot(null)}
						type="button"
					>
						Latest
					</button>
				{/if}
			</div>
			{#if missingSnapshotId}
				<div class="border border-warning bg-warning-bg px-2 py-1 text-[10px] text-warning-fg">
					Selected snapshot #{missingSnapshotId} no longer exists.
					<button
						class="ml-2 border border-warning px-1.5 py-0.5"
						onclick={() => setSnapshot(null)}
						type="button"
					>
						Switch to latest
					</button>
				</div>
			{/if}

			{#if deleteError}
				<div class="text-xs text-error-fg">{deleteError}</div>
			{/if}

			{#if snapshotsLoading}
				<div class="flex items-center gap-2 text-xs text-fg-tertiary">
					<div class="spinner-sm"></div>
					Loading snapshots...
				</div>
			{:else if snapshotsError}
				<div class="text-xs text-error-fg">{snapshotsError}</div>
			{:else if snapshotList.length === 0}
				<div class="text-xs text-fg-tertiary">No snapshots found.</div>
			{:else}
				<div class="flex gap-2">
					<div class="flex flex-1 flex-col gap-2">
						<div class="flex items-center gap-2">
							<button
								class="border border-tertiary bg-secondary px-2 py-1 text-xs"
								onclick={() => shiftMonth(-1)}
								type="button"
							>
								←
							</button>
							<span class="text-xs font-mono text-fg-secondary">{snapshotMonth}</span>
							<button
								class="border border-tertiary bg-secondary px-2 py-1 text-xs"
								onclick={() => shiftMonth(1)}
								type="button"
							>
								→
							</button>
						</div>

						<div class="grid grid-cols-7 gap-1 border border-tertiary p-2">
							{#each ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'] as day (day)}
								<div class="text-[10px] text-fg-tertiary text-center">{day}</div>
							{/each}
							{#each calendarDays as day (day.key)}
								{#if day.inMonth}
									<button
										class="relative h-9 border border-tertiary text-xs hover:bg-tertiary"
										class:bg-tertiary={selectedDay === day.key}
										onclick={() => selectDay(day.key)}
										type="button"
									>
										<span>{day.day}</span>
										{#if day.count > 0}
											<span
												class="absolute right-1 top-1 bg-accent-bg px-1 text-[9px] text-accent-primary"
											>
												{day.count}
											</span>
										{/if}
									</button>
								{:else}
									<div class="h-9"></div>
								{/if}
							{/each}
						</div>
					</div>
					<div class="w-50 max-h-56 overflow-y-auto overflow-x-hidden border border-tertiary">
						{#if selectedDay}
							{#each filteredSnapshots as snap (snap.id)}
								<div
									class="flex w-full items-center justify-between gap-2 px-2 py-1 text-left text-xs hover:bg-tertiary"
									class:bg-tertiary={selectedSnapshotId === snap.id ||
										(!selectedSnapshotId && snap.is_current)}
								>
									<button
										class="flex flex-1 items-center justify-start gap-2 bg-transparent p-0 text-left"
										onclick={() => setSnapshot(snap.id, snap.timestamp)}
										type="button"
									>
										<span
											class="font-mono"
											class:text-fg-secondary={selectedSnapshotId !== snap.id}
											class:text-fg-primary={selectedSnapshotId === snap.id}
										>
											{formatSnapshotTime(snap.timestamp)}
										</span>
									</button>
									{#if showDelete && !snap.is_current}
										{#if deleteConfirmId === snap.id}
											<button
												class="border border-tertiary px-1.5 py-0.5 text-[10px] uppercase text-fg-secondary"
												onclick={() => deleteSnapshot(snap.id)}
												disabled={deleteLoading}
												type="button"
											>
												{#if deleteLoading}...
												{:else}Confirm{/if}
											</button>
											<button
												class="ml-1 border border-tertiary px-1.5 py-0.5 text-[10px] uppercase text-fg-secondary"
												onclick={() => (deleteConfirmId = null)}
												type="button"
											>
												Cancel
											</button>
										{:else}
											<button
												class="border border-tertiary p-1 text-fg-tertiary hover:text-error-fg"
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
							<div class="p-2 text-xs text-fg-tertiary">Select a day to view builds.</div>
						{/if}
					</div>
				</div>
			{/if}
		</div>
	{/if}
</div>
