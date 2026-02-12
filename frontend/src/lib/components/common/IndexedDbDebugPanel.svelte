<script lang="ts">
	import { idbEntries, idbDelete, idbClear } from '$lib/utils/indexeddb';

	type Entry = { key: string; value: unknown };

	let entries = $state<Entry[]>([]);
	let loading = $state(false);
	let error = $state<string | null>(null);

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
		error = null;
		const list = await idbEntries();
		entries = list;
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

	$effect(() => {
		void refresh();
	});
</script>

<div class="idb-debug-panel">
	<div class="idb-debug-panel__header">
		<span class="idb-debug-panel__title">IndexedDB</span>
		<div class="idb-debug-panel__actions">
			<button class="idb-debug-panel__btn" onclick={refresh} type="button"> Refresh </button>
			<button
				class="idb-debug-panel__btn idb-debug-panel__btn--danger"
				onclick={clearAll}
				type="button"
			>
				Clear
			</button>
		</div>
	</div>

	{#if loading}
		<div class="idb-debug-panel__status">Loading...</div>
	{:else if error}
		<div class="idb-debug-panel__status">{error}</div>
	{:else if entries.length === 0}
		<div class="idb-debug-panel__status">No entries</div>
	{:else}
		<div class="idb-debug-panel__list">
			{#each entries as entry (entry.key)}
				<div class="idb-debug-panel__row">
					<div class="idb-debug-panel__key">{entry.key}</div>
					<div class="idb-debug-panel__value">{formatValue(entry.value)}</div>
					<button
						class="idb-debug-panel__btn idb-debug-panel__btn--danger"
						onclick={() => removeKey(entry.key)}
						type="button"
					>
						Delete
					</button>
				</div>
			{/each}
		</div>
	{/if}
</div>
