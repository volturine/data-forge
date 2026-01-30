<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { uploadFile, connectDatabase, connectApi, connectDuckDB } from '$lib/api/datasource';
	import { preflightExcel, previewExcel, confirmExcel } from '$lib/api/excel';
	import type { ExcelPreflightResponse, ExcelPreviewResponse } from '$lib/api/excel';
	import type { CSVOptions } from '$lib/types/datasource';

	type Tab = 'file' | 'database' | 'api';
	type DatabaseType = 'duckdb' | 'other';

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

	// CSV options state
	let delimiter = $state(',');
	let quoteChar = $state('"');
	let hasHeader = $state(true);
	let skipRows = $state(0);
	let encoding = $state('utf8');
	let showCsvOptions = $state(false);

	// DuckDB state
	let duckdbName = $state('');
	let duckdbPath = $state('');
	let duckdbQuery = $state('');
	let duckdbReadOnly = $state(true);

	// Generic database state
	let dbName = $state('');
	let connectionString = $state('');
	let query = $state('');

	// API state
	let apiName = $state('');
	let apiUrl = $state('');
	let apiMethod = $state('GET');

	function handleFileChange(event: Event) {
		const target = event.target as HTMLInputElement;
		if (target.files && target.files.length > 0) {
			file = target.files[0];
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
			if (!fileName) {
				fileName = file.name.replace(/\.[^/.]+$/, '');
			}
			if (file.name.endsWith('.csv')) {
				showCsvOptions = true;
			} else {
				showCsvOptions = false;
			}
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

		let csvOptions: CSVOptions | undefined;
		if (file.name.endsWith('.csv')) {
			csvOptions = {
				delimiter,
				quote_char: quoteChar,
				has_header: hasHeader,
				skip_rows: skipRows,
				encoding
			};
		}

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
				await uploadFile(file, fileName, csvOptions);
				goto(resolve('/datasources'), { invalidateAll: true });
			}
		} catch (err) {
			error = err instanceof Error ? err.message : 'Upload failed';
		} finally {
			loading = false;
		}
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
					<label for="file-name">Name</label>
					<input
						id="file-name"
						type="text"
						bind:value={fileName}
						placeholder="My Dataset"
						disabled={loading}
					/>
				</div>

				<div class="form-group">
					<label for="file-input">File</label>
					<input id="file-input" type="file" onchange={handleFileChange} disabled={loading} />
					{#if file}
						<p class="file-info">Selected: {file.name}</p>
					{/if}
				</div>

				{#if showCsvOptions}
					<div class="csv-options">
						<h3>CSV Options</h3>
						<div class="form-row">
							<div class="form-group">
								<label for="delimiter">Delimiter</label>
								<select id="delimiter" bind:value={delimiter} disabled={loading}>
									<option value=",">Comma (,)</option>
									<option value=";">Semicolon (;)</option>
									<option value="\t">Tab (\t)</option>
									<option value="|">Pipe (|)</option>
								</select>
							</div>

							<div class="form-group">
								<label for="quote-char">Quote Character</label>
								<input
									id="quote-char"
									type="text"
									bind:value={quoteChar}
									maxlength="1"
									disabled={loading}
								/>
							</div>
						</div>

						<div class="form-row">
							<div class="form-group checkbox-group">
								<input
									id="has-header"
									type="checkbox"
									bind:checked={hasHeader}
									disabled={loading}
								/>
								<label for="has-header">Has Header Row</label>
							</div>

							<div class="form-group">
								<label for="skip-rows">Skip Rows</label>
								<input
									id="skip-rows"
									type="number"
									bind:value={skipRows}
									min="0"
									disabled={loading}
								/>
							</div>
						</div>

						<div class="form-group">
							<label for="encoding">Encoding</label>
							<select id="encoding" bind:value={encoding} disabled={loading}>
								<option value="utf8">UTF8</option>
								<option value="utf8-lossy">UTF8 (lossy)</option>
								<option value="latin1">Latin-1 (ISO-8859-1)</option>
								<option value="cp1252">Windows-1252</option>
							</select>
						</div>
					</div>
				{/if}

				{#if file?.name.endsWith('.xlsx')}
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

				<button class="btn-primary" onclick={handleFileUpload} disabled={loading || !file}>
					{loading ? 'Uploading...' : 'Upload'}
				</button>
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
	input[type='number'],
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
	input[type='number']:focus,
	select:focus,
	textarea:focus {
		outline: none;
		border-color: var(--border-focus);
		box-shadow: 0 0 0 3px var(--accent-bg);
	}
	input[type='text']:disabled,
	input[type='url']:disabled,
	input[type='number']:disabled,
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
	.hint,
	.file-info {
		font-size: var(--text-xs);
		color: var(--fg-muted);
		margin: 0;
	}
	.file-info {
		font-size: var(--text-sm);
		color: var(--fg-secondary);
	}
	.csv-options {
		background-color: var(--bg-tertiary);
		padding: var(--space-4);
		border-radius: var(--radius-md);
		border: 1px solid var(--border-primary);
	}
	.csv-options h3 {
		font-size: var(--text-sm);
		font-weight: var(--font-semibold);
		margin: 0 0 var(--space-4) 0;
		color: var(--fg-secondary);
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
</style>
