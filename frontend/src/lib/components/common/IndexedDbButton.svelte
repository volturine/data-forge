<script lang="ts">
	import { Check, Copy, Database, LoaderCircle, X } from 'lucide-svelte';
	import { onClickOutside } from 'runed';
	import { configStore } from '$lib/stores/config.svelte';
	import { idbEntries, idbDelete, idbClear } from '$lib/utils/indexeddb';

	let open = $state(false);
	let entries = $state<Array<{ key: string; value: unknown }>>([]);
	let loading = $state(false);
	let dropdownRef = $state<HTMLElement>();
	let expandedKey = $state<string | null>(null);
	let copiedKey = $state<string | null>(null);
	const truncateLimit = 120;

	function formatValue(value: unknown): string {
		if (typeof value === 'string') return value;
		try {
			return JSON.stringify(value);
		} catch (err) {
			void err;
			return String(value);
		}
	}

	function truncateValue(value: string): string {
		if (value.length <= truncateLimit) return value;
		return `${value.slice(0, truncateLimit)}...`;
	}

	function toggleExpand(key: string) {
		expandedKey = expandedKey === key ? null : key;
	}

	async function copyValue(key: string, value: unknown) {
		const formatted = formatValue(value);
		await navigator.clipboard.writeText(formatted);
		copiedKey = key;
		window.setTimeout(() => {
			copiedKey = null;
		}, 1500);
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
		if (!open) {
			expandedKey = null;
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
								<li class="border-b p-3 last:border-b-0 border-tertiary">
									<div class="flex items-start gap-3">
										<div class="min-w-0 flex-1">
											<div class="flex items-center justify-between gap-2">
												<span class="font-mono text-xs text-fg-primary">{entry.key}</span>
												<button
													class="flex items-center gap-1 border border-tertiary bg-transparent px-2 py-0.5 text-[11px] text-fg-secondary hover:bg-hover"
													onclick={() => copyValue(entry.key, entry.value)}
													type="button"
												>
													{#if copiedKey === entry.key}
														<Check size={12} />
														Copied
													{:else}
														<Copy size={12} />
														Copy
													{/if}
												</button>
											</div>
											<button
												class="mt-1 w-full text-left text-xs text-fg-muted break-words"
												onclick={() => toggleExpand(entry.key)}
												type="button"
											>
												{#if expandedKey === entry.key}
													<pre class="whitespace-pre-wrap text-xs text-fg-primary">{formatValue(
															entry.value
														)}</pre>
												{:else}
													{truncateValue(formatValue(entry.value))}
												{/if}
											</button>
										</div>
										<button
											class="flex cursor-pointer items-center justify-center border border-error bg-transparent px-2 py-1 text-xs text-error-fg hover:bg-error"
											onclick={() => removeKey(entry.key)}
											type="button"
										>
											Delete
										</button>
									</div>
								</li>
							{/each}
						</ul>
					{/if}
				</div>
			</div>
		{/if}
	</div>
{/if}
