<script lang="ts">
	import BuildsManager from '$lib/components/common/BuildsManager.svelte';
	import ScheduleManager from '$lib/components/common/ScheduleManager.svelte';
	import HealthChecksManager from '$lib/components/common/HealthChecksManager.svelte';
	import { Search } from 'lucide-svelte';

	const tabs = [
		{ key: 'builds', label: 'Builds' },
		{ key: 'schedules', label: 'Schedules' },
		{ key: 'health', label: 'Health Checks' }
	] as const;

	type TabKey = (typeof tabs)[number]['key'];

	let activeTab = $state<TabKey>('builds');
	let search = $state('');
	let showPreviews = $state(true);
</script>

<div class="mx-auto max-w-300 px-6 py-7">
	<header class="mb-6 border-b border-tertiary pb-5">
		<h1 class="m-0 mb-2 text-2xl">Monitoring</h1>
		<p class="m-0 text-fg-tertiary">Review builds, schedules, and health checks</p>
	</header>

	<div class="flex flex-col gap-3 border-b border-tertiary pb-3">
		<div class="relative max-w-120">
			<Search size={14} class="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-muted" />
			<input
				type="text"
				placeholder="Search builds, schedules, or health checks..."
				class="w-full border border-tertiary bg-transparent px-3 py-1.5 pl-8 text-sm"
				bind:value={search}
			/>
		</div>
		<div class="flex gap-0 border-b border-tertiary">
			{#each tabs as tab (tab.key)}
				<button
					class="tab -mb-px bg-transparent border-b-2 border-transparent px-3 py-1.5 text-xs font-medium text-fg-muted hover:text-fg-secondary"
					class:active={activeTab === tab.key}
					onclick={() => (activeTab = tab.key)}
				>
					{tab.label}
				</button>
			{/each}
		</div>
	</div>

	{#if activeTab === 'builds'}
		<div class="mt-4">
			<BuildsManager searchQuery={search} {showPreviews} />
		</div>
	{:else if activeTab === 'schedules'}
		<div class="mt-4">
			<ScheduleManager searchQuery={search} />
		</div>
	{:else}
		<div class="mt-4 flex flex-col gap-3">
			<HealthChecksManager searchQuery={search} />
		</div>
	{/if}
</div>
