<script lang="ts">
	import { QueryClient, QueryClientProvider } from '@tanstack/svelte-query';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { PersistedState } from 'runed';
	import favicon from '$lib/assets/favicon.svg';
	import { Sun, Moon } from 'lucide-svelte';
	import EngineMonitor from '$lib/components/common/EngineMonitor.svelte';
	import { initializeStores } from '$lib/stores/context.svelte';
	import { configStore } from '$lib/stores/config.svelte';
	import { installAuditListeners, setAuditPage, track } from '$lib/utils/audit-log';
	import '$lib/../app.css';

	let { children } = $props();

	// Initialize stores via context API for SSR safety
	// This creates fresh store instances per request, preventing state leakage
	initializeStores();

	// Use runed's PersistedState for persisted theme state across tabs/sessions
	const theme = new PersistedState<'light' | 'dark'>('theme', 'dark');
	let currentPath = $derived(page.url.pathname);

	$effect(() => {
		document.documentElement.setAttribute('data-theme', theme.current);
	});

	$effect(() => {
		if (typeof window === 'undefined') return;
		configStore.fetch();
	});

	$effect(() => {
		if (typeof window === 'undefined') return;
		installAuditListeners();
	});

	$effect(() => {
		setAuditPage(currentPath);
	});

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

	const findScrollableX = (node: Element | null): HTMLElement | null => {
		if (!node) return null;
		if (node instanceof HTMLElement) {
			const style = getComputedStyle(node);
			const canScrollX = style.overflowX === 'auto' || style.overflowX === 'scroll';
			if (canScrollX && node.scrollWidth > node.clientWidth) {
				return node;
			}
		}
		return findScrollableX(node.parentElement);
	};

	$effect(() => {
		if (typeof window === 'undefined') return;
		const handler = (event: WheelEvent) => {
			if (event.defaultPrevented) return;
			if (event.deltaX !== 0 && !event.shiftKey) return;
			if (!event.shiftKey || event.deltaY === 0) return;
			const target = event.target instanceof Element ? event.target : null;
			if (target && target.closest('input, textarea, select, button, [contenteditable="true"]')) {
				return;
			}
			const scroller =
				findScrollableX(target) ??
				(document.scrollingElement instanceof HTMLElement ? document.scrollingElement : null);
			if (!scroller || scroller.scrollWidth <= scroller.clientWidth) return;
			scroller.scrollBy({ left: event.deltaY, behavior: 'auto' });
			event.preventDefault();
		};
		window.addEventListener('wheel', handler, { passive: false, capture: true });
		return () => {
			window.removeEventListener('wheel', handler, { capture: true } as AddEventListenerOptions);
		};
	});

	function toggleTheme() {
		theme.current = theme.current === 'light' ? 'dark' : 'light';
	}

	const queryClient = new QueryClient({
		defaultOptions: {
			queries: {
				staleTime: 1000 * 60 * 5,
				retry: 1
			}
		}
	});

	const navItems = [
		{ href: '/', label: 'Analyses' },
		{ href: '/datasources', label: 'Data Sources' },
		{ href: '/udfs', label: 'UDF Library' }
	];
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
	<div class="flex h-screen flex-col">
		<header
			class="sticky top-0 z-header border-b border-border-primary bg-bg-primary backdrop-blur-sm"
		>
			<div class="mx-auto flex max-w-[1200px] items-center gap-6 px-6 py-3">
				<a
					href={resolve('/')}
					class="flex items-center gap-1 text-base font-semibold no-underline"
					data-sveltekit-reload
				>
					<span class="text-fg-primary">polars</span>
					<span class="text-fg-muted">/</span>
					<span class="text-fg-tertiary">analysis</span>
				</a>

				<nav class="flex items-center gap-1">
					{#each navItems as item (item.href)}
						<a
							href={resolve(item.href as '/')}
							class="nav-link rounded-sm border border-transparent px-3 py-2 text-sm text-fg-tertiary no-underline transition-all hover:border-border-primary hover:bg-bg-hover hover:text-fg-primary"
							class:active={currentPath === item.href ||
								(currentPath.startsWith('/analysis') && item.href === '/') ||
								(currentPath.startsWith('/udfs') && item.href === '/udfs')}
							data-sveltekit-reload
						>
							{item.label}
						</a>
					{/each}
				</nav>

				<div class="ml-auto flex items-center gap-2">
					<EngineMonitor />
					<button
						class="theme-toggle flex items-center justify-center rounded-sm border border-border-primary bg-bg-primary p-2 text-fg-secondary shadow-[var(--card-shadow)] transition-all hover:bg-bg-hover hover:text-fg-primary"
						onclick={toggleTheme}
						title="Toggle theme"
						aria-label="Toggle theme"
					>
						{#if theme.current === 'light'}
							<Sun size={16} />
						{:else}
							<Moon size={16} />
						{/if}
					</button>
				</div>
			</div>
		</header>

		<main class="min-h-0 flex-1 overflow-y-auto bg-bg-secondary">
			{@render children()}
		</main>
	</div>
</QueryClientProvider>

<style>
	:global(html, body) {
		height: 100%;
		overflow: hidden;
	}

	.nav-link.active {
		color: var(--fg-primary);
		background-color: var(--bg-tertiary);
		border-color: var(--border-primary);
	}
</style>
