<script lang="ts">
	import { untrack } from 'svelte';
	import { listDataFiles } from '$lib/api/datasource';
	import type { FileListItem, FileListResponse } from '$lib/api/datasource';
	import FileTypeBadge from '$lib/components/common/FileTypeBadge.svelte';
	import BaseModal from '$lib/components/ui/BaseModal.svelte';
	import { ArrowUp } from 'lucide-svelte';
	import { css, emptyText } from '$lib/styles/panda';

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
	let entries = $state.raw<FileListItem[]>([]);

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

	// Network: $derived can't load file list on mount.
	$effect(() => {
		if (!root) {
			load(initialPath || undefined);
		}
	});
</script>

<BaseModal
	open={true}
	onClose={oncancel}
	closeOnEscape={true}
	closeOnBackdrop={true}
	overlayClass={css({
		display: 'flex',
		alignItems: 'center',
		position: 'fixed',
		inset: '0',
		zIndex: 'modal',
		justifyContent: 'center',
		padding: '4',
		backgroundColor: 'bg.overlaySoft'
	})}
	panelClass={css({
		display: 'flex',
		width: '100%',
		maxWidth: 'modal',
		maxHeight: '70vh',
		flexDirection: 'column',
		borderWidth: '1',
		backgroundColor: 'bg.primary'
	})}
	{content}
/>

{#snippet content()}
	<div
		class={css({
			display: 'grid',
			gridTemplateColumns: '1fr auto',
			gap: '2',
			borderBottomWidth: '1',
			padding: '4'
		})}
	>
		<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
			<h4 class={css({ margin: '0', fontSize: 'sm', fontWeight: 'semibold' })}>Data directory</h4>
			<div
				class={css({ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '1' })}
				role="navigation"
				aria-label="Path breadcrumb"
			>
				{#each crumbs as crumb, index (crumb.path)}
					<button
						type="button"
						class={css({
							cursor: 'pointer',
							border: 'none',
							backgroundColor: 'transparent',
							padding: '0',
							fontSize: 'xs',
							color: 'fg.secondary',
							_hover: { color: 'fg.primary', textDecoration: 'underline' },
							_disabled: { color: 'fg.muted', cursor: 'default', textDecoration: 'none' }
						})}
						onclick={() => load(crumb.path)}
						disabled={loading}
					>
						{crumb.label}
					</button>
					{#if index < crumbs.length - 1}
						<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>/</span>
					{/if}
				{/each}
			</div>
			<span class={css({ wordBreak: 'break-all', fontSize: 'xs', color: 'fg.muted' })}>{path}</span>
			<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>
				Select files or choose a folder for parquet datasets.
			</span>
		</div>
		<div
			class={css({ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '2' })}
		>
			<button
				class={css({
					cursor: 'pointer',
					border: 'none',
					backgroundColor: 'transparent',
					padding: '0',
					fontSize: 'xs',
					color: 'accent.primary'
				})}
				onclick={oncancel}
				type="button"
			>
				Close
			</button>
		</div>
	</div>

	<div class={css({ flex: '1', overflow: 'auto', padding: '3' })}>
		{#if loading}
			<div class={emptyText({ size: 'panel' })}>Loading...</div>
		{:else if error}
			<div class={emptyText({ size: 'panel' })}>
				{error}
			</div>
		{:else if entries.length === 0}
			<div class={emptyText({ size: 'panel' })}>No files found</div>
		{:else}
			<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
				{#each entries as entry (entry.path)}
					<button
						type="button"
						class={css({
							display: 'flex',
							width: '100%',
							cursor: 'pointer',
							alignItems: 'center',
							justifyContent: 'space-between',
							gap: '2',
							borderWidth: '1',
							padding: '2',
							paddingX: '3',
							textAlign: 'left',
							backgroundColor: 'bg.primary',
							_hover: { backgroundColor: 'bg.hover' }
						})}
						onclick={() => (entry.is_dir ? load(entry.path) : onselect(entry.path, false))}
						disabled={loading}
					>
						<div class={css({ display: 'flex', flexDirection: 'column', gap: '0.5' })}>
							<span class={css({ fontSize: 'sm' })}>{entry.name}</span>
							<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>{entryType(entry)}</span>
						</div>
						<FileTypeBadge path={entry.name} isFolder={entry.is_dir} size="sm" />
					</button>
				{/each}
			</div>
		{/if}
	</div>

	<div
		class={css({
			borderTopWidth: '1',
			display: 'flex',
			justifyContent: 'space-between',
			gap: '2',
			padding: '3'
		})}
	>
		<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
			<button
				class={css({
					display: 'inline-flex',
					height: 'rowLg',
					width: 'rowLg',
					cursor: 'pointer',
					alignItems: 'center',
					justifyContent: 'center',
					borderWidth: '1',
					backgroundColor: 'bg.primary',
					color: 'fg.secondary',
					_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' },
					_disabled: { cursor: 'not-allowed', opacity: 0.5 }
				})}
				onclick={up}
				disabled={!canUp}
				aria-label="Go up"
				type="button"
			>
				<ArrowUp size={14} />
			</button>
			<button
				class={css({
					cursor: 'pointer',
					borderWidth: '1',
					paddingX: '4',
					paddingY: '2',
					fontSize: 'sm',
					fontWeight: 'medium',
					backgroundColor: 'bg.secondary',
					_hover: { backgroundColor: 'bg.hover' },
					_disabled: { cursor: 'not-allowed', opacity: 0.5 }
				})}
				onclick={() => onselect(path, true)}
				disabled={loading || !path}
				type="button"
			>
				Use folder
			</button>
		</div>
		<button
			class={css({
				cursor: 'pointer',
				borderWidth: '1',
				paddingX: '4',
				paddingY: '2',
				fontSize: 'sm',
				fontWeight: 'medium',
				backgroundColor: 'bg.secondary',
				_hover: { backgroundColor: 'bg.hover' },
				_disabled: { cursor: 'not-allowed', opacity: 0.5 }
			})}
			onclick={() => load(path)}
			disabled={loading}
			type="button"
		>
			Refresh
		</button>
	</div>
{/snippet}
