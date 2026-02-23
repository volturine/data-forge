<script lang="ts">
	import { onDestroy, untrack } from 'svelte';
	import { preflightExcel, preflightExcelFromPath, previewExcel } from '$lib/api/excel';
	import DataTable from '$lib/components/common/DataTable.svelte';

	interface ExcelConfig {
		sheet_name: string;
		table_name: string;
		named_range: string;
		cell_range: string;
		start_row: number;
		start_col: number;
		end_col: number;
		end_row: number | null;
		has_header: boolean;
	}

	interface Props {
		mode: 'upload' | 'config';
		file?: File | null;
		filePath?: string | null;
		initialConfig?: Partial<ExcelConfig> | null;
		disabled?: boolean;
		preflightId?: string | null;
		onConfigChange?: (config: ExcelConfig) => void;
	}

	let {
		mode,
		file = null,
		filePath = null,
		initialConfig = null,
		disabled = false,
		preflightId = $bindable(null),
		onConfigChange
	}: Props = $props();

	let sheetNames = $state<string[]>([]);
	let tableMap = $state<Record<string, string[]>>({});
	let namedRanges = $state<string[]>([]);
	let previewGrid = $state<Array<Array<string | null>>>([]);
	let selectedSheet = $state('');
	let selectedTable = $state('');
	let selectedRange = $state('');
	let cellRange = $state('');
	let cellRangeInput = $state('');
	let startRow = $state(0);
	let startCol = $state(0);
	let endCol = $state(0);
	let endRow = $state<number | null>(null);
	let endRowManual = $state(false);
	let detectedEndRow = $state<number | null>(null);
	let excelHeader = $state(true);
	let previewLoading = $state(false);
	let error = $state<string | null>(null);
	let dirty = $state(false);
	let initialized = $state(false);
	let suppressNotification = $state(false);

	let previewTimer: ReturnType<typeof setTimeout> | null = null;

	const config = $derived<ExcelConfig>({
		sheet_name: selectedSheet,
		table_name: selectedTable,
		named_range: selectedRange,
		cell_range: cellRangeInput.trim() || '',
		start_row: startRow,
		start_col: startCol,
		end_col: endCol,
		end_row: endRow,
		has_header: excelHeader
	});

	const previewColumns = $derived.by(() => {
		if (previewGrid.length === 0) return [] as string[];
		const cols = previewGrid[0]?.length ?? 0;
		if (excelHeader && previewGrid[0]) {
			return previewGrid[0].map((val, index) => (val ? String(val) : cellLabel(startCol + index)));
		}
		return Array.from({ length: cols }, (_, index) => cellLabel(startCol + index));
	});

	const previewData = $derived.by(() => {
		if (previewGrid.length === 0) return [] as Record<string, unknown>[];
		const columns = previewColumns;
		const dataRows = excelHeader ? previewGrid.slice(1) : previewGrid;
		return dataRows.map((row) => {
			const record: Record<string, unknown> = {};
			columns.forEach((col, index) => {
				record[col] = row[index] ?? null;
			});
			return record;
		});
	});

	// Subscription: $derived can't notify parent callbacks.
	$effect(() => {
		if (!onConfigChange || !initialized) return;
		if (suppressNotification) {
			suppressNotification = false;
			return;
		}
		onConfigChange(config);
	});

	// Subscription: $derived can't sync external config.
	$effect(() => {
		const next = initialConfig;
		if (!next) return;
		const normalized = normalizeConfig(next);
		if (isConfigEqual(normalized, config)) {
			if (!initialized) initialized = true;
			return;
		}
		suppressNotification = true;
		applyConfig(normalized);
		initialized = true;
	});

	function resetPreviewState() {
		sheetNames = [];
		tableMap = {};
		namedRanges = [];
		previewGrid = [];
		preflightId = null;
		detectedEndRow = null;
		error = null;
		dirty = false;
		initialized = false;
		suppressNotification = false;
	}

	function normalizeConfig(value: Partial<ExcelConfig>): ExcelConfig {
		return {
			sheet_name: value.sheet_name ?? '',
			table_name: value.table_name ?? '',
			named_range: value.named_range ?? '',
			cell_range: value.cell_range ?? '',
			start_row: value.start_row ?? 0,
			start_col: value.start_col ?? 0,
			end_col: value.end_col ?? 0,
			end_row: value.end_row ?? null,
			has_header: value.has_header ?? true
		};
	}

	function isConfigEqual(a: ExcelConfig, b: ExcelConfig): boolean {
		return (
			a.sheet_name === b.sheet_name &&
			a.table_name === b.table_name &&
			a.named_range === b.named_range &&
			a.cell_range === b.cell_range &&
			a.start_row === b.start_row &&
			a.start_col === b.start_col &&
			a.end_col === b.end_col &&
			a.end_row === b.end_row &&
			a.has_header === b.has_header
		);
	}

	function applyConfig(next: ExcelConfig) {
		selectedSheet = next.sheet_name;
		selectedTable = next.table_name;
		selectedRange = next.named_range;
		cellRange = next.cell_range;
		cellRangeInput = next.cell_range;
		startRow = next.start_row;
		startCol = next.start_col;
		endCol = next.end_col;
		endRow = next.end_row;
		endRowManual = next.end_row !== null && next.end_row !== undefined;
		excelHeader = next.has_header;
	}

	async function runPreflight(): Promise<void> {
		error = null;
		previewLoading = true;
		const params: Record<string, unknown> = {
			sheet_name: selectedSheet || undefined,
			start_row: startRow,
			start_col: startCol,
			end_col: endCol,
			has_header: excelHeader,
			table_name: selectedTable || undefined,
			named_range: selectedRange || undefined,
			cell_range: cellRangeInput.trim() || undefined
		};
		if (endRowManual && endRow !== null) {
			params.end_row = endRow;
		}

		const result =
			mode === 'upload'
				? await preflightExcel(file as File, params as Parameters<typeof preflightExcel>[1])
				: await preflightExcelFromPath(
						filePath as string,
						params as Parameters<typeof preflightExcelFromPath>[1]
					);
		result.match(
			(data) => {
				preflightId = data.preflight_id;
				sheetNames = data.sheet_names;
				tableMap = data.tables;
				namedRanges = data.named_ranges;
				previewGrid = data.preview;
				selectedSheet = data.sheet_name ?? data.sheet_names[0] ?? '';
				startRow = data.start_row;
				startCol = data.start_col;
				endCol = data.end_col;
				cellRange = cellRangeInput.trim();
				cellRangeInput = cellRange;
				detectedEndRow = data.detected_end_row;
				if (!endRowManual) {
					endRow = data.detected_end_row;
				}
				dirty = false;
				initialized = true;
				previewLoading = false;
			},
			(err) => {
				error = err.message || 'Preflight failed';
				previewLoading = false;
			}
		);
	}

	async function handleRefreshClick(): Promise<void> {
		if (preflightId) {
			await refreshPreview();
			return;
		}
		await runPreflight();
	}

	async function refreshPreview(): Promise<void> {
		if (!preflightId || !selectedSheet) return;
		error = null;
		previewLoading = true;
		const params: Record<string, unknown> = {
			sheet_name: selectedSheet,
			start_row: startRow,
			start_col: startCol,
			end_col: endCol,
			has_header: excelHeader,
			table_name: selectedTable || undefined,
			named_range: selectedRange || undefined,
			cell_range: cellRangeInput.trim() || undefined
		};
		if (endRowManual && endRow !== null) {
			params.end_row = endRow;
		}
		const result = await previewExcel(preflightId, params as Parameters<typeof previewExcel>[1]);
		result.match(
			(data) => {
				previewGrid = data.preview;
				startRow = data.start_row;
				startCol = data.start_col;
				endCol = data.end_col;
				cellRange = cellRangeInput.trim();
				cellRangeInput = cellRange;
				detectedEndRow = data.detected_end_row;
				if (!endRowManual) {
					endRow = data.detected_end_row;
				}
				dirty = false;
				previewLoading = false;
			},
			(err) => {
				error = err.message || 'Preview failed';
				previewLoading = false;
			}
		);
	}

	function schedulePreview() {
		if (previewTimer) {
			clearTimeout(previewTimer);
		}
		previewTimer = setTimeout(() => {
			previewTimer = null;
			void refreshPreview();
		}, 120);
	}

	function markDirty() {
		dirty = true;
	}

	function applySheet(sheet: string) {
		selectedSheet = sheet;
		startRow = 0;
		startCol = 0;
		endCol = 0;
		selectedTable = '';
		selectedRange = '';
		cellRange = '';
		cellRangeInput = '';
		endRow = null;
		endRowManual = false;
		schedulePreview();
		dirty = false;
	}

	function applyTable(table: string) {
		selectedTable = table;
		selectedRange = '';
		cellRange = '';
		cellRangeInput = '';
		startRow = 0;
		startCol = 0;
		endCol = 0;
		endRow = null;
		endRowManual = false;
		schedulePreview();
		dirty = false;
	}

	function applyNamedRange(range: string) {
		selectedRange = range;
		selectedTable = '';
		cellRange = '';
		cellRangeInput = '';
		startRow = 0;
		startCol = 0;
		endCol = 0;
		endRow = null;
		endRowManual = false;
		schedulePreview();
		dirty = false;
	}

	function applyCellRange(range: string) {
		cellRange = range;
		cellRangeInput = range;
		selectedTable = '';
		selectedRange = '';
		startRow = 0;
		startCol = 0;
		endCol = 0;
		endRow = null;
		endRowManual = false;
		markDirty();
	}

	function handleCellRangeInput(event: Event) {
		const target = event.currentTarget as HTMLInputElement;
		cellRangeInput = target.value;
		selectedTable = '';
		selectedRange = '';
		endRowManual = false;
		endRow = null;
		markDirty();
	}

	function handleCellRangeBlur() {
		const trimmed = cellRangeInput.trim();
		if (!trimmed) {
			cellRange = '';
			markDirty();
			return;
		}
		applyCellRange(trimmed);
	}

	function applyManualRange() {
		const trimmed = cellRangeInput.trim();
		if (!trimmed) return;
		applyCellRange(trimmed);
	}

	function handleHeaderToggle() {
		markDirty();
	}

	function cellLabel(col: number): string {
		let idx = col + 1;
		let label = '';
		while (idx > 0) {
			const rem = (idx - 1) % 26;
			label = String.fromCharCode(65 + rem) + label;
			idx = Math.floor((idx - 1) / 26);
		}
		return label;
	}

	onDestroy(() => {
		if (!previewTimer) return;
		clearTimeout(previewTimer);
		previewTimer = null;
	});

	// Network: $derived can't run preflight.
	$effect(() => {
		if (mode === 'upload') {
			if (!file) {
				resetPreviewState();
				return;
			}
			untrack(() => {
				resetPreviewState();
				void runPreflight();
			});
			return;
		}
		if (!filePath) {
			resetPreviewState();
			return;
		}
		untrack(() => {
			resetPreviewState();
			void runPreflight();
		});
	});
</script>

<div class="excel-selector flex flex-col gap-4 border border-tertiary bg-tertiary p-4">
	<div class="flex items-center justify-between">
		<h3 class="m-0 text-sm font-semibold text-fg-secondary">Excel Table Selection</h3>
		<button
			type="button"
			class="btn-secondary"
			class:unsaved={dirty}
			onclick={handleRefreshClick}
			disabled={disabled || previewLoading}
		>
			{previewLoading ? 'Loading preview...' : 'Refresh preview'}
		</button>
	</div>

	{#if error}
		<div class="error-box">{error}</div>
	{/if}

	<div class="grid grid-cols-2 gap-4">
		<div class="flex flex-col gap-2">
			<label class="text-sm font-medium text-fg-secondary" for="excel-sheet">Sheet</label>
			<select
				id="excel-sheet"
				value={selectedSheet}
				onchange={(event) => applySheet(event.currentTarget.value)}
				disabled={disabled || previewLoading || !sheetNames.length}
				class="border px-3 py-2 text-sm input-base"
			>
				<option value="">Select sheet</option>
				{#each sheetNames as sheet (sheet)}
					<option value={sheet}>{sheet}</option>
				{/each}
			</select>
		</div>
		<div class="flex flex-col gap-2">
			<label class="text-sm font-medium text-fg-secondary" for="excel-table">Excel Table</label>
			<select
				id="excel-table"
				value={selectedTable}
				onchange={(event) => applyTable(event.currentTarget.value)}
				disabled={disabled || previewLoading || !selectedSheet}
				class="border px-3 py-2 text-sm input-base"
			>
				<option value="">Manual selection</option>
				{#each tableMap[selectedSheet] ?? [] as table (table)}
					<option value={table}>{table}</option>
				{/each}
			</select>
		</div>
		<div class="flex flex-col gap-2">
			<label class="text-sm font-medium text-fg-secondary" for="excel-range">Named Range</label>
			<select
				id="excel-range"
				value={selectedRange}
				onchange={(event) => applyNamedRange(event.currentTarget.value)}
				disabled={disabled || previewLoading}
				class="border px-3 py-2 text-sm input-base"
			>
				<option value="">None</option>
				{#each namedRanges as range (range)}
					<option value={range}>{range}</option>
				{/each}
			</select>
		</div>
		<div class="flex flex-col gap-2">
			<label class="text-sm font-medium text-fg-secondary" for="excel-cell-range"
				>Manual Range</label
			>
			<input
				id="excel-cell-range"
				type="text"
				value={cellRangeInput}
				oninput={handleCellRangeInput}
				onblur={handleCellRangeBlur}
				onkeydown={(event) => {
					if (event.key !== 'Enter') return;
					applyManualRange();
				}}
				disabled={disabled || previewLoading}
				placeholder="A1:D50"
				class="border px-3 py-2 text-sm input-base"
			/>
			<p class="m-0 text-xs text-fg-muted">Optional A1 range (use Sheet1!A1:D50).</p>
		</div>
	</div>

	<div class="flex items-center gap-2">
		<input
			id="excel-header"
			type="checkbox"
			bind:checked={excelHeader}
			onchange={handleHeaderToggle}
			disabled={disabled || previewLoading}
			class="h-4 w-4 cursor-pointer"
		/>
		<label for="excel-header" class="m-0 text-sm font-medium text-fg-secondary"
			>First row is header</label
		>
	</div>

	{#if preflightId}
		<div class="overflow-hidden border border-tertiary bg-primary">
			<div
				class="flex flex-wrap gap-x-4 gap-y-1 px-3 py-1.5 text-[11px] font-medium bg-tertiary border-b border-tertiary text-fg-muted"
			>
				<span class="flex items-center gap-1"
					><span class="text-fg-tertiary">Start row:</span>
					<span class="text-fg-primary font-semibold">{startRow + 1}</span></span
				>
				<span class="flex items-center gap-1"
					><span class="text-fg-tertiary">Start col:</span>
					<span class="text-fg-primary font-semibold">{cellLabel(startCol)}</span></span
				>
				<span class="flex items-center gap-1"
					><span class="text-fg-tertiary">End col:</span>
					<span class="text-fg-primary font-semibold">{cellLabel(endCol)}</span></span
				>
				{#if endRow !== null}
					<span class="flex items-center gap-1"
						><span class="text-fg-tertiary">End row:</span>
						<span class="text-fg-primary font-semibold">{endRow + 1}</span></span
					>
				{/if}
				{#if detectedEndRow !== null}
					<span class="flex items-center gap-1"
						><span class="text-fg-tertiary">Detected end:</span>
						<span class="text-fg-primary font-semibold">{detectedEndRow + 1}</span></span
					>
				{/if}
			</div>
			<div class="excel-grid max-h-80 overflow-auto border-t border-tertiary">
				<DataTable
					columns={previewColumns}
					data={previewData}
					fillContainer
					showHeader
					showFooter={false}
					showPagination={false}
					enableResize={false}
					enableCopy={false}
				/>
			</div>
		</div>
	{/if}
</div>
