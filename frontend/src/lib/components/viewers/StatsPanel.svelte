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
		background: #fff;
		border: 1px solid #e5e7eb;
		border-radius: 8px;
		overflow: hidden;
	}

	.stats-header {
		padding: 1rem 1.25rem;
		border-bottom: 1px solid #e5e7eb;
		background: #f9fafb;
	}

	.stats-header h3 {
		margin: 0;
		font-size: 1.125rem;
		font-weight: 600;
		color: #111827;
	}

	.primary-stats {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
		gap: 1rem;
		padding: 1.25rem;
	}

	.stat-card {
		display: flex;
		align-items: center;
		gap: 1rem;
		padding: 1rem;
		background: #f9fafb;
		border: 1px solid #e5e7eb;
		border-radius: 6px;
		transition:
			transform 0.15s ease,
			box-shadow 0.15s ease;
	}

	.stat-card:hover {
		transform: translateY(-2px);
		box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
	}

	.stat-icon {
		font-size: 2rem;
		line-height: 1;
	}

	.stat-content {
		flex: 1;
	}

	.stat-label {
		font-size: 0.75rem;
		font-weight: 500;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: #6b7280;
		margin-bottom: 0.25rem;
	}

	.stat-value {
		font-size: 1.5rem;
		font-weight: 700;
		color: #111827;
		line-height: 1;
	}

	.column-stats {
		padding: 0 1.25rem 1.25rem;
	}

	.column-stats h4 {
		margin: 0 0 1rem 0;
		font-size: 0.875rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: #6b7280;
	}

	.stats-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
		gap: 0.75rem;
	}

	.column-stat-card {
		padding: 0.875rem;
		background: #f9fafb;
		border: 1px solid #e5e7eb;
		border-radius: 6px;
	}

	.column-stat-header {
		font-size: 0.875rem;
		font-weight: 600;
		font-family: 'Courier New', monospace;
		color: #111827;
		margin-bottom: 0.5rem;
		padding-bottom: 0.5rem;
		border-bottom: 1px solid #e5e7eb;
	}

	.column-stat-details {
		display: flex;
		flex-direction: column;
		gap: 0.375rem;
	}

	.stat-row {
		display: flex;
		justify-content: space-between;
		font-size: 0.813rem;
	}

	.stat-key {
		color: #6b7280;
		font-weight: 500;
	}

	.stat-val {
		color: #111827;
		font-weight: 600;
		font-family: 'Courier New', monospace;
	}

	.null-count {
		color: #dc2626;
	}
</style>
