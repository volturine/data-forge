<script lang="ts">
	import { QueryClient, QueryClientProvider } from '@tanstack/svelte-query';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { idbGet, idbSet } from '$lib/utils/indexeddb';
	import favicon from '$lib/assets/favicon.svg';
	import { css, spinner } from '$lib/styles/panda';
	import { PanelLeftClose } from 'lucide-svelte';
	import SettingsPopup from '$lib/components/common/SettingsPopup.svelte';
	import EnginesPopup from '$lib/components/common/EnginesPopup.svelte';
	import NamespacePickerModal from '$lib/components/common/NamespacePickerModal.svelte';
	import ChatPanel from '$lib/components/common/ChatPanel.svelte';
	import Sidebar from '$lib/components/shell/Sidebar.svelte';
	import { chatStore } from '$lib/stores/chat.svelte';
	import { initNamespace, setNamespace, useNamespace } from '$lib/stores/namespace.svelte';
	import { configStore } from '$lib/stores/config.svelte';
	import { authStore } from '$lib/stores/auth.svelte';
	import { installAuditListeners, setAuditPage, track } from '$lib/utils/audit-log';
	import { untrack } from 'svelte';
	import 'styled-system/styles.css';

	let { children } = $props();

	const themeAttribute =
		typeof document === 'undefined' ? null : document.documentElement.getAttribute('data-theme');
	const initialTheme = themeAttribute === 'dark' ? 'dark' : 'light';
	let theme = $state<'light' | 'dark'>(initialTheme);
	let settingsOpen = $state(false);
	let enginesOpen = $state(false);
	let sidebarCollapsed = $state(false);
	let sidebarHovered = $state(false);
	const currentPath = $derived(page.url.pathname);

	const authPaths = [
		'/login',
		'/register',
		'/callback',
		'/verify',
		'/forgot-password',
		'/reset-password'
	];
	const onAuthPage = $derived(authPaths.some((p) => currentPath.startsWith(p)));

	// Network: resolve auth eagerly in parallel with config fetch.
	$effect(() => {
		if (typeof window === 'undefined') return;
		untrack(() => void authStore.resolve());
	});

	const ready = $derived(
		configStore.config !== null && (!configStore.authRequired || authStore.resolved)
	);

	// Navigation: $derived can't redirect; side effect redirects unauthenticated users.
	$effect(() => {
		if (!ready) return;
		if (!configStore.authRequired) {
			if (onAuthPage) void goto(resolve('/'));
			return;
		}
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
		const cleanup = installAuditListeners();
		return cleanup;
	});

	// Cleanup: $derived can't teardown singleton resources.
	$effect(() => {
		return () => chatStore.destroy();
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
	let enginesTrigger = $state<HTMLButtonElement>();
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
				staleTime: 30_000,
				refetchOnWindowFocus: false,
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
	{#if !ready && !onAuthPage}
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
	{:else if onAuthPage && configStore.authRequired}
		{@render children()}
	{:else}
		<div class={css({ display: 'flex', height: '100vh' })}>
			<div
				class={css({ position: 'relative', flexShrink: 0 })}
				onmouseenter={() => (sidebarHovered = true)}
				onmouseleave={() => (sidebarHovered = false)}
				role="presentation"
			>
				<Sidebar
					collapsed={sidebarCollapsed}
					onToggle={toggleSidebar}
					{theme}
					onToggleTheme={toggleTheme}
					onOpenSettings={() => (settingsOpen = true)}
					onOpenEngines={() => (enginesOpen = true)}
					onOpenChat={handleOpenChat}
					onOpenNamespace={openNamespace}
					onSignOut={handleSignOut}
					namespace={namespaceDraft}
					authenticated={authStore.authenticated}
					authRequired={configStore.authRequired}
					avatarUrl={authStore.user?.avatar_url ?? null}
					bind:namespaceTrigger
					bind:enginesTrigger
				/>

				{#if !sidebarCollapsed}
					<button
						class={css({
							position: 'absolute',
							top: '0.5',
							right: '-8',
							zIndex: 'popover',
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'center',
							cursor: 'pointer',
							backgroundColor: 'transparent',
							padding: '3',
							borderWidth: '1',
							borderRadius: 'sm',
							color: 'fg.muted',
							opacity: sidebarHovered ? 1 : 0,
							transitionProperty: 'opacity, color',
							transitionDuration: '160ms',
							transitionTimingFunction: 'ease',
							_hover: { color: 'fg.primary' }
						})}
						onclick={toggleSidebar}
						aria-label="Collapse sidebar"
						type="button"
					>
						<PanelLeftClose size={16} />
					</button>
				{/if}
			</div>

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
		<EnginesPopup bind:open={enginesOpen} anchor={enginesTrigger} />
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
