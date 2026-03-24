<script lang="ts">
	import { QueryClient, QueryClientProvider } from '@tanstack/svelte-query';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { idbGet, idbSet } from '$lib/utils/indexeddb';
	import favicon from '$lib/assets/favicon.svg';
	import { Sun, Moon, Settings, MessageSquare } from 'lucide-svelte';
	import { css, cx, iconButton, navLink, row, muted } from '$lib/styles/panda';
	import EngineMonitor from '$lib/components/common/EngineMonitor.svelte';
	import IndexedDbButton from '$lib/components/common/IndexedDbButton.svelte';
	import SettingsPopup from '$lib/components/common/SettingsPopup.svelte';
	import NamespacePickerModal from '$lib/components/common/NamespacePickerModal.svelte';
	import ChatPanel from '$lib/components/common/ChatPanel.svelte';
	import { chatStore } from '$lib/stores/chat.svelte';
	import { initializeStores } from '$lib/stores/context.svelte';
	import { initNamespace, setNamespace, useNamespace } from '$lib/stores/namespace.svelte';
	import { configStore } from '$lib/stores/config.svelte';
	import { installAuditListeners, setAuditPage, track } from '$lib/utils/audit-log';
	import { untrack } from 'svelte';
	import 'styled-system/styles.css';

	let { children } = $props();

	// Initialize stores via context API for SSR safety
	// This creates fresh store instances per request, preventing state leakage
	initializeStores();

	const themeAttribute =
		typeof document === 'undefined' ? null : document.documentElement.getAttribute('data-theme');
	const initialTheme = themeAttribute === 'dark' ? 'dark' : 'light';
	let theme = $state<'light' | 'dark'>(initialTheme);
	let settingsOpen = $state(false);
	const currentPath = $derived(page.url.pathname);

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

	// Shift-scroll handling is now scoped to DataTable only.

	function toggleTheme() {
		theme = theme === 'light' ? 'dark' : 'light';
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
		{ href: '/monitoring', label: 'Monitoring' },
		{ href: '/lineage', label: 'Lineage' },
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
	<div class={css({ display: 'flex', height: '100vh', flexDirection: 'column' })}>
		<header
			class={css({
				position: 'sticky',
				top: '0',
				zIndex: 'nav',
				backgroundColor: 'bg.panel'
			})}
		>
			<div
				class={css({
					marginX: 'auto',
					maxWidth: 'page',
					display: 'flex',
					alignItems: 'center',
					gap: '6',
					paddingX: '6',
					paddingY: '3'
				})}
			>
				<div class={cx(row, css({ gap: '2' }))}>
					<button
						class={css({
							display: 'flex',
							alignItems: 'center',
							gap: '1',
							fontSize: 'md',
							fontWeight: 'semibold',
							textDecoration: 'none',
							backgroundColor: 'transparent',
							borderWidth: '0',
							padding: '0'
						})}
						onclick={openNamespace}
						type="button"
						aria-label="Select namespace"
						bind:this={namespaceTrigger}
					>
						<span>analysis</span>
						<span class={muted}>/</span>
						<span class={css({ color: 'fg.tertiary' })}>{namespaceDraft}</span>
					</button>
				</div>

				<nav class={cx(row, css({ gap: '1' }))}>
					{#each navItems as item (item.href)}
						<a
							href={resolve(item.href as '/')}
							class={cx(
								navLink({
									active:
										currentPath === item.href ||
										(currentPath.startsWith('/analysis') && item.href === '/') ||
										(currentPath.startsWith('/udfs') && item.href === '/udfs') ||
										(currentPath.startsWith('/monitoring') && item.href === '/monitoring') ||
										(currentPath.startsWith('/lineage') && item.href === '/lineage')
								})
							)}
						>
							{item.label}
						</a>
					{/each}
				</nav>

				<div
					class={css({
						marginLeft: 'auto',
						display: 'flex',
						alignItems: 'center',
						gap: '2'
					})}
				>
					<EngineMonitor />
					<IndexedDbButton />
					<button
						class={iconButton()}
						onclick={() => (settingsOpen = true)}
						title="Settings"
						aria-label="Settings"
					>
						<Settings size={16} />
					</button>
					<button
						class={iconButton()}
						onclick={() => {
							if (chatStore.open) {
								chatStore.close();
								return;
							}
							void chatStore.open_panel();
						}}
						title="AI Assistant"
						aria-label="AI Assistant"
					>
						<MessageSquare size={16} />
					</button>
					<button
						class={iconButton()}
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

		<main
			class={css({ minHeight: '0', flex: '1', overflowY: 'auto', backgroundColor: 'bg.secondary' })}
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
</QueryClientProvider>
