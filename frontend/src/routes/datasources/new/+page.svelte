<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import {
		uploadFile,
		uploadBulkFiles,
		connectDatabase,
		connectApi,
		connectDuckDB,
		connectIceberg,
		resolveIcebergMetadata,
		connectFilePath
	} from '$lib/api/datasource';
	import { preflightExcel, previewExcel, confirmExcel } from '$lib/api/excel';
	import type { ExcelPreflightResponse, ExcelPreviewResponse } from '$lib/api/excel';
	import type { BulkUploadResult } from '$lib/api/datasource';
	import FileBrowser from '$lib/components/common/FileBrowser.svelte';
	import { detectFileType } from '$lib/utils/fileTypes';
	import { MessageCircleQuestionMark, Check, X } from 'lucide-svelte';

	type Tab = 'file' | 'database' | 'api';
	type DatabaseType = 'duckdb' | 'iceberg' | 'other';

	let activeTab = $state<Tab>('file');
	let databaseType = $state<DatabaseType>('duckdb');
	let loading = $state(false);
	let error = $state<string | null>(null);

	// File upload state
	let file = $state<File | null>(null);
	let fileName = $state('');
	let preflightId = $state<string | null>(null);
	let sheetNames = $state<string[]>([]);
	let tableMap = $state<Record<string, string[]>>({});
	let namedRanges = $state<string[]>([]);
	let previewGrid = $state<Array<Array<string | null>>>([]);
	let selectedSheet = $state<string>('');
	let selectedTable = $state<string>('');
	let selectedRange = $state<string>('');
	let startRow = $state(0);
	let startCol = $state(0);
	let endCol = $state(0);
	let detectedEndRow = $state<number | null>(null);
	let excelHeader = $state(true);
	let previewLoading = $state(false);

	// DuckDB state
	let duckdbName = $state('');
	let duckdbPath = $state('');
	let duckdbQuery = $state('');
	let duckdbReadOnly = $state(true);

	// Iceberg state
	let icebergName = $state('');
	let icebergMetadataPath = $state('');
	let icebergSnapshotId = $state<number | null>(null);
	let icebergReader = $state('');
	let icebergStorageOptions = $state('');
	let icebergResolvedPath = $state('');

	// Generic database state
	let dbName = $state('');
	let connectionString = $state('');
	let query = $state('');

	// API state
	let apiName = $state('');
	let apiUrl = $state('');
	let apiMethod = $state('GET');

	// Upload state
	let selectedFiles = $state<File[]>([]);
	let bulkResults = $state<BulkUploadResult[]>([]);
	let showBulkResults = $state(false);
	let fileMode = $state<'upload' | 'path'>('upload');

	$effect(() => {
		if (fileMode !== 'path') return;
		selectedFiles = [];
		file = null;
		fileName = '';
		resetExcelState();
	});

	function resetExcelState() {
		preflightId = null;
		sheetNames = [];
		tableMap = {};
		namedRanges = [];
		previewGrid = [];
		selectedSheet = '';
		selectedTable = '';
		selectedRange = '';
		startRow = 0;
		startCol = 0;
		endCol = 0;
		detectedEndRow = null;
	}

	function applySelection(files: File[]) {
		selectedFiles = files;
		showBulkResults = false;
		bulkResults = [];
		resetExcelState();
		if (files.length !== 1) {
			file = null;
			fileName = '';
			return;
		}
		file = files[0];
		fileName = file.name.replace(/\.[^/.]+$/, '');
	}

	function handleFileChange(event: Event) {
		const target = event.target as HTMLInputElement;
		if (!target.files || target.files.length === 0) return;
		applySelection(Array.from(target.files));
	}

	async function handleBulkUpload() {
		if (selectedFiles.length === 0) {
			error = 'Please select at least one file';
			return;
		}

		loading = true;
		error = null;
		showBulkResults = false;

		const result = await uploadBulkFiles(selectedFiles);
		result.match(
			(response: import('$lib/api/datasource').BulkUploadResponse) => {
				bulkResults = response.results;
				showBulkResults = true;
				if (response.successful === response.total) {
					selectedFiles = [];
					goto(resolve('/datasources'), { invalidateAll: true });
				}
			},
			(err: { message?: string }) => {
				error = err.message || 'Bulk upload failed';
			}
		);

		loading = false;
	}

	function clearBulkSelection() {
		selectedFiles = [];
		bulkResults = [];
		showBulkResults = false;
		file = null;
		fileName = '';
		resetExcelState();
	}

	function removeBulkFile(index: number) {
		selectedFiles = selectedFiles.filter((_, i) => i !== index);
		if (selectedFiles.length === 1) {
			applySelection(selectedFiles);
		}
		if (selectedFiles.length === 0) {
			bulkResults = [];
			showBulkResults = false;
			file = null;
			fileName = '';
			resetExcelState();
		}
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

	async function runPreflight(): Promise<void> {
		if (!file) return;
		previewLoading = true;
		const result = await preflightExcel(file, {
			start_row: startRow,
			start_col: startCol,
			end_col: endCol,
			has_header: excelHeader,
			table_name: selectedTable || undefined,
			named_range: selectedRange || undefined
		});
		result.match(
			(data: ExcelPreflightResponse) => {
				preflightId = data.preflight_id;
				sheetNames = data.sheet_names;
				tableMap = data.tables;
				namedRanges = data.named_ranges;
				previewGrid = data.preview;
				selectedSheet = data.sheet_names[0] ?? '';
				startRow = data.start_row;
				startCol = data.start_col;
				endCol = data.end_col;
				detectedEndRow = data.detected_end_row;
				previewLoading = false;
			},
			(err) => {
				error = err.message || 'Preflight failed';
				previewLoading = false;
			}
		);
	}

	async function refreshPreview(): Promise<void> {
		if (!preflightId || !selectedSheet) return;
		previewLoading = true;
		const result = await previewExcel(preflightId, {
			sheet_name: selectedSheet,
			start_row: startRow,
			start_col: startCol,
			end_col: endCol,
			has_header: excelHeader,
			table_name: selectedTable || undefined,
			named_range: selectedRange || undefined
		});
		result.match(
			(data: ExcelPreviewResponse) => {
				previewGrid = data.preview;
				startRow = data.start_row;
				startCol = data.start_col;
				endCol = data.end_col;
				detectedEndRow = data.detected_end_row;
				previewLoading = false;
			},
			(err) => {
				error = err.message || 'Preview failed';
				previewLoading = false;
			}
		);
	}

	function applySheet(sheet: string) {
		selectedSheet = sheet;
		startRow = 0;
		startCol = 0;
		endCol = 0;
		selectedTable = '';
		selectedRange = '';
		refreshPreview();
	}

	function applyTable(table: string) {
		selectedTable = table;
		selectedRange = '';
		startRow = 0;
		startCol = 0;
		endCol = 0;
		refreshPreview();
	}

	function applyNamedRange(range: string) {
		selectedRange = range;
		selectedTable = '';
		startRow = 0;
		startCol = 0;
		endCol = 0;
		refreshPreview();
	}

	function handleStartRow(row: number) {
		startRow = row;
		selectedTable = '';
		selectedRange = '';
		refreshPreview();
	}

	function handleStartCol(col: number) {
		startCol = col;
		selectedTable = '';
		selectedRange = '';
		refreshPreview();
	}

	function handleEndCol(col: number) {
		endCol = col;
		selectedTable = '';
		selectedRange = '';
		refreshPreview();
	}

	async function handleFileUpload() {
		if (!file || !fileName) {
			error = 'Please select a file and provide a name';
			return;
		}

		loading = true;
		error = null;

		try {
			if (file.name.endsWith('.xlsx')) {
				if (!preflightId) {
					error = 'Run preflight to select table bounds before uploading';
					loading = false;
					return;
				}
				const result = await confirmExcel(preflightId, fileName, {
					sheet_name: selectedSheet,
					start_row: startRow,
					start_col: startCol,
					end_col: endCol,
					has_header: excelHeader,
					table_name: selectedTable || undefined,
					named_range: selectedRange || undefined
				});
				if (result.isErr()) {
					error = result.error.message || 'Upload failed';
					loading = false;
					return;
				}
				goto(resolve('/datasources'), { invalidateAll: true });
			} else {
				await uploadFile(file, fileName);
				goto(resolve('/datasources'), { invalidateAll: true });
			}
		} catch (err) {
			error = err instanceof Error ? err.message : 'Upload failed';
		} finally {
			loading = false;
		}
	}

	// Path-based file datasource
	let pathName = $state('');
	let pathValue = $state('');
	let pathOptions = $state('');
	let pickerOpen = $state(false);
	let pathIsFolder = $state(false);

	async function handlePathConnect() {
		if (!pathName || !pathValue) {
			error = 'Please fill in name and path';
			return;
		}
		const trimmedPath = pathValue.trim();
		const normalizedPath = trimmedPath.replace(/\/+$/, '');
		const isFolder = pathIsFolder;
		const detectedType = detectFileType(normalizedPath, isFolder);
		if (detectedType === 'unknown') {
			error = 'Unknown file type. Add an extension or use a folder for parquet.';
			return;
		}
		loading = true;
		error = null;

		let options: Record<string, unknown> | null = null;
		if (pathOptions.trim()) {
			try {
				const parsed = JSON.parse(pathOptions);
				if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
					throw new Error('Options must be an object');
				}
				options = parsed as Record<string, unknown>;
			} catch {
				error = 'Options must be valid JSON';
				loading = false;
				return;
			}
		}

		const result = await connectFilePath(pathName, normalizedPath, detectedType, options);
		if (result.isErr()) {
			error = result.error.message || 'Failed to create datasource';
			loading = false;
			return;
		}

		goto(resolve('/datasources'), { invalidateAll: true });
	}

	function openPicker() {
		pickerOpen = true;
	}

	function closePicker() {
		pickerOpen = false;
	}

	function handlePathSelect(next: string, isFolder: boolean) {
		pathValue = next;
		pathIsFolder = isFolder;
		pickerOpen = false;
	}

	function handlePathInput(event: Event) {
		const target = event.currentTarget as HTMLInputElement;
		pathIsFolder = target.value.trim().endsWith('/');
	}

	function browserStart() {
		const value = pathValue.trim();
		if (!value) return '';
		if (pathIsFolder) return value;
		const normalized = value.replace(/\/+$/, '');
		const index = normalized.lastIndexOf('/');
		if (index <= 0) return '';
		return normalized.slice(0, index);
	}

	async function handleDuckDBConnect() {
		if (!duckdbName || !duckdbQuery) {
			error = 'Please fill in name and query';
			return;
		}

		loading = true;
		error = null;

		const result = await connectDuckDB(
			duckdbName,
			duckdbQuery,
			duckdbPath.trim() || undefined,
			duckdbReadOnly
		);

		if (result.isErr()) {
			error = result.error.message || 'Connection failed';
			loading = false;
			return;
		}

		goto(resolve('/datasources'), { invalidateAll: true });
	}

	async function handleIcebergConnect() {
		if (!icebergName || !icebergMetadataPath) {
			error = 'Please fill in name and metadata path';
			return;
		}

		loading = true;
		error = null;

		const reader = icebergReader.trim();
		if (reader && reader !== 'native' && reader !== 'pyiceberg') {
			error = 'Reader must be "native" or "pyiceberg"';
			loading = false;
			return;
		}

		const resolvedMetadataPath = await resolveMetadataPath();
		if (!resolvedMetadataPath) {
			loading = false;
			return;
		}
		const normalizedMetadataPath = resolvedMetadataPath.replace(
			/\/metadata\/[^/]+\.metadata\.json$/,
			'/metadata'
		);

		const snapshotId = icebergSnapshotId ?? null;

		let storageOptions: Record<string, string> | null = null;
		if (icebergStorageOptions.trim()) {
			try {
				const parsed = JSON.parse(icebergStorageOptions);
				if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
					throw new Error('Storage options must be an object');
				}
				storageOptions = parsed as Record<string, string>;
			} catch {
				error = 'Storage options must be valid JSON';
				loading = false;
				return;
			}
		}

		const result = await connectIceberg(icebergName, {
			metadata_path: normalizedMetadataPath,
			snapshot_id: snapshotId,
			storage_options: storageOptions,
			reader: reader || null
		});

		if (result.isErr()) {
			error = result.error.message || 'Connection failed';
			loading = false;
			return;
		}

		goto(resolve('/datasources'), { invalidateAll: true });
	}

	async function resolveMetadataPath(): Promise<string | null> {
		const input = icebergMetadataPath.trim();
		if (!input) {
			error = 'Please provide a metadata path';
			return null;
		}
		const resolveResult = await resolveIcebergMetadata(input);
		if (resolveResult.isErr()) {
			error = resolveResult.error.message || 'Failed to resolve metadata path';
			return null;
		}
		icebergResolvedPath = resolveResult.value.metadata_path;
		return icebergResolvedPath;
	}

	async function handleDatabaseConnect() {
		if (!dbName || !connectionString || !query) {
			error = 'Please fill in all fields';
			return;
		}

		loading = true;
		error = null;

		try {
			await connectDatabase(dbName, connectionString, query);
			goto(resolve('/datasources'), { invalidateAll: true });
		} catch (err) {
			error = err instanceof Error ? err.message : 'Connection failed';
		} finally {
			loading = false;
		}
	}

	async function handleApiConnect() {
		if (!apiName || !apiUrl) {
			error = 'Please fill in all required fields';
			return;
		}

		loading = true;
		error = null;

		try {
			await connectApi(apiName, apiUrl, apiMethod);
			goto(resolve('/datasources'), { invalidateAll: true });
		} catch (err) {
			error = err instanceof Error ? err.message : 'Connection failed';
		} finally {
			loading = false;
		}
	}
</script>

<div class="datasource-new-page mx-auto box-border max-w-200 p-8">
	<header class="mb-8 flex items-center justify-between">
		<h1 class="m-0 text-2xl font-semibold">Add Data Source</h1>
		<a href={resolve('/datasources')} class="btn-secondary no-underline" data-sveltekit-reload
			>Cancel</a
		>
	</header>

	<div class="mb-8 flex gap-2 border-b-2 border-tertiary">
		<button
			class="tab -mb-0.5 border-b-2 border-transparent px-6 py-3 text-sm font-medium text-fg-muted transition-all hover:text-fg-secondary"
			class:active={activeTab === 'file'}
			onclick={() => (activeTab = 'file')}
		>
			File Upload
		</button>
		<button
			class="tab -mb-0.5 border-b-2 border-transparent px-6 py-3 text-sm font-medium text-fg-muted transition-all hover:text-fg-secondary"
			class:active={activeTab === 'database'}
			onclick={() => (activeTab = 'database')}
		>
			Database
		</button>
		<button
			class="tab -mb-0.5 border-b-2 border-transparent px-6 py-3 text-sm font-medium text-fg-muted transition-all hover:text-fg-secondary"
			class:active={activeTab === 'api'}
			onclick={() => (activeTab = 'api')}
		>
			API
		</button>
	</div>

	{#if error}
		<div class="error-box">{error}</div>
	{/if}

	<div class="card-base border p-8">
		{#if activeTab === 'file'}
			<div class="flex flex-col gap-6">
				<div class="flex flex-col gap-2">
					<span class="text-sm font-medium text-fg-secondary">Source</span>
					<div class="flex flex-col gap-3">
						<label
							class="radio-option grid cursor-pointer grid-cols-[auto_1fr] gap-x-3 border border-tertiary p-3 transition-all hover:border-tertiary hover:bg-hover"
						>
							<input
								type="radio"
								name="file-mode"
								value="upload"
								bind:group={fileMode}
								disabled={loading}
								class="row-span-2 h-4 w-4 cursor-pointer self-center"
							/>
							<span class="text-sm font-medium">Upload</span>
							<span class="text-xs text-fg-muted">Upload one or many files in one step</span>
						</label>
						<label
							class="radio-option grid cursor-pointer grid-cols-[auto_1fr] gap-x-3 border border-tertiary p-3 transition-all hover:border-tertiary hover:bg-hover"
						>
							<input
								type="radio"
								name="file-mode"
								value="path"
								bind:group={fileMode}
								disabled={loading}
								class="row-span-2 h-4 w-4 cursor-pointer self-center"
							/>
							<span class="text-sm font-medium">Path</span>
							<span class="text-xs text-fg-muted">Point to a local file or folder path</span>
						</label>
					</div>
				</div>

				{#if fileMode === 'upload'}
					<div class="flex flex-col gap-2">
						<label for="file-input" class="text-sm font-medium text-fg-secondary">Files</label>
						<input
							id="file-input"
							type="file"
							multiple
							accept=".csv,.parquet,.json,.ndjson,.jsonl,.xlsx"
							onchange={handleFileChange}
							disabled={loading}
							class="rounded-sm border border-input p-2"
						/>
						<p class="m-0 text-xs leading-relaxed text-fg-muted">
							Select one or more files. Names are derived from filenames.
						</p>
						{#if selectedFiles.length > 0}
							<div class="mt-3 border border-tertiary bg-tertiary p-3">
								<div
									class="mb-2 flex items-center justify-between border-b border-tertiary pb-2 text-sm text-fg-secondary"
								>
									<span>{selectedFiles.length} file(s) selected</span>
									<button
										type="button"
										class="btn-text border-none bg-transparent p-0 text-xs text-accent-primary hover:underline"
										onclick={clearBulkSelection}
										disabled={loading}>Clear all</button
									>
								</div>
								{#each selectedFiles as selectedFile, index (index)}
									<div class="flex items-center justify-between border-b border-tertiary p-2">
										<span
											class="flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-sm text-fg-primary"
											>{selectedFile.name}</span
										>
										<button
											type="button"
											class="btn-remove border-none bg-transparent p-1 text-lg leading-none text-fg-muted hover:text-error-fg"
											onclick={() => removeBulkFile(index)}
											disabled={loading}>x</button
										>
									</div>
								{/each}
							</div>
						{/if}
					</div>

					{#if selectedFiles.length === 1}
						<div class="flex flex-col gap-2">
							<label for="file-name" class="text-sm font-medium text-fg-secondary">Name</label>
							<input
								id="file-name"
								type="text"
								bind:value={fileName}
								placeholder="My Dataset"
								disabled={loading}
								class="input-base border px-3 py-2 text-sm"
							/>
							{#if file}
								<p class="m-0 text-sm text-fg-secondary">Selected: {file.name}</p>
							{/if}
						</div>
					{/if}

					{#if showBulkResults && bulkResults.length > 0}
						<div class="mt-4 border border-tertiary bg-tertiary p-4">
							<h4 class="m-0 mb-3 text-sm font-semibold text-fg-secondary">Upload Results</h4>
							{#each bulkResults as result (result.name)}
								<div
									class="flex items-center gap-2 border-b border-tertiary p-2 text-sm"
									class:text-success={result.success}
									class:text-error={!result.success}
								>
									<span class="w-5 text-center font-bold">
										{#if result.success}
											<Check size={12} />
										{:else}
											<X size={12} />
										{/if}
									</span>
									<span class="flex-1 overflow-hidden text-ellipsis whitespace-nowrap"
										>{result.name}</span
									>
									{#if result.error}
										<span class="max-w-50 overflow-hidden text-ellipsis text-xs text-fg-muted"
											>{result.error}</span
										>
									{/if}
								</div>
							{/each}
						</div>
					{/if}
				{:else}
					<div class="flex flex-col gap-2">
						<label for="path-name" class="text-sm font-medium text-fg-secondary">Name</label>
						<input
							id="path-name"
							type="text"
							bind:value={pathName}
							placeholder="My Dataset"
							disabled={loading}
							class="input-base border px-3 py-2 text-sm"
						/>
					</div>

					<div class="flex flex-col gap-2">
						<label for="path-value" class="text-sm font-medium text-fg-secondary">Path</label>
						<input
							id="path-value"
							type="text"
							bind:value={pathValue}
							placeholder="/path/to/data"
							oninput={handlePathInput}
							disabled={loading}
							class="input-base border px-3 py-2 text-sm"
						/>
						<div class="flex flex-wrap items-center gap-2">
							<button class="btn-secondary" type="button" onclick={openPicker} disabled={loading}
								>Browse server</button
							>
						</div>
					</div>

					<div class="flex flex-col gap-2">
						<label
							for="path-options"
							class="flex items-center gap-2 text-sm font-medium text-fg-secondary"
						>
							<span>Options (optional)</span>
							<a
								href="https://docs.pola.rs/api/python/stable/reference/io.html"
								target="_blank"
								rel="noopener noreferrer"
								class="inline-flex items-center no-underline transition-colors text-fg-muted"
							>
								<MessageCircleQuestionMark size={16} />
							</a>
						</label>
						<textarea
							id="path-options"
							bind:value={pathOptions}
							placeholder={'{"ignore_errors": true, "rechunk": false}'}
							rows="3"
							disabled={loading}
							class="resize-y border px-3 py-2 text-sm input-base"
						></textarea>
						<p class="m-0 text-xs leading-relaxed text-fg-muted">
							Advanced Polars scan options in JSON format. Common options: <code
								class="code-inline rounded px-1 py-0.5 text-xs">ignore_errors</code
							>,
							<code class="code-inline rounded px-1 py-0.5 text-xs">rechunk</code>,
							<code class="code-inline rounded px-1 py-0.5 text-xs">low_memory</code>,
							<code class="code-inline rounded px-1 py-0.5 text-xs">n_rows</code>.
						</p>
					</div>

					<button class="btn-primary" onclick={handlePathConnect} disabled={loading}>
						{loading ? 'Creating...' : 'Create datasource'}
					</button>
				{/if}

				{#if pickerOpen}
					<FileBrowser
						initialPath={browserStart()}
						onselect={handlePathSelect}
						oncancel={closePicker}
					/>
				{/if}

				{#if fileMode === 'upload' && file?.name.endsWith('.xlsx')}
					<div class="flex flex-col gap-4 border p-4 bg-tertiary border-tertiary">
						<h3 class="m-0 text-sm font-semibold text-fg-secondary">Excel Table Selection</h3>
						<div class="grid grid-cols-2 gap-4">
							<div class="flex flex-col gap-2">
								<label for="excel-sheet" class="text-sm font-medium text-fg-secondary">Sheet</label>
								<select
									id="excel-sheet"
									value={selectedSheet}
									onchange={(event) => applySheet(event.currentTarget.value)}
									disabled={loading || previewLoading || !sheetNames.length}
									class="rounded-sm border px-3 py-2 text-sm input-base"
								>
									<option value="">Select sheet</option>
									{#each sheetNames as sheet (sheet)}
										<option value={sheet}>{sheet}</option>
									{/each}
								</select>
							</div>
							<div class="flex flex-col gap-2">
								<label for="excel-table" class="text-sm font-medium text-fg-secondary"
									>Excel Table</label
								>
								<select
									id="excel-table"
									value={selectedTable}
									onchange={(event) => applyTable(event.currentTarget.value)}
									disabled={loading || previewLoading || !selectedSheet}
									class="rounded-sm border px-3 py-2 text-sm input-base"
								>
									<option value="">Manual selection</option>
									{#each tableMap[selectedSheet] ?? [] as table (table)}
										<option value={table}>{table}</option>
									{/each}
								</select>
							</div>
							<div class="flex flex-col gap-2">
								<label for="excel-range" class="text-sm font-medium text-fg-secondary"
									>Named Range</label
								>
								<select
									id="excel-range"
									value={selectedRange}
									onchange={(event) => applyNamedRange(event.currentTarget.value)}
									disabled={loading || previewLoading}
									class="rounded-sm border px-3 py-2 text-sm input-base"
								>
									<option value="">None</option>
									{#each namedRanges as range (range)}
										<option value={range}>{range}</option>
									{/each}
								</select>
							</div>
						</div>

						<div class="flex items-center gap-4">
							<div class="flex items-center gap-2">
								<input
									id="excel-header"
									type="checkbox"
									bind:checked={excelHeader}
									onchange={() => refreshPreview()}
									disabled={loading || previewLoading}
									class="h-4 w-4 cursor-pointer"
								/>
								<label for="excel-header" class="m-0 text-sm font-medium text-fg-secondary"
									>First row is header</label
								>
							</div>
							<button
								type="button"
								class="btn-secondary"
								onclick={runPreflight}
								disabled={loading || previewLoading}
							>
								{previewLoading ? 'Loading preview...' : 'Run preflight'}
							</button>
						</div>

						{#if preflightId}
							<div class="overflow-hidden border border-tertiary bg-primary">
								<div class="flex flex-wrap gap-3 px-3 py-2 text-xs bg-tertiary text-fg-muted">
									<span>Start row: {startRow + 1}</span>
									<span>Start col: {cellLabel(startCol)}</span>
									<span>End col: {cellLabel(endCol)}</span>
									{#if detectedEndRow !== null}
										<span>Detected end row: {detectedEndRow + 1}</span>
									{/if}
								</div>
								<div class="max-h-80 overflow-auto">
									<div class="preview-row grid grid-flow-col auto-cols-[minmax(120px,1fr)]">
										<div
											class="cell border-b border-r border-tertiary bg-tertiary p-2 text-left text-xs font-semibold text-fg-primary"
										></div>
										{#each previewGrid[0] ?? [] as _cell, index (index)}
											<button
												class="cell cursor-pointer border-b border-r border-tertiary bg-tertiary p-2 text-left text-xs font-semibold text-fg-primary"
												onclick={() => handleEndCol(startCol + index)}
											>
												{cellLabel(startCol + index)}
											</button>
										{/each}
									</div>
									{#each previewGrid as row, rowIndex (rowIndex)}
										<div class="preview-row grid grid-flow-col auto-cols-[minmax(120px,1fr)]">
											<button
												class="cell cursor-pointer border-b border-r border-tertiary bg-tertiary p-2 text-left text-xs font-semibold text-fg-primary"
												onclick={() => handleStartRow(startRow + rowIndex)}
											>
												{startRow + rowIndex + 1}
											</button>
											{#each row as cell, colIndex (colIndex)}
												<button
													class="cell cursor-pointer border-b border-r border-tertiary bg-transparent p-2 text-left text-xs text-fg-secondary"
													onclick={() => handleStartCol(startCol + colIndex)}
												>
													{cell ?? ''}
												</button>
											{/each}
										</div>
									{/each}
								</div>
							</div>
						{/if}
					</div>
				{/if}

				{#if fileMode === 'upload'}
					<button
						class="btn-primary"
						onclick={selectedFiles.length === 1 ? handleFileUpload : handleBulkUpload}
						disabled={loading ||
							selectedFiles.length === 0 ||
							(selectedFiles.length === 1 && !fileName)}
					>
						{loading
							? 'Uploading...'
							: selectedFiles.length === 1
								? 'Upload'
								: `Upload ${selectedFiles.length} Files`}
					</button>
				{/if}
			</div>
		{:else if activeTab === 'database'}
			<div class="flex flex-col gap-6">
				<div class="flex flex-col gap-2">
					<label for="db-type" class="text-sm font-medium text-fg-secondary">Database Type</label>
					<div class="flex flex-col gap-3">
						<label
							class="radio-option grid cursor-pointer grid-cols-[auto_1fr] gap-x-3 border p-3 transition-all border-tertiary"
						>
							<input
								type="radio"
								name="db-type"
								value="duckdb"
								bind:group={databaseType}
								disabled={loading}
								class="row-span-2 h-4 w-4 cursor-pointer self-center"
							/>
							<span class="text-sm font-medium">DuckDB</span>
							<span class="text-xs text-fg-muted">In-memory or file-based analytics database</span>
						</label>
						<label
							class="radio-option grid cursor-pointer grid-cols-[auto_1fr] gap-x-3 border p-3 transition-all border-tertiary"
						>
							<input
								type="radio"
								name="db-type"
								value="iceberg"
								bind:group={databaseType}
								disabled={loading}
								class="row-span-2 h-4 w-4 cursor-pointer self-center"
							/>
							<span class="text-sm font-medium">Iceberg</span>
							<span class="text-xs text-fg-muted"
								>Connect to an Iceberg table via metadata JSON</span
							>
						</label>
						<label
							class="radio-option grid cursor-pointer grid-cols-[auto_1fr] gap-x-3 border p-3 transition-all border-tertiary"
						>
							<input
								type="radio"
								name="db-type"
								value="other"
								bind:group={databaseType}
								disabled={loading}
								class="row-span-2 h-4 w-4 cursor-pointer self-center"
							/>
							<span class="text-sm font-medium">Other Database</span>
							<span class="text-xs text-fg-muted"
								>PostgreSQL, MySQL, SQLite via connection string</span
							>
						</label>
					</div>
				</div>

				{#if databaseType === 'duckdb'}
					<div class="flex flex-col gap-2">
						<label for="duckdb-name" class="text-sm font-medium text-fg-secondary">Name</label>
						<input
							id="duckdb-name"
							type="text"
							bind:value={duckdbName}
							placeholder="My DuckDB Data"
							disabled={loading}
							class="rounded-sm border px-3 py-2 text-sm input-base"
						/>
					</div>

					<div class="flex flex-col gap-2">
						<label for="duckdb-path" class="text-sm font-medium text-fg-secondary"
							>Database Path (optional)</label
						>
						<input
							id="duckdb-path"
							type="text"
							bind:value={duckdbPath}
							placeholder="/path/to/database.duckdb"
							disabled={loading}
							class="rounded-sm border px-3 py-2 text-sm input-base"
						/>
						<p class="m-0 text-xs text-fg-muted">Leave empty for in-memory database</p>
					</div>

					<div class="flex flex-col gap-2">
						<label for="duckdb-query" class="text-sm font-medium text-fg-secondary">Query</label>
						<textarea
							id="duckdb-query"
							bind:value={duckdbQuery}
							placeholder="SELECT * FROM read_csv_auto('data.csv')"
							rows="5"
							disabled={loading}
							class="resize-y border px-3 py-2 text-sm input-base"
						></textarea>
						<p class="m-0 text-xs text-fg-muted">
							DuckDB can read CSV, Parquet, JSON directly: read_csv_auto(), read_parquet(),
							read_json_auto()
						</p>
					</div>

					<div class="flex items-center gap-2">
						<input
							id="duckdb-readonly"
							type="checkbox"
							bind:checked={duckdbReadOnly}
							disabled={loading}
							class="h-4 w-4 cursor-pointer"
						/>
						<label for="duckdb-readonly" class="m-0 text-sm font-medium text-fg-secondary"
							>Read-only mode</label
						>
					</div>

					<button class="btn-primary" onclick={handleDuckDBConnect} disabled={loading}>
						{loading ? 'Connecting...' : 'Connect'}
					</button>
				{:else if databaseType === 'iceberg'}
					<div class="flex flex-col gap-2">
						<label for="iceberg-name" class="text-sm font-medium text-fg-secondary">Name</label>
						<input
							id="iceberg-name"
							type="text"
							bind:value={icebergName}
							placeholder="My Iceberg Table"
							disabled={loading}
							class="rounded-sm border px-3 py-2 text-sm input-base"
						/>
					</div>

					<div class="flex flex-col gap-2">
						<label for="iceberg-metadata" class="text-sm font-medium text-fg-secondary"
							>Metadata JSON Path</label
						>
						<input
							id="iceberg-metadata"
							type="text"
							bind:value={icebergMetadataPath}
							placeholder="/path/to/table/metadata or metadata.json"
							disabled={loading}
							class="rounded-sm border px-3 py-2 text-sm input-base"
						/>
						<p class="m-0 text-xs text-fg-muted">
							Point to metadata.json or a folder containing metadata/*.metadata.json
						</p>
						<div class="flex flex-wrap items-center gap-2">
							<button
								class="btn-secondary"
								type="button"
								onclick={resolveMetadataPath}
								disabled={loading}>Resolve Path</button
							>
							{#if icebergResolvedPath}
								<span
									class="break-all border px-1.5 py-0.5 text-xs text-fg-secondary bg-secondary border-tertiary"
									>{icebergResolvedPath}</span
								>
							{/if}
						</div>
					</div>

					<div class="flex flex-col gap-2">
						<label for="iceberg-snapshot" class="text-sm font-medium text-fg-secondary"
							>Snapshot ID (optional)</label
						>
						<input
							id="iceberg-snapshot"
							type="number"
							bind:value={icebergSnapshotId}
							placeholder="7051579356916758811"
							disabled={loading}
							class="rounded-sm border px-3 py-2 text-sm input-base"
						/>
					</div>

					<div class="flex flex-col gap-2">
						<label for="iceberg-reader" class="text-sm font-medium text-fg-secondary"
							>Reader Override (optional)</label
						>
						<input
							id="iceberg-reader"
							type="text"
							bind:value={icebergReader}
							placeholder="native or pyiceberg"
							disabled={loading}
							class="rounded-sm border px-3 py-2 text-sm input-base"
						/>
					</div>

					<div class="flex flex-col gap-2">
						<label for="iceberg-storage" class="text-sm font-medium text-fg-secondary"
							>Storage Options (optional)</label
						>
						<textarea
							id="iceberg-storage"
							bind:value={icebergStorageOptions}
							placeholder={'{"s3.region": "us-east-1"}'}
							rows="3"
							disabled={loading}
							class="resize-y border px-3 py-2 text-sm input-base"
						></textarea>
						<p class="m-0 text-xs text-fg-muted">JSON map of storage options for S3/GCS/Azure</p>
					</div>

					<button class="btn-primary" onclick={handleIcebergConnect} disabled={loading}>
						{loading ? 'Connecting...' : 'Connect'}
					</button>
				{:else}
					<div class="flex flex-col gap-2">
						<label for="db-name" class="text-sm font-medium text-fg-secondary">Name</label>
						<input
							id="db-name"
							type="text"
							bind:value={dbName}
							placeholder="My Database"
							disabled={loading}
							class="rounded-sm border px-3 py-2 text-sm input-base"
						/>
					</div>

					<div class="flex flex-col gap-2">
						<label for="connection-string" class="text-sm font-medium text-fg-secondary"
							>Connection String</label
						>
						<input
							id="connection-string"
							type="text"
							bind:value={connectionString}
							placeholder="postgresql://user:pass@localhost/db"
							disabled={loading}
							class="rounded-sm border px-3 py-2 text-sm input-base"
						/>
						<p class="m-0 text-xs text-fg-muted">
							Example: postgresql://user:pass@localhost/dbname
						</p>
					</div>

					<div class="flex flex-col gap-2">
						<label for="query" class="text-sm font-medium text-fg-secondary">Query</label>
						<textarea
							id="query"
							bind:value={query}
							placeholder="SELECT * FROM table"
							rows="5"
							disabled={loading}
							class="resize-y border px-3 py-2 text-sm input-base"
						></textarea>
					</div>

					<button class="btn-primary" onclick={handleDatabaseConnect} disabled={loading}>
						{loading ? 'Connecting...' : 'Connect'}
					</button>
				{/if}
			</div>
		{:else if activeTab === 'api'}
			<div class="flex flex-col gap-6">
				<div class="flex flex-col gap-2">
					<label for="api-name" class="text-sm font-medium text-fg-secondary">Name</label>
					<input
						id="api-name"
						type="text"
						bind:value={apiName}
						placeholder="My API"
						disabled={loading}
						class="rounded-sm border px-3 py-2 text-sm input-base"
					/>
				</div>

				<div class="flex flex-col gap-2">
					<label for="api-url" class="text-sm font-medium text-fg-secondary">URL</label>
					<input
						id="api-url"
						type="url"
						bind:value={apiUrl}
						placeholder="https://api.example.com/data"
						disabled={loading}
						class="rounded-sm border px-3 py-2 text-sm input-base"
					/>
				</div>

				<div class="flex flex-col gap-2">
					<label for="api-method" class="text-sm font-medium text-fg-secondary">Method</label>
					<select
						id="api-method"
						bind:value={apiMethod}
						disabled={loading}
						class="rounded-sm border px-3 py-2 text-sm input-base"
					>
						<option value="GET">GET</option>
						<option value="POST">POST</option>
					</select>
				</div>

				<button class="btn-primary" onclick={handleApiConnect} disabled={loading}>
					{loading ? 'Connecting...' : 'Connect'}
				</button>
			</div>
		{/if}
	</div>
</div>
