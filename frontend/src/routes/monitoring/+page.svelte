<script lang="ts">
	import BuildsManager from '$lib/components/common/BuildsManager.svelte';
	import ScheduleManager from '$lib/components/common/ScheduleManager.svelte';
	import HealthChecksManager from '$lib/components/common/HealthChecksManager.svelte';
	import { Search } from 'lucide-svelte';
	import { css, tabButton, input } from '$lib/styles/panda';

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

<div class={css({ marginX: 'auto', maxWidth: 'page', paddingX: '6', paddingY: '7' })}>
	<header
		class={css({
			marginBottom: '6',
			borderBottomWidth: '1',
			paddingBottom: '5'
		})}
	>
		<h1 class={css({ margin: '0', marginBottom: '2', fontSize: '2xl' })}>Monitoring</h1>
		<p class={css({ margin: '0', color: 'fg.tertiary' })}>
			Review builds, schedules, and health checks
		</p>
	</header>

	<div
		class={css({
			display: 'flex',
			flexDirection: 'column',
			gap: '3',
			borderBottomWidth: '1',
			paddingBottom: '3'
		})}
	>
		<div class={css({ position: 'relative', maxWidth: 'modalSm' })}>
			<Search
				size={14}
				class={css({
					position: 'absolute',
					left: '2.5',
					top: '50%',
					transform: 'translateY(-50%)',
					color: 'fg.muted'
				})}
			/>
			<input
				type="text"
				id="monitor-search"
				aria-label="Search builds, schedules, or health checks"
				placeholder="Search builds, schedules, or health checks..."
				class={input({ variant: 'search' })}
				bind:value={search}
			/>
		</div>
		<div
			class={css({
				display: 'flex',
				gap: '0',
				borderBottomWidth: '1'
			})}
		>
			{#each tabs as tab (tab.key)}
				<button
					class={tabButton({ active: activeTab === tab.key })}
					onclick={() => (activeTab = tab.key)}
				>
					{tab.label}
				</button>
			{/each}
		</div>
	</div>

	{#if activeTab === 'builds'}
		<div class={css({ marginTop: '4' })}>
			<BuildsManager searchQuery={search} {showPreviews} />
		</div>
	{:else if activeTab === 'schedules'}
		<div class={css({ marginTop: '4' })}>
			<ScheduleManager searchQuery={search} />
		</div>
	{:else}
		<div class={css({ marginTop: '4', display: 'flex', flexDirection: 'column', gap: '3' })}>
			<HealthChecksManager searchQuery={search} />
		</div>
	{/if}
</div>
