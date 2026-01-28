<script lang="ts">
	import type { AnalysisGalleryItem } from '$lib/types/analysis';
	import AnalysisCard from './AnalysisCard.svelte';

	interface Props {
		analyses: AnalysisGalleryItem[];
		onDelete: (id: string) => void;
	}

	let { analyses, onDelete }: Props = $props();
</script>

<div class="grid">
	{#each analyses as analysis (analysis.id)}
		<AnalysisCard {analysis} {onDelete} />
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
