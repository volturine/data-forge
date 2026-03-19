<script lang="ts">
	import { acquireLock, releaseLock, getLockState } from '$lib/stores/lockManager.svelte';
	import { Lock, LockOpen } from 'lucide-svelte';
	import { css } from '$lib/styles/panda';

	interface Props {
		resourceId: string;
		onAcquire?: () => void;
		onRelease?: () => void;
	}

	let { resourceId, onAcquire, onRelease }: Props = $props();

	// Reactive state for this resource's lock
	const state = $derived(getLockState(resourceId));
	const isLocked = $derived(state.locked);
	const isMine = $derived(state.byMe);

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
		class={css({
			display: 'flex',
			cursor: 'pointer',
			alignItems: 'center',
			gap: '2',
			borderWidth: '1',
			borderColor: 'warning.border',
			backgroundColor: 'transparent',
			color: 'fg.tertiary',
			paddingX: '3',
			paddingY: '2',
			fontSize: 'sm',
			fontWeight: 'medium',
			_hover: { backgroundColor: 'warning.border' }
		})}
		onclick={handleRelease}
		type="button"
	>
		<Lock size={16} />
		<span>Release</span>
	</button>
{:else}
	<button
		class={css({
			display: 'flex',
			alignItems: 'center',
			gap: '2',
			borderWidth: '1',
			borderColor: 'transparent',
			paddingX: '3',
			paddingY: '2',
			fontSize: 'sm',
			fontWeight: 'medium',
			_disabled: { cursor: 'not-allowed' },
			...(isLocked
				? { backgroundColor: 'bg.tertiary', color: 'fg.muted', cursor: 'not-allowed' }
				: {
						backgroundColor: 'accent.primary',
						color: 'warning.contrast',
						cursor: 'pointer',
						_hover: { opacity: '0.9' }
					})
		})}
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
