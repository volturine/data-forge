<script lang="ts">
	import { QueryClient, QueryClientProvider } from '@tanstack/svelte-query';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { idbGet, idbSet } from '$lib/utils/indexeddb';
	import favicon from '$lib/assets/favicon.svg';
	import { css, spinner } from '$lib/styles/panda';
	import SettingsPopup from '$lib/components/common/SettingsPopup.svelte';
	import NamespacePickerModal from '$lib/components/common/NamespacePickerModal.svelte';
	import ChatPanel from '$lib/components/common/ChatPanel.svelte';
	import Sidebar from '$lib/components/shell/Sidebar.svelte';
	import { chatStore } from '$lib/stores/chat.svelte';
	import { initializeStores } from '$lib/stores/context.svelte';
	import { initNamespace, setNamespace, useNamespace } from '$lib/stores/namespace.svelte';
	import { configStore } from '$lib/stores/config.svelte';
	import { authStore } from '$lib/stores/auth.svelte';
	import { installAuditListeners, setAuditPage, track } from '$lib/utils/audit-log';
	import { untrack } from 'svelte';
	import 'styled-system/styles.css';

	let { children } = $props();

	initializeStores();

	const themeAttribute =
		typeof document === 'undefined' ? null : document.documentElement.getAttribute('data-theme');
	const initialTheme = themeAttribute === 'dark' ? 'dark' : 'light';
	let theme = $state<'light' | 'dark'>(initialTheme);
	let settingsOpen = $state(false);
	let sidebarCollapsed = $state(false);
	const currentPath = $derived(page.url.pathname);

	const authPaths = ['/login', '/register', '/callback', '/verify', '/forgot-password', '/reset-password'];
	const onAuthPage = $derived(authPaths.some((p) => currentPath.startsWith(p)));

	// Network: $derived can't trigger async auth resolution.
	$effect(() => {
		void authStore.resolve();
	});

	// Navigation: $derived can't redirect; side effect redirects unauthenticated users.
	$effect(() => {
		if (!authStore.resolved) return;
		if (authStore.authenticated) return;
		if (onAuthPage) return;
		void goto(resolve('/login'));
	});

	// DOM: $derived can't sync theme to DOM/storage.
	$effect(() => {
		document.documentElement.setAttribute('data-theme', theme);
		document.body.setAttribute('data-theme', theme);
		void idbSet('theme', theme);
	});

	if (typeof window !== 'undefined') {
		void idbGet<'light' | 'dark'>('theme').then((value) => {
			if (!value) return;
			theme = value;
		});

		void idbGet<boolean>('sidebar_collapsed').then((value) => {
			if (value === null) return;
			sidebarCollapsed = value;
		});
	}

	// Network: $derived can't fetch config on client.
	$effect(() => {
		if (typeof window === 'undefined') return;
		untrack(() => configStore.fetch());
	});

	// Storage: $derived can't load namespace from storage.
	$effect(() => {
		if (typeof window === 'undefined') return;
		void initNamespace();
	});

	// Subscription: $derived can't install listeners.
	$effect(() => {
		if (typeof window === 'undefined') return;
		if (!configStore.config) return;
		installAuditListeners();
	});

	// Subscription: $derived can't update audit page.
	$effect(() => {
		if (!configStore.config) return;
		setAuditPage(currentPath);
	});

	// Subscription: $derived can't attach global listeners.
	$effect(() => {
		if (typeof window === 'undefined') return;
		const onError = (event: ErrorEvent) => {
			track({
				event: 'client_error',
				action: 'error',
				page: currentPath,
				meta: { message: event.message, filename: event.filename, lineno: event.lineno }
			});
		};
		const onReject = (event: PromiseRejectionEvent) => {
			track({
				event: 'client_error',
				action: 'unhandledrejection',
				page: currentPath,
				meta: { reason: String(event.reason) }
			});
		};
		window.addEventListener('error', onError);
		window.addEventListener('unhandledrejection', onReject);
		return () => {
			window.removeEventListener('error', onError);
			window.removeEventListener('unhandledrejection', onReject);
		};
	});

	function toggleTheme() {
		theme = theme === 'light' ? 'dark' : 'light';
	}

	function toggleSidebar() {
		sidebarCollapsed = !sidebarCollapsed;
		void idbSet('sidebar_collapsed', sidebarCollapsed);
	}

	const namespaceState = useNamespace();
	let namespaceOpen = $state(false);
	let namespaceTrigger = $state<HTMLButtonElement>();
	const namespaceDraft = $derived(namespaceState.value);

	async function handleNamespaceSelect(value: string) {
		await setNamespace(value);
		window.location.reload();
		namespaceOpen = false;
	}

	function openNamespace() {
		namespaceOpen = true;
	}

	async function handleSignOut() {
		await authStore.logout();
		void goto(resolve('/login'));
	}

	function handleOpenChat() {
		if (chatStore.open) {
			chatStore.close();
			return;
		}
		void chatStore.open_panel();
	}

	const queryClient = new QueryClient({
		defaultOptions: {
			queries: {
				staleTime: 0,
				gcTime: 0,
				refetchOnMount: 'always',
				retry: 1
			}
		}
	});
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<link rel="preconnect" href="https://fonts.googleapis.com" />
	<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin="anonymous" />
	<link
		href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap"
		rel="stylesheet"
	/>
	<title>Data Analysis Platform</title>
</svelte:head>

<QueryClientProvider client={queryClient}>
	{#if !authStore.resolved && !onAuthPage}
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'center',
				height: '100vh',
				backgroundColor: 'bg.secondary'
			})}
		>
			<div class={spinner()}></div>
		</div>
	{:else if onAuthPage}
		{@render children()}
	{:else}
		<div class={css({ display: 'flex', height: '100vh' })}>
			<Sidebar
				collapsed={sidebarCollapsed}
				onToggle={toggleSidebar}
				{theme}
				onToggleTheme={toggleTheme}
				onOpenSettings={() => (settingsOpen = true)}
				onOpenChat={handleOpenChat}
				onOpenNamespace={openNamespace}
				onSignOut={handleSignOut}
				namespace={namespaceDraft}
				authenticated={authStore.authenticated}
				avatarUrl={authStore.user?.avatar_url ?? null}
				bind:namespaceTrigger
			/>

			<main
				class={css({
					minHeight: '0',
					minWidth: '0',
					flex: '1',
					overflowY: 'auto',
					backgroundColor: 'bg.secondary'
				})}
			>
				{@render children()}
			</main>
		</div>

		<SettingsPopup bind:open={settingsOpen} />
		<NamespacePickerModal
			open={namespaceOpen}
			selected={namespaceDraft}
			onSelect={handleNamespaceSelect}
			onClose={() => (namespaceOpen = false)}
			anchor={namespaceTrigger}
		/>
		<ChatPanel />
	{/if}
</QueryClientProvider>
