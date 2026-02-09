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
</script>

<div class="grid w-full grid-cols-1 gap-4 sm:grid-cols-[repeat(auto-fill,minmax(280px,1fr))]">
	{#each analyses as analysis (analysis.id)}
		<AnalysisCard {analysis} selected={selectedIds.has(analysis.id)} {onDelete} {onToggleSelect} />
	{/each}
</div>
