<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { useQueryClient } from '@tanstack/svelte-query';
	import { uploadFile, uploadBulkFiles, connectDatabase } from '$lib/api/datasource';
	import { confirmExcel } from '$lib/api/excel';
	import type { ExcelParams } from '$lib/api/excel';
	import ExcelTableSelector from '$lib/components/common/ExcelTableSelector.svelte';
	import type { BulkUploadResult } from '$lib/api/datasource';

	import { SvelteSet } from 'svelte/reactivity';
	import { Check, X } from 'lucide-svelte';
	import { css, cx, button, input, tabButton, label } from '$lib/styles/panda';

	type Tab = 'file' | 'database';

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
				const params: ExcelParams = {
					sheet_name: excelConfig.sheet_name || undefined,
					start_row: excelConfig.start_row,
					start_col: excelConfig.start_col,
					end_col: excelConfig.end_col,
					has_header: excelConfig.has_header,
					table_name: excelConfig.table_name || undefined,
					named_range: excelConfig.named_range || undefined,
					cell_range: excelConfig.cell_range || undefined,
					end_row: excelConfig.end_row ?? undefined
				};
				const result = await confirmExcel(preflightId, fileName, params);
				if (result.isErr()) {
					error = result.error.message || 'Upload failed';
					loading = false;
					return;
				}
				queryClient.invalidateQueries({ queryKey: ['datasources'] });
				goto(resolve('/datasources'), { invalidateAll: true });
				return;
			}
			await uploadFile(file, fileName, {
				delimiter: csvDelimiter,
				quote_char: csvQuoteChar,
				has_header: csvHasHeader,
				skip_rows: csvSkipRows,
				encoding: csvEncoding
			});
			queryClient.invalidateQueries({ queryKey: ['datasources'] });
			goto(resolve('/datasources'), { invalidateAll: true });
		} catch (err) {
			error = err instanceof Error ? err.message : 'Upload failed';
		} finally {
			loading = false;
		}
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

<div
	class={css({ marginX: 'auto', boxSizing: 'border-box', maxWidth: 'pageNarrow', padding: '8' })}
>
	<header
		class={css({
			marginBottom: '8',
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'space-between'
		})}
	>
		<h1 class={css({ margin: '0', fontSize: '2xl', fontWeight: 'semibold' })}>Add Data Source</h1>
		<a
			href={resolve('/datasources')}
			class={cx(button({ variant: 'secondary' }), css({ textDecoration: 'none' }))}
			data-sveltekit-reload
		>
			Cancel
		</a>
	</header>

	<div
		class={css({
			marginBottom: '8',
			display: 'flex',
			gap: '2',
			borderBottomWidth: '2'
		})}
	>
		<button
			class={tabButton({ active: activeTab === 'file', size: 'lg' })}
			onclick={() => (activeTab = 'file')}
		>
			File Upload
		</button>
		<button
			class={tabButton({ active: activeTab === 'database', size: 'lg' })}
			onclick={() => (activeTab = 'database')}
		>
			External DB
		</button>
	</div>

	{#if error}
		<div
			class={css({
				paddingX: '2.5',
				paddingY: '3',
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
			borderWidth: '1',
			padding: '8'
		})}
	>
		{#if activeTab === 'file'}
			<div class={css({ display: 'flex', flexDirection: 'column', gap: '6' })}>
				<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
					<span class={label({ variant: 'field' })}>Source</span>
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '3' })}>
						<div
							class={css({
								borderWidth: '1',
								backgroundColor: 'bg.secondary',
								padding: '3'
							})}
						>
							<div class={css({ fontSize: 'sm', fontWeight: 'medium' })}>Upload</div>
							<div class={css({ fontSize: 'xs', color: 'fg.muted' })}>
								Upload one or many files in one step
							</div>
						</div>
					</div>
				</div>

				<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
					<label for="file-input" class={label({ variant: 'field' })}> Files </label>
					<input
						id="file-input"
						type="file"
						multiple
						accept=".csv,.xlsx"
						onchange={handleFileChange}
						disabled={loading}
						class={input()}
					/>
					<p class={css({ margin: '0', fontSize: 'xs', lineHeight: '1.625', color: 'fg.muted' })}>
						Select one or more CSV or Excel files (one type per batch). Names are derived from
						filenames.
					</p>
					{#if selectedFiles.length > 0}
						<div
							class={css({
								marginTop: '3',
								borderWidth: '1',
								backgroundColor: 'bg.tertiary',
								padding: '3'
							})}
						>
							<div
								class={css({
									marginBottom: '2',
									display: 'flex',
									alignItems: 'center',
									justifyContent: 'space-between',
									borderBottomWidth: '1',
									paddingBottom: '2',
									fontSize: 'sm',
									color: 'fg.secondary'
								})}
							>
								<span>{selectedFiles.length} file(s) selected</span>
								<button
									type="button"
									class={css({
										border: 'none',
										backgroundColor: 'transparent',
										padding: '0',
										fontSize: 'xs',
										color: 'accent.primary',
										_hover: { textDecoration: 'underline' }
									})}
									onclick={clearBulkSelection}
									disabled={loading}
								>
									Clear all
								</button>
							</div>
							{#each selectedFiles as selectedFile, index (index)}
								<div
									class={css({
										display: 'flex',
										alignItems: 'center',
										justifyContent: 'space-between',
										borderBottomWidth: '1',
										padding: '2'
									})}
								>
									<span
										class={css({
											flex: '1',
											overflow: 'hidden',
											textOverflow: 'ellipsis',
											whiteSpace: 'nowrap',
											fontSize: 'sm'
										})}
									>
										{selectedFile.name}
									</span>
									<button
										type="button"
										class={css({
											border: 'none',
											backgroundColor: 'transparent',
											padding: '1',
											fontSize: 'lg',
											lineHeight: 'none',
											color: 'fg.muted',
											_hover: { color: 'fg.error' }
										})}
										onclick={() => removeBulkFile(index)}
										disabled={loading}
									>
										x
									</button>
								</div>
							{/each}
						</div>
					{/if}
				</div>

				{#if selectedFiles.length === 1}
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
						<label for="file-name" class={label({ variant: 'field' })}> Name </label>
						<input
							id="file-name"
							type="text"
							bind:value={fileName}
							placeholder="My Dataset"
							disabled={loading}
							class={input()}
						/>
						{#if file}
							<p class={css({ margin: '0', fontSize: 'sm', color: 'fg.secondary' })}>
								Selected: {file.name}
							</p>
						{/if}
					</div>
				{/if}

				{#if batchType === 'csv'}
					<div
						class={css({
							display: 'flex',
							flexDirection: 'column',
							gap: '3',
							borderWidth: '1',
							backgroundColor: 'bg.tertiary',
							padding: '4'
						})}
					>
						<h3
							class={css({
								margin: '0',
								fontSize: 'sm',
								fontWeight: 'semibold',
								color: 'fg.secondary'
							})}
						>
							CSV Options
						</h3>
						<div
							class={css({
								display: 'grid',
								gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
								gap: '3'
							})}
						>
							<div class={css({ display: 'flex', flexDirection: 'column', gap: '1.5' })}>
								<label
									for="csv-delimiter"
									class={cx(label({ variant: 'field' }), css({ fontSize: 'xs' }))}
								>
									Delimiter
								</label>
								<select
									id="csv-delimiter"
									bind:value={csvDelimiter}
									disabled={loading}
									class={input()}
								>
									<option value=",">Comma (,)</option>
									<option value=";">Semicolon (;)</option>
									<option value="\t">Tab</option>
									<option value="|">Pipe (|)</option>
									<option value=" ">Space</option>
								</select>
							</div>
							<div class={css({ display: 'flex', flexDirection: 'column', gap: '1.5' })}>
								<label
									for="csv-quote"
									class={cx(label({ variant: 'field' }), css({ fontSize: 'xs' }))}
								>
									Quote
								</label>
								<select id="csv-quote" bind:value={csvQuoteChar} disabled={loading} class={input()}>
									<option value="&quot;">Double Quote (")</option>
									<option value="'">Single Quote (')</option>
									<option value="">None</option>
								</select>
							</div>
							<div class={css({ display: 'flex', flexDirection: 'column', gap: '1.5' })}>
								<label
									for="csv-encoding"
									class={cx(label({ variant: 'field' }), css({ fontSize: 'xs' }))}
								>
									Encoding
								</label>
								<select
									id="csv-encoding"
									bind:value={csvEncoding}
									disabled={loading}
									class={input()}
								>
									<option value="utf8">UTF-8</option>
									<option value="utf8-lossy">UTF-8 (lossy)</option>
									<option value="latin1">Latin-1</option>
									<option value="ascii">ASCII</option>
								</select>
							</div>
							<div class={css({ display: 'flex', flexDirection: 'column', gap: '1.5' })}>
								<label
									for="csv-skip-rows"
									class={cx(label({ variant: 'field' }), css({ fontSize: 'xs' }))}
								>
									Skip Rows
								</label>
								<input
									id="csv-skip-rows"
									type="number"
									min="0"
									bind:value={csvSkipRows}
									disabled={loading}
									class={input()}
								/>
							</div>
						</div>
						<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
							<input
								id="csv-header"
								type="checkbox"
								bind:checked={csvHasHeader}
								disabled={loading}
								class={css({ width: 'iconSm', height: 'iconSm', cursor: 'pointer' })}
							/>
							<label
								for="csv-header"
								class={css({ margin: '0', fontSize: 'sm', color: 'fg.secondary' })}
							>
								First row is header
							</label>
						</div>
					</div>
				{/if}

				{#if showBulkResults && bulkResults.length > 0}
					<div
						class={css({
							marginTop: '4',
							borderWidth: '1',
							backgroundColor: 'bg.tertiary',
							padding: '4'
						})}
					>
						<h4
							class={css({
								margin: '0',
								marginBottom: '3',
								fontSize: 'sm',
								fontWeight: 'semibold',
								color: 'fg.secondary'
							})}
						>
							Upload Results
						</h4>
						{#each bulkResults as result (result.name)}
							<div
								class={css({
									display: 'flex',
									alignItems: 'center',
									gap: '2',
									borderBottomWidth: '1',
									padding: '2',
									fontSize: 'sm',
									color: result.success ? 'fg.success' : 'fg.error'
								})}
							>
								<span class={css({ width: 'iconMd', textAlign: 'center', fontWeight: 'bold' })}>
									{#if result.success}
										<Check size={12} />
									{:else}
										<X size={12} />
									{/if}
								</span>
								<span
									class={css({
										flex: '1',
										overflow: 'hidden',
										textOverflow: 'ellipsis',
										whiteSpace: 'nowrap'
									})}
								>
									{result.name}
								</span>
								{#if result.error}
									<span
										class={css({
											maxWidth: 'listSm',
											overflow: 'hidden',
											textOverflow: 'ellipsis',
											fontSize: 'xs',
											color: 'fg.muted'
										})}
									>
										{result.error}
									</span>
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
					class={button({ variant: 'primary' })}
					onclick={selectedFiles.length === 1 ? handleFileUpload : handleBulkUpload}
					disabled={loading ||
						selectedFiles.length === 0 ||
						(selectedFiles.length === 1 && !fileName)}
				>
					{loading
						? 'Uploading...'
						: selectedFiles.length <= 1
							? 'Upload'
							: `Upload ${selectedFiles.length} Files`}
				</button>
			</div>
		{:else if activeTab === 'database'}
			<div class={css({ display: 'flex', flexDirection: 'column', gap: '6' })}>
				<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
					<label for="db-name" class={label({ variant: 'field' })}> Name </label>
					<input
						id="db-name"
						type="text"
						bind:value={dbName}
						placeholder="My Database"
						disabled={loading}
						class={input()}
					/>
				</div>

				<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
					<label for="connection-string" class={label({ variant: 'field' })}>
						Connection String
					</label>
					<input
						id="connection-string"
						type="text"
						bind:value={connectionString}
						placeholder="postgresql://user:pass@localhost/db"
						disabled={loading}
						class={input()}
					/>
					<p class={css({ margin: '0', fontSize: 'xs', color: 'fg.muted' })}>
						Example: postgresql://user:pass@localhost/dbname
					</p>
				</div>

				<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
					<label for="query" class={label({ variant: 'field' })}> Query </label>
					<textarea
						id="query"
						bind:value={query}
						placeholder="SELECT * FROM table"
						rows="5"
						disabled={loading}
						class={cx(input(), css({ resize: 'vertical' }))}
					></textarea>
				</div>

				<button
					class={button({ variant: 'primary' })}
					onclick={handleDatabaseConnect}
					disabled={loading}
				>
					{loading ? 'Connecting...' : 'Connect'}
				</button>
			</div>
		{/if}
	</div>
</div>
