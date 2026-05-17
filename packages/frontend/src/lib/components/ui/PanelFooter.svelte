<script lang="ts">
	import { panelFooter } from '$lib/styles/panda';
	import type { Snippet } from 'svelte';

	interface Props {
		children: Snippet;
	}

	let { children }: Props = $props();
</script>

<div class={panelFooter()}>{@render children()}</div>
