<script lang="ts">
	import type { AnalysisGalleryItem } from '$lib/types/analysis';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { BarChart3, Trash2 } from 'lucide-svelte';

	interface Props {
		analysis: AnalysisGalleryItem;
		onDelete: (id: string) => void;
	}

	let { analysis, onDelete }: Props = $props();

	function handleClick(e: MouseEvent) {
		if (!(e.target as HTMLElement).closest('button')) {
			goto(resolve(`/analysis/${analysis.id}`), { invalidateAll: true });
		}
	}

	function handleKeyPress(e: KeyboardEvent) {
		if ((e.key === 'Enter' || e.key === ' ') && !(e.target as HTMLElement).closest('button')) {
			e.preventDefault();
			goto(resolve(`/analysis/${analysis.id}`), { invalidateAll: true });
		}
	}

	function handleDelete(e: MouseEvent) {
		e.stopPropagation();
		onDelete(analysis.id);
	}

	function formatDate(date: string): string {
		return new Date(date).toLocaleDateString('en-US', {
			month: 'short',
			day: 'numeric'
		});
	}
</script>

<div class="card" onclick={handleClick} onkeypress={handleKeyPress} role="button" tabindex="0">
	<div class="thumbnail">
		{#if analysis.thumbnail}
			<img src={analysis.thumbnail} alt={analysis.name} />
		{:else}
			<div class="placeholder">
				<BarChart3 size={32} strokeWidth={1.5} />
			</div>
		{/if}
	</div>

	<div class="content">
		<div class="header">
			<h3>{analysis.name}</h3>
			<button class="btn-delete" onclick={handleDelete} aria-label="Delete analysis">
				<Trash2 size={14} />
			</button>
		</div>

		<div class="metadata">
			<span class="stat">
				{#if analysis.row_count !== null}
					{analysis.row_count.toLocaleString()} rows
				{:else}
					-- rows
				{/if}
			</span>
			<span class="divider">/</span>
			<span class="stat">
				{#if analysis.column_count !== null}
					{analysis.column_count} cols
				{:else}
					-- cols
				{/if}
			</span>
			<span class="divider">/</span>
			<span class="date">{formatDate(analysis.updated_at)}</span>
		</div>
	</div>
</div>

<style>
	.card {
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		overflow: hidden;
		cursor: pointer;
		transition: all var(--transition);
		background-color: var(--bg-primary);
		box-shadow: var(--card-shadow);
	}
	.card:hover {
		border-color: var(--border-tertiary);
		transform: translateY(-1px);
	}
	.card:focus {
		outline: none;
		border-color: var(--border-focus);
	}
	.thumbnail {
		width: 100%;
		aspect-ratio: 16 / 9;
		background-color: var(--bg-tertiary);
		display: flex;
		align-items: center;
		justify-content: center;
		border-bottom: 1px solid var(--border-primary);
	}
	.thumbnail img {
		width: 100%;
		height: 100%;
		object-fit: cover;
	}
	.placeholder {
		color: var(--fg-faint);
	}
	.content {
		padding: var(--space-4);
	}
	.header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: var(--space-3);
		margin-bottom: var(--space-3);
	}
	h3 {
		margin: 0;
		font-size: var(--text-sm);
		font-weight: var(--font-semibold);
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.metadata {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-xs);
		color: var(--fg-muted);
	}
	.divider {
		color: var(--fg-faint);
	}
	.btn-delete {
		flex-shrink: 0;
		background-color: transparent;
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		padding: var(--space-1);
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--fg-muted);
		transition: all var(--transition);
	}
	.btn-delete:hover {
		background-color: var(--error-bg);
		border-color: var(--error-border);
		color: var(--error-fg);
	}
</style>
