<script lang="ts">
	import { Cpu, X, ChevronDown, LoaderCircle } from 'lucide-svelte';
	import { onClickOutside } from 'runed';
	import { enginesStore } from '$lib/stores/engines.svelte';

	let expanded = $state(false);
	let killing = $state<string | null>(null);

	$effect(() => {
		enginesStore.startPolling();
		return () => enginesStore.stopPolling();
	});

	async function handleKill(analysisId: string) {
		killing = analysisId;
		try {
			await enginesStore.shutdownEngine(analysisId);
		} finally {
			killing = null;
		}
	}

	function formatTime(isoString: string | null): string {
		if (!isoString) return 'N/A';
		const date = new Date(isoString);
		const now = new Date();
		const diff = Math.floor((now.getTime() - date.getTime()) / 1000);

		if (diff < 60) return `${diff}s ago`;
		if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
		return `${Math.floor(diff / 3600)}h ago`;
	}

	function toggleExpanded() {
		expanded = !expanded;
	}

	let dropdownRef = $state<HTMLElement>();
	onClickOutside(
		() => dropdownRef,
		() => {
			expanded = false;
		},
		{ immediate: true }
	);
</script>

<div class="engine-monitor">
	<button
		class="trigger"
		class:active={expanded}
		class:has-engines={enginesStore.count > 0}
		onclick={toggleExpanded}
		title="Engine Monitor"
	>
		<Cpu size={16} />
		{#if enginesStore.count > 0}
			<span class="count">{enginesStore.count}</span>
		{/if}
		<ChevronDown size={12} class="chevron" />
	</button>

	{#if expanded}
		<div class="dropdown" bind:this={dropdownRef}>
			<div class="dropdown-header">
				<span class="dropdown-title">Active Engines</span>
				<button class="close-btn" onclick={() => (expanded = false)}>
					<X size={14} />
				</button>
			</div>

			<div class="dropdown-content">
				{#if enginesStore.count === 0}
					{#if enginesStore.loading}
						<div class="empty">
							<LoaderCircle size={16} class="spinner" />
							<span>Loading...</span>
						</div>
					{:else}
						<div class="empty">
							<span>No active engines</span>
						</div>
					{/if}
				{:else}
					<ul class="engine-list">
						{#each enginesStore.engines as engine (engine.analysis_id)}
							<li class="engine-item">
								<div class="engine-info">
									<div class="engine-row">
										<span class="engine-id" title={engine.analysis_id}>
											{engine.analysis_id.slice(0, 8)}...
										</span>
										<span
											class="engine-status"
											class:healthy={engine.status === 'healthy'}
											class:terminated={engine.status === 'terminated'}
										>
											{engine.status}
										</span>
									</div>
									<div class="engine-meta">
										{#if engine.current_job_id}
											<span class="job-badge">Job: {engine.current_job_id.slice(0, 6)}</span>
										{/if}
										<span class="last-activity">{formatTime(engine.last_activity)}</span>
									</div>
								</div>
								<button
									class="kill-btn"
									onclick={() => handleKill(engine.analysis_id)}
									disabled={killing === engine.analysis_id}
									title="Shutdown engine"
								>
									{#if killing === engine.analysis_id}
										<LoaderCircle size={12} class="spinner" />
									{:else}
										<X size={12} />
									{/if}
								</button>
							</li>
						{/each}
					</ul>
				{/if}
			</div>

			{#if enginesStore.error}
				<div class="error">{enginesStore.error}</div>
			{/if}
		</div>
		<button class="backdrop" aria-label="Close engine monitor"></button>
	{/if}
</div>

<style>
	.engine-monitor {
		position: relative;
	}
	.trigger {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-3);
		background-color: var(--bg-primary);
		border: 1px solid var(--border-primary);
		color: var(--fg-tertiary);
		font-size: var(--text-xs);
		cursor: pointer;
		border-radius: var(--radius-sm);
		transition: all var(--transition);
		box-shadow: var(--card-shadow);
	}
	.trigger:hover,
	.trigger.active {
		background-color: var(--bg-hover);
		color: var(--fg-primary);
	}
	.trigger.has-engines {
		color: var(--fg-secondary);
	}
	.count {
		background-color: var(--accent-primary);
		color: var(--bg-primary);
		padding: 0 var(--space-2);
		border-radius: var(--radius-full);
		font-size: var(--text-xs);
		font-weight: 600;
		min-width: 18px;
		text-align: center;
	}
	.trigger :global(.chevron) {
		transition: transform var(--transition);
	}
	.trigger.active :global(.chevron) {
		transform: rotate(180deg);
	}
	.backdrop {
		position: fixed;
		inset: 0;
		z-index: 99;
		background: transparent;
		border: none;
		cursor: default;
	}
	.dropdown {
		position: absolute;
		top: calc(100% + var(--space-2));
		right: 0;
		width: 280px;
		background-color: var(--bg-primary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		box-shadow: var(--dialog-shadow);
		z-index: 100;
		overflow: hidden;
	}
	.dropdown-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-3);
		border-bottom: 1px solid var(--border-primary);
		background-color: var(--bg-secondary);
	}
	.dropdown-title {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--fg-primary);
	}
	.close-btn {
		background: transparent;
		border: none;
		padding: var(--space-1);
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: var(--radius-sm);
		color: var(--fg-muted);
		transition: all var(--transition);
	}
	.close-btn:hover {
		background-color: var(--bg-hover);
		color: var(--fg-primary);
	}
	.dropdown-content {
		max-height: 300px;
		overflow-y: auto;
	}
	.empty {
		padding: var(--space-6);
		text-align: center;
		color: var(--fg-muted);
		font-size: var(--text-sm);
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-2);
	}
	.engine-list {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.engine-item {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-3);
		border-bottom: 1px solid var(--border-primary);
	}
	.engine-item:last-child {
		border-bottom: none;
	}
	.engine-info {
		flex: 1;
		min-width: 0;
	}
	.engine-row {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.engine-id {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--fg-primary);
	}
	.engine-status {
		font-size: var(--text-xs);
		padding: 1px var(--space-2);
		border-radius: var(--radius-full);
		background-color: var(--bg-tertiary);
		color: var(--fg-muted);
		text-transform: uppercase;
		font-weight: 500;
	}
	.engine-status.healthy {
		background-color: var(--success-bg);
		color: var(--success-fg);
	}
	.engine-status.terminated {
		background-color: var(--bg-tertiary);
		color: var(--fg-muted);
	}
	.engine-meta {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin-top: var(--space-1);
	}
	.job-badge {
		font-size: var(--text-xs);
		color: var(--accent-primary);
		font-family: var(--font-mono);
	}
	.last-activity {
		font-size: var(--text-xs);
		color: var(--fg-muted);
	}
	.kill-btn {
		background-color: transparent;
		border: 1px solid var(--border-primary);
		color: var(--fg-muted);
		padding: var(--space-1);
		border-radius: var(--radius-sm);
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		transition: all var(--transition);
	}
	.kill-btn:hover:not(:disabled) {
		background-color: var(--error-bg);
		border-color: var(--error-border);
		color: var(--error-fg);
	}
	.kill-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.error {
		padding: var(--space-2) var(--space-3);
		background-color: var(--error-bg);
		color: var(--error-fg);
		font-size: var(--text-xs);
		border-top: 1px solid var(--error-border);
	}
	:global(.spinner) {
		animation: spin 1s linear infinite;
	}
</style>
