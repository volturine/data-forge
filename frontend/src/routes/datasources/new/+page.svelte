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
	import { MessageCircleQuestionMark } from 'lucide-svelte';

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

<div class="container">
	<header>
		<h1>Add Data Source</h1>
		<a href={resolve('/datasources')} class="btn-secondary" data-sveltekit-reload>Cancel</a>
	</header>

	<div class="tabs">
		<button class="tab" class:active={activeTab === 'file'} onclick={() => (activeTab = 'file')}>
			File Upload
		</button>
		<button
			class="tab"
			class:active={activeTab === 'database'}
			onclick={() => (activeTab = 'database')}
		>
			Database
		</button>
		<button class="tab" class:active={activeTab === 'api'} onclick={() => (activeTab = 'api')}>
			API
		</button>
	</div>

	{#if error}
		<div class="error-box">{error}</div>
	{/if}

	<div class="content">
		{#if activeTab === 'file'}
			<div class="form">
				<div class="form-group">
					<span class="form-label">Source</span>
					<div class="radio-group">
						<label class="radio-option">
							<input
								type="radio"
								name="file-mode"
								value="upload"
								bind:group={fileMode}
								disabled={loading}
							/>
							<span class="radio-label">Upload</span>
							<span class="radio-desc">Upload one or many files in one step</span>
						</label>
						<label class="radio-option">
							<input
								type="radio"
								name="file-mode"
								value="path"
								bind:group={fileMode}
								disabled={loading}
							/>
							<span class="radio-label">Path</span>
							<span class="radio-desc">Point to a local file or folder path</span>
						</label>
					</div>
				</div>

				{#if fileMode === 'upload'}
					<div class="form-group">
						<label for="file-input">Files</label>
						<input
							id="file-input"
							type="file"
							multiple
							accept=".csv,.parquet,.json,.ndjson,.jsonl,.xlsx"
							onchange={handleFileChange}
							disabled={loading}
						/>
						<p class="hint">Select one or more files. Names are derived from filenames.</p>
						{#if selectedFiles.length > 0}
							<div class="file-list">
								<div class="file-list-header">
									<span>{selectedFiles.length} file(s) selected</span>
									<button
										type="button"
										class="btn-text"
										onclick={clearBulkSelection}
										disabled={loading}
									>
										Clear all
									</button>
								</div>
								{#each selectedFiles as selectedFile, index (index)}
									<div class="file-item">
										<span class="file-name">{selectedFile.name}</span>
										<button
											type="button"
											class="btn-remove"
											onclick={() => removeBulkFile(index)}
											disabled={loading}
										>
											×
										</button>
									</div>
								{/each}
							</div>
						{/if}
					</div>

					{#if selectedFiles.length === 1}
						<div class="form-group">
							<label for="file-name">Name</label>
							<input
								id="file-name"
								type="text"
								bind:value={fileName}
								placeholder="My Dataset"
								disabled={loading}
							/>
							{#if file}
								<p class="file-info">Selected: {file.name}</p>
							{/if}
						</div>
					{/if}

					{#if showBulkResults && bulkResults.length > 0}
						<div class="bulk-results">
							<h4>Upload Results</h4>
							{#each bulkResults as result (result.name)}
								<div
									class="result-item"
									class:success={result.success}
									class:error={!result.success}
								>
									<span class="result-icon">{result.success ? '✓' : '✗'}</span>
									<span class="result-name">{result.name}</span>
									{#if result.error}
										<span class="result-error">{result.error}</span>
									{/if}
								</div>
							{/each}
						</div>
					{/if}
				{:else}
					<div class="form-group">
						<label for="path-name">Name</label>
						<input
							id="path-name"
							type="text"
							bind:value={pathName}
							placeholder="My Dataset"
							disabled={loading}
						/>
					</div>

					<div class="form-group">
						<label for="path-value">Path</label>
						<input
							id="path-value"
							type="text"
							bind:value={pathValue}
							placeholder="/path/to/data"
							oninput={handlePathInput}
							disabled={loading}
						/>
						<div class="path-actions">
							<button class="btn-secondary" type="button" onclick={openPicker} disabled={loading}>
								Browse server
							</button>
						</div>
					</div>

					<div class="form-group">
						<label for="path-options" class="label-with-help">
							<span>Options (optional)</span>
							<span class="help-icon" title="Click to view Polars documentation">
								<a
									href="https://docs.pola.rs/api/python/stable/reference/io.html"
									target="_blank"
									rel="noopener noreferrer"
									class="help-link"
								>
									<MessageCircleQuestionMark size={16} />
								</a>
							</span>
						</label>
						<textarea
							id="path-options"
							bind:value={pathOptions}
							placeholder={'{"ignore_errors": true, "rechunk": false}'}
							rows="3"
							disabled={loading}
						></textarea>
						<p class="hint">
							Advanced Polars scan options in JSON format. Common options: <code>ignore_errors</code
							>,
							<code>rechunk</code>, <code>low_memory</code>, <code>n_rows</code>.
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
					<div class="excel-preflight">
						<h3>Excel Table Selection</h3>
						<div class="form-row">
							<div class="form-group">
								<label for="excel-sheet">Sheet</label>
								<select
									id="excel-sheet"
									value={selectedSheet}
									onchange={(event) => applySheet(event.currentTarget.value)}
									disabled={loading || previewLoading || !sheetNames.length}
								>
									<option value="">Select sheet</option>
									{#each sheetNames as sheet (sheet)}
										<option value={sheet}>{sheet}</option>
									{/each}
								</select>
							</div>
							<div class="form-group">
								<label for="excel-table">Excel Table</label>
								<select
									id="excel-table"
									value={selectedTable}
									onchange={(event) => applyTable(event.currentTarget.value)}
									disabled={loading || previewLoading || !selectedSheet}
								>
									<option value="">Manual selection</option>
									{#each tableMap[selectedSheet] ?? [] as table (table)}
										<option value={table}>{table}</option>
									{/each}
								</select>
							</div>
							<div class="form-group">
								<label for="excel-range">Named Range</label>
								<select
									id="excel-range"
									value={selectedRange}
									onchange={(event) => applyNamedRange(event.currentTarget.value)}
									disabled={loading || previewLoading}
								>
									<option value="">None</option>
									{#each namedRanges as range (range)}
										<option value={range}>{range}</option>
									{/each}
								</select>
							</div>
						</div>

						<div class="form-row">
							<div class="form-group checkbox-group">
								<input
									id="excel-header"
									type="checkbox"
									bind:checked={excelHeader}
									onchange={() => refreshPreview()}
									disabled={loading || previewLoading}
								/>
								<label for="excel-header">First row is header</label>
							</div>
							<button
								type="button"
								class="btn-secondary"
								onclick={runPreflight}
								disabled={loading || previewLoading}
							>
								{previewLoading ? 'Loading preview…' : 'Run preflight'}
							</button>
						</div>

						{#if preflightId}
							<div class="preview-panel">
								<div class="preview-meta">
									<span>Start row: {startRow + 1}</span>
									<span>Start col: {cellLabel(startCol)}</span>
									<span>End col: {cellLabel(endCol)}</span>
									{#if detectedEndRow !== null}
										<span>Detected end row: {detectedEndRow + 1}</span>
									{/if}
								</div>
								<div class="preview-grid">
									<div class="preview-row header">
										<div class="cell corner"></div>
										{#each previewGrid[0] ?? [] as _cell, index (index)}
											<button class="cell header" onclick={() => handleEndCol(startCol + index)}>
												{cellLabel(startCol + index)}
											</button>
										{/each}
									</div>
									{#each previewGrid as row, rowIndex (rowIndex)}
										<div class="preview-row">
											<button
												class="cell header"
												onclick={() => handleStartRow(startRow + rowIndex)}
											>
												{startRow + rowIndex + 1}
											</button>
											{#each row as cell, colIndex (colIndex)}
												<button class="cell" onclick={() => handleStartCol(startCol + colIndex)}>
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
			<div class="form">
				<div class="form-group">
					<label for="db-type">Database Type</label>
					<div class="radio-group">
						<label class="radio-option">
							<input
								type="radio"
								name="db-type"
								value="duckdb"
								bind:group={databaseType}
								disabled={loading}
							/>
							<span class="radio-label">DuckDB</span>
							<span class="radio-desc">In-memory or file-based analytics database</span>
						</label>
						<label class="radio-option">
							<input
								type="radio"
								name="db-type"
								value="iceberg"
								bind:group={databaseType}
								disabled={loading}
							/>
							<span class="radio-label">Iceberg</span>
							<span class="radio-desc">Connect to an Iceberg table via metadata JSON</span>
						</label>
						<label class="radio-option">
							<input
								type="radio"
								name="db-type"
								value="other"
								bind:group={databaseType}
								disabled={loading}
							/>
							<span class="radio-label">Other Database</span>
							<span class="radio-desc">PostgreSQL, MySQL, SQLite via connection string</span>
						</label>
					</div>
				</div>

				{#if databaseType === 'duckdb'}
					<div class="form-group">
						<label for="duckdb-name">Name</label>
						<input
							id="duckdb-name"
							type="text"
							bind:value={duckdbName}
							placeholder="My DuckDB Data"
							disabled={loading}
						/>
					</div>

					<div class="form-group">
						<label for="duckdb-path">Database Path (optional)</label>
						<input
							id="duckdb-path"
							type="text"
							bind:value={duckdbPath}
							placeholder="/path/to/database.duckdb"
							disabled={loading}
						/>
						<p class="hint">Leave empty for in-memory database</p>
					</div>

					<div class="form-group">
						<label for="duckdb-query">Query</label>
						<textarea
							id="duckdb-query"
							bind:value={duckdbQuery}
							placeholder="SELECT * FROM read_csv_auto('data.csv')"
							rows="5"
							disabled={loading}
						></textarea>
						<p class="hint">
							DuckDB can read CSV, Parquet, JSON directly: read_csv_auto(), read_parquet(),
							read_json_auto()
						</p>
					</div>

					<div class="form-group checkbox-group">
						<input
							id="duckdb-readonly"
							type="checkbox"
							bind:checked={duckdbReadOnly}
							disabled={loading}
						/>
						<label for="duckdb-readonly">Read-only mode</label>
					</div>

					<button class="btn-primary" onclick={handleDuckDBConnect} disabled={loading}>
						{loading ? 'Connecting...' : 'Connect'}
					</button>
				{:else if databaseType === 'iceberg'}
					<div class="form-group">
						<label for="iceberg-name">Name</label>
						<input
							id="iceberg-name"
							type="text"
							bind:value={icebergName}
							placeholder="My Iceberg Table"
							disabled={loading}
						/>
					</div>

					<div class="form-group">
						<label for="iceberg-metadata">Metadata JSON Path</label>
						<input
							id="iceberg-metadata"
							type="text"
							bind:value={icebergMetadataPath}
							placeholder="/path/to/table/metadata or metadata.json"
							disabled={loading}
						/>
						<p class="hint">
							Point to metadata.json or a folder containing metadata/*.metadata.json
						</p>
						<div class="resolve-row">
							<button
								class="btn-secondary"
								type="button"
								onclick={resolveMetadataPath}
								disabled={loading}
							>
								Resolve Path
							</button>
							{#if icebergResolvedPath}
								<span class="resolve-value">{icebergResolvedPath}</span>
							{/if}
						</div>
					</div>

					<div class="form-group">
						<label for="iceberg-snapshot">Snapshot ID (optional)</label>
						<input
							id="iceberg-snapshot"
							type="number"
							bind:value={icebergSnapshotId}
							placeholder="7051579356916758811"
							disabled={loading}
						/>
					</div>

					<div class="form-group">
						<label for="iceberg-reader">Reader Override (optional)</label>
						<input
							id="iceberg-reader"
							type="text"
							bind:value={icebergReader}
							placeholder="native or pyiceberg"
							disabled={loading}
						/>
					</div>

					<div class="form-group">
						<label for="iceberg-storage">Storage Options (optional)</label>
						<textarea
							id="iceberg-storage"
							bind:value={icebergStorageOptions}
							placeholder={'{"s3.region": "us-east-1"}'}
							rows="3"
							disabled={loading}
						></textarea>
						<p class="hint">JSON map of storage options for S3/GCS/Azure</p>
					</div>

					<button class="btn-primary" onclick={handleIcebergConnect} disabled={loading}>
						{loading ? 'Connecting...' : 'Connect'}
					</button>
				{:else}
					<div class="form-group">
						<label for="db-name">Name</label>
						<input
							id="db-name"
							type="text"
							bind:value={dbName}
							placeholder="My Database"
							disabled={loading}
						/>
					</div>

					<div class="form-group">
						<label for="connection-string">Connection String</label>
						<input
							id="connection-string"
							type="text"
							bind:value={connectionString}
							placeholder="postgresql://user:pass@localhost/db"
							disabled={loading}
						/>
						<p class="hint">Example: postgresql://user:pass@localhost/dbname</p>
					</div>

					<div class="form-group">
						<label for="query">Query</label>
						<textarea
							id="query"
							bind:value={query}
							placeholder="SELECT * FROM table"
							rows="5"
							disabled={loading}
						></textarea>
					</div>

					<button class="btn-primary" onclick={handleDatabaseConnect} disabled={loading}>
						{loading ? 'Connecting...' : 'Connect'}
					</button>
				{/if}
			</div>
		{:else if activeTab === 'api'}
			<div class="form">
				<div class="form-group">
					<label for="api-name">Name</label>
					<input
						id="api-name"
						type="text"
						bind:value={apiName}
						placeholder="My API"
						disabled={loading}
					/>
				</div>

				<div class="form-group">
					<label for="api-url">URL</label>
					<input
						id="api-url"
						type="url"
						bind:value={apiUrl}
						placeholder="https://api.example.com/data"
						disabled={loading}
					/>
				</div>

				<div class="form-group">
					<label for="api-method">Method</label>
					<select id="api-method" bind:value={apiMethod} disabled={loading}>
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

<style>
	.container {
		max-width: 800px;
		margin: 0 auto;
		padding: var(--space-8);
		min-height: 100%;
		box-sizing: border-box;
	}
	header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: var(--space-8);
	}
	h1 {
		font-size: var(--text-2xl);
		font-weight: var(--font-semibold);
		margin: 0;
	}
	.btn-secondary {
		text-decoration: none;
	}
	.tabs {
		display: flex;
		gap: var(--space-2);
		border-bottom: 2px solid var(--border-primary);
		margin-bottom: var(--space-8);
	}
	.tab {
		padding: var(--space-3) var(--space-6);
		background: none;
		border: none;
		border-bottom: 2px solid transparent;
		cursor: pointer;
		font-size: var(--text-sm);
		font-weight: var(--font-medium);
		color: var(--fg-muted);
		margin-bottom: -2px;
		transition: all var(--transition);
	}
	.tab:hover {
		color: var(--fg-secondary);
	}
	.tab.active {
		color: var(--accent-primary);
		border-bottom-color: var(--accent-primary);
	}
	.content {
		background-color: var(--card-bg);
		padding: var(--space-8);
		border-radius: var(--radius-md);
		box-shadow: var(--card-shadow);
	}
	.form {
		display: flex;
		flex-direction: column;
		gap: var(--space-6);
	}
	.form-group {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	label {
		font-weight: var(--font-medium);
		font-size: var(--text-sm);
		color: var(--fg-secondary);
	}
	input[type='text'],
	input[type='url'],
	select,
	textarea {
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--input-border);
		border-radius: var(--radius-sm);
		font-size: var(--text-sm);
		background-color: var(--input-bg);
		transition: border-color var(--transition);
	}
	input[type='text']:focus,
	input[type='url']:focus,
	select:focus,
	textarea:focus {
		outline: none;
		border-color: var(--border-focus);
		box-shadow: 0 0 0 3px var(--accent-bg);
	}
	input[type='text']:disabled,
	input[type='url']:disabled,
	select:disabled,
	textarea:disabled {
		background: var(--bg-tertiary);
		cursor: not-allowed;
	}
	input[type='file'] {
		padding: var(--space-2);
		border: 1px solid var(--input-border);
		border-radius: var(--radius-sm);
	}
	textarea {
		resize: vertical;
	}
	.path-actions {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex-wrap: wrap;
	}
	.resolve-row {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex-wrap: wrap;
	}
	.resolve-value {
		font-size: var(--text-xs);
		color: var(--fg-secondary);
		background: var(--bg-secondary);
		border: 1px solid var(--border-secondary);
		padding: 2px 6px;
		border-radius: var(--radius-sm);
		word-break: break-all;
	}
	.hint,
	.file-info {
		font-size: var(--text-xs);
		color: var(--fg-muted);
		margin: 0;
		line-height: 1.5;
	}
	.hint code {
		font-family: var(--font-mono);
		background: var(--bg-tertiary);
		padding: 1px 4px;
		border-radius: 3px;
		font-size: 0.9em;
		color: var(--fg-secondary);
	}
	.file-info {
		font-size: var(--text-sm);
		color: var(--fg-secondary);
	}
	.label-with-help {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.help-icon {
		display: inline-flex;
		align-items: center;
		flex-shrink: 0;
	}
	.help-link {
		display: inline-flex;
		align-items: center;
		color: var(--fg-muted);
		transition: color var(--transition);
		text-decoration: none;
	}
	.help-link:hover {
		color: var(--accent-primary);
	}
	.form-row {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-4);
	}
	.excel-preflight {
		background-color: var(--bg-tertiary);
		padding: var(--space-4);
		border-radius: var(--radius-md);
		border: 1px solid var(--border-primary);
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}
	.excel-preflight h3 {
		margin: 0;
		font-size: var(--text-sm);
		font-weight: var(--font-semibold);
		color: var(--fg-secondary);
	}
	.preview-panel {
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		overflow: hidden;
		background: var(--bg-primary);
	}
	.preview-meta {
		display: flex;
		gap: var(--space-3);
		padding: var(--space-2) var(--space-3);
		background: var(--bg-tertiary);
		font-size: var(--text-xs);
		color: var(--fg-muted);
		flex-wrap: wrap;
	}
	.preview-grid {
		overflow: auto;
		max-height: 320px;
	}
	.preview-row {
		display: grid;
		grid-auto-flow: column;
		grid-auto-columns: minmax(120px, 1fr);
	}
	.cell {
		padding: var(--space-2);
		border-bottom: 1px solid var(--border-primary);
		border-right: 1px solid var(--border-primary);
		background: transparent;
		text-align: left;
		font-size: var(--text-xs);
		color: var(--fg-secondary);
		cursor: pointer;
	}
	.cell.header {
		background: var(--bg-tertiary);
		font-weight: var(--font-semibold);
		color: var(--fg-primary);
	}
	.cell.corner {
		background: var(--bg-tertiary);
	}
	.checkbox-group {
		flex-direction: row;
		align-items: center;
		gap: var(--space-2);
	}
	.checkbox-group input {
		width: auto;
	}
	.checkbox-group label {
		margin: 0;
	}
	input[type='checkbox'] {
		width: 1rem;
		height: 1rem;
		cursor: pointer;
	}
	.radio-group {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.radio-option {
		display: grid;
		grid-template-columns: auto 1fr;
		grid-template-rows: auto auto;
		gap: 0 var(--space-3);
		padding: var(--space-3) var(--space-4);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		cursor: pointer;
		transition: all var(--transition);
	}
	.radio-option:hover {
		background: var(--bg-hover);
		border-color: var(--border-secondary);
	}
	.radio-option:has(input:checked) {
		background: var(--accent-bg);
		border-color: var(--accent-border);
	}
	.radio-option input[type='radio'] {
		grid-row: span 2;
		align-self: center;
		width: 1rem;
		height: 1rem;
		cursor: pointer;
	}
	.radio-label {
		font-weight: var(--font-medium);
		font-size: var(--text-sm);
	}
	.radio-desc {
		font-size: var(--text-xs);
		color: var(--fg-muted);
	}

	/* Bulk upload styles */
	.file-list {
		background-color: var(--bg-tertiary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		padding: var(--space-3);
		margin-top: var(--space-3);
	}
	.file-list-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: var(--space-2);
		padding-bottom: var(--space-2);
		border-bottom: 1px solid var(--border-primary);
		font-size: var(--text-sm);
		color: var(--fg-secondary);
	}
	.btn-text {
		background: transparent;
		border: none;
		color: var(--accent-primary);
		font-size: var(--text-xs);
		cursor: pointer;
		padding: 0;
	}
	.btn-text:hover {
		text-decoration: underline;
	}
	.btn-text:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.file-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--space-2);
		border-bottom: 1px solid var(--border-primary);
	}
	.file-item:last-child {
		border-bottom: none;
	}
	.file-name {
		font-size: var(--text-sm);
		color: var(--fg-primary);
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.btn-remove {
		background: transparent;
		border: none;
		color: var(--fg-muted);
		font-size: var(--text-lg);
		cursor: pointer;
		padding: var(--space-1);
		line-height: 1;
	}
	.btn-remove:hover {
		color: var(--error-fg);
	}
	.btn-remove:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	/* Bulk results */
	.bulk-results {
		background-color: var(--bg-tertiary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		padding: var(--space-4);
		margin-top: var(--space-4);
	}
	.bulk-results h4 {
		margin: 0 0 var(--space-3) 0;
		font-size: var(--text-sm);
		font-weight: var(--font-semibold);
		color: var(--fg-secondary);
	}
	.result-item {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-2);
		border-bottom: 1px solid var(--border-primary);
		font-size: var(--text-sm);
	}
	.result-item:last-child {
		border-bottom: none;
	}
	.result-item.success {
		color: var(--success-fg);
	}
	.result-item.error {
		color: var(--error-fg);
	}
	.result-icon {
		font-weight: var(--font-bold);
		width: 20px;
		text-align: center;
	}
	.result-name {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.result-error {
		font-size: var(--text-xs);
		color: var(--fg-muted);
		max-width: 200px;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	/* Form label for non-control labels */
	.form-label {
		font-weight: var(--font-medium);
		font-size: var(--text-sm);
		color: var(--fg-secondary);
	}
</style>
