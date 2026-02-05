<script lang="ts">
	interface Props {
		rowCount: number;
		columnCount: number;
		stats?: Record<string, { mean?: number; min?: number; max?: number; nullCount?: number }>;
	}

	let { rowCount, columnCount, stats }: Props = $props();

	let hasStats = $derived(stats && Object.keys(stats).length > 0);
</script>

<div
	class="overflow-hidden rounded-md border"
	style="background: var(--panel-bg); border-color: var(--panel-border);"
>
	<div
		class="px-5 py-4 border-b"
		style="border-color: var(--border-primary); background: var(--panel-header-bg);"
	>
		<h3 class="m-0">Summary Statistics</h3>
	</div>

	<div class="grid gap-4 p-5" style="grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));">
		<div
			class="stat-card flex items-center gap-4 p-4 rounded-md border transition-all"
			style="background: var(--bg-tertiary); border-color: var(--border-primary);"
		>
			<div class="text-3xl leading-none">📊</div>
			<div class="flex-1">
				<div
					class="text-xs font-medium uppercase tracking-wider mb-1"
					style="color: var(--fg-muted);"
				>
					Total Rows
				</div>
				<div class="text-2xl font-bold leading-none" style="color: var(--fg-primary);">
					{rowCount.toLocaleString()}
				</div>
			</div>
		</div>

		<div
			class="stat-card flex items-center gap-4 p-4 rounded-md border transition-all"
			style="background: var(--bg-tertiary); border-color: var(--border-primary);"
		>
			<div class="text-3xl leading-none">📋</div>
			<div class="flex-1">
				<div
					class="text-xs font-medium uppercase tracking-wider mb-1"
					style="color: var(--fg-muted);"
				>
					Total Columns
				</div>
				<div class="text-2xl font-bold leading-none" style="color: var(--fg-primary);">
					{columnCount.toLocaleString()}
				</div>
			</div>
		</div>

		<div
			class="stat-card flex items-center gap-4 p-4 rounded-md border transition-all"
			style="background: var(--bg-tertiary); border-color: var(--border-primary);"
		>
			<div class="text-3xl leading-none">🔢</div>
			<div class="flex-1">
				<div
					class="text-xs font-medium uppercase tracking-wider mb-1"
					style="color: var(--fg-muted);"
				>
					Data Points
				</div>
				<div class="text-2xl font-bold leading-none" style="color: var(--fg-primary);">
					{(rowCount * columnCount).toLocaleString()}
				</div>
			</div>
		</div>
	</div>

	{#if hasStats && stats}
		<div class="px-5 pb-5">
			<h4
				class="m-0 mb-4 text-sm font-semibold uppercase tracking-wider"
				style="color: var(--fg-muted);"
			>
				Column Statistics
			</h4>
			<div class="grid gap-3" style="grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));">
				{#each Object.entries(stats) as [column, columnStats] (column)}
					<div
						class="p-3 rounded-md border"
						style="background: var(--bg-tertiary); border-color: var(--border-primary);"
					>
						<div
							class="text-sm font-semibold font-mono mb-2 pb-2 border-b"
							style="color: var(--fg-primary); border-color: var(--border-primary);"
						>
							{column}
						</div>
						<div class="flex flex-col gap-1">
							{#if columnStats.mean !== undefined}
								<div class="flex justify-between text-sm">
									<span class="font-medium" style="color: var(--fg-muted);">Mean:</span>
									<span class="font-semibold font-mono" style="color: var(--fg-primary);">
										{columnStats.mean.toFixed(2)}
									</span>
								</div>
							{/if}
							{#if columnStats.min !== undefined}
								<div class="flex justify-between text-sm">
									<span class="font-medium" style="color: var(--fg-muted);">Min:</span>
									<span class="font-semibold font-mono" style="color: var(--fg-primary);">
										{columnStats.min.toLocaleString()}
									</span>
								</div>
							{/if}
							{#if columnStats.max !== undefined}
								<div class="flex justify-between text-sm">
									<span class="font-medium" style="color: var(--fg-muted);">Max:</span>
									<span class="font-semibold font-mono" style="color: var(--fg-primary);">
										{columnStats.max.toLocaleString()}
									</span>
								</div>
							{/if}
							{#if columnStats.nullCount !== undefined && columnStats.nullCount > 0}
								<div class="flex justify-between text-sm">
									<span class="font-medium" style="color: var(--fg-muted);">Nulls:</span>
									<span class="font-semibold font-mono" style="color: var(--error-fg);">
										{columnStats.nullCount.toLocaleString()}
									</span>
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
	.stat-card:hover {
		transform: translateY(-2px);
		box-shadow: var(--shadow-soft);
	}
</style>
