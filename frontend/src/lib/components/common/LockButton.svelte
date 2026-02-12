<script lang="ts">
	import { acquireLock, releaseLock, getLockState } from '$lib/stores/lockManager.svelte';
	import { Lock, LockOpen } from 'lucide-svelte';

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
		class="lock-btn release flex cursor-pointer items-center gap-2 border px-3 py-2 text-sm font-medium"
		onclick={handleRelease}
		type="button"
		class:callout-warning={true}
	>
		<Lock size={16} />
		<span>Release</span>
	</button>
{:else}
	<button
		class="lock-btn acquire flex items-center gap-2 border border-transparent px-3 py-2 text-sm font-medium disabled:cursor-not-allowed {isLocked
			? 'cursor-not-allowed'
			: 'cursor-pointer hover:opacity-90'}"
		class:locked={isLocked}
		onclick={handleAcquire}
		disabled={isLocked}
		type="button"
	>
		{#if isLocked}
			<Lock size={16} />
		{:else}
			<LockOpen size={16} />
		{/if}
		<span>{isLocked ? 'Locked' : 'Edit'}</span>
	</button>
{/if}
