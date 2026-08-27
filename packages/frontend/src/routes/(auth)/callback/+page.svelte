<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';
	import { css, spinner } from '$lib/styles/panda';
	import { authStore } from '$lib/stores/auth.svelte';

	onMount(() => {
		let cancelled = false;
		authStore.status = 'unknown';
		void authStore.resolve().then(() => {
			if (cancelled) return;
			void goto(resolve('/'));
		});
		return () => {
			cancelled = true;
		};
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
