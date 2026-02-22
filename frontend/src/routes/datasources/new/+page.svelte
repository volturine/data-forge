<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { useQueryClient } from '@tanstack/svelte-query';
	import {
		uploadFile,
		uploadBulkFiles,
		connectDatabase,
		connectIcebergPath
	} from '$lib/api/datasource';
	import { confirmExcel } from '$lib/api/excel';
	import ExcelTableSelector from '$lib/components/common/ExcelTableSelector.svelte';
	import type { BulkUploadResult } from '$lib/api/datasource';
	import FileBrowser from '$lib/components/common/FileBrowser.svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { Check, X } from 'lucide-svelte';

	type Tab = 'file' | 'database' | 'path';

	const queryClient = useQueryClient();
	let activeTab = $state<Tab>('file');
	let loading = $state(false);
	let error = $state<string | null>(null);

	// File upload state
	let file = $state<File | null>(null);
	let fileName = $state('');
	let preflightId = $state<string | null>(null);
	let excelConfig = $state({
		sheet_name: '',
		table_name: '',
		named_range: '',
		cell_range: '',
		start_row: 0,
		start_col: 0,
		end_col: 0,
		end_row: null as number | null,
		has_header: true
	});

	// External database state
	let dbName = $state('');
	let connectionString = $state('');
	let query = $state('');

	// Upload state
	let selectedFiles = $state<File[]>([]);
	let bulkResults = $state<BulkUploadResult[]>([]);
	let showBulkResults = $state(false);
	const allowedFileTypes = new SvelteSet(['csv', 'xlsx']);
	let batchType = $state<'csv' | 'excel' | null>(null);
	let csvDelimiter = $state(',');
	let csvQuoteChar = $state('"');
	let csvEncoding = $state('utf8');
	let csvSkipRows = $state(0);
	let csvHasHeader = $state(true);

	function resetExcelState() {
		preflightId = null;
		excelConfig = {
			sheet_name: '',
			table_name: '',
			named_range: '',
			cell_range: '',
			start_row: 0,
			start_col: 0,
			end_col: 0,
			end_row: null,
			has_header: true
		};
	}

	function applySelection(files: File[]) {
		selectedFiles = files;
		showBulkResults = false;
		bulkResults = [];
		resetExcelState();
		batchType = null;
		if (files.length === 0) {
			file = null;
			fileName = '';
			return;
		}
		const types = new SvelteSet<string>();
		for (const next of files) {
			const ext = next.name.split('.').pop()?.toLowerCase() ?? '';
			if (!allowedFileTypes.has(ext)) {
				error = `Unsupported file type: .${ext}`;
				selectedFiles = [];
				file = null;
				fileName = '';
				return;
			}
			types.add(ext);
		}
		if (types.size > 1) {
			error = 'Bulk upload must use a single file type per batch';
			selectedFiles = [];
			file = null;
			fileName = '';
			return;
		}
		batchType = types.has('csv') ? 'csv' : types.has('xlsx') ? 'excel' : null;
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
		error = null;
		applySelection(Array.from(target.files));
	}

	async function handleBulkUpload() {
		if (selectedFiles.length === 0) {
			error = 'Please select at least one file';
			return;
		}
		if (!batchType) {
			error = 'Select a CSV or Excel batch to upload';
			return;
		}

		loading = true;
		error = null;
		showBulkResults = false;

		const csvOptions =
			batchType === 'csv'
				? {
						delimiter: csvDelimiter,
						quote_char: csvQuoteChar,
						has_header: csvHasHeader,
						skip_rows: csvSkipRows,
						encoding: csvEncoding
					}
				: undefined;
		const result = await uploadBulkFiles(selectedFiles, csvOptions);
		result.match(
			(response: import('$lib/api/datasource').BulkUploadResponse) => {
				bulkResults = response.results;
				showBulkResults = true;
				if (response.successful === response.total) {
					selectedFiles = [];
					queryClient.invalidateQueries({ queryKey: ['datasources'] });
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
		batchType = null;
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
			batchType = null;
			resetExcelState();
		}
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
				const params: Record<string, unknown> = {
					sheet_name: excelConfig.sheet_name || undefined,
					start_row: excelConfig.start_row,
					start_col: excelConfig.start_col,
					end_col: excelConfig.end_col,
					has_header: excelConfig.has_header,
					table_name: excelConfig.table_name || undefined,
					named_range: excelConfig.named_range || undefined,
					cell_range: excelConfig.cell_range || undefined
				};
				if (excelConfig.end_row !== null) {
					params.end_row = excelConfig.end_row;
				}
				const result = await confirmExcel(
					preflightId,
					fileName,
					params as Parameters<typeof confirmExcel>[2]
				);
				if (result.isErr()) {
					error = result.error.message || 'Upload failed';
					loading = false;
					return;
				}
				queryClient.invalidateQueries({ queryKey: ['datasources'] });
				goto(resolve('/datasources'), { invalidateAll: true });
			} else {
				await uploadFile(file, fileName, {
					delimiter: csvDelimiter,
					quote_char: csvQuoteChar,
					has_header: csvHasHeader,
					skip_rows: csvSkipRows,
					encoding: csvEncoding
				});
				queryClient.invalidateQueries({ queryKey: ['datasources'] });
				goto(resolve('/datasources'), { invalidateAll: true });
			}
		} catch (err) {
			error = err instanceof Error ? err.message : 'Upload failed';
		} finally {
			loading = false;
		}
	}

	// Iceberg path datasource
	let pathName = $state('');
	let pathValue = $state('');
	let pickerOpen = $state(false);

	async function handlePathConnect() {
		if (!pathName || !pathValue) {
			error = 'Please fill in name and path';
			return;
		}
		const trimmedPath = pathValue.trim().replace(/\/+$/, '');
		if (!trimmedPath) {
			error = 'Please provide the datasource root path';
			return;
		}
		const parts = trimmedPath.split('/').filter((part) => part.length > 0);
		const lastPart = parts[parts.length - 1] ?? '';
		if (!/^[0-9a-fA-F-]{36}$/.test(lastPart)) {
			error = 'Path must point to the datasource UUID directory';
			return;
		}
		loading = true;
		error = null;

		const result = await connectIcebergPath(pathName, trimmedPath);
		if (result.isErr()) {
			error = result.error.message || 'Failed to create datasource';
			loading = false;
			return;
		}
		queryClient.invalidateQueries({ queryKey: ['datasources'] });
		goto(resolve('/datasources'), { invalidateAll: true });
	}

	function openPicker() {
		pickerOpen = true;
	}

	function closePicker() {
		pickerOpen = false;
	}

	function handlePathSelect(next: string) {
		pathValue = next.replace(/\/+$/, '');
		pickerOpen = false;
	}

	function browserStart() {
		const value = pathValue.trim();
		if (!value) return '';
		return value;
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
			queryClient.invalidateQueries({ queryKey: ['datasources'] });
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
			class="tab -mb-0.5 border-b-2 border-transparent px-6 py-3 text-sm font-medium text-fg-muted hover:text-fg-secondary"
			class:active={activeTab === 'file'}
			onclick={() => (activeTab = 'file')}
		>
			File Upload
		</button>
		<button
			class="tab -mb-0.5 border-b-2 border-transparent px-6 py-3 text-sm font-medium text-fg-muted hover:text-fg-secondary"
			class:active={activeTab === 'database'}
			onclick={() => (activeTab = 'database')}
		>
			External DB
		</button>
		<button
			class="tab -mb-0.5 border-b-2 border-transparent px-6 py-3 text-sm font-medium text-fg-muted hover:text-fg-secondary"
			class:active={activeTab === 'path'}
			onclick={() => (activeTab = 'path')}
		>
			Iceberg Path
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
						<div class="border border-tertiary bg-secondary p-3">
							<div class="text-sm font-medium">Upload</div>
							<div class="text-xs text-fg-muted">Upload one or many files in one step</div>
						</div>
					</div>
				</div>

				<div class="flex flex-col gap-2">
					<label for="file-input" class="text-sm font-medium text-fg-secondary">Files</label>
					<input
						id="file-input"
						type="file"
						multiple
						accept=".csv,.xlsx"
						onchange={handleFileChange}
						disabled={loading}
						class="border border-input p-2"
					/>
					<p class="m-0 text-xs leading-relaxed text-fg-muted">
						Select one or more CSV or Excel files (one type per batch). Names are derived from
						filenames.
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

				{#if batchType === 'csv'}
					<div class="flex flex-col gap-3 border border-tertiary bg-tertiary p-4">
						<h3 class="m-0 text-sm font-semibold text-fg-secondary">CSV Options</h3>
						<div class="grid grid-cols-2 gap-3">
							<div class="flex flex-col gap-1.5">
								<label for="csv-delimiter" class="text-xs font-medium text-fg-secondary"
									>Delimiter</label
								>
								<select
									id="csv-delimiter"
									bind:value={csvDelimiter}
									disabled={loading}
									class="input-base border px-3 py-2 text-sm"
								>
									<option value=",">Comma (,)</option>
									<option value=";">Semicolon (;)</option>
									<option value="\t">Tab</option>
									<option value="|">Pipe (|)</option>
									<option value=" ">Space</option>
								</select>
							</div>
							<div class="flex flex-col gap-1.5">
								<label for="csv-quote" class="text-xs font-medium text-fg-secondary">Quote</label>
								<select
									id="csv-quote"
									bind:value={csvQuoteChar}
									disabled={loading}
									class="input-base border px-3 py-2 text-sm"
								>
									<option value="&quot;">Double Quote (")</option>
									<option value="'">Single Quote (')</option>
									<option value="">None</option>
								</select>
							</div>
							<div class="flex flex-col gap-1.5">
								<label for="csv-encoding" class="text-xs font-medium text-fg-secondary"
									>Encoding</label
								>
								<select
									id="csv-encoding"
									bind:value={csvEncoding}
									disabled={loading}
									class="input-base border px-3 py-2 text-sm"
								>
									<option value="utf8">UTF-8</option>
									<option value="utf8-lossy">UTF-8 (lossy)</option>
									<option value="latin1">Latin-1</option>
									<option value="ascii">ASCII</option>
								</select>
							</div>
							<div class="flex flex-col gap-1.5">
								<label for="csv-skip-rows" class="text-xs font-medium text-fg-secondary"
									>Skip Rows</label
								>
								<input
									id="csv-skip-rows"
									type="number"
									min="0"
									bind:value={csvSkipRows}
									disabled={loading}
									class="input-base border px-3 py-2 text-sm"
								/>
							</div>
						</div>
						<div class="flex items-center gap-2">
							<input
								id="csv-header"
								type="checkbox"
								bind:checked={csvHasHeader}
								disabled={loading}
								class="h-4 w-4 cursor-pointer"
							/>
							<label for="csv-header" class="m-0 text-sm text-fg-secondary"
								>First row is header</label
							>
						</div>
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
				{#if file?.name.endsWith('.xlsx')}
					<ExcelTableSelector
						mode="upload"
						{file}
						disabled={loading}
						bind:preflightId
						onConfigChange={(config) => {
							excelConfig = config;
						}}
					/>
				{/if}

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
			</div>
		{:else if activeTab === 'database'}
			<div class="flex flex-col gap-6">
				<div class="flex flex-col gap-2">
					<label for="db-name" class="text-sm font-medium text-fg-secondary">Name</label>
					<input
						id="db-name"
						type="text"
						bind:value={dbName}
						placeholder="My Database"
						disabled={loading}
						class="border px-3 py-2 text-sm input-base"
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
						class="border px-3 py-2 text-sm input-base"
					/>
					<p class="m-0 text-xs text-fg-muted">Example: postgresql://user:pass@localhost/dbname</p>
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
			</div>
		{:else if activeTab === 'path'}
			<div class="flex flex-col gap-6">
				<div class="flex flex-col gap-2">
					<label for="iceberg-path-name" class="text-sm font-medium text-fg-secondary">Name</label>
					<input
						id="iceberg-path-name"
						type="text"
						bind:value={pathName}
						placeholder="Existing Iceberg"
						disabled={loading}
						class="border px-3 py-2 text-sm input-base"
					/>
				</div>
				<div class="flex flex-col gap-2">
					<label for="iceberg-path-value" class="text-sm font-medium text-fg-secondary"
						>Table Root Path</label
					>
					<input
						id="iceberg-path-value"
						type="text"
						bind:value={pathValue}
						placeholder="/data/<namespace>/clean/<uuid>"
						disabled={loading}
						class="border px-3 py-2 text-sm input-base"
					/>
					<div class="flex items-center gap-2">
						<button class="btn-secondary" type="button" onclick={openPicker} disabled={loading}>
							Browse
						</button>
					</div>
				</div>
				{#if pickerOpen}
					<FileBrowser
						initialPath={browserStart()}
						oncancel={closePicker}
						onselect={(path) => handlePathSelect(path)}
					/>
				{/if}
				<button class="btn-primary" onclick={handlePathConnect} disabled={loading}>
					{loading ? 'Connecting...' : 'Connect'}
				</button>
			</div>
		{/if}
	</div>
</div>
