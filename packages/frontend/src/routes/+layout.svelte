<script lang="ts">
	import { QueryClient, QueryClientProvider } from '@tanstack/svelte-query';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { idbGet, idbSet } from '$lib/utils/indexeddb';
	import favicon from '$lib/assets/favicon.svg';
	import { css, spinner } from '$lib/styles/panda';
	import { PanelLeftClose } from 'lucide-svelte';
	// SettingsPopup removed — settings now live under /profile tabs
	import NamespacePickerModal from '$lib/components/common/NamespacePickerModal.svelte';
	import ChatPanel from '$lib/components/common/ChatPanel.svelte';
	import Sidebar from '$lib/components/shell/Sidebar.svelte';
	import { chatStore } from '$lib/stores/chat.svelte';
	import { enginesStore } from '$lib/stores/engines.svelte';
	import { computeActivityStore } from '$lib/stores/compute-activity.svelte';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { favoriteStore } from '$lib/stores/favorites.svelte';
	import { schemaStore } from '$lib/stores/schema.svelte';
	import { overlayStack } from '$lib/stores/overlay.svelte';
	import {
		initNamespace,
		switchNamespace,
		useNamespace,
		isNamespaceReady
	} from '$lib/stores/namespace.svelte';
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
	// settingsOpen removed — settings now live under /profile tabs
	let sidebarCollapsed = $state(false);
	let sidebarHovered = $state(false);
	let shellInteractive = $state(false);
	const currentPath = $derived(page.url.pathname);
	const namespaceState = useNamespace();

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
		configStore.config !== null &&
			(!configStore.authRequired || authStore.resolved) &&
			isNamespaceReady()
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

	// State: favorites are namespace-scoped and reset on namespace changes.
	$effect(() => {
		if (!isNamespaceReady()) return;
		favoriteStore.setNamespace(namespaceState.value);
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

	// Websocket: keep engines status lazy and only active during compute work.
	$effect(() => {
		if (typeof window === 'undefined') return;
		if (!ready) return;
		if (!computeActivityStore.active) return;
		untrack(() => enginesStore.startStream());
		return () => enginesStore.stopStream();
	});

	// DOM: shell controls need one painted frame after ready before JS-bound buttons are reliable.
	$effect(() => {
		shellInteractive = false;
		if (typeof window === 'undefined') return;
		if (!ready) return;
		let frameA = 0;
		let frameB = 0;
		frameA = window.requestAnimationFrame(() => {
			frameB = window.requestAnimationFrame(() => {
				shellInteractive = true;
			});
		});
		return () => {
			window.cancelAnimationFrame(frameA);
			window.cancelAnimationFrame(frameB);
			shellInteractive = false;
		};
	});

	// DOM: global capture-phase arbiter for overlay Escape / outside-click.
	$effect(() => {
		if (typeof window === 'undefined') return;
		function onKeydown(event: KeyboardEvent) {
			if (event.key !== 'Escape') return;
			if (overlayStack.handleEscape()) {
				event.preventDefault();
				event.stopImmediatePropagation();
			}
		}
		function onMousedown(event: MouseEvent) {
			const target = event.target as Node | null;
			if (!target) return;
			overlayStack.handleOutsideClick(target);
		}
		window.addEventListener('keydown', onKeydown, true);
		window.addEventListener('mousedown', onMousedown, true);
		return () => {
			window.removeEventListener('keydown', onKeydown, true);
			window.removeEventListener('mousedown', onMousedown, true);
		};
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

	let namespaceOpen = $state(false);
	let namespaceTrigger = $state<HTMLButtonElement>();
	const namespaceDraft = $derived(namespaceState.value);

	async function handleNamespaceSelect(value: string) {
		await switchNamespace(value, {
			async beforeCommit() {
				await queryClient.cancelQueries();
				computeActivityStore.reset();
				enginesStore.reset();
				chatStore.reset();
				analysisStore.reset();
				datasourceStore.reset();
				favoriteStore.reset();
				schemaStore.reset();
			},
			async afterCommit() {
				await goto(resolve(currentPath as '/'), {
					invalidateAll: true,
					replaceState: true
				});
				await queryClient.resetQueries();
			}
		});
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
					interactive={shellInteractive}
					onToggle={toggleSidebar}
					{theme}
					onToggleTheme={toggleTheme}
					onOpenChat={handleOpenChat}
					onOpenNamespace={openNamespace}
					onSignOut={handleSignOut}
					namespace={namespaceDraft}
					authenticated={authStore.authenticated}
					authRequired={configStore.authRequired}
					avatarUrl={authStore.user?.avatar_url ?? null}
					bind:namespaceTrigger
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
