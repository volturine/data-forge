<script lang="ts">
	import { goto } from '$app/navigation';

	function createNew() {
		goto('/analysis/new');
	}
</script>

<div class="empty">
	<div class="icon">
		<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
			<rect x="3" y="3" width="18" height="18" rx="1" />
			<path d="M3 9h18M9 3v18" />
		</svg>
	</div>

	<h2>No analyses yet</h2>
	<p>Create your first analysis to get started with data exploration.</p>

	<button class="btn-create" onclick={createNew}>
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
			<path d="M12 5v14M5 12h14" />
		</svg>
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
		font-size: var(--text-lg);
		font-weight: 600;
		color: var(--fg-primary);
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
		transition: opacity var(--transition-fast);
	}

	.btn-create:hover {
		opacity: 0.85;
	}
</style>
