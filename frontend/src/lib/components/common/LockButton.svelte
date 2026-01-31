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
	<button class="lock-btn release" onclick={handleRelease} type="button">
		<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
			<path
				d="M8 1a2 2 0 0 1 2 2v4H6V3a2 2 0 0 1 2-2zm3 6V3a3 3 0 0 0-6 0v4a2 2 0 0 0-2 2v5a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2z"
			/>
		</svg>
		<span>Release</span>
	</button>
{:else}
	<button
		class="lock-btn acquire"
		class:disabled={isLocked}
		onclick={handleAcquire}
		disabled={isLocked}
		type="button"
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
	.lock-btn {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-sm);
		font-size: var(--text-sm);
		font-weight: 500;
		cursor: pointer;
		transition: all var(--transition);
		border: 1px solid transparent;
	}

	.lock-btn.acquire {
		background: var(--accent-primary);
		color: white;
	}

	.lock-btn.acquire:hover:not(.disabled) {
		opacity: 0.9;
	}

	.lock-btn.acquire.disabled {
		background: var(--bg-tertiary);
		color: var(--fg-muted);
		cursor: not-allowed;
	}

	.lock-btn.release {
		background: var(--warning-bg);
		color: var(--warning-fg);
		border-color: var(--warning-border);
	}

	.lock-btn.release:hover {
		background: var(--warning-border);
	}
</style>
