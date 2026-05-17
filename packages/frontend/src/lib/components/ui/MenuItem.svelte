<script lang="ts">
	import { menuItem } from '$lib/styles/panda';
	import type { Snippet } from 'svelte';

	interface Props {
		onclick: () => void;
		children: Snippet;
		disabled?: boolean;
	}

	let { onclick, children, disabled = false }: Props = $props();
</script>

<button type="button" class={menuItem()} {onclick} {disabled}>
	{@render children()}
</button>
