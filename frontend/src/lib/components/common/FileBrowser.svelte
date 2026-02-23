<script lang="ts">
	import { untrack } from 'svelte';
	import { listDataFiles } from '$lib/api/datasource';
	import type { FileListItem, FileListResponse } from '$lib/api/datasource';
	import FileTypeBadge from '$lib/components/common/FileTypeBadge.svelte';
	import { ArrowUp } from 'lucide-svelte';

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

	const canUp = $derived(Boolean(root) && path.replace(/\/+$/, '') !== root.replace(/\/+$/, ''));

	const crumbs = $derived.by(() => {
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

	// Network: $derived can't load file list on mount.
	$effect(() => {
		if (!root) {
			load(initialPath || undefined);
		}
	});
</script>

<div
	class="fixed inset-0 z-1000 flex items-center justify-center p-4 bg-overlay-soft"
	role="button"
	tabindex="0"
	aria-label="Close file picker"
	onclick={oncancel}
	onkeydown={handleBackdropKeydown}
>
	<div
		class="flex w-full max-w-180 max-h-[70vh] flex-col border bg-panel border-tertiary"
		role="dialog"
		aria-modal="true"
		tabindex="-1"
		onclick={stopPickerEvent}
		onkeydown={stopPickerEvent}
	>
		<div class="grid grid-cols-[1fr_auto] gap-2 border-b p-4 border-tertiary">
			<div class="flex flex-col gap-1">
				<h4 class="m-0 text-sm font-semibold text-fg-primary">Data directory</h4>
				<div
					class="flex flex-wrap items-center gap-1"
					role="navigation"
					aria-label="Path breadcrumb"
				>
					{#each crumbs as crumb, index (crumb.path)}
						<button
							type="button"
							class="cursor-pointer border-none bg-transparent p-0 text-xs text-fg-secondary hover:text-fg-primary hover:underline disabled:text-fg-muted disabled:cursor-default disabled:no-underline"
							onclick={() => load(crumb.path)}
							disabled={loading}
						>
							{crumb.label}
						</button>
						{#if index < crumbs.length - 1}
							<span class="text-xs text-fg-muted">/</span>
						{/if}
					{/each}
				</div>
				<span class="break-all text-xs text-fg-muted">{path}</span>
				<span class="text-xs text-fg-muted"
					>Select files or choose a folder for parquet datasets.</span
				>
			</div>
			<div class="flex items-center justify-end gap-2">
				<button
					class="cursor-pointer border-none bg-transparent p-0 text-xs text-accent"
					onclick={oncancel}
				>
					Close
				</button>
			</div>
		</div>

		<div class="flex-1 overflow-auto p-3">
			{#if loading}
				<div class="p-6 text-center text-sm text-fg-muted">Loading...</div>
			{:else if error}
				<div class="p-6 text-center text-sm text-fg-muted">{error}</div>
			{:else if entries.length === 0}
				<div class="p-6 text-center text-sm text-fg-muted">No files found</div>
			{:else}
				<div class="flex flex-col gap-2">
					{#each entries as entry (entry.path)}
						<button
							type="button"
							class="flex w-full cursor-pointer items-center justify-between gap-2 border p-2 px-3 text-left bg-primary border-tertiary hover:bg-hover"
							onclick={() => (entry.is_dir ? load(entry.path) : onselect(entry.path, false))}
							disabled={loading}
						>
							<div class="flex flex-col gap-0.5">
								<span class="text-sm text-fg-primary">{entry.name}</span>
								<span class="text-xs text-fg-muted">{entryType(entry)}</span>
							</div>
							<FileTypeBadge path={entry.name} isFolder={entry.is_dir} size="sm" />
						</button>
					{/each}
				</div>
			{/if}
		</div>

		<div class="flex justify-between gap-2 border-t p-3 border-tertiary">
			<div class="flex items-center gap-2">
				<button
					class="inline-flex h-8 w-8 cursor-pointer items-center justify-center border disabled:cursor-not-allowed disabled:opacity-50 bg-primary border-tertiary text-fg-secondary hover:bg-hover hover:text-fg-primary"
					onclick={up}
					disabled={!canUp}
					aria-label="Go up"
				>
					<ArrowUp size={14} />
				</button>
				<button
					class="cursor-pointer border px-4 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 bg-secondary text-fg-primary border-tertiary hover:bg-hover hover:border-tertiary"
					onclick={() => onselect(path, true)}
					disabled={loading || !path}
				>
					Use folder
				</button>
			</div>
			<button
				class="cursor-pointer border px-4 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 bg-secondary text-fg-primary border-tertiary hover:bg-hover hover:border-tertiary"
				onclick={() => load(path)}
				disabled={loading}
			>
				Refresh
			</button>
		</div>
	</div>
</div>
