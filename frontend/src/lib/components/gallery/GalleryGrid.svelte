<script lang="ts">
	import type { AnalysisGalleryItem } from '$lib/types/analysis';
	import AnalysisCard from './AnalysisCard.svelte';

	interface Props {
		analyses: AnalysisGalleryItem[];
		selectedIds: Set<string>;
		onDelete: (id: string) => void;
		onToggleSelect: (id: string) => void;
	}

	let { analyses, selectedIds, onDelete, onToggleSelect }: Props = $props();

	const anySelected = $derived(selectedIds.size > 0);
</script>

<div class="grid">
	{#each analyses as analysis (analysis.id)}
		<AnalysisCard
			{analysis}
			selected={selectedIds.has(analysis.id)}
			{anySelected}
			{onDelete}
			{onToggleSelect}
		/>
	{/each}
</div>

<style>
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: var(--space-4);
		width: 100%;
	}
	@media (max-width: 640px) {
		.grid {
			grid-template-columns: 1fr;
		}
	}
</style>
