<script lang="ts">
	import type { AnalysisGalleryItem } from '$lib/types/analysis';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { ChartBar, Trash2 } from 'lucide-svelte';
	import { formatDateDisplay, getYearDisplay } from '$lib/utils/datetime';

	interface Props {
		analysis: AnalysisGalleryItem;
		selected: boolean;
		onDelete: (id: string) => void;
		onToggleSelect: (id: string) => void;
	}

	let { analysis, selected, onDelete, onToggleSelect }: Props = $props();

	function handleClick(e: MouseEvent) {
		const target = e.target as HTMLElement;
		if (target.closest('button') || target.closest('input[type=checkbox]')) return;
		goto(resolve(`/analysis/${analysis.id}`), { invalidateAll: true });
	}

	function handleKeyPress(e: KeyboardEvent) {
		if ((e.key === 'Enter' || e.key === ' ') && !(e.target as HTMLElement).closest('button')) {
			e.preventDefault();
			goto(resolve(`/analysis/${analysis.id}`), { invalidateAll: true });
		}
	}

	function formatDate(date: string): string {
		const now = new Date();
		const year = getYearDisplay(date);
		const currentYear = getYearDisplay(now);
		const opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' };
		if (year !== null && currentYear !== null && year !== currentYear) {
			opts.year = 'numeric';
		}
		return formatDateDisplay(date, opts);
	}
</script>

<div
	class="analysis-card group relative cursor-pointer overflow-hidden bg-primary"
	class:selected
	onclick={handleClick}
	onkeypress={handleKeyPress}
	role="button"
	tabindex="0"
>
	<div class="relative flex aspect-video w-full items-center justify-center bg-tertiary">
		<input
			type="checkbox"
			class="absolute left-5 top-5 h-4.5 w-4.5"
			checked={selected}
			onchange={(e) => {
				e.stopPropagation();
				onToggleSelect(analysis.id);
			}}
			onclick={(e) => e.stopPropagation()}
			aria-label={`Select ${analysis.name}`}
		/>
		{#if analysis.thumbnail}
			<img src={analysis.thumbnail} alt={analysis.name} class="h-full w-full object-cover" />
		{:else}
			<ChartBar size={32} class="text-fg-faint" />
		{/if}
	</div>

	<div class="p-4">
		<div class="mb-2 flex items-start justify-between gap-3">
			<h3 class="m-0 min-w-0 flex-1 truncate text-sm font-semibold">{analysis.name}</h3>
			<Trash2
				size={16}
				onclick={(e) => {
					e.stopPropagation();
					onDelete(analysis.id);
				}}
			/>
		</div>

		<div class="text-xs text-fg-muted">
			<span>{formatDate(analysis.updated_at)}</span>
		</div>
	</div>
</div>
