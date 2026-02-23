<script lang="ts">
	import {
		createTable,
		getCoreRowModel,
		getSortedRowModel,
		type ColumnDef,
		type ColumnSizingInfoState,
		type ColumnSizingState,
		type ColumnPinningState,
		type SortingState,
		type HeaderGroup,
		type Row
	} from '@tanstack/table-core';
	import {
		Check,
		Copy,
		GripVertical,
		Pin,
		Settings2,
		LoaderCircle,
		Bug,
		Play
	} from 'lucide-svelte';
	import { onClickOutside } from 'runed';
	import { SvelteMap, SvelteSet } from 'svelte/reactivity';
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';
	import type { TableCellValue } from '$lib/types/api-responses';
	import { resolveColumnType } from '$lib/utils/columnTypes';
	import { formatDateTimeDisplay, formatDateDisplay } from '$lib/utils/datetime';

	interface Props {
		columns: string[];
		data: Record<string, unknown>[];
		columnTypes?: Record<string, string>;
		loading?: boolean;
		error?: Error | null;
		analysis?: boolean;
		fillContainer?: boolean;
		onSort?: (column: string, direction: 'asc' | 'desc') => void;
		showTypeBadges?: boolean;
		showFooter?: boolean;
		showHeader?: boolean;
		showPagination?: boolean;
		pagination?: {
			page: number;
			canPrev: boolean;
			canNext: boolean;
			onPrev: () => void;
			onNext: () => void;
			loading?: boolean;
		};
		onPreview?: () => void;
		onColumnStats?: (columnName: string) => void;
		density?: 'default' | 'compact';
		enableResize?: boolean;
		enableCopy?: boolean;
		columnSearch?: string;
	}

	type RowData = Record<string, unknown>;

	let {
		columns,
		data,
		columnTypes = {},
		loading = false,
		error = null,
		analysis = false,
		fillContainer = false,
		onSort,
		showTypeBadges = false,
		showFooter = true,
		showHeader = false,
		showPagination = false,
		pagination,
		onPreview,
		onColumnStats,
		density = 'default',
		enableResize = true,
		enableCopy = true,
		columnSearch = $bindable('')
	}: Props = $props();

	let sorting = $state<SortingState>([]);
	let columnSizing = $state<ColumnSizingState>({});
	let columnSizingInfo = $state<ColumnSizingInfoState>({
		columnSizingStart: [],
		deltaOffset: null,
		deltaPercentage: null,
		isResizingColumn: false,
		startOffset: null,
		startSize: null
	});

	// Non-reactive resize tracking to avoid table re-renders during resize
	let resizeOffset = { delta: 0, start: 0 };
	let columnVisibility = $state<Record<string, boolean>>({});
	let columnOrder = $state<string[]>([]);
	let columnPinning = $state<ColumnPinningState>({ left: [], right: [] });
	let columnMenuRef = $state<HTMLElement>();
	let activeColumn = $state<string | null>(null);
	let dragColumn = $state<string | null>(null);
	let dragOver = $state<string | null>(null);
	let dragPointerX = $state<number | null>(null);
	let dragPointerY = $state<number | null>(null);
	let dragLabel = $state<string | null>(null);
	let tipRef = $state<HTMLDivElement>();
	let scrollRef = $state<HTMLDivElement>();

	// Non-reactive copy state to avoid table re-renders
	let copiedCells = new SvelteSet<string>();
	let copyTimers = new SvelteMap<string, number>();

	// Non-reactive tooltip state to avoid table re-renders
	let tipState = {
		text: '',
		x: 0,
		y: 0,
		visible: false,
		timer: null as number | null,
		hoverId: ''
	};

	let lastTooltipUpdate = { text: '', x: 0, y: 0, visible: false };

	// DOM: $derived can't position tooltip via measurements.
	$effect(() => {
		if (!tipRef) return;
		if (
			tipState.text === lastTooltipUpdate.text &&
			tipState.x === lastTooltipUpdate.x &&
			tipState.y === lastTooltipUpdate.y &&
			tipState.visible === lastTooltipUpdate.visible
		) {
			return;
		}
		lastTooltipUpdate = {
			text: tipState.text,
			x: tipState.x,
			y: tipState.y,
			visible: tipState.visible
		};
		if (tipState.visible) {
			tipRef.style.setProperty('--tip-left', `${tipState.x}px`);
			tipRef.style.setProperty('--tip-top', `${tipState.y}px`);
			tipRef.style.opacity = '1';
			tipRef.style.visibility = 'visible';
		} else {
			tipRef.style.opacity = '0';
			tipRef.style.visibility = 'hidden';
		}
	});

	function setWidth(node: HTMLElement, size: number) {
		node.style.width = `${size}px`;
		return {
			update(next: number) {
				node.style.width = `${next}px`;
			}
		};
	}

	const minColumnWidthPx = 220;
	const defaultColumnWidthPx = 150;
	const columnHoverDelayMs = 1000;
	let panelWidth = $state(0);

	let initialSize = $state(defaultColumnWidthPx);

	const table = $derived.by(() => {
		if (data.length === 0 || columns.length === 0) return null;

		const columnDefs: ColumnDef<RowData>[] = columns.map((col) => ({
			id: col,
			accessorKey: col,
			header: col,
			size: initialSize,
			minSize: minColumnWidthPx
		}));

		return createTable({
			data,
			columns: columnDefs,
			state: {
				sorting,
				columnSizing,
				columnSizingInfo,
				columnPinning,
				columnVisibility: effectiveVisibility,
				expanded: {},
				grouping: [],
				rowSelection: {},
				columnOrder
			},
			onSortingChange: () => {},
			onColumnVisibilityChange: (updater) => {
				columnVisibility = typeof updater === 'function' ? updater(columnVisibility) : updater;
			},
			onColumnOrderChange: (updater) => {
				columnOrder = typeof updater === 'function' ? updater(columnOrder) : updater;
			},
			onColumnPinningChange: (updater) => {
				columnPinning = typeof updater === 'function' ? updater(columnPinning) : updater;
			},
			onColumnSizingChange: (updater) => {
				const next = typeof updater === 'function' ? updater(columnSizing) : updater;
				columnSizing = normalizeSizing(next);
			},
			onColumnSizingInfoChange: (updater) => {
				const next = typeof updater === 'function' ? updater(columnSizingInfo) : updater;
				// Only update reactive state when resize starts/ends, not during
				const wasResizing = columnSizingInfo.isResizingColumn !== false;
				const isResizing = next.isResizingColumn !== false;

				if (wasResizing && isResizing) {
					// During resize - update non-reactive offset only
					resizeOffset.delta = next.deltaOffset ?? 0;
					resizeOffset.start = next.startOffset ?? 0;
					document.documentElement.style.setProperty('--resize-delta', `${resizeOffset.delta}px`);
				} else {
					// Resize start/end - update reactive state
					columnSizingInfo = next;
					resizeOffset.delta = next.deltaOffset ?? 0;
					resizeOffset.start = next.startOffset ?? 0;
					if (!isResizing) {
						document.documentElement.style.removeProperty('--resize-delta');
					}
				}
			},
			getCoreRowModel: getCoreRowModel(),
			getSortedRowModel: getSortedRowModel(),
			onStateChange: () => {},
			columnResizeMode: 'onChange',
			enableColumnResizing: enableResize,
			renderFallbackValue: null
		});
	});

	const headerGroups = $derived<HeaderGroup<RowData>[]>(table ? table.getHeaderGroups() : []);
	const rows = $derived<Row<RowData>[]>(table ? table.getRowModel().rows : []);
	const compact = $derived(density === 'compact');
	const resizing = $derived(columnSizingInfo.isResizingColumn !== false);
	const effectiveVisibility = $derived(
		columns.reduce(
			(acc, col) => {
				const term = columnSearch.trim().toLowerCase();
				const matches = term ? col.toLowerCase().includes(term) : true;
				acc[col] = (columnVisibility[col] ?? true) && matches;
				return acc;
			},
			{} as Record<string, boolean>
		)
	);

	function normalizeSizing(next: ColumnSizingState): ColumnSizingState {
		const safe = Object.fromEntries(
			Object.entries(next).map(([key, value]) => [key, Math.max(minColumnWidthPx, value)])
		);
		if (!panelWidth) return safe;
		const order = columnOrder.length ? columnOrder : columns;
		const visible = order.filter((col) => columnVisibility[col] ?? true);
		if (!visible.length) return safe;
		const total = visible.reduce((sum, col) => {
			const current = safe[col] ?? columnSizing[col] ?? initialSize;
			return sum + current;
		}, 0);
		if (total >= panelWidth) return safe;
		const last = visible[visible.length - 1];
		const lastSize = safe[last] ?? columnSizing[last] ?? initialSize;
		return { ...safe, [last]: lastSize + (panelWidth - total) };
	}

	function toggleColumnVisibility(columnId: string) {
		const visible = columnVisibility[columnId] ?? true;
		columnVisibility = { ...columnVisibility, [columnId]: !visible };
	}

	function pinColumn(columnId: string, side: 'left' | 'right' | 'none') {
		const left = (columnPinning.left ?? []).filter((id) => id !== columnId);
		const right = (columnPinning.right ?? []).filter((id) => id !== columnId);
		if (side === 'left') {
			columnPinning = { left: [...left, columnId], right };
			return;
		}
		if (side === 'right') {
			columnPinning = { left, right: [...right, columnId] };
			return;
		}
		columnPinning = { left, right };
	}

	function toggleColumnMenu(columnId: string) {
		activeColumn = activeColumn === columnId ? null : columnId;
	}

	function handleColumnPointerDown(event: PointerEvent, columnId: string, label: string) {
		if (event.button !== 0) return;
		event.preventDefault();
		dragColumn = columnId;
		dragLabel = label;
		dragPointerX = event.clientX;
		dragPointerY = event.clientY;

		const target = event.currentTarget as HTMLElement;
		target.setPointerCapture(event.pointerId);
	}

	function handleColumnPointerMove(event: PointerEvent) {
		if (!dragColumn) return;
		event.preventDefault();
		dragPointerX = event.clientX;
		dragPointerY = event.clientY;

		// Hit-test which <th> the pointer is over
		const els = document.elementsFromPoint(event.clientX, event.clientY);
		const th = els.find((el) => el.closest('.dataset-table__th')) as HTMLElement | undefined;
		const header = th?.closest('.dataset-table__th') as HTMLElement | null;
		if (header) {
			const id = header.dataset.columnId ?? null;
			dragOver = id && id !== dragColumn ? id : null;
		} else {
			dragOver = null;
		}
	}

	function handleColumnPointerUp() {
		if (!dragColumn) return;
		if (dragOver) {
			const source = dragColumn;
			const order = columnOrder.length ? [...columnOrder] : [...columns];
			const sourceIndex = order.indexOf(source);
			const targetIndex = order.indexOf(dragOver);
			if (sourceIndex !== -1 && targetIndex !== -1) {
				const updated = [...order];
				const [item] = updated.splice(sourceIndex, 1);
				updated.splice(targetIndex, 0, item);
				columnOrder = updated;
			}
		}
		dragColumn = null;
		dragOver = null;
		dragPointerX = null;
		dragPointerY = null;
		dragLabel = null;
	}

	function setSort(columnId: string, direction: 'asc' | 'desc' | 'none') {
		if (direction === 'none') {
			sorting = [];
			return;
		}
		sorting = [{ id: columnId, desc: direction === 'desc' }];
		if (onSort) {
			onSort(columnId, direction);
		}
	}

	function handlePreview() {
		if (!onPreview) return;
		onPreview();
	}

	function handlePreviewKey(event: KeyboardEvent) {
		if (!onPreview) return;
		if (event.key !== 'Enter' && event.key !== ' ') return;
		event.preventDefault();
		onPreview();
	}

	onClickOutside(
		() => columnMenuRef,
		() => {
			if (activeColumn) {
				activeColumn = null;
			}
		}
	);

	function getTemporalType(dtype: string | undefined): 'date' | 'datetime' | null {
		if (!dtype) return null;
		const lower = dtype.toLowerCase();
		if (lower.includes('datetime')) return 'datetime';
		if (lower.includes('date')) return 'date';
		if (lower.includes('time')) return 'datetime';
		return null;
	}

	function formatValue(value: TableCellValue, columnId: string): string {
		if (value === null || value === undefined) return '-';
		const temporal = getTemporalType(resolveColumnType(columnTypes[columnId]));
		if (temporal === 'date') return formatDateDisplay(value as string);
		if (temporal === 'datetime') return formatDateTimeDisplay(value as string);
		if (typeof value === 'number') return value.toLocaleString();
		if (typeof value === 'boolean') return value ? 'true' : 'false';
		if (Array.isArray(value)) {
			return (
				'[' +
				value
					.map((item) => {
						if (typeof item === 'number') return item.toLocaleString();
						if (item === null || item === undefined) return 'null';
						return String(item);
					})
					.join(', ') +
				']'
			);
		}
		return String(value);
	}

	function getColumnType(columnId: string): string {
		return resolveColumnType(columnTypes[columnId]);
	}

	function isListType(columnType: string): boolean {
		return columnType.includes('List') || columnType === 'list';
	}

	async function copyValue(event: MouseEvent, id: string, value: string) {
		event.preventDefault();
		event.stopPropagation();

		// Direct DOM manipulation - show visual feedback immediately
		const button = event.currentTarget as HTMLButtonElement;
		if (!button) return;

		// Clear existing timer if any
		const existingTimer = copyTimers.get(id);
		if (existingTimer) {
			window.clearTimeout(existingTimer);
		}

		copiedCells.add(id);
		button.classList.add('dataset-table__copy--copied');

		const timer = window.setTimeout(() => {
			copiedCells.delete(id);
			copyTimers.delete(id);
			button.classList.remove('dataset-table__copy--copied');
		}, 1400);

		copyTimers.set(id, timer);

		// Try to copy to clipboard
		if (!navigator?.clipboard) return;
		const textToCopy = String(value);
		await navigator.clipboard.writeText(textToCopy).catch(() => {
			// Silently fail - visual feedback already shown
		});
	}

	function tipHide(id: string) {
		if (tipState.hoverId !== id) return;
		tipState.hoverId = '';
		if (tipState.timer) {
			window.clearTimeout(tipState.timer);
			tipState.timer = null;
		}
		tipState.visible = false;
	}

	function tipShow(event: MouseEvent, id: string, value: string) {
		const target = event.target as HTMLElement;
		if (target?.closest('button')) return;
		const currentTarget = event.currentTarget as HTMLElement;
		const valueEl = currentTarget.querySelector('[data-cell-value="true"]') as HTMLElement | null;
		if (!valueEl) return;
		const overflow = valueEl.scrollWidth > valueEl.clientWidth;
		tipState.hoverId = id;
		if (tipState.timer) {
			window.clearTimeout(tipState.timer);
			tipState.timer = null;
		}
		if (!overflow) {
			tipState.visible = false;
			return;
		}
		const rect = valueEl.getBoundingClientRect();
		tipState.text = value;
		tipState.x = rect.left + rect.width / 2;
		tipState.y = rect.bottom + 8;
		const hoverId = id;
		tipState.timer = window.setTimeout(() => {
			if (tipState.hoverId !== hoverId) return;
			tipState.visible = true;
		}, columnHoverDelayMs);
	}
</script>

<div
	class="dataset-table relative overflow-hidden bg-panel"
	class:h-full={fillContainer}
	class:flex={fillContainer}
	class:flex-col={fillContainer}
	class:dataset-table--compact={compact}
	class:dataset-table--resizing={resizing}
>
	{#if showHeader}
		<div class="flex items-center gap-3 px-4 py-2 border-b border-tertiary bg-tertiary">
			{#if showPagination && pagination}
				<button
					class="py-1 px-2.5 border border-tertiary bg-primary text-fg-primary text-xs disabled:opacity-50 disabled:cursor-not-allowed"
					onclick={pagination.onPrev}
					disabled={!pagination.canPrev || !!pagination.loading}
				>
					Prev
				</button>
				<span class="text-xs text-fg-muted">Page {pagination.page}</span>
				<button
					class="py-1 px-2.5 border border-tertiary bg-primary text-fg-primary text-xs disabled:opacity-50 disabled:cursor-not-allowed"
					onclick={pagination.onNext}
					disabled={!pagination.canNext || !!pagination.loading}
				>
					Next
				</button>
			{/if}
			<input
				type="text"
				class="input-base border px-2 py-1 text-xs ml-auto w-60"
				placeholder="Filter columns"
				bind:value={columnSearch}
			/>
		</div>
	{/if}

	{#if loading}
		<div class="flex h-full flex-col items-center justify-center gap-3 text-fg-tertiary">
			<LoaderCircle size={18} class="animate-spin" />
			<p class="m-0 text-fg-tertiary">Loading</p>
		</div>
	{/if}

	{#if error}
		<div class="flex h-full flex-col items-center justify-center gap-3 text-fg-tertiary">
			<Bug size={18} />
			<p class="m-0 text-fg-tertiary">Failed</p>
			<p class="m-0 text-fg-tertiary">{error.message}</p>
		</div>
	{/if}

	{#if !loading && data.length === 0}
		{#if analysis}
			<div
				class="flex h-full flex-col items-center justify-center gap-3 text-fg-tertiary"
				role="button"
				tabindex={onPreview ? 0 : -1}
				aria-disabled={!onPreview}
				onclick={handlePreview}
				onkeydown={handlePreviewKey}
			>
				<Play size={18} />
				<p class="m-0 text-fg-tertiary">Preview</p>
			</div>
		{:else}
			<div class="p-12 text-center m-0 text-fg-muted">
				<p class="m-0">No data available</p>
			</div>
		{/if}
	{:else if headerGroups.length > 0}
		<div
			class="dataset-table__scroll overflow-x-auto overflow-y-auto bg-panel"
			class:flex-1={fillContainer}
			bind:this={scrollRef}
		>
			<table
				class="dataset-table__table w-full border-collapse text-sm"
				use:setWidth={table?.getTotalSize() ?? 0}
			>
				<thead class="dataset-table__thead sticky top-0 z-20 bg-tertiary">
					{#each headerGroups as headerGroup (headerGroup.id)}
						<tr>
							{#each headerGroup.headers as header (header.id)}
								{@const headerLabel =
									typeof header.column.columnDef.header === 'string'
										? header.column.columnDef.header
										: header.id}
								<th
									class="dataset-table__th p-0 text-left font-semibold border-b border-tertiary"
									class:dataset-table__th--drag={dragOver === header.id}
									class:dataset-table__th--dragging={dragColumn === header.id}
									data-column-id={header.id}
									use:setWidth={header.getSize()}
								>
									<div
										class="dataset-table__header flex items-start justify-between w-full px-4 py-2"
									>
										<div class="dataset-table__header-left">
											<div class="dataset-table__header-actions">
												<div class="dataset-table__drag-slot">
													{#if (columnPinning.left ?? []).includes(header.id) || (columnPinning.right ?? []).includes(header.id)}
														<Pin class="dataset-table__pin-icon" size={12} />
													{:else}
														<button
															class="dataset-table__drag"
															onpointerdown={(event) =>
																handleColumnPointerDown(event, header.id, headerLabel)}
															onpointermove={handleColumnPointerMove}
															onpointerup={handleColumnPointerUp}
															onpointercancel={handleColumnPointerUp}
															aria-label="Drag to reorder"
														>
															<GripVertical size={12} />
														</button>
													{/if}
												</div>
											</div>
											<div class="dataset-table__sort-label" role="presentation">
												<span
													class="dataset-table__label-text font-mono text-sm font-semibold text-fg-primary"
												>
													{typeof header.column.columnDef.header === 'string'
														? header.column.columnDef.header
														: header.id}
												</span>
												{#if showTypeBadges}
													{#if getColumnType(header.id)}
														<ColumnTypeBadge columnType={getColumnType(header.id)} size="xs" />
													{:else}
														<span class="dataset-table__type-text">-</span>
													{/if}
												{/if}
											</div>
										</div>
										<div class="dataset-table__header-actions dataset-table__header-actions--right">
											<button
												class="dataset-table__header-btn"
												onclick={() => toggleColumnMenu(header.id)}
												aria-label="Column options"
											>
												<Settings2 size={12} />
											</button>
										</div>
									</div>
									{#if enableResize}
										<button
											class="dataset-table__resizer"
											onmousedown={header.getResizeHandler()}
											ontouchstart={header.getResizeHandler()}
											aria-label="Resize column"
											class:dataset-table__resizer--active={header.column.getIsResizing()}
										></button>
									{/if}
									{#if activeColumn === header.id}
										<div class="dataset-table__column-menu" bind:this={columnMenuRef}>
											<button
												class="dataset-table__menu-btn"
												onclick={() => setSort(header.id, 'asc')}>Sort A-Z</button
											>
											<button
												class="dataset-table__menu-btn"
												onclick={() => setSort(header.id, 'desc')}>Sort Z-A</button
											>
											<button
												class="dataset-table__menu-btn"
												onclick={() => setSort(header.id, 'none')}>Clear sort</button
											>
											<button
												class="dataset-table__menu-btn"
												onclick={() => pinColumn(header.id, 'left')}>Pin left</button
											>
											<button
												class="dataset-table__menu-btn"
												onclick={() => pinColumn(header.id, 'right')}>Pin right</button
											>
											<button
												class="dataset-table__menu-btn"
												onclick={() => pinColumn(header.id, 'none')}>Unpin</button
											>
											<button
												class="dataset-table__menu-btn"
												onclick={() => toggleColumnVisibility(header.id)}
											>
												{(columnVisibility[header.id] ?? true) ? 'Hide column' : 'Show column'}
											</button>
											{#if onColumnStats}
												<button
													class="dataset-table__menu-btn"
													onclick={() => {
														onColumnStats(header.id);
														activeColumn = null;
													}}
												>
													Column stats
												</button>
											{/if}
										</div>
									{/if}
								</th>
							{/each}
						</tr>
					{/each}
				</thead>
				<tbody>
					{#each rows as row (row.id)}
						<tr class="dataset-table__row">
							{#each row.getVisibleCells() as cell (cell.id)}
								{@const display = formatValue(cell.getValue() as TableCellValue, cell.column.id)}
								<td class="dataset-table__td">
									<div
										class="dataset-table__cell px-4 text-sm text-fg-secondary"
										class:text-xs={isListType(getColumnType(cell.column.id))}
										role="presentation"
										onmouseenter={(event) => tipShow(event, cell.id, display)}
										onmouseleave={() => tipHide(cell.id)}
									>
										<span class="dataset-table__value" data-cell-value="true">{display}</span>
										{#if enableCopy}
											<button
												class="dataset-table__copy"
												aria-label="Copy cell value"
												onclick={(event) => copyValue(event, cell.id, display)}
											>
												<span class="dataset-table__copy-icon dataset-table__copy-icon--copy"
													><Copy size={14} /></span
												>
												<span class="dataset-table__copy-icon dataset-table__copy-icon--check"
													><Check size={14} /></span
												>
											</button>
										{/if}
									</div>
								</td>
							{/each}
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}

	{#if showFooter && !loading && data.length > 0}
		<div class="px-4 py-3 border-t border-tertiary bg-tertiary">
			<span class="text-xs text-fg-tertiary">
				Showing {data.length.toLocaleString()} row{data.length !== 1 ? 's' : ''}
			</span>
		</div>
	{/if}

	<div class="dataset-table__tooltip" bind:this={tipRef}></div>
</div>

{#if dragColumn && dragPointerX !== null && dragPointerY !== null}
	<div
		class="dataset-table__drag-preview pointer-events-none fixed z-9999 flex items-center gap-2 whitespace-nowrap border px-3 py-1.5 text-sm font-semibold border-tertiary bg-panel text-fg-primary"
		style="left: {dragPointerX + 12}px; top: {dragPointerY + 12}px;"
	>
		<GripVertical size={12} class="text-fg-muted" />
		<span class="font-mono">{dragLabel}</span>
	</div>
{/if}
