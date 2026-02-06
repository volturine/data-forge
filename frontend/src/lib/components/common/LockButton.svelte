<script lang="ts">
	import { acquireLock, releaseLock, getLockState } from '$lib/stores/lockManager.svelte';

	interface Props {
		resourceId: string;
		onAcquire?: () => void;
		onRelease?: () => void;
	}

	let { resourceId, onAcquire, onRelease }: Props = $props();

	// Reactive state for this resource's lock
	let state = $derived(getLockState(resourceId));
	let isLocked = $derived(state.locked);
	let isMine = $derived(state.byMe);

	async function handleAcquire() {
		const success = await acquireLock(resourceId);
		if (success) {
			onAcquire?.();
		} else {
			alert('This resource is currently locked by another user. Please try again later.');
		}
	}

	async function handleRelease() {
		await releaseLock(resourceId);
		onRelease?.();
	}
</script>

{#if isMine}
	<button
		class="lock-btn release flex cursor-pointer items-center gap-2 rounded-sm border px-3 py-2 text-sm font-medium transition-all"
		onclick={handleRelease}
		type="button"
		style="background: var(--warning-bg); color: var(--warning-fg); border-color: var(--warning-border);"
	>
		<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
			<path
				d="M8 1a2 2 0 0 1 2 2v4H6V3a2 2 0 0 1 2-2zm3 6V3a3 3 0 0 0-6 0v4a2 2 0 0 0-2 2v5a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2z"
			/>
		</svg>
		<span>Release</span>
	</button>
{:else}
	<button
		class="lock-btn acquire flex items-center gap-2 rounded-sm border border-transparent px-3 py-2 text-sm font-medium transition-all disabled:cursor-not-allowed {isLocked
			? 'cursor-not-allowed'
			: 'cursor-pointer hover:opacity-90'}"
		onclick={handleAcquire}
		disabled={isLocked}
		type="button"
		style="background: {isLocked ? 'var(--bg-tertiary)' : 'var(--accent-primary)'}; color: {isLocked
			? 'var(--fg-muted)'
			: 'white'};"
	>
		<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
			{#if isLocked}
				<path
					d="M8 1a2 2 0 0 1 2 2v4H6V3a2 2 0 0 1 2-2zm3 6V3a3 3 0 0 0-6 0v4a2 2 0 0 0-2 2v5a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2z"
				/>
			{:else}
				<path
					d="M11 1a2 2 0 0 0-2 2v4a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h5V3a3 3 0 0 1 6 0v4a.5.5 0 0 1-1 0V3a2 2 0 0 0-2-2z"
				/>
			{/if}
		</svg>
		<span>{isLocked ? 'Locked' : 'Edit'}</span>
	</button>
{/if}

<style>
	.lock-btn.release:hover {
		background: var(--warning-border);
	}
</style>
