<script lang="ts">
	import { untrack } from 'svelte';
	import { listDataFiles } from '$lib/api/datasource';
	import type { FileListItem, FileListResponse } from '$lib/api/datasource';
	import FileTypeBadge from '$lib/components/common/FileTypeBadge.svelte';

	let {
		initialPath = '',
		onselect,
		oncancel
	}: {
		initialPath?: string;
		onselect: (path: string, isFolder: boolean) => void;
		oncancel: () => void;
	} = $props();

	let path = $state(untrack(() => initialPath));
	let root = $state('');
	let loading = $state(false);
	let error = $state<string | null>(null);
	let entries = $state<FileListItem[]>([]);

	let canUp = $derived(Boolean(root) && path.replace(/\/+$/, '') !== root.replace(/\/+$/, ''));

	let crumbs = $derived.by(() => {
		if (!root) return [] as { label: string; path: string }[];
		const base = root.replace(/\/+$/, '');
		const current = (path || root).replace(/\/+$/, '');
		if (!current.startsWith(base)) {
			return [{ label: base, path: base }];
		}
		const suffix = current.slice(base.length);
		const parts = suffix.split('/').filter(Boolean);
		const rootLabel = base.split('/').filter(Boolean).pop() || base;
		const items = [{ label: rootLabel, path: base }];
		let cursor = base;
		for (const part of parts) {
			cursor = `${cursor}/${part}`;
			items.push({ label: part, path: cursor });
		}
		return items;
	});

	function entryType(entry: FileListItem) {
		if (entry.is_dir) return 'folder';
		return 'file';
	}

	async function load(next?: string) {
		loading = true;
		error = null;
		const result = await listDataFiles(next);
		result.match(
			(response: FileListResponse) => {
				entries = response.entries;
				path = response.base_path;
				if (!root) {
					root = response.base_path;
				}
				loading = false;
			},
			(err: { message?: string }) => {
				error = err.message || 'Failed to load files';
				loading = false;
			}
		);
	}

	function up() {
		if (!root) return;
		const base = root.replace(/\/+$/, '');
		const current = path.replace(/\/+$/, '');
		if (!current || current === base) return;
		const lastSlash = current.lastIndexOf('/');
		const parent = lastSlash > 0 ? current.slice(0, lastSlash) : base;
		const next = parent.startsWith(base) ? parent : base;
		load(next);
	}

	function handleBackdropKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') {
			event.preventDefault();
			oncancel();
		}
	}

	function stopPickerEvent(event: Event) {
		event.stopPropagation();
	}

	$effect(() => {
		if (!root) {
			load(initialPath || undefined);
		}
	});
</script>

<div
	class="picker-backdrop"
	role="button"
	tabindex="0"
	aria-label="Close file picker"
	onclick={oncancel}
	onkeydown={handleBackdropKeydown}
>
	<div
		class="picker"
		role="dialog"
		aria-modal="true"
		tabindex="-1"
		onclick={stopPickerEvent}
		onkeydown={stopPickerEvent}
	>
		<div class="picker-header">
			<div class="picker-title">
				<h4>Data directory</h4>
				<div class="picker-crumbs" role="navigation" aria-label="Path breadcrumb">
					{#each crumbs as crumb, index (crumb.path)}
						<button type="button" class="crumb" onclick={() => load(crumb.path)} disabled={loading}>
							{crumb.label}
						</button>
						{#if index < crumbs.length - 1}
							<span class="crumb-sep">/</span>
						{/if}
					{/each}
				</div>
				<span class="picker-path">{path}</span>
				<span class="picker-hint">Select files or choose a folder for parquet datasets.</span>
			</div>
			<div class="picker-header-actions">
				<button class="btn-text" onclick={oncancel}>Close</button>
			</div>
		</div>
		<div class="picker-body">
			{#if loading}
				<div class="picker-empty">Loading...</div>
			{:else if error}
				<div class="picker-empty">{error}</div>
			{:else if entries.length === 0}
				<div class="picker-empty">No files found</div>
			{:else}
				<div class="picker-list">
					{#each entries as entry (entry.path)}
						<button
							type="button"
							class="picker-item"
							onclick={() => (entry.is_dir ? load(entry.path) : onselect(entry.path, false))}
							disabled={loading}
						>
							<div class="picker-info">
								<span class="picker-name">{entry.name}</span>
								<span class="picker-type">{entryType(entry)}</span>
							</div>
							<FileTypeBadge path={entry.name} isFolder={entry.is_dir} size="sm" />
						</button>
					{/each}
				</div>
			{/if}
		</div>
		<div class="picker-footer">
			<div class="picker-footer-left">
				<button class="btn-icon" onclick={up} disabled={!canUp} aria-label="Go up">←</button>
				<button
					class="btn-secondary"
					onclick={() => onselect(path, true)}
					disabled={loading || !path}
				>
					Use folder
				</button>
			</div>
			<button class="btn-secondary" onclick={() => load(path)} disabled={loading}> Refresh </button>
		</div>
	</div>
</div>

<style>
	.picker-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.4);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 1000;
		padding: var(--space-4);
	}
	.picker {
		background: var(--panel-bg);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-lg);
		max-width: 720px;
		width: 100%;
		max-height: 70vh;
		display: flex;
		flex-direction: column;
	}
	.picker-header {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: var(--space-2);
		padding: var(--space-4);
		border-bottom: 1px solid var(--panel-border);
	}
	.picker-title {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.picker-header h4 {
		margin: 0;
		font-size: var(--text-sm);
		font-weight: var(--font-semibold);
		color: var(--fg-primary);
	}
	.picker-path {
		font-size: var(--text-xs);
		color: var(--fg-muted);
		word-break: break-all;
	}
	.picker-hint {
		font-size: var(--text-xs);
		color: var(--fg-muted);
	}
	.picker-header-actions {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		justify-content: flex-end;
	}
	.picker-crumbs {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 4px;
	}
	.crumb {
		border: none;
		background: transparent;
		color: var(--fg-secondary);
		font-size: var(--text-xs);
		padding: 0;
		cursor: pointer;
	}
	.crumb:hover {
		color: var(--fg-primary);
		text-decoration: underline;
	}
	.crumb:disabled {
		color: var(--fg-muted);
		cursor: default;
		text-decoration: none;
	}
	.crumb-sep {
		color: var(--fg-muted);
		font-size: var(--text-xs);
	}
	.picker-body {
		padding: var(--space-3);
		overflow: auto;
		flex: 1;
	}
	.picker-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.picker-item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		background: var(--bg-primary);
		gap: var(--space-2);
		width: 100%;
		text-align: left;
		cursor: pointer;
	}
	.picker-item:hover {
		background: var(--bg-hover);
	}
	.picker-info {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.picker-name {
		font-size: var(--text-sm);
		color: var(--fg-primary);
	}
	.picker-type {
		font-size: var(--text-xs);
		color: var(--fg-muted);
	}
	.picker-empty {
		padding: var(--space-6);
		text-align: center;
		color: var(--fg-muted);
		font-size: var(--text-sm);
	}
	.picker-footer {
		padding: var(--space-3);
		border-top: 1px solid var(--panel-border);
		display: flex;
		justify-content: space-between;
		gap: var(--space-2);
	}
	.picker-footer-left {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.btn-icon {
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		background: var(--bg-primary);
		color: var(--fg-secondary);
		width: 32px;
		height: 32px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		cursor: pointer;
	}
	.btn-icon:hover {
		background: var(--bg-hover);
		color: var(--fg-primary);
	}
	.btn-icon:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.btn-secondary {
		text-decoration: none;
		padding: var(--space-2) var(--space-4);
		background: var(--bg-secondary);
		color: var(--fg-primary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: var(--text-sm);
		font-weight: var(--font-medium);
		transition: all var(--transition);
	}
	.btn-secondary:hover:not(:disabled) {
		background: var(--bg-hover);
		border-color: var(--border-secondary);
	}
	.btn-secondary:disabled {
		opacity: 0.5;
		cursor: not-allowed;
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
</style>
