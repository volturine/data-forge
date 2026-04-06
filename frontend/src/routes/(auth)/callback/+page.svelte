<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { css, spinner } from '$lib/styles/panda';
	import { authStore } from '$lib/stores/auth.svelte';

	// Network: $derived can't trigger async auth resolution or navigation.
	$effect(() => {
		authStore.status = 'unknown';
		void authStore.resolve().then(() => {
			void goto(resolve('/'));
		});
	});
</script>

<div
	class={css({
		display: 'flex',
		flexDirection: 'column',
		alignItems: 'center',
		gap: '4',
		paddingY: '12'
	})}
>
	<div class={spinner()}></div>
	<p class={css({ fontSize: 'sm', color: 'fg.muted' })}>Completing sign in…</p>
</div>
