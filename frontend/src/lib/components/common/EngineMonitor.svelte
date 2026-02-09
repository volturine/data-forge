<script lang="ts">
	import { Cpu, X, ChevronDown, LoaderCircle } from 'lucide-svelte';
	import { onClickOutside } from 'runed';
	import { untrack } from 'svelte';
	import { enginesStore } from '$lib/stores/engines.svelte';
	import { toEpochDisplay } from '$lib/utils/datetime';

	let expanded = $state(false);
	let killing = $state<string | null>(null);

	$effect(() => {
		untrack(() => enginesStore.startPolling());
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
		if (expanded) {
			enginesStore.fetch();
		}
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

<div class="relative" bind:this={dropdownRef}>
	<button
		class="flex cursor-pointer items-center gap-2 border border-transparent px-3 py-2 text-xs transition-all text-fg-tertiary hover:text-fg-primary"
		class:!bg-bg-hover={expanded}
		class:!text-fg-primary={expanded}
		class:text-fg-secondary={enginesStore.count > 0}
		onclick={toggleExpanded}
		title="Engine Monitor"
	>
		<Cpu size={16} />
		{#if enginesStore.count > 0}
			<span class="min-w-4.5 px-2 text-center text-xs font-semibold bg-accent text-bg-primary">
				{enginesStore.count}
			</span>
		{/if}
		<span class="transition-transform" class:rotate-180={expanded}>
			<ChevronDown size={12} />
		</span>
	</button>

	{#if expanded}
		<div
			class="absolute right-0 top-full z-engine w-70 overflow-hidden border bg-primary border-tertiary"
		>
			<div class="flex items-center justify-between border-b p-3 bg-secondary border-tertiary">
				<span class="text-sm font-semibold text-fg-primary">Active Engines</span>
				<button
					class="flex cursor-pointer items-center justify-center border-none bg-transparent p-1 transition-all text-fg-muted hover:bg-hover hover:text-fg-primary"
					onclick={() => (expanded = false)}
				>
					<X size={14} />
				</button>
			</div>

			<div class="max-h-75 overflow-y-auto">
				{#if enginesStore.count === 0}
					{#if enginesStore.loading}
						<div
							class="flex items-center justify-center gap-2 p-6 text-center text-sm text-fg-muted"
						>
							<LoaderCircle size={16} class="animate-spin" />
							<span>Loading...</span>
						</div>
					{:else}
						<div class="p-6 text-center text-sm text-fg-muted">
							<span>No active engines</span>
						</div>
					{/if}
				{:else}
					<ul class="m-0 list-none p-0">
						{#each enginesStore.engines as engine (engine.analysis_id)}
							<li class="flex items-center gap-3 border-b p-3 last:border-b-0 border-tertiary">
								<div class="min-w-0 flex-1">
									<div class="flex items-center gap-2">
										<span class="font-mono text-xs text-fg-primary" title={engine.analysis_id}>
											{engine.analysis_id.slice(0, 8)}...
										</span>
										<span
											class="rounded-full px-2 py-px text-xs font-medium uppercase"
											class:bg-accent-bg={engine.status === 'healthy'}
											class:text-accent-primary={engine.status === 'healthy'}
											class:bg-tertiary={engine.status !== 'healthy'}
											class:text-fg-muted={engine.status !== 'healthy'}
										>
											{engine.status}
										</span>
									</div>
									<div class="mt-1 flex items-center gap-2">
										{#if engine.current_job_id}
											<span class="font-mono text-xs text-accent">
												Job: {engine.current_job_id.slice(0, 6)}
											</span>
										{/if}
										<span class="text-xs text-fg-muted">
											{formatTime(engine.last_activity)}
										</span>
									</div>
								</div>
								<button
									class="flex cursor-pointer items-center justify-center border p-1 transition-all disabled:cursor-not-allowed disabled:opacity-50 bg-transparent border-tertiary text-fg-muted hover:bg-error hover:border-error hover:text-error-fg"
									onclick={() => handleKill(engine.analysis_id)}
									disabled={killing === engine.analysis_id}
									title="Shutdown engine"
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
				<div class="border-t p-2 text-xs bg-error text-error-fg border-error">
					{enginesStore.error}
				</div>
			{/if}
		</div>
	{/if}
</div>
