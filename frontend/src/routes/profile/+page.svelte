<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { css, tabButton } from '$lib/styles/panda';
	import AccountTab from './AccountTab.svelte';
	import NotificationsTab from './NotificationsTab.svelte';
	import AiProvidersTab from './AiProvidersTab.svelte';
	import SystemTab from './SystemTab.svelte';

	const tabs = [
		{ key: 'account', label: 'Account' },
		{ key: 'notifications', label: 'Notifications' },
		{ key: 'ai-providers', label: 'AI Providers' },
		{ key: 'system', label: 'System' }
	] as const;

	type TabKey = (typeof tabs)[number]['key'];

	const validKeys = new Set<string>(tabs.map((t) => t.key));

	function resolveTab(hash: string): TabKey {
		const key = hash.replace('#', '');
		if (validKeys.has(key)) return key as TabKey;
		return 'account';
	}

	const activeTab = $derived(resolveTab(page.url.hash));

	function selectTab(key: TabKey) {
		goto(resolve(`/profile#${key}` as '/'), {
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

	// Track which tabs have been activated for lazy loading
	let activated = $state(new Set<TabKey>(['account']));

	$effect(() => {
		if (!activated.has(activeTab)) {
			activated = new Set([...activated, activeTab]);
		}
	});
</script>

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

	<div
		class={css({
			display: 'flex',
			gap: '0',
			borderBottomWidth: '1'
		})}
		role="tablist"
		aria-label="Profile sections"
	>
		{#each tabs as tab, i (tab.key)}
			<button
				id={`tab-${tab.key}`}
				class={tabButton({ active: activeTab === tab.key, size: 'lg' })}
				onclick={() => selectTab(tab.key)}
				onkeydown={(e) => handleTabKeydown(e, i)}
				role="tab"
				aria-selected={activeTab === tab.key}
				aria-controls={`panel-${tab.key}`}
				tabindex={activeTab === tab.key ? 0 : -1}
				type="button"
			>
				{tab.label}
			</button>
		{/each}
	</div>

	{#if activeTab === 'account'}
		<div id="panel-account" role="tabpanel" aria-labelledby="tab-account">
			<AccountTab />
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
			<SystemTab />
		</div>
	{/if}
</div>
