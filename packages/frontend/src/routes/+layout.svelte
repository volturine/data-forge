<script lang="ts">
	import { QueryClient, QueryClientProvider } from '@tanstack/svelte-query';
	import { page } from '$app/state';
	import { afterNavigate, goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';
	import { idbGet, idbSet } from '$lib/utils/indexeddb';
	import favicon from '$lib/assets/favicon.svg';
	import { css, spinner } from '$lib/styles/panda';
	import { PanelLeftClose } from '@lucide/svelte';
	import NamespacePickerModal from '$lib/components/common/NamespacePickerModal.svelte';
	import IndexedDbButton from '$lib/components/common/IndexedDbButton.svelte';
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
	import { switchNamespace, useNamespace, isNamespaceReady } from '$lib/stores/namespace.svelte';
	import { configStore } from '$lib/stores/config.svelte';
	import { authStore } from '$lib/stores/auth.svelte';
	import { AppLifecycle } from '$lib/services/app-lifecycle';
	import { appBootstrap } from '$lib/services/app-bootstrap.svelte';
	import { installAuditListeners, setAuditPage, track } from '$lib/utils/audit-log';
	import 'styled-system/styles.css';

	let { children } = $props();

	const themeAttribute =
		typeof document === 'undefined' ? null : document.documentElement.getAttribute('data-theme');
	const initialTheme = themeAttribute === 'dark' ? 'dark' : 'light';
	let theme = $state<'light' | 'dark'>(initialTheme);
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

	const shellPhase = $derived(appBootstrap.phase(onAuthPage));
	const bootstrapError = $derived(appBootstrap.errorFor(onAuthPage));

	function applyTheme(next: 'light' | 'dark'): void {
		theme = next;
		document.documentElement.setAttribute('data-theme', next);
		document.body.setAttribute('data-theme', next);
		void idbSet('theme', next);
	}

	function bindNamespaceServices(): void {
		if (!isNamespaceReady()) return;
		favoriteStore.setNamespace(namespaceState.value);
		void analysisStore.initialize(namespaceState.value);
	}

	if (typeof window !== 'undefined') {
		void idbGet<'light' | 'dark'>('theme').then((value) => {
			if (!value) return;
			applyTheme(value);
		});

		void idbGet<boolean>('sidebar_collapsed').then((value) => {
			if (value === null) return;
			sidebarCollapsed = value;
		});
	}

	function redirectIfNeeded(): void {
		if (!appBootstrap.appReady) return;
		if (!configStore.authRequired) {
			if (onAuthPage) void goto(resolve('/'));
			return;
		}
		if (authStore.authenticated) return;
		if (authStore.bootstrapFailed) return;
		if (onAuthPage) return;
		if (authStore.status !== 'unauthenticated') return;
		void goto(resolve('/login'));
	}

	function enableShell(_node: HTMLElement): () => void {
		shellInteractive = false;
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
	}

	function toggleTheme(): void {
		applyTheme(theme === 'light' ? 'dark' : 'light');
	}

	function onOverlayKeydown(event: KeyboardEvent): void {
		if (event.key !== 'Escape') return;
		if (overlayStack.handleEscape()) {
			event.preventDefault();
			event.stopImmediatePropagation();
		}
	}

	function onOverlayMousedown(event: MouseEvent): void {
		const target = event.target as Node | null;
		if (!target) return;
		overlayStack.handleOutsideClick(target);
	}

	function onWindowError(event: Event): void {
		const errorEvent = event as ErrorEvent;
		track({
			event: 'client_error',
			action: 'error',
			page: currentPath,
			meta: {
				message: errorEvent.message,
				filename: errorEvent.filename,
				lineno: errorEvent.lineno
			}
		});
	}

	function onWindowReject(event: Event): void {
		const rejection = event as PromiseRejectionEvent;
		track({
			event: 'client_error',
			action: 'unhandledrejection',
			page: currentPath,
			meta: { reason: String(rejection.reason) }
		});
	}

	function toggleSidebar() {
		sidebarCollapsed = !sidebarCollapsed;
		void idbSet('sidebar_collapsed', sidebarCollapsed);
	}

	let namespaceOpen = $state(false);
	let namespaceTrigger = $state<HTMLButtonElement>();
	const namespaceDraft = $derived(namespaceState.value);

	async function handleNamespaceSelect(value: string) {
		namespaceOpen = false;
		await switchNamespace(value, {
			async beforeCommit() {
				if (currentPath === '/datasources' && page.url.searchParams.has('id')) {
					await goto(resolve('/datasources'), {
						replaceState: true,
						invalidateAll: false,
						keepFocus: true,
						noScroll: true
					});
				}
				await appLifecycle.releaseNamespace();
			},
			async afterCommit() {
				const nextUrl = new URL(page.url);
				if (nextUrl.pathname === '/datasources') {
					nextUrl.searchParams.delete('id');
				}
				await goto(resolve(`${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}` as '/'), {
					invalidateAll: true,
					replaceState: true
				});
				appLifecycle.activateNamespace();
				bindNamespaceServices();
			}
		});
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
	const appLifecycle = new AppLifecycle(queryClient, {
		analysis: analysisStore,
		chat: chatStore,
		computeActivity: computeActivityStore,
		datasource: datasourceStore,
		engines: enginesStore,
		favorites: favoriteStore,
		schema: schemaStore
	});

	onMount(() => {
		void appBootstrap.start().then(() => {
			bindNamespaceServices();
			redirectIfNeeded();
		});
		applyTheme(theme);
		const cleanupAudit = installAuditListeners();
		return () => {
			cleanupAudit?.();
			appLifecycle.destroy();
		};
	});

	afterNavigate(() => {
		setAuditPage(currentPath);
		redirectIfNeeded();
	});
</script>

<svelte:window
	onkeydowncapture={onOverlayKeydown}
	onmousedowncapture={onOverlayMousedown}
	onerror={onWindowError}
	onunhandledrejection={onWindowReject}
/>

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
	{#if shellPhase === 'loading'}
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'center',
				height: '100vh',
				backgroundColor: 'bg.secondary'
			})}
			data-shell-bootstrap="loading"
		>
			<div class={spinner()}></div>
		</div>
	{:else if shellPhase === 'error'}
		<div
			class={css({
				display: 'flex',
				flexDirection: 'column',
				alignItems: 'center',
				justifyContent: 'center',
				height: '100vh',
				backgroundColor: 'bg.secondary',
				padding: '6',
				gap: '3',
				textAlign: 'center'
			})}
			data-shell-bootstrap="error"
			role="alert"
		>
			<h1 class={css({ fontSize: 'lg', fontWeight: 'semibold', color: 'fg.primary', margin: '0' })}>
				Unable to start the app
			</h1>
			<p class={css({ fontSize: 'sm', color: 'fg.muted', margin: '0', maxWidth: 'md' })}>
				{bootstrapError}
			</p>
			<p class={css({ fontSize: 'xs', color: 'fg.muted', margin: '0' })}>
				Reload the page once the API is reachable.
			</p>
		</div>
	{:else if shellPhase === 'auth'}
		{@render children()}
	{:else}
		<div class={css({ display: 'flex', height: '100vh' })} {@attach enableShell}>
			<div
				class={css({ position: 'relative', flexShrink: 0 })}
				onmouseenter={() => (sidebarHovered = true)}
				onmouseleave={() => (sidebarHovered = false)}
				role="presentation"
			>
				<Sidebar
					collapsed={sidebarCollapsed}
					interactive={shellInteractive && !namespaceState.switching}
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
					position: 'relative',
					minHeight: '0',
					minWidth: '0',
					flex: '1',
					overflowY: 'auto',
					backgroundColor: 'bg.secondary'
				})}
			>
				{#if configStore.publicIdbDebug}
					<div
						class={css({
							position: 'sticky',
							top: '0',
							zIndex: 'nav',
							display: 'flex',
							justifyContent: 'flex-end',
							paddingX: '3',
							paddingY: '2',
							pointerEvents: 'none'
						})}
					>
						<div class={css({ pointerEvents: 'auto' })}>
							<IndexedDbButton />
						</div>
					</div>
				{/if}
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
