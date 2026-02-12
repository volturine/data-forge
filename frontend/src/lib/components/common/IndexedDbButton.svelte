<script lang="ts">
	import { Database, LoaderCircle, X } from 'lucide-svelte';
	import { onClickOutside } from 'runed';
	import { configStore } from '$lib/stores/config.svelte';
	import { idbEntries, idbDelete, idbClear } from '$lib/utils/indexeddb';

	let open = $state(false);
	let entries = $state<Array<{ key: string; value: unknown }>>([]);
	let loading = $state(false);
	let dropdownRef = $state<HTMLElement>();

	function formatValue(value: unknown): string {
		if (typeof value === 'string') return value;
		try {
			return JSON.stringify(value);
		} catch {
			return String(value);
		}
	}

	async function refresh() {
		loading = true;
		entries = await idbEntries();
		loading = false;
	}

	async function clearAll() {
		await idbClear();
		await refresh();
	}

	async function removeKey(key: string) {
		await idbDelete(key);
		await refresh();
	}

	function toggle() {
		open = !open;
		if (open) {
			void refresh();
		}
	}

	onClickOutside(
		() => dropdownRef,
		() => {
			open = false;
		},
		{ immediate: true }
	);
</script>

{#if configStore.publicIdbDebug}
	<div class="relative" bind:this={dropdownRef}>
		<button
			class="flex cursor-pointer items-center gap-2 border border-transparent px-3 py-2 text-xs text-fg-tertiary hover:text-fg-primary"
			class:!bg-bg-hover={open}
			class:!text-fg-primary={open}
			onclick={toggle}
			title="IndexedDB"
			type="button"
		>
			<Database size={16} />
		</button>

		{#if open}
			<div
				class="absolute right-0 top-full mt-2 z-engine w-90 overflow-hidden border bg-primary border-tertiary"
			>
				<div class="flex items-center justify-between border-b p-3 bg-secondary border-tertiary">
					<span class="text-sm font-semibold text-fg-primary">IndexedDB</span>
					<div class="flex items-center gap-2">
						<button
							class="flex cursor-pointer items-center justify-center border border-tertiary bg-transparent px-2 py-1 text-xs text-fg-secondary hover:bg-hover"
							onclick={refresh}
							type="button"
						>
							Refresh
						</button>
						<button
							class="flex cursor-pointer items-center justify-center border border-error bg-transparent px-2 py-1 text-xs text-error-fg hover:bg-error"
							onclick={clearAll}
							type="button"
						>
							Clear
						</button>
						<button
							class="flex cursor-pointer items-center justify-center border-none bg-transparent p-1 text-fg-muted hover:bg-hover hover:text-fg-primary"
							onclick={() => (open = false)}
							type="button"
						>
							<X size={14} />
						</button>
					</div>
				</div>

				<div class="max-h-75 overflow-y-auto">
					{#if loading}
						<div
							class="flex items-center justify-center gap-2 p-6 text-center text-sm text-fg-muted"
						>
							<LoaderCircle size={16} class="animate-spin" />
							<span>Loading...</span>
						</div>
					{:else if entries.length === 0}
						<div class="p-6 text-center text-sm text-fg-muted">
							<span>No entries</span>
						</div>
					{:else}
						<ul class="m-0 list-none p-0">
							{#each entries as entry (entry.key)}
								<li class="flex items-start gap-3 border-b p-3 last:border-b-0 border-tertiary">
									<div class="min-w-0 flex-1">
										<div class="font-mono text-xs text-fg-primary">{entry.key}</div>
										<div class="mt-1 text-xs text-fg-muted break-words">
											{formatValue(entry.value)}
										</div>
									</div>
									<button
										class="flex cursor-pointer items-center justify-center border border-error bg-transparent px-2 py-1 text-xs text-error-fg hover:bg-error"
										onclick={() => removeKey(entry.key)}
										type="button"
									>
										Delete
									</button>
								</li>
							{/each}
						</ul>
					{/if}
				</div>
			</div>
		{/if}
	</div>
{/if}
