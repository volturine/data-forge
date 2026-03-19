<script lang="ts">
	import type { AnalysisGalleryItem } from '$lib/types/analysis';
	import AnalysisCard from './AnalysisCard.svelte';
	import { css } from '$lib/styles/panda';

	interface Props {
		analyses: AnalysisGalleryItem[];
		selectedIds: Set<string>;
		onDelete: (id: string) => void;
		onToggleSelect: (id: string) => void;
	}

	let { analyses, selectedIds, onDelete, onToggleSelect }: Props = $props();
</script>

<div
	class={css({
		display: 'grid',
		width: '100%',
		gridTemplateColumns: 'repeat(1, minmax(0, 1fr))',
		gap: '4',
		sm: { gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }
	})}
>
	{#each analyses as analysis (analysis.id)}
		<AnalysisCard {analysis} selected={selectedIds.has(analysis.id)} {onDelete} {onToggleSelect} />
	{/each}
</div>
