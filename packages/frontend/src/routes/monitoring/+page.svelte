<script lang="ts">
	import BuildsManager from '#lib/components/common/BuildsManager.svelte';
	import ScheduleManager from '#lib/components/common/ScheduleManager.svelte';
	import HealthChecksManager from '#lib/components/common/HealthChecksManager.svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { css } from '#lib/styles/panda.js';
	import TabList from '#lib/components/ui/TabList.svelte';

	const tabs = [
		{ key: 'builds', label: 'Builds' },
		{ key: 'schedules', label: 'Schedules' },
		{ key: 'health', label: 'Health Checks' }
	] as const;

	type TabKey = (typeof tabs)[number]['key'];

	function resolveTab(param: string | null): TabKey {
		return tabs.find((t) => t.key === param)?.key ?? 'builds';
	}

	const activeTab = $derived(resolveTab(page.url.searchParams.get('tab')));

	function selectTab(key: TabKey) {
		goto(resolve(`/monitoring?tab=${key}` as '/'), {
			replaceState: true,
			reset: false
		});
	}
</script>

<div class={css({ marginX: 'auto', paddingX: '6', paddingY: '7' })}>
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
		<TabList {tabs} active={activeTab} onSelect={selectTab} label="Monitoring sections" />
	</div>

	{#if activeTab === 'builds'}
		<div
			id="panel-builds"
			role="tabpanel"
			aria-labelledby="tab-builds"
			class={css({ marginTop: '4', display: 'flex', flexDirection: 'column', gap: '4' })}
		>
			<BuildsManager embedded />
		</div>
	{:else if activeTab === 'schedules'}
		<div
			id="panel-schedules"
			role="tabpanel"
			aria-labelledby="tab-schedules"
			class={css({ marginTop: '4' })}
		>
			<ScheduleManager />
		</div>
	{:else if activeTab === 'health'}
		<div
			id="panel-health"
			role="tabpanel"
			aria-labelledby="tab-health"
			class={css({ marginTop: '4', display: 'flex', flexDirection: 'column', gap: '3' })}
		>
			<HealthChecksManager />
		</div>
	{/if}
</div>
