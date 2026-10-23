<script lang="ts">
	import { QueryClient, QueryClientProvider } from '@tanstack/svelte-query';
	import { page } from '$app/state';
	import { afterNavigate, goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';
	import { idbGet, idbSet } from '#lib/utils/indexeddb.js';
	import favicon from '#lib/assets/favicon.svg';
	import { button, css, spinner } from '#lib/styles/panda.js';
	import { PanelLeftClose } from '@lucide/svelte';
	import NamespacePickerModal from '#lib/components/common/NamespacePickerModal.svelte';
	import IndexedDbButton from '#lib/components/common/IndexedDbButton.svelte';
	import ChatPanel from '#lib/components/common/ChatPanel.svelte';
	import Sidebar from '#lib/components/shell/Sidebar.svelte';
	import { chatStore } from '#lib/stores/chat.svelte.js';
	import { computeWorkersStore } from '#lib/stores/compute-workers.svelte.js';
	import { computeActivityStore } from '#lib/stores/compute-activity.svelte.js';
	import { analysisStore } from '#lib/stores/analysis.svelte.js';
	import { datasourceStore } from '#lib/stores/datasource.svelte.js';
	import { favoriteStore } from '#lib/stores/favorites.svelte.js';
	import { schemaStore } from '#lib/stores/schema.svelte.js';
	import { overlayStack } from '#lib/stores/overlay.svelte.js';
	import { switchNamespace, useNamespace, isNamespaceReady } from '#lib/stores/namespace.svelte.js';
	import { configStore } from '#lib/stores/config.svelte.js';
	import { authStore } from '#lib/stores/auth.svelte.js';
	import { AppLifecycle } from '#lib/services/app-lifecycle.js';
	import { appBootstrap } from '#lib/services/app-bootstrap.svelte.js';
	import { installAuditListeners, setAuditPage, track } from '#lib/utils/audit-log.js';
	import '../../styled-system/styles.css';

	let { children } = $props();

	const themeAttribute =
		typeof document === 'undefined' ? null : document.documentElement.getAttribute('data-theme');
	const initialTheme = themeAttribute === 'dark' ? 'dark' : 'light';
	let theme = $state<'light' | 'dark'>(initialTheme);
	let sidebarCollapsed = $state(false);
	let sidebarHovered = $state(false);
	let shellInteractive = $state(false);

	// Manual sidebar resizing (drag the grip seam between sidebar and content).
	const SIDEBAR_MIN_WIDTH = 180;
	const SIDEBAR_DEFAULT_WIDTH = 220; // matches the `sidebarExpanded` token
	const SIDEBAR_MAX_WIDTH = 480;
	const SIDEBAR_COLLAPSED_WIDTH = 56; // matches the `sidebarCollapsed` token
	let sidebarWidth = $state(SIDEBAR_DEFAULT_WIDTH);
	let sidebarResizing = $state(false);
	let sidebarGripHovered = $state(false);
	let sidebarPortEl = $state<HTMLElement | null>(null);

	function clampSidebarWidth(value: unknown): number {
		if (typeof value !== 'number' || !Number.isFinite(value)) return SIDEBAR_DEFAULT_WIDTH;
		return Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, Math.round(value)));
	}
	const sidebarPortClass = $derived(
		css({
			position: 'relative',
			flexShrink: 0,
			transitionProperty: 'width',
			transitionDuration: sidebarResizing ? '0ms' : '200ms',
			transitionTimingFunction: 'ease'
		})
	);

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

		void idbGet<number>('sidebar_width').then((value) => {
			if (value === null) return;
			sidebarWidth = clampSidebarWidth(value);
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
		void goto(resolve('login'));
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

	// Collapse chip plugs into the sidebar's right border line: fillet webs
	// painted in the chip's surface color arc the line into the chip's top and
	// bottom edges so the seam reads as one fluid shape.
	const chipSurfaceColor = 'var(--colors-bg-hover)';
	// Top fillet keeps a 2px visible line run-in above the arc (the tangent
	// point sits below the page top edge); the bottom one reaches to the row
	// boundary. Sweeps are drawn wider than tall (14px x 8px) so the line flows
	// tangentially into the chip edges with a long pronounced swoop.
	const chipFilletCss = `radial-gradient(ellipse 14px 6px at 100% 0px, transparent 0 92%, ${chipSurfaceColor} 100%)`;
	const sidebarCollapseChipClass = $derived(
		css({
			position: 'absolute',
			top: '2',
			right: '-31px',
			width: '8',
			height: '8',
			padding: '2',
			zIndex: 'popover',
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'center',
			cursor: 'pointer',
			backgroundColor: 'bg.hover',
			borderTopRightRadius: 'sm2',
			borderBottomRightRadius: 'sm2',
			color: 'fg.secondary',
			opacity: sidebarHovered ? 1 : 0,
			pointerEvents: sidebarHovered ? 'auto' : 'none',
			transitionProperty: 'opacity, color',
			transitionDuration: '160ms',
			transitionTimingFunction: 'ease',
			_hover: { color: 'fg.primary' },
			_before: {
				content: '""',
				position: 'absolute',
				left: '0',
				top: '-6px',
				width: '15px',
				height: '6px',
				background: chipFilletCss
			},
			_after: {
				content: '""',
				position: 'absolute',
				left: '0',
				top: '100%',
				width: '15px',
				height: '8px',
				background: `radial-gradient(ellipse 14px 8px at 100% 100%, transparent 0 92%, ${chipSurfaceColor} 100%)`
			}
		})
	);

	const sidebarGripClass = css({
		position: 'absolute',
		top: '3rem',
		bottom: '0',
		right: '-4px',
		width: '8px',
		zIndex: 'nav',
		cursor: 'col-resize',
		display: 'flex',
		alignItems: 'stretch',
		justifyContent: 'center',
		touchAction: 'none'
	});

	const sidebarGripLineClass = css({
		width: '2px',
		height: '100%',
		backgroundColor: 'accent.primary',
		opacity: '0',
		transitionProperty: 'opacity',
		transitionDuration: '160ms',
		transitionTimingFunction: 'ease'
	});

	const sidebarGripLineActiveClass = css({
		opacity: '1'
	});

	function startSidebarResize(event: PointerEvent): void {
		if (event.button !== 0) return;
		event.preventDefault();
		sidebarResizing = true;
		document.body.style.cursor = 'col-resize';
		document.body.style.userSelect = 'none';
		if (event.currentTarget instanceof Element) {
			// Keep stream events during fast drags outside the 8px hit zone; the
			// pointer may already be disengaged when the event is replayed manually.
			try {
				event.currentTarget.setPointerCapture(event.pointerId);
			} catch {
				// Fall back to plain hover-bound movement.
			}
		}
	}

	function moveSidebarResize(event: PointerEvent): void {
		if (!sidebarResizing) return;
		if (event.buttons === 0) {
			endSidebarResize();
			return;
		}
		if (!sidebarPortEl) return;
		const left = sidebarPortEl.getBoundingClientRect().left;
		sidebarWidth = clampSidebarWidth(event.clientX - left);
	}

	function endSidebarResize(): void {
		if (!sidebarResizing) return;
		sidebarResizing = false;
		document.body.style.cursor = '';
		document.body.style.userSelect = '';
		void idbSet('sidebar_width', sidebarWidth);
	}

	function nudgeSidebarWidth(event: KeyboardEvent): void {
		if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
		const step = event.shiftKey ? 32 : 16;
		const direction = event.key === 'ArrowLeft' ? -1 : 1;
		sidebarWidth = clampSidebarWidth(sidebarWidth + direction * step);
		void idbSet('sidebar_width', sidebarWidth);
		event.preventDefault();
	}

	let namespaceOpen = $state(false);
	let namespaceError = $state<string | null>(null);
	const namespaceDraft = $derived(namespaceState.value);

	async function handleNamespaceSelect(value: string) {
		await switchNamespace(value, {
			async beforeCommit() {
				if (currentPath === '/datasources' && page.url.searchParams.has('id')) {
					await goto(resolve('datasources'), {
						replaceState: true,
						refreshAll: false,
						reset: false
					});
				}
				await appLifecycle.releaseNamespace();
			},
			afterCommit() {
				const nextUrl = new URL(page.url.href);
				if (nextUrl.pathname === '/datasources') {
					nextUrl.searchParams.delete('id');
				}
				// The namespace value is already committed and all old namespace
				// services have been reset. Activate the new scope synchronously so
				// the shell reflects the selection immediately; waiting for SvelteKit
				// to invalidate page data here leaves the namespace control disabled
				// while unrelated page queries drain.
				appLifecycle.activateNamespace();
				bindNamespaceServices();
				void goto(resolve(`${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}` as '/'), {
					refreshAll: false,
					replaceState: true,
					reset: false
				}).catch((error: unknown) => {
					namespaceError = error instanceof Error ? error.message : String(error);
				});
			}
		});
	}

	function openNamespace() {
		if (namespaceState.switching) return;
		namespaceError = null;
		namespaceOpen = true;
	}

	function handleNamespaceError(message: string): void {
		namespaceError = message;
	}

	async function handleSignOut() {
		await authStore.logout();
		chatStore.resetForSignOut();
		void goto(resolve('login'));
	}

	function handleOpenChat() {
		if (chatStore.open) {
			chatStore.close();
			return;
		}
		void chatStore.open_panel();
	}

	function refreshComputeWorkersSnapshotWhenVisible(): void {
		if (document.visibilityState !== 'visible') return;
		if (!appBootstrap.appReady || onAuthPage || !isNamespaceReady()) return;
		if (configStore.authRequired && !authStore.authenticated) return;
		if (!namespaceState.value) return;
		computeWorkersStore.refreshSnapshot();
	}

	const queryClient = new QueryClient({
		defaultOptions: {
			queries: {
				staleTime: 30_000,
				refetchOnWindowFocus: false,
				retry: false
			}
		}
	});
	const appLifecycle = new AppLifecycle(queryClient, {
		analysis: analysisStore,
		chat: chatStore,
		computeActivity: computeActivityStore,
		datasource: datasourceStore,
		computeWorkers: computeWorkersStore,
		favorites: favoriteStore,
		schema: schemaStore
	});

	$effect(() => {
		if (!appBootstrap.appReady || onAuthPage || !isNamespaceReady()) return;
		if (configStore.authRequired && !authStore.authenticated) return;
		const namespace = namespaceState.value;
		if (!namespace) return;
		computeWorkersStore.loadSnapshotOnce();
	});

	onMount(() => {
		document.addEventListener('visibilitychange', refreshComputeWorkersSnapshotWhenVisible);
		void appBootstrap.start().then(() => {
			bindNamespaceServices();
			redirectIfNeeded();
		});
		applyTheme(theme);
		const cleanupAudit = installAuditListeners();
		return () => {
			cleanupAudit?.();
			document.removeEventListener('visibilitychange', refreshComputeWorkersSnapshotWhenVisible);
			appLifecycle.destroy();
		};
	});

	afterNavigate(({ shallow, type }) => {
		if (shallow && type === 'goto') return;

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
			<button
				class={button({ variant: 'primary' })}
				disabled={appBootstrap.retrying}
				aria-busy={appBootstrap.retrying}
				onclick={() => void appBootstrap.retry()}
				type="button"
			>
				{appBootstrap.retrying ? 'Retrying…' : 'Retry'}
			</button>
		</div>
	{:else if shellPhase === 'auth'}
		{@render children()}
	{:else}
		<div class={css({ display: 'flex', height: '100vh' })} {@attach enableShell}>
			<div
				bind:this={sidebarPortEl}
				class={sidebarPortClass}
				style="width: {sidebarCollapsed ? SIDEBAR_COLLAPSED_WIDTH : sidebarWidth}px"
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
				/>

				{#if !sidebarCollapsed}
					<button
						class={sidebarCollapseChipClass}
						onclick={toggleSidebar}
						aria-label="Collapse sidebar"
						title="Collapse sidebar"
						type="button"
					>
						<PanelLeftClose size={16} />
					</button>
				{/if}

				{#if !sidebarCollapsed}
					<div
						role="slider"
						aria-orientation="vertical"
						aria-label="Resize sidebar"
						aria-controls="app-sidebar"
						aria-valuenow={Math.round(sidebarWidth)}
						aria-valuemin={SIDEBAR_MIN_WIDTH}
						aria-valuemax={SIDEBAR_MAX_WIDTH}
						tabindex="0"
						class={sidebarGripClass}
						onmouseenter={() => (sidebarGripHovered = true)}
						onmouseleave={() => (sidebarGripHovered = false)}
						onpointerdown={startSidebarResize}
						onpointermove={moveSidebarResize}
						onpointerup={endSidebarResize}
						onpointercancel={endSidebarResize}
						onkeydown={nudgeSidebarWidth}
					>
						<div
							class={[
								sidebarGripLineClass,
								(sidebarGripHovered || sidebarResizing) && sidebarGripLineActiveClass
							]}
						></div>
					</div>
				{/if}
			</div>

			<main
				data-app-route={currentPath}
				class={css({
					position: 'relative',
					minHeight: '0',
					minWidth: '0',
					flex: '1',
					overflowY: 'auto',
					backgroundColor: 'bg.secondary'
				})}
			>
				{#if namespaceError}
					<div
						class={css({
							position: 'absolute',
							top: '3',
							right: '3',
							zIndex: 'toast',
							display: 'flex',
							alignItems: 'center',
							gap: '2',
							maxWidth: 'lg',
							borderWidth: '1',
							borderColor: 'border.error',
							backgroundColor: 'bg.primary',
							paddingX: '3',
							paddingY: '2',
							color: 'error',
							fontSize: 'sm'
						})}
						role="alert"
					>
						<span>Namespace switch failed: {namespaceError}</span>
						<button
							class={css({ color: 'fg.muted', fontSize: 'xs' })}
							onclick={() => (namespaceError = null)}
							type="button"
						>
							Dismiss
						</button>
					</div>
				{/if}
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
			onSelectError={handleNamespaceError}
			onClose={() => (namespaceOpen = false)}
		/>
		<ChatPanel />
	{/if}
</QueryClientProvider>
