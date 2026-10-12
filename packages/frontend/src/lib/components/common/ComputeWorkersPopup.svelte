<script lang="ts">
	import { SvelteSet } from 'svelte/reactivity';
	import ComputeWorkersDialog from '$lib/components/common/ComputeWorkersDialog.svelte';

	interface Props {
		open: boolean;
	}

	let { open = $bindable() }: Props = $props();
	const shuttingDown = new SvelteSet<string>();

	function handleDialogClose(): void {
		open = false;
	}
</script>

{#if open}
	<ComputeWorkersDialog {shuttingDown} onClose={handleDialogClose} />
{/if}
