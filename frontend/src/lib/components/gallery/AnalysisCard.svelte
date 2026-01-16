<script lang="ts">
	import type { AnalysisGalleryItem } from '$lib/types/analysis';
	import { goto } from '$app/navigation';

	interface Props {
		analysis: AnalysisGalleryItem;
		onDelete: (id: string) => void;
	}

	let { analysis, onDelete }: Props = $props();

	function handleClick(e: MouseEvent) {
		if (!(e.target as HTMLElement).closest('button')) {
			goto(`/analysis/${analysis.id}`);
		}
	}

	function handleKeyPress(e: KeyboardEvent) {
		if ((e.key === 'Enter' || e.key === ' ') && !(e.target as HTMLElement).closest('button')) {
			e.preventDefault();
			goto(`/analysis/${analysis.id}`);
		}
	}

	function handleDelete(e: MouseEvent) {
		e.stopPropagation();
		onDelete(analysis.id);
	}

	function formatDate(date: string): string {
		return new Date(date).toLocaleDateString('en-US', {
			month: 'short',
			day: 'numeric',
			year: 'numeric'
		});
	}
</script>

<div class="card" onclick={handleClick} onkeypress={handleKeyPress} role="button" tabindex="0">
	<div class="thumbnail">
		{#if analysis.thumbnail}
			<img src={analysis.thumbnail} alt={analysis.name} />
		{:else}
			<div class="placeholder">
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
				>
					<path d="M3 3h18v18H3z" stroke-width="2" />
					<path d="M3 9l6 6 3-3 9 9" stroke-width="2" />
					<circle cx="7.5" cy="6.5" r="1.5" fill="currentColor" />
				</svg>
			</div>
		{/if}
	</div>

	<div class="content">
		<h3>{analysis.name}</h3>

		<div class="metadata">
			{#if analysis.row_count !== null || analysis.column_count !== null}
				<div class="stats">
					{#if analysis.row_count !== null}
						<span>{analysis.row_count.toLocaleString()} rows</span>
					{/if}
					{#if analysis.column_count !== null}
						<span>{analysis.column_count} cols</span>
					{/if}
				</div>
			{/if}
			<div class="date">Updated {formatDate(analysis.updated_at)}</div>
		</div>
	</div>

	<div class="actions">
		<button class="btn-delete" onclick={handleDelete} aria-label="Delete analysis">
			<svg
				xmlns="http://www.w3.org/2000/svg"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
			>
				<path d="M3 6h18M8 6V4h8v2M19 6v14H5V6" stroke-width="2" />
				<path d="M10 11v6M14 11v6" stroke-width="2" />
			</svg>
		</button>
	</div>
</div>

<style>
	.card {
		border: 1px solid #e0e0e0;
		border-radius: 8px;
		overflow: hidden;
		cursor: pointer;
		transition: all 0.2s;
		background: white;
		position: relative;
	}

	.card:hover {
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
		transform: translateY(-2px);
	}

	.thumbnail {
		width: 100%;
		aspect-ratio: 16 / 9;
		background: #f5f5f5;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.thumbnail img {
		width: 100%;
		height: 100%;
		object-fit: cover;
	}

	.placeholder {
		width: 64px;
		height: 64px;
		color: #bdbdbd;
	}

	.placeholder svg {
		width: 100%;
		height: 100%;
	}

	.content {
		padding: 16px;
	}

	h3 {
		margin: 0 0 12px 0;
		font-size: 18px;
		font-weight: 600;
		color: #212121;
	}

	.metadata {
		display: flex;
		flex-direction: column;
		gap: 8px;
		font-size: 14px;
		color: #757575;
	}

	.stats {
		display: flex;
		gap: 12px;
	}

	.stats span {
		display: inline-flex;
		align-items: center;
		gap: 4px;
	}

	.date {
		color: #9e9e9e;
		font-size: 13px;
	}

	.actions {
		position: absolute;
		top: 12px;
		right: 12px;
	}

	.btn-delete {
		background: rgba(255, 255, 255, 0.9);
		border: 1px solid #e0e0e0;
		border-radius: 6px;
		padding: 8px;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		transition: all 0.2s;
		width: 36px;
		height: 36px;
	}

	.btn-delete:hover {
		background: #fff;
		border-color: #d32f2f;
		color: #d32f2f;
	}

	.btn-delete svg {
		width: 20px;
		height: 20px;
		stroke-width: 2;
	}
</style>
