<script lang="ts">
	import { QueryClient, QueryClientProvider } from '@tanstack/svelte-query';
	import { page } from '$app/stores';
	import { resolve } from '$app/paths';
	import { PersistedState } from 'runed';
	import favicon from '$lib/assets/favicon.svg';
	import { Sun, Moon } from 'lucide-svelte';
	import EngineMonitor from '$lib/components/common/EngineMonitor.svelte';
	import '$lib/../app.css';

	let { children } = $props();

	// Use runed's PersistedState for persisted theme state across tabs/sessions
	const theme = new PersistedState<'light' | 'dark'>('theme', 'dark');

	$effect(() => {
		document.documentElement.setAttribute('data-theme', theme.current);
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
		{ href: '/datasources', label: 'Data Sources' }
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
	<div class="app">
		<header class="header">
			<div class="header-content">
				<a href={resolve('/')} class="logo" data-sveltekit-reload>
					<span class="logo-text">polars</span>
					<span class="logo-divider">/</span>
					<span class="logo-sub">analysis</span>
				</a>

				<nav class="nav">
					{#each navItems as item (item.href)}
						<a
							href={resolve(item.href as '/' | '/datasources')}
							class="nav-link"
							class:active={$page.url.pathname === item.href ||
								($page.url.pathname.startsWith('/analysis') && item.href === '/')}
							data-sveltekit-reload
						>
							{item.label}
						</a>
					{/each}
				</nav>

				<div class="header-actions">
					<EngineMonitor />
					<button
						class="theme-toggle"
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

		<main class="main">
			{@render children()}
		</main>
	</div>
</QueryClientProvider>

<style>
	:global(html, body) {
		height: 100%;
		overflow: hidden;
	}
	.app {
		height: 100vh;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}
	.header {
		border-bottom: 1px solid var(--border-primary);
		background-color: var(--bg-primary);
		position: sticky;
		top: 0;
		z-index: var(--z-header);
		backdrop-filter: blur(8px);
	}
	.header-content {
		max-width: 1200px;
		margin: 0 auto;
		padding: var(--space-3) var(--space-6);
		display: flex;
		align-items: center;
		gap: var(--space-6);
	}
	.logo {
		display: flex;
		align-items: center;
		gap: var(--space-1);
		text-decoration: none;
		font-weight: var(--font-semibold);
		font-size: var(--text-base);
	}
	.logo-text {
		color: var(--fg-primary);
	}
	.logo-divider {
		color: var(--fg-muted);
	}
	.logo-sub {
		color: var(--fg-tertiary);
	}
	.nav {
		display: flex;
		align-items: center;
		gap: var(--space-1);
	}
	.nav-link {
		padding: var(--space-2) var(--space-3);
		text-decoration: none;
		color: var(--fg-tertiary);
		font-size: var(--text-sm);
		border-radius: var(--radius-sm);
		transition: all var(--transition);
		border: 1px solid transparent;
	}
	.nav-link:hover {
		color: var(--fg-primary);
		background-color: var(--bg-hover);
		border-color: var(--border-primary);
	}
	.nav-link.active {
		color: var(--fg-primary);
		background-color: var(--bg-tertiary);
		border-color: var(--border-primary);
	}
	.header-actions {
		margin-left: auto;
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.theme-toggle {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: var(--space-2);
		background-color: var(--bg-primary);
		border: 1px solid var(--border-primary);
		color: var(--fg-secondary);
		cursor: pointer;
		border-radius: var(--radius-sm);
		transition: all var(--transition);
		box-shadow: var(--card-shadow);
	}
	.theme-toggle:hover {
		background-color: var(--bg-hover);
		color: var(--fg-primary);
	}
	.main {
		flex: 1;
		background-color: var(--bg-secondary);
		overflow: hidden;
	}
</style>
