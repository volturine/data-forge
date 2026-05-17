<script lang="ts">
	import { callout } from '$lib/styles/panda';
	import type { Snippet } from 'svelte';

	interface Props {
		tone?: 'info' | 'warn' | 'error';
		children: Snippet;
	}

	let { tone = 'info', children }: Props = $props();
</script>

<div class={callout({ tone })} aria-live="polite">{@render children()}</div>
