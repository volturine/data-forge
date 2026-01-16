<script lang="ts">
	import { QueryClient, QueryClientProvider } from '@tanstack/svelte-query';
	import { page } from '$app/stores';
	import favicon from '$lib/assets/favicon.svg';
	import '$lib/../app.css';

	let { children } = $props();

	let theme = $state<'light' | 'dark' | 'system'>('system');

	$effect(() => {
		// Check for saved preference or system preference
		const saved = localStorage.getItem('theme') as 'light' | 'dark' | 'system' | null;
		if (saved) {
			theme = saved;
		}
	});

	$effect(() => {
		// Apply theme to document
		if (theme === 'system') {
			document.documentElement.removeAttribute('data-theme');
		} else {
			document.documentElement.setAttribute('data-theme', theme);
		}
		localStorage.setItem('theme', theme);
	});

	function cycleTheme() {
		if (theme === 'system') theme = 'light';
		else if (theme === 'light') theme = 'dark';
		else theme = 'system';
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
				<a href="/" class="logo">
					<span class="logo-text">polars</span>
					<span class="logo-divider">/</span>
					<span class="logo-sub">analysis</span>
				</a>

				<nav class="nav">
					{#each navItems as item}
						<a
							href={item.href}
							class="nav-link"
							class:active={$page.url.pathname === item.href ||
								($page.url.pathname.startsWith('/analysis') && item.href === '/')}
						>
							{item.label}
						</a>
					{/each}
				</nav>

				<div class="header-actions">
					<button class="theme-toggle" onclick={cycleTheme} title="Toggle theme">
						{#if theme === 'system'}
							<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
								<rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>
								<line x1="8" y1="21" x2="16" y2="21"></line>
								<line x1="12" y1="17" x2="12" y2="21"></line>
							</svg>
						{:else if theme === 'light'}
							<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
								<circle cx="12" cy="12" r="5"></circle>
								<line x1="12" y1="1" x2="12" y2="3"></line>
								<line x1="12" y1="21" x2="12" y2="23"></line>
								<line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
								<line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
								<line x1="1" y1="12" x2="3" y2="12"></line>
								<line x1="21" y1="12" x2="23" y2="12"></line>
								<line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
								<line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
							</svg>
						{:else}
							<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
								<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
							</svg>
						{/if}
						<span class="theme-label">{theme}</span>
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
	.app {
		min-height: 100vh;
		display: flex;
		flex-direction: column;
	}

	.header {
		border-bottom: 1px solid var(--border-primary);
		background-color: var(--bg-primary);
		position: sticky;
		top: 0;
		z-index: 100;
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
		font-weight: 600;
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
		transition: all var(--transition-fast);
		border: 1px solid transparent;
	}

	.nav-link:hover {
		color: var(--fg-primary);
		background-color: var(--bg-hover);
		border-color: var(--border-primary);
		opacity: 1;
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
		gap: var(--space-2);
		padding: var(--space-2) var(--space-3);
		background-color: var(--bg-primary);
		border: 1px solid var(--border-primary);
		color: var(--fg-secondary);
		font-size: var(--text-xs);
		cursor: pointer;
		border-radius: var(--radius-sm);
		transition: all var(--transition-fast);
		box-shadow: var(--card-shadow);
	}

	.theme-toggle:hover {
		background-color: var(--bg-hover);
		color: var(--fg-primary);
	}

	.theme-label {
		text-transform: capitalize;
	}

	.main {
		flex: 1;
		background-color: var(--bg-secondary);
	}
</style>
