<script lang="ts">
	import { goto } from '$app/navigation';
	import { uploadFile, connectDatabase, connectApi } from '$lib/api/datasource';

	type Tab = 'file' | 'database' | 'api';

	let activeTab = $state<Tab>('file');
	let loading = $state(false);
	let error = $state<string | null>(null);

	// File upload state
	let file = $state<File | null>(null);
	let fileName = $state('');

	// Database state
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
			if (!fileName) {
				fileName = file.name.replace(/\.[^/.]+$/, '');
			}
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
			await uploadFile(file, fileName);
			goto('/datasources', { invalidateAll: true });
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
			goto('/datasources', { invalidateAll: true });
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
			goto('/datasources', { invalidateAll: true });
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
		<a href="/datasources" class="button" data-sveltekit-reload>Cancel</a>
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
		<div class="error-banner">{error}</div>
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

				<button class="button primary" onclick={handleFileUpload} disabled={loading || !file}>
					{loading ? 'Uploading...' : 'Upload'}
				</button>
			</div>
		{:else if activeTab === 'database'}
			<div class="form">
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

				<button class="button primary" onclick={handleDatabaseConnect} disabled={loading}>
					{loading ? 'Connecting...' : 'Connect'}
				</button>
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

				<button class="button primary" onclick={handleApiConnect} disabled={loading}>
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
		padding: 2rem;
	}

	header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 2rem;
	}

	h1 {
		font-size: 2rem;
		font-weight: 600;
		margin: 0;
	}

	.button {
		display: inline-block;
		padding: 0.5rem 1rem;
		background: #e5e7eb;
		border: none;
		border-radius: 0.375rem;
		cursor: pointer;
		text-decoration: none;
		color: #1f2937;
		font-size: 0.875rem;
		font-weight: 500;
		transition: background-color 0.15s;
	}

	.button:hover:not(:disabled) {
		background: #d1d5db;
	}

	.button.primary {
		background: #3b82f6;
		color: white;
	}

	.button.primary:hover:not(:disabled) {
		background: #2563eb;
	}

	.button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.tabs {
		display: flex;
		gap: 0.5rem;
		border-bottom: 2px solid #e5e7eb;
		margin-bottom: 2rem;
	}

	.tab {
		padding: 0.75rem 1.5rem;
		background: none;
		border: none;
		border-bottom: 2px solid transparent;
		cursor: pointer;
		font-size: 0.875rem;
		font-weight: 500;
		color: #6b7280;
		margin-bottom: -2px;
		transition: all 0.15s;
	}

	.tab:hover {
		color: #374151;
	}

	.tab.active {
		color: #3b82f6;
		border-bottom-color: #3b82f6;
	}

	.error-banner {
		padding: 1rem;
		background: #fee2e2;
		color: #991b1b;
		border-radius: 0.5rem;
		margin-bottom: 1.5rem;
	}

	.content {
		background: white;
		padding: 2rem;
		border-radius: 0.5rem;
		box-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1);
	}

	.form {
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
	}

	.form-group {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	label {
		font-weight: 500;
		font-size: 0.875rem;
		color: #374151;
	}

	input[type='text'],
	input[type='url'],
	select,
	textarea {
		padding: 0.5rem 0.75rem;
		border: 1px solid #d1d5db;
		border-radius: 0.375rem;
		font-size: 0.875rem;
		transition: border-color 0.15s;
	}

	input[type='text']:focus,
	input[type='url']:focus,
	select:focus,
	textarea:focus {
		outline: none;
		border-color: #3b82f6;
		box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
	}

	input[type='text']:disabled,
	input[type='url']:disabled,
	select:disabled,
	textarea:disabled {
		background: #f9fafb;
		cursor: not-allowed;
	}

	input[type='file'] {
		padding: 0.5rem;
		border: 1px solid #d1d5db;
		border-radius: 0.375rem;
		font-size: 0.875rem;
	}

	textarea {
		resize: vertical;
		font-family: monospace;
	}

	.hint {
		font-size: 0.75rem;
		color: #6b7280;
		margin: 0;
	}

	.file-info {
		font-size: 0.875rem;
		color: #374151;
		margin: 0;
	}
</style>
