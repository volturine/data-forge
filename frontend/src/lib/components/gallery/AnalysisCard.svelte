<script lang="ts">
	import type { AnalysisGalleryItem } from '$lib/types/analysis';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { BarChart3, Trash2 } from 'lucide-svelte';

	interface Props {
		analysis: AnalysisGalleryItem;
		selected: boolean;
		anySelected: boolean;
		onDelete: (id: string) => void;
		onToggleSelect: (id: string) => void;
	}

	let { analysis, selected, anySelected, onDelete, onToggleSelect }: Props = $props();

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
		const d = new Date(date);
		const now = new Date();
		const opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' };
		if (d.getFullYear() !== now.getFullYear()) opts.year = 'numeric';
		return d.toLocaleDateString('en-US', opts);
	}
</script>

<div
	class="card"
	class:selected
	onclick={handleClick}
	onkeypress={handleKeyPress}
	role="button"
	tabindex="0"
>
	<div class="thumbnail">
		<input
			type="checkbox"
			class="checkbox"
			class:visible={anySelected}
			checked={selected}
			onchange={(e) => {
				e.stopPropagation();
				onToggleSelect(analysis.id);
			}}
			onclick={(e) => e.stopPropagation()}
			aria-label={`Select ${analysis.name}`}
		/>
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
			<button
				class="btn-delete"
				onclick={(e) => {
					e.stopPropagation();
					onDelete(analysis.id);
				}}
				aria-label="Delete analysis"
			>
				<Trash2 size={14} />
			</button>
		</div>

		<div class="metadata">
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
		position: relative;
	}
	.card:hover {
		border-color: var(--border-tertiary);
		transform: translateY(-1px);
	}
	.card:focus {
		outline: none;
		border-color: var(--border-focus);
	}
	.card.selected {
		border-color: var(--accent-primary);
	}

	/* Checkbox */
	.checkbox {
		position: absolute;
		top: var(--space-2);
		left: var(--space-2);
		z-index: 2;
		width: 18px;
		height: 18px;
		margin: 0;
		cursor: pointer;
		opacity: 0;
		transition: opacity var(--transition);
		accent-color: var(--accent-primary);
	}
	.card:hover .checkbox,
	.checkbox.visible {
		opacity: 1;
	}

	/* Delete button: hover-only */
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
		opacity: 0;
	}
	.card:hover .btn-delete {
		opacity: 1;
	}
	.btn-delete:hover {
		background-color: var(--error-bg);
		border-color: var(--error-border);
		color: var(--error-fg);
	}

	.thumbnail {
		position: relative;
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
		margin-bottom: var(--space-2);
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
		font-size: var(--text-xs);
		color: var(--fg-muted);
	}
</style>
