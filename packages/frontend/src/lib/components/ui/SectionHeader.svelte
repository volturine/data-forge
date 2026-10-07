<script lang="ts">
	import { sectionHeader } from '$lib/styles/panda';
	import type { Snippet } from 'svelte';

	interface Props {
		id?: string;
		children: Snippet;
	}

	let { id, children }: Props = $props();
</script>

<span {id} class={sectionHeader()}>{@render children()}</span>
