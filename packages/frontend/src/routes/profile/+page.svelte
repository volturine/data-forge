<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { SvelteSet } from 'svelte/reactivity';
	import { css } from '#lib/styles/panda.js';
	import { useNamespace } from '#lib/stores/namespace.svelte.js';
	import TabList from '#lib/components/ui/TabList.svelte';
	import AccountTab from './AccountTab.svelte';
	import PreferencesTab from './PreferencesTab.svelte';
	import NotificationsTab from './NotificationsTab.svelte';
	import AiProvidersTab from './AiProvidersTab.svelte';
	import SystemTab from './SystemTab.svelte';

	const tabs = [
		{ key: 'account', label: 'Account' },
		{ key: 'preferences', label: 'Preferences' },
		{ key: 'notifications', label: 'Notifications' },
		{ key: 'ai-providers', label: 'AI Providers' },
		{ key: 'system', label: 'System' }
	] as const;

	type TabKey = (typeof tabs)[number]['key'];

	function resolveTab(hash: string): TabKey {
		return tabs.find((t) => t.key === hash.replace('#', ''))?.key ?? 'account';
	}

	const activeTab = $derived(resolveTab(page.url.hash));
	const ns = useNamespace();
	const systemTabKey = $derived(ns.ready ? ns.value : '');
	const activated = new SvelteSet<TabKey>(['account', resolveTab(page.url.hash)]);

	function selectTab(key: TabKey) {
		activated.add(key);
		goto(resolve(`/profile#${key}` as '/'), {
			replaceState: true,
			reset: false
		});
	}
</script>

<svelte:window onhashchange={() => activated.add(resolveTab(page.url.hash))} />

<div
	class={css({
		maxWidth: '640px',
		marginX: 'auto',
		width: '100%',
		paddingX: '6',
		paddingY: '8',
		display: 'flex',
		flexDirection: 'column',
		gap: '6'
	})}
>
	<div>
		<h1 class={css({ fontSize: 'xl', fontWeight: 'semibold', color: 'fg.primary' })}>Profile</h1>
		<p class={css({ fontSize: 'sm', color: 'fg.muted', marginTop: '1' })}>
			Manage your account and application settings
		</p>
	</div>

	<TabList {tabs} active={activeTab} onSelect={selectTab} label="Profile sections" size="lg" />

	{#if activeTab === 'account'}
		<div id="panel-account" role="tabpanel" aria-labelledby="tab-account">
			<AccountTab />
		</div>
	{/if}
	{#if activeTab === 'preferences' || activated.has('preferences')}
		<div
			id="panel-preferences"
			role="tabpanel"
			aria-labelledby="tab-preferences"
			hidden={activeTab !== 'preferences'}
		>
			<PreferencesTab />
		</div>
	{/if}

	{#if activeTab === 'notifications' || activated.has('notifications')}
		<div
			id="panel-notifications"
			role="tabpanel"
			aria-labelledby="tab-notifications"
			hidden={activeTab !== 'notifications'}
		>
			<NotificationsTab />
		</div>
	{/if}

	{#if activeTab === 'ai-providers' || activated.has('ai-providers')}
		<div
			id="panel-ai-providers"
			role="tabpanel"
			aria-labelledby="tab-ai-providers"
			hidden={activeTab !== 'ai-providers'}
		>
			<AiProvidersTab />
		</div>
	{/if}

	{#if activeTab === 'system' || activated.has('system')}
		<div
			id="panel-system"
			role="tabpanel"
			aria-labelledby="tab-system"
			hidden={activeTab !== 'system'}
		>
			{#key systemTabKey}
				<SystemTab />
			{/key}
		</div>
	{/if}
</div>
