<script lang="ts">
	import { QueryClient, QueryClientProvider } from '@tanstack/svelte-query';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { idbGet, idbSet } from '$lib/utils/indexeddb';
	import favicon from '$lib/assets/favicon.svg';
	import { Sun, Moon } from 'lucide-svelte';
	import EngineMonitor from '$lib/components/common/EngineMonitor.svelte';
	import IndexedDbButton from '$lib/components/common/IndexedDbButton.svelte';
	import { initializeStores } from '$lib/stores/context.svelte';
	import { configStore } from '$lib/stores/config.svelte';
	import { installAuditListeners, setAuditPage, track } from '$lib/utils/audit-log';
	import { untrack } from 'svelte';
	import '$lib/../app.css';

	let { children } = $props();

	// Initialize stores via context API for SSR safety
	// This creates fresh store instances per request, preventing state leakage
	initializeStores();

	const themeAttribute =
		typeof document === 'undefined' ? null : document.documentElement.getAttribute('data-theme');
	const initialTheme = themeAttribute === 'dark' ? 'dark' : 'light';
	let theme = $state<'light' | 'dark'>(initialTheme);
	let currentPath = $derived(page.url.pathname);

	$effect(() => {
		document.documentElement.setAttribute('data-theme', theme);
		void idbSet('theme', theme);
	});

	if (typeof window !== 'undefined') {
		void idbGet<'light' | 'dark'>('theme').then((value) => {
			if (!value) return;
			theme = value;
		});
	}

	$effect(() => {
		if (typeof window === 'undefined') return;
		untrack(() => configStore.fetch());
	});

	$effect(() => {
		if (typeof window === 'undefined') return;
		if (!configStore.config) return;
		installAuditListeners();
	});

	$effect(() => {
		if (!configStore.config) return;
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

	// Shift-scroll handling is now scoped to DataTable only.

	function toggleTheme() {
		theme = theme === 'light' ? 'dark' : 'light';
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

	const navItems = [
		{ href: '/', label: 'Analyses' },
		{ href: '/datasources', label: 'Data Sources' },
		{ href: '/builds', label: 'Builds' },
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
		<header class="sticky top-0 z-header bg-panel">
			<div class="mx-auto flex max-w-300 items-center gap-6 px-6 py-3">
				<a href={resolve('/')} class="flex items-center gap-1 text-base font-semibold no-underline">
					<span class="text-fg-primary">polars</span>
					<span class="text-fg-muted">/</span>
					<span class="text-fg-tertiary">analysis</span>
				</a>

				<nav class="flex items-center gap-1">
					{#each navItems as item (item.href)}
						<a
							href={resolve(item.href as '/')}
							class="nav-link border border-transparent px-3 py-1.5 text-sm text-fg-tertiary no-underline hover:text-fg-primary"
							class:active={currentPath === item.href ||
								(currentPath.startsWith('/analysis') && item.href === '/') ||
								(currentPath.startsWith('/udfs') && item.href === '/udfs') ||
								(currentPath.startsWith('/builds') && item.href === '/builds')}
						>
							{item.label}
						</a>
					{/each}
				</nav>

				<div class="ml-auto flex items-center gap-2">
					<EngineMonitor />
					<IndexedDbButton />
					<button
						class="theme-toggle flex items-center justify-center border border-tertiary bg-bg-primary p-2 text-fg-secondary hover:bg-bg-hover hover:text-fg-primary"
						onclick={toggleTheme}
						title="Toggle theme"
						aria-label="Toggle theme"
					>
						{#if theme === 'light'}
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
