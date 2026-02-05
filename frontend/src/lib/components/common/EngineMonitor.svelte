<script lang="ts">
	import { Cpu, X, ChevronDown, LoaderCircle } from 'lucide-svelte';
	import { onClickOutside } from 'runed';
	import { enginesStore } from '$lib/stores/engines.svelte';
	import { toEpochDisplay } from '$lib/utils/datetime';

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
		const dateMs = toEpochDisplay(isoString);
		const nowMs = Date.now();
		const diff = Math.floor((nowMs - dateMs) / 1000);

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

<div class="relative">
	<button
		class="trigger flex cursor-pointer items-center gap-2 rounded-sm border px-3 py-2 text-xs transition-all"
		class:active={expanded}
		class:has-engines={enginesStore.count > 0}
		onclick={toggleExpanded}
		title="Engine Monitor"
		style="background-color: var(--bg-primary); border-color: var(--border-primary); color: var(--fg-tertiary); box-shadow: var(--card-shadow);"
	>
		<Cpu size={16} />
		{#if enginesStore.count > 0}
			<span
				class="min-w-[18px] rounded-full px-2 text-center text-xs font-semibold"
				style="background-color: var(--accent-primary); color: var(--bg-primary);"
			>
				{enginesStore.count}
			</span>
		{/if}
		<ChevronDown size={12} class="chevron transition-transform" class:rotate-180={expanded} />
	</button>

	{#if expanded}
		<div
			class="absolute right-0 top-[calc(100%+0.5rem)] z-[100] w-[280px] overflow-hidden rounded-sm border"
			bind:this={dropdownRef}
			style="background-color: var(--bg-primary); border-color: var(--border-primary); box-shadow: var(--dialog-shadow);"
		>
			<div
				class="flex items-center justify-between border-b p-3"
				style="background-color: var(--bg-secondary); border-color: var(--border-primary);"
			>
				<span class="text-sm font-semibold" style="color: var(--fg-primary);">Active Engines</span>
				<button
					class="close-btn flex cursor-pointer items-center justify-center rounded-sm border-none bg-transparent p-1 transition-all"
					onclick={() => (expanded = false)}
					style="color: var(--fg-muted);"
				>
					<X size={14} />
				</button>
			</div>

			<div class="max-h-[300px] overflow-y-auto">
				{#if enginesStore.count === 0}
					{#if enginesStore.loading}
						<div class="flex items-center justify-center gap-2 p-6 text-center text-sm" style="color: var(--fg-muted);">
							<LoaderCircle size={16} class="animate-spin" />
							<span>Loading...</span>
						</div>
					{:else}
						<div class="p-6 text-center text-sm" style="color: var(--fg-muted);">
							<span>No active engines</span>
						</div>
					{/if}
				{:else}
					<ul class="m-0 list-none p-0">
						{#each enginesStore.engines as engine (engine.analysis_id)}
							<li class="engine-item flex items-center gap-3 border-b p-3 last:border-b-0" style="border-color: var(--border-primary);">
								<div class="min-w-0 flex-1">
									<div class="flex items-center gap-2">
										<span class="font-mono text-xs" style="color: var(--fg-primary);" title={engine.analysis_id}>
											{engine.analysis_id.slice(0, 8)}...
										</span>
										<span
											class="rounded-full px-2 py-px text-xs font-medium uppercase"
											class:healthy={engine.status === 'healthy'}
											class:terminated={engine.status === 'terminated'}
											style="background-color: var(--bg-tertiary); color: var(--fg-muted);"
										>
											{engine.status}
										</span>
									</div>
									<div class="mt-1 flex items-center gap-2">
										{#if engine.current_job_id}
											<span class="font-mono text-xs" style="color: var(--accent-primary);">
												Job: {engine.current_job_id.slice(0, 6)}
											</span>
										{/if}
										<span class="text-xs" style="color: var(--fg-muted);">
											{formatTime(engine.last_activity)}
										</span>
									</div>
								</div>
								<button
									class="kill-btn flex cursor-pointer items-center justify-center rounded-sm border p-1 transition-all disabled:cursor-not-allowed disabled:opacity-50"
									onclick={() => handleKill(engine.analysis_id)}
									disabled={killing === engine.analysis_id}
									title="Shutdown engine"
									style="background-color: transparent; border-color: var(--border-primary); color: var(--fg-muted);"
								>
									{#if killing === engine.analysis_id}
										<LoaderCircle size={12} class="animate-spin" />
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
				<div
					class="border-t p-2 text-xs"
					style="background-color: var(--error-bg); color: var(--error-fg); border-color: var(--error-border);"
				>
					{enginesStore.error}
				</div>
			{/if}
		</div>
		<button class="fixed inset-0 z-[99] cursor-default border-none bg-transparent" aria-label="Close engine monitor"></button>
	{/if}
</div>

<style>
	.trigger:hover,
	.trigger.active {
		background-color: var(--bg-hover);
		color: var(--fg-primary);
	}

	.trigger.has-engines {
		color: var(--fg-secondary);
	}

	.close-btn:hover {
		background-color: var(--bg-hover);
		color: var(--fg-primary);
	}

	.healthy {
		background-color: var(--success-bg) !important;
		color: var(--success-fg) !important;
	}

	.terminated {
		background-color: var(--bg-tertiary) !important;
		color: var(--fg-muted) !important;
	}

	.kill-btn:hover:not(:disabled) {
		background-color: var(--error-bg);
		border-color: var(--error-border);
		color: var(--error-fg);
	}
</style>
