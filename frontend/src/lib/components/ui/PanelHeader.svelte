<script lang="ts">
	import { panelHeader } from '$lib/styles/panda';
	import type { Snippet } from 'svelte';

	interface Props {
		title: Snippet;
		actions?: Snippet;
	}

	let { title, actions }: Props = $props();
</script>

<div class={panelHeader()}>
	{@render title()}
	{#if actions}
		{@render actions()}
	{/if}
</div>
