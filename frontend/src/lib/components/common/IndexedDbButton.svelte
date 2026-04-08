<script lang="ts">
	import { Check, Copy, Database, LoaderCircle, X } from 'lucide-svelte';
	import { onClickOutside } from 'runed';
	import { configStore } from '$lib/stores/config.svelte';
	import { idbEntries, idbDelete, idbClear } from '$lib/utils/indexeddb';
	import { css, emptyText } from '$lib/styles/panda';

	let open = $state(false);
	let entries = $state<Array<{ key: string; value: unknown }>>([]);
	let loading = $state(false);
	let dropdownRef = $state<HTMLElement>();
	let expandedKey = $state<string | null>(null);
	let copiedKey = $state<string | null>(null);
	let copyTimer = $state<number | null>(null);
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
		await navigator.clipboard.writeText(formatted).catch(() => {});
		copiedKey = key;
		if (copyTimer !== null) window.clearTimeout(copyTimer);
		copyTimer = window.setTimeout(() => {
			copiedKey = null;
			copyTimer = null;
		}, 1500);
	}

	// Cleanup: $derived can't clear pending timers on destroy.
	$effect(() => {
		return () => {
			if (copyTimer !== null) window.clearTimeout(copyTimer);
		};
	});

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
	<div class={css({ position: 'relative' })} bind:this={dropdownRef}>
		<button
			class={css({
				display: 'flex',
				cursor: 'pointer',
				alignItems: 'center',
				gap: '2',
				borderWidth: '1',
				borderColor: 'transparent',
				paddingX: '3',
				paddingY: '2',
				fontSize: 'xs',
				color: open ? 'fg.primary' : 'fg.tertiary',
				backgroundColor: open ? 'bg.hover' : undefined,
				_hover: { color: 'fg.primary' }
			})}
			onclick={toggle}
			title="IndexedDB"
			type="button"
		>
			<Database size={16} />
		</button>

		{#if open}
			<div
				class={css({
					position: 'absolute',
					right: '0',
					top: '100%',
					marginTop: '2',
					zIndex: 'engine',
					width: 'popover',
					overflow: 'hidden',
					borderWidth: '1',
					backgroundColor: 'bg.primary'
				})}
			>
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'space-between',
						borderBottomWidth: '1',
						padding: '3',
						backgroundColor: 'bg.secondary'
					})}
				>
					<span class={css({ fontSize: 'sm', fontWeight: 'semibold' })}> IndexedDB </span>
					<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
						<button
							class={css({
								display: 'flex',
								cursor: 'pointer',
								alignItems: 'center',
								justifyContent: 'center',
								borderWidth: '1',
								backgroundColor: 'transparent',
								paddingX: '2',
								paddingY: '1',
								fontSize: 'xs',
								color: 'fg.secondary',
								_hover: { backgroundColor: 'bg.hover' }
							})}
							onclick={refresh}
							type="button"
						>
							Refresh
						</button>
						<button
							class={css({
								display: 'flex',
								cursor: 'pointer',
								alignItems: 'center',
								justifyContent: 'center',
								borderWidth: '1',
								borderColor: 'border.error',
								backgroundColor: 'transparent',
								paddingX: '2',
								paddingY: '1',
								fontSize: 'xs',
								color: 'fg.error',
								_hover: { backgroundColor: 'bg.error' }
							})}
							onclick={clearAll}
							type="button"
						>
							Clear
						</button>
						<button
							class={css({
								display: 'flex',
								cursor: 'pointer',
								alignItems: 'center',
								justifyContent: 'center',
								border: 'none',
								backgroundColor: 'transparent',
								padding: '1',
								color: 'fg.muted',
								_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
							})}
							onclick={() => (open = false)}
							type="button"
						>
							<X size={14} />
						</button>
					</div>
				</div>

				<div class={css({ maxHeight: 'dropdownTall', overflowY: 'auto' })}>
					{#if loading}
						<div
							class={css({
								display: 'flex',
								alignItems: 'center',
								justifyContent: 'center',
								gap: '2',
								padding: '6',
								textAlign: 'center',
								fontSize: 'sm',
								color: 'fg.muted'
							})}
						>
							<LoaderCircle size={16} class={css({ animation: 'spin 1s linear infinite' })} />
							<span>Loading...</span>
						</div>
					{:else if entries.length === 0}
						<div class={emptyText({ size: 'panel' })}>
							<span>No entries</span>
						</div>
					{:else}
						<ul class={css({ margin: '0', listStyle: 'none', padding: '0' })}>
							{#each entries as entry (entry.key)}
								<li
									class={css({
										borderBottomWidth: '1',
										padding: '3'
									})}
								>
									<div class={css({ display: 'flex', alignItems: 'flex-start', gap: '3' })}>
										<div class={css({ minWidth: '0', flex: '1' })}>
											<div
												class={css({
													display: 'flex',
													alignItems: 'center',
													justifyContent: 'space-between',
													gap: '2'
												})}
											>
												<span
													class={css({
														fontFamily: 'mono',
														fontSize: 'xs'
													})}
												>
													{entry.key}
												</span>
												<button
													class={css({
														display: 'flex',
														alignItems: 'center',
														gap: '1',
														borderWidth: '1',
														backgroundColor: 'transparent',
														paddingX: '2',
														paddingY: '0.5',
														fontSize: 'xs',
														color: 'fg.secondary',
														_hover: { backgroundColor: 'bg.hover' }
													})}
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
												class={css({
													marginTop: '1',
													width: '100%',
													textAlign: 'left',
													fontSize: 'xs',
													color: 'fg.muted',
													backgroundColor: 'bg.primary',
													wordBreak: 'break-word'
												})}
												onclick={() => toggleExpand(entry.key)}
												type="button"
											>
												{#if expandedKey === entry.key}
													<pre
														class={css({
															whiteSpace: 'pre-wrap',
															fontSize: 'xs'
														})}>
													{formatValue(entry.value)}
												</pre>
												{:else}
													{truncateValue(formatValue(entry.value))}
												{/if}
											</button>
										</div>
										<button
											class={css({
												display: 'flex',
												cursor: 'pointer',
												alignItems: 'center',
												justifyContent: 'center',
												borderWidth: '1',
												borderColor: 'border.error',
												backgroundColor: 'transparent',
												paddingX: '2',
												paddingY: '1',
												fontSize: 'xs',
												color: 'fg.error',
												_hover: { backgroundColor: 'bg.error' }
											})}
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
