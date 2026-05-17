<script lang="ts">
	import { onDestroy, untrack } from 'svelte';
	import { preflightExcel, preflightExcelFromPath, previewExcel } from '$lib/api/excel';
	import type { ExcelParams } from '$lib/api/excel';
	import DataTable from '$lib/components/common/DataTable.svelte';
	import { css, button, label } from '$lib/styles/panda';

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

	let sheetNames = $state.raw<string[]>([]);
	let tableMap = $state.raw<Record<string, string[]>>({});
	let namedRanges = $state.raw<string[]>([]);
	let previewGrid = $state.raw<Array<Array<string | null>>>([]);
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
		const params: ExcelParams = {
			sheet_name: selectedSheet || undefined,
			start_row: startRow,
			start_col: startCol,
			end_col: endCol,
			has_header: excelHeader,
			table_name: selectedTable || undefined,
			named_range: selectedRange || undefined,
			cell_range: cellRangeInput.trim() || undefined,
			end_row: endRowManual && endRow !== null ? endRow : undefined
		};

		const result =
			mode === 'upload'
				? await preflightExcel(file as File, params)
				: await preflightExcelFromPath(filePath as string, params);
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
		const params: ExcelParams & { sheet_name: string } = {
			sheet_name: selectedSheet,
			start_row: startRow,
			start_col: startCol,
			end_col: endCol,
			has_header: excelHeader,
			table_name: selectedTable || undefined,
			named_range: selectedRange || undefined,
			cell_range: cellRangeInput.trim() || undefined,
			end_row: endRowManual && endRow !== null ? endRow : undefined
		};
		const result = await previewExcel(preflightId, params);
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

<div
	class={css({
		display: 'flex',
		flexDirection: 'column',
		gap: '4',
		borderWidth: '1',
		backgroundColor: 'bg.tertiary',
		padding: '4'
	})}
>
	<div class={css({ display: 'flex', alignItems: 'center', justifyContent: 'space-between' })}>
		<h3 class={css({ margin: '0', fontSize: 'sm', fontWeight: 'semibold', color: 'fg.secondary' })}>
			Excel Table Selection
		</h3>
		<button
			type="button"
			class={dirty
				? `${button({ variant: 'secondary' })} ${css({
						backgroundColor: 'bg.warning',
						color: 'fg.warning',
						borderColor: 'border.warning'
					})}`
				: button({ variant: 'secondary' })}
			onclick={handleRefreshClick}
			disabled={disabled || previewLoading}
		>
			{previewLoading ? 'Loading preview...' : 'Refresh preview'}
		</button>
	</div>

	{#if error}
		<div
			class={css({
				paddingX: '3',
				paddingY: '2.5',
				border: 'none',
				borderLeftWidth: '2',

				marginTop: '3',
				marginBottom: '0',
				fontSize: 'xs',
				lineHeight: '1.5',
				backgroundColor: 'transparent',
				borderLeftColor: 'border.error',
				color: 'fg.error'
			})}
		>
			{error}
		</div>
	{/if}

	<div
		class={css({
			display: 'grid',
			gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
			gap: '4'
		})}
	>
		<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
			<label class={label({ variant: 'field' })} for="excel-sheet">Sheet</label>
			<select
				id="excel-sheet"
				value={selectedSheet}
				onchange={(event) => applySheet(event.currentTarget.value)}
				disabled={disabled || previewLoading || !sheetNames.length}
				class={css({
					width: 'full',
					fontSize: 'sm',
					color: 'fg.primary',
					backgroundColor: 'bg.primary',
					borderWidth: '1',
					borderRadius: '0',
					paddingX: '3',
					paddingY: '2',
					transitionProperty: 'border-color',
					transitionDuration: '160ms',
					transitionTimingFunction: 'ease',
					_focus: { outline: 'none' },
					_focusVisible: { borderColor: 'border.accent' },
					_disabled: { opacity: '0.5', cursor: 'not-allowed', backgroundColor: 'bg.tertiary' },
					_placeholder: { color: 'fg.muted' }
				})}
			>
				<option value="">Select sheet</option>
				{#each sheetNames as sheet (sheet)}
					<option value={sheet}>{sheet}</option>
				{/each}
			</select>
		</div>
		<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
			<label class={label({ variant: 'field' })} for="excel-table">Excel Table</label>
			<select
				id="excel-table"
				value={selectedTable}
				onchange={(event) => applyTable(event.currentTarget.value)}
				disabled={disabled || previewLoading || !selectedSheet}
				class={css({
					width: 'full',
					fontSize: 'sm',
					color: 'fg.primary',
					backgroundColor: 'bg.primary',
					borderWidth: '1',
					borderRadius: '0',
					paddingX: '3',
					paddingY: '2',
					transitionProperty: 'border-color',
					transitionDuration: '160ms',
					transitionTimingFunction: 'ease',
					_focus: { outline: 'none' },
					_focusVisible: { borderColor: 'border.accent' },
					_disabled: { opacity: '0.5', cursor: 'not-allowed', backgroundColor: 'bg.tertiary' },
					_placeholder: { color: 'fg.muted' }
				})}
			>
				<option value="">Manual selection</option>
				{#each tableMap[selectedSheet] ?? [] as table (table)}
					<option value={table}>{table}</option>
				{/each}
			</select>
		</div>
		<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
			<label class={label({ variant: 'field' })} for="excel-range">Named Range</label>
			<select
				id="excel-range"
				value={selectedRange}
				onchange={(event) => applyNamedRange(event.currentTarget.value)}
				disabled={disabled || previewLoading}
				class={css({
					width: 'full',
					fontSize: 'sm',
					color: 'fg.primary',
					backgroundColor: 'bg.primary',
					borderWidth: '1',
					borderRadius: '0',
					paddingX: '3',
					paddingY: '2',
					transitionProperty: 'border-color',
					transitionDuration: '160ms',
					transitionTimingFunction: 'ease',
					_focus: { outline: 'none' },
					_focusVisible: { borderColor: 'border.accent' },
					_disabled: { opacity: '0.5', cursor: 'not-allowed', backgroundColor: 'bg.tertiary' },
					_placeholder: { color: 'fg.muted' }
				})}
			>
				<option value="">None</option>
				{#each namedRanges as range (range)}
					<option value={range}>{range}</option>
				{/each}
			</select>
		</div>
		<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
			<label class={label({ variant: 'field' })} for="excel-cell-range">Manual Range</label>
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
				class={css({
					width: 'full',
					fontSize: 'sm',
					color: 'fg.primary',
					backgroundColor: 'bg.primary',
					borderWidth: '1',
					borderRadius: '0',
					paddingX: '3',
					paddingY: '2',
					transitionProperty: 'border-color',
					transitionDuration: '160ms',
					transitionTimingFunction: 'ease',
					_focus: { outline: 'none' },
					_focusVisible: { borderColor: 'border.accent' },
					_disabled: { opacity: '0.5', cursor: 'not-allowed', backgroundColor: 'bg.tertiary' },
					_placeholder: { color: 'fg.muted' }
				})}
			/>
			<p class={css({ margin: '0', fontSize: 'xs', color: 'fg.muted' })}>
				Optional A1 range (use Sheet1!A1:D50).
			</p>
		</div>
	</div>

	<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
		<input
			id="excel-header"
			type="checkbox"
			bind:checked={excelHeader}
			onchange={handleHeaderToggle}
			disabled={disabled || previewLoading}
			class={css({ height: 'iconSm', width: 'iconSm', cursor: 'pointer' })}
		/>
		<label
			for="excel-header"
			class={css({
				display: 'block',
				fontSize: 'sm',
				fontWeight: 'medium',
				color: 'fg.secondary',
				textTransform: 'none',
				letterSpacing: 'normal',
				margin: '0'
			})}>First row is header</label
		>
	</div>

	{#if preflightId}
		<div
			class={css({
				overflow: 'hidden',
				borderWidth: '1',
				backgroundColor: 'bg.primary'
			})}
		>
			<div
				class={css({
					display: 'flex',
					flexWrap: 'wrap',
					columnGap: '4',
					rowGap: '1',
					paddingX: '3',
					paddingY: '1.5',
					fontSize: 'xs',
					fontWeight: 'medium',
					backgroundColor: 'bg.tertiary',
					borderBottomWidth: '1',
					color: 'fg.muted'
				})}
			>
				<span class={css({ display: 'flex', alignItems: 'center', gap: '1' })}
					><span class={css({ color: 'fg.tertiary' })}>Start row:</span>
					<span class={css({ fontWeight: 'semibold' })}>{startRow + 1}</span></span
				>
				<span class={css({ display: 'flex', alignItems: 'center', gap: '1' })}
					><span class={css({ color: 'fg.tertiary' })}>Start col:</span>
					<span class={css({ fontWeight: 'semibold' })}>{cellLabel(startCol)}</span></span
				>
				<span class={css({ display: 'flex', alignItems: 'center', gap: '1' })}
					><span class={css({ color: 'fg.tertiary' })}>End col:</span>
					<span class={css({ fontWeight: 'semibold' })}>{cellLabel(endCol)}</span></span
				>
				{#if endRow !== null}
					<span class={css({ display: 'flex', alignItems: 'center', gap: '1' })}
						><span class={css({ color: 'fg.tertiary' })}>End row:</span>
						<span class={css({ fontWeight: 'semibold' })}>{endRow + 1}</span></span
					>
				{/if}
				{#if detectedEndRow !== null}
					<span class={css({ display: 'flex', alignItems: 'center', gap: '1' })}
						><span class={css({ color: 'fg.tertiary' })}>Detected end:</span>
						<span class={css({ fontWeight: 'semibold' })}>{detectedEndRow + 1}</span></span
					>
				{/if}
			</div>
			<div
				class={css({
					contain: 'content',
					maxHeight: 'listLg',
					overflow: 'auto',
					borderTopWidth: '1'
				})}
			>
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
