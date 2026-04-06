<script lang="ts">
	import { sectionHeader } from '$lib/styles/panda';
	import type { Snippet } from 'svelte';

	interface Props {
		children: Snippet;
	}

	let { children }: Props = $props();
</script>

<span class={sectionHeader()}>{@render children()}</span>
