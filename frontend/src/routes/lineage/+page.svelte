<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { getLineage, type LineageResponse } from '$lib/api/lineage';
	import LineageGraph from '$lib/components/common/LineageGraph.svelte';
	import { Loader } from 'lucide-svelte';

	const query = createQuery(() => ({
		queryKey: ['lineage'],
		queryFn: async () => {
			const result = await getLineage();
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		}
	}));

	const emptyLineage: LineageResponse = { nodes: [], edges: [] };
	const lineage = $derived(query.data ?? emptyLineage);
</script>

<div class="mx-auto max-w-300 px-6 py-7">
	<header class="mb-6 border-b border-tertiary pb-5">
		<h1 class="m-0 mb-2 text-2xl">Data Lineage</h1>
		<p class="m-0 text-fg-tertiary">Track how datasources and analyses relate</p>
	</header>

	{#if query.isLoading}
		<div class="flex items-center gap-2 text-fg-tertiary">
			<Loader size={16} class="spin" />
			Loading lineage...
		</div>
	{:else if query.isError}
		<p class="text-sm text-error-fg">Failed to load lineage.</p>
	{:else}
		<LineageGraph {lineage} />
	{/if}
</div>
