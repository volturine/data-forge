<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { LayoutGrid, Plus } from 'lucide-svelte';

	function createNew() {
		goto(resolve('/analysis/new'), { invalidateAll: true });
	}
</script>

<div class="empty">
	<div class="icon">
		<LayoutGrid size={32} strokeWidth={1.5} />
	</div>

	<h2>No analyses yet</h2>
	<p>Create your first analysis to get started with data exploration.</p>

	<button class="btn-create" onclick={createNew}>
		<Plus size={16} />
		Create Analysis
	</button>
</div>

<style>
	.empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: var(--space-12) var(--space-6);
		text-align: center;
		min-height: 400px;
		border: 1px dashed var(--border-secondary);
		border-radius: var(--radius-sm);
		background-color: var(--bg-primary);
		box-shadow: var(--card-shadow);
	}
	.icon {
		width: 64px;
		height: 64px;
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--fg-faint);
		margin-bottom: var(--space-6);
	}
	h2 {
		margin: 0 0 var(--space-2) 0;
		font-weight: var(--font-semibold);
	}
	p {
		margin: 0 0 var(--space-6) 0;
		font-size: var(--text-sm);
		color: var(--fg-tertiary);
		max-width: 300px;
	}
	.btn-create {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-4);
		background-color: var(--accent-primary);
		color: var(--bg-primary);
		border: 1px solid var(--accent-primary);
		border-radius: var(--radius-sm);
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		font-weight: 500;
		cursor: pointer;
		transition: opacity var(--transition);
	}
	.btn-create:hover {
		opacity: 0.85;
	}
</style>
