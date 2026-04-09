<script lang="ts">
	import BuildsManager from '$lib/components/common/BuildsManager.svelte';
	import ActiveBuilds from '$lib/components/common/ActiveBuilds.svelte';
	import ScheduleManager from '$lib/components/common/ScheduleManager.svelte';
	import HealthChecksManager from '$lib/components/common/HealthChecksManager.svelte';
	import { Search } from 'lucide-svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { css, tabButton, input } from '$lib/styles/panda';

	const tabs = [
		{ key: 'builds', label: 'Builds' },
		{ key: 'schedules', label: 'Schedules' },
		{ key: 'health', label: 'Health Checks' }
	] as const;

	type TabKey = (typeof tabs)[number]['key'];

	const validKeys = new Set<string>(tabs.map((t) => t.key));

	function resolveTab(param: string | null): TabKey {
		if (param && validKeys.has(param)) return param as TabKey;
		return 'builds';
	}

	const activeTab = $derived(resolveTab(page.url.searchParams.get('tab')));
	let search = $state('');
	let showPreviews = $state(true);

	function selectTab(key: TabKey) {
		goto(resolve(`/monitoring?tab=${key}` as '/'), {
			replaceState: true,
			keepFocus: true,
			noScroll: true
		});
	}

	function handleTabKeydown(event: KeyboardEvent, index: number) {
		const count = tabs.length;
		let next = -1;
		if (event.key === 'ArrowRight') next = (index + 1) % count;
		if (event.key === 'ArrowLeft') next = (index - 1 + count) % count;
		if (event.key === 'Home') next = 0;
		if (event.key === 'End') next = count - 1;
		if (next < 0) return;
		event.preventDefault();
		selectTab(tabs[next].key);
		const target = document.getElementById(`tab-${tabs[next].key}`);
		target?.focus();
	}
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
			role="tablist"
			aria-label="Monitoring sections"
			class={css({
				display: 'flex',
				gap: '0',
				borderBottomWidth: '1'
			})}
		>
			{#each tabs as tab, i (tab.key)}
				<button
					id="tab-{tab.key}"
					role="tab"
					aria-selected={activeTab === tab.key}
					aria-controls="panel-{tab.key}"
					tabindex={activeTab === tab.key ? 0 : -1}
					class={tabButton({ active: activeTab === tab.key })}
					onclick={() => selectTab(tab.key)}
					onkeydown={(e) => handleTabKeydown(e, i)}
				>
					{tab.label}
				</button>
			{/each}
		</div>
	</div>

	{#if activeTab === 'builds'}
		<div
			id="panel-builds"
			role="tabpanel"
			aria-labelledby="tab-builds"
			class={css({ marginTop: '4', display: 'flex', flexDirection: 'column', gap: '4' })}
		>
			<ActiveBuilds searchQuery={search} />
			<BuildsManager searchQuery={search} {showPreviews} embedded />
		</div>
	{:else if activeTab === 'schedules'}
		<div
			id="panel-schedules"
			role="tabpanel"
			aria-labelledby="tab-schedules"
			class={css({ marginTop: '4' })}
		>
			<ScheduleManager searchQuery={search} />
		</div>
	{:else if activeTab === 'health'}
		<div
			id="panel-health"
			role="tabpanel"
			aria-labelledby="tab-health"
			class={css({ marginTop: '4', display: 'flex', flexDirection: 'column', gap: '3' })}
		>
			<HealthChecksManager searchQuery={search} />
		</div>
	{/if}
</div>
