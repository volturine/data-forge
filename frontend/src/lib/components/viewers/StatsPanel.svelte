<script lang="ts">
	interface Props {
		rowCount: number;
		columnCount: number;
		stats?: Record<string, { mean?: number; min?: number; max?: number; nullCount?: number }>;
	}

	let { rowCount, columnCount, stats }: Props = $props();

	let hasStats = $derived(stats && Object.keys(stats).length > 0);
</script>

<div class="stats-panel">
	<div class="stats-header">
		<h3>Summary Statistics</h3>
	</div>

	<div class="primary-stats">
		<div class="stat-card">
			<div class="stat-icon">📊</div>
			<div class="stat-content">
				<div class="stat-label">Total Rows</div>
				<div class="stat-value">{rowCount.toLocaleString()}</div>
			</div>
		</div>

		<div class="stat-card">
			<div class="stat-icon">📋</div>
			<div class="stat-content">
				<div class="stat-label">Total Columns</div>
				<div class="stat-value">{columnCount.toLocaleString()}</div>
			</div>
		</div>

		<div class="stat-card">
			<div class="stat-icon">🔢</div>
			<div class="stat-content">
				<div class="stat-label">Data Points</div>
				<div class="stat-value">{(rowCount * columnCount).toLocaleString()}</div>
			</div>
		</div>
	</div>

	{#if hasStats && stats}
		<div class="column-stats">
			<h4>Column Statistics</h4>
			<div class="stats-grid">
				{#each Object.entries(stats) as [column, columnStats] (column)}
					<div class="column-stat-card">
						<div class="column-stat-header">{column}</div>
						<div class="column-stat-details">
							{#if columnStats.mean !== undefined}
								<div class="stat-row">
									<span class="stat-key">Mean:</span>
									<span class="stat-val">{columnStats.mean.toFixed(2)}</span>
								</div>
							{/if}
							{#if columnStats.min !== undefined}
								<div class="stat-row">
									<span class="stat-key">Min:</span>
									<span class="stat-val">{columnStats.min.toLocaleString()}</span>
								</div>
							{/if}
							{#if columnStats.max !== undefined}
								<div class="stat-row">
									<span class="stat-key">Max:</span>
									<span class="stat-val">{columnStats.max.toLocaleString()}</span>
								</div>
							{/if}
							{#if columnStats.nullCount !== undefined && columnStats.nullCount > 0}
								<div class="stat-row">
									<span class="stat-key">Nulls:</span>
									<span class="stat-val null-count">{columnStats.nullCount.toLocaleString()}</span>
								</div>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		</div>
	{/if}
</div>

<style>
	.stats-panel {
		background: var(--panel-bg);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		overflow: hidden;
	}
	.stats-header {
		padding: var(--space-4) var(--space-5);
		border-bottom: 1px solid var(--border-primary);
		background: var(--panel-header-bg);
	}
	.stats-header h3 {
		margin: 0;
	}
	.primary-stats {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
		gap: var(--space-4);
		padding: var(--space-5);
	}
	.stat-card {
		display: flex;
		align-items: center;
		gap: var(--space-4);
		padding: var(--space-4);
		background: var(--bg-tertiary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-md);
		transition:
			transform var(--transition),
			box-shadow var(--transition);
	}
	.stat-card:hover {
		transform: translateY(-2px);
		box-shadow: var(--shadow-soft);
	}
	.stat-icon {
		font-size: var(--text-3xl);
		line-height: 1;
	}
	.stat-content {
		flex: 1;
	}
	.stat-label {
		font-size: var(--text-xs);
		font-weight: var(--font-medium);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--fg-muted);
		margin-bottom: var(--space-1);
	}
	.stat-value {
		font-size: var(--text-2xl);
		font-weight: var(--font-bold);
		color: var(--fg-primary);
		line-height: 1;
	}
	.column-stats {
		padding: 0 var(--space-5) var(--space-5);
	}
	.column-stats h4 {
		margin: 0 0 var(--space-4) 0;
		font-size: var(--text-sm);
		font-weight: var(--font-semibold);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--fg-muted);
	}
	.stats-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
		gap: var(--space-3);
	}
	.column-stat-card {
		padding: var(--space-3);
		background: var(--bg-tertiary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-md);
	}
	.column-stat-header {
		font-size: var(--text-sm);
		font-weight: var(--font-semibold);
		font-family: var(--font-mono);
		color: var(--fg-primary);
		margin-bottom: var(--space-2);
		padding-bottom: var(--space-2);
		border-bottom: 1px solid var(--border-primary);
	}
	.column-stat-details {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.stat-row {
		display: flex;
		justify-content: space-between;
		font-size: var(--text-sm);
	}
	.stat-key {
		color: var(--fg-muted);
		font-weight: var(--font-medium);
	}
	.stat-val {
		color: var(--fg-primary);
		font-weight: var(--font-semibold);
		font-family: var(--font-mono);
	}
	.null-count {
		color: var(--error-fg);
	}
</style>
