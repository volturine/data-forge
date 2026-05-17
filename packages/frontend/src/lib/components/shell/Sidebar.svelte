<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { createQuery } from '@tanstack/svelte-query';
	import {
		LayoutGrid,
		Database,
		Activity,
		GitBranch,
		CodeXml,
		PanelLeftOpen,
		Sun,
		Moon,
		MessageSquare,
		Cpu,
		LogOut,
		User,
		Star
	} from 'lucide-svelte';
	import { listFavoriteAnalyses } from '$lib/api/analysis';
	import { css } from '$lib/styles/panda';
	import { enginesStore } from '$lib/stores/engines.svelte';
	import { favoriteStore } from '$lib/stores/favorites.svelte';
	import EnginesPopup from '$lib/components/common/EnginesPopup.svelte';

	interface Props {
		collapsed: boolean;
		interactive: boolean;
		onToggle: () => void;
		theme: 'light' | 'dark';
		onToggleTheme: () => void;
		onOpenChat: () => void;
		onOpenNamespace: () => void;
		onSignOut: () => void;
		namespace: string;
		authenticated: boolean;
		authRequired: boolean;
		avatarUrl: string | null;
		namespaceTrigger?: HTMLButtonElement;
	}

	let {
		collapsed,
		interactive,
		onToggle,
		theme,
		onToggleTheme,
		onOpenChat,
		onOpenNamespace,
		onSignOut,
		namespace,
		authenticated,
		authRequired,
		avatarUrl,
		namespaceTrigger = $bindable()
	}: Props = $props();

	const currentPath = $derived(page.url.pathname);
	let enginesOpen = $state(false);
	let enginesTrigger = $state<HTMLButtonElement>();

	const analysesQuery = createQuery(() => ({
		queryKey: ['favorite-analyses', namespace],
		enabled: namespace.trim().length > 0,
		queryFn: async () => {
			const result = await listFavoriteAnalyses();
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		}
	}));

	const favoriteAnalyses = $derived(analysesQuery.data ?? []);

	const navItems = [
		{ href: '/', label: 'Analyses', icon: LayoutGrid, prefix: '/analysis' },
		{ href: '/datasources', label: 'Data Sources', icon: Database, prefix: '/datasources' },
		{ href: '/monitoring', label: 'Monitoring', icon: Activity, prefix: '/monitoring' },
		{ href: '/lineage', label: 'Lineage', icon: GitBranch, prefix: '/lineage' },
		{ href: '/udfs', label: 'UDFs', icon: CodeXml, prefix: '/udfs' }
	] as const;

	function isActive(item: (typeof navItems)[number]): boolean {
		if (item.href === '/') return currentPath === '/' || currentPath.startsWith('/analysis');
		return currentPath.startsWith(item.prefix);
	}

	const sidebarClass = $derived(
		css({
			display: 'flex',
			flexDirection: 'column',
			height: '100vh',
			backgroundColor: 'bg.panel',
			borderRightWidth: '1',
			zIndex: 'nav',
			flexShrink: 0,
			width: collapsed ? 'sidebarCollapsed' : 'sidebarExpanded',
			transitionProperty: 'width',
			transitionDuration: '200ms',
			transitionTimingFunction: 'ease',
			overflow: 'visible'
		})
	);

	const navLinkClass = (active: boolean) =>
		css({
			display: 'flex',
			alignItems: 'center',
			justifyContent: collapsed ? 'center' : 'flex-start',
			gap: collapsed ? '0' : '3',
			width: '100%',
			paddingX: collapsed ? '0' : '3',
			paddingY: '2',
			fontSize: 'sm',
			cursor: 'pointer',
			color: active ? 'fg.primary' : 'fg.tertiary',
			backgroundColor: active ? 'bg.tertiary' : 'transparent',
			textDecoration: 'none',
			borderWidth: '0',
			borderLeftWidth: '2',
			borderLeftColor: active ? 'accent.primary' : 'transparent',
			transitionProperty: 'color, background-color, border-color',
			transitionDuration: '160ms',
			transitionTimingFunction: 'ease',
			_hover: { color: 'fg.primary', backgroundColor: 'bg.hover' },
			whiteSpace: 'nowrap',
			overflow: 'hidden'
		});

	const sidebarBtnClass = $derived(
		css({
			display: 'flex',
			alignItems: 'center',
			justifyContent: collapsed ? 'center' : 'flex-start',
			gap: collapsed ? '0' : '3',
			width: '100%',
			paddingX: collapsed ? '0' : '3',
			paddingY: '2',
			fontSize: 'sm',
			cursor: 'pointer',
			color: 'fg.tertiary',
			backgroundColor: 'transparent',
			borderWidth: '0',
			borderLeftWidth: '2',
			borderLeftColor: 'transparent',
			transitionProperty: 'color, background-color',
			transitionDuration: '160ms',
			transitionTimingFunction: 'ease',
			_hover: { color: 'fg.primary', backgroundColor: 'bg.hover' },
			whiteSpace: 'nowrap',
			overflow: 'hidden'
		})
	);

	const profileActive = $derived(currentPath.startsWith('/profile'));

	function openEngines(): void {
		enginesOpen = true;
	}

	$effect(() => {
		const analyses = analysesQuery.data;
		if (!analyses) return;
		favoriteStore.sync(analyses);
	});

	// Subscription: opening the popup is an explicit on-demand owner of the engines stream.
	$effect(() => {
		if (!enginesOpen) return;
		enginesStore.startStream();
		return () => enginesStore.stopStream();
	});
</script>

<aside
	class={sidebarClass}
	aria-label="Main navigation"
	data-shell-interactive={interactive ? 'true' : 'false'}
>
	<div
		class={css({
			display: 'flex',
			alignItems: 'center',
			paddingX: '3',
			height: '12',
			borderBottomWidth: '1'
		})}
	>
		{#if collapsed}
			<button
				class={[
					sidebarBtnClass,
					css({
						paddingX: '0',
						borderLeftWidth: '0',
						justifyContent: 'center'
					})
				]}
				onclick={onToggle}
				type="button"
				aria-label="Expand sidebar"
			>
				<span
					class={css({
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						flexShrink: 0,
						width: '5',
						height: '5'
					})}
				>
					<PanelLeftOpen size={16} />
				</span>
			</button>
		{:else}
			<button
				class={css({
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
					gap: '0',
					width: '100%',
					paddingX: '0',
					paddingY: '2',
					fontSize: 'md',
					fontWeight: 'semibold',
					cursor: 'pointer',
					color: 'fg.tertiary',
					backgroundColor: 'transparent',
					borderWidth: '0',
					transitionProperty: 'color, background-color',
					transitionDuration: '160ms',
					transitionTimingFunction: 'ease',
					_hover: { color: 'fg.primary', backgroundColor: 'bg.hover' }
				})}
				onclick={onOpenNamespace}
				type="button"
				aria-label="Select namespace"
				bind:this={namespaceTrigger}
			>
				<span class={css({ display: 'flex', alignItems: 'center', gap: '0', overflow: 'hidden' })}>
					<span
						class={css({ display: 'flex', alignItems: 'center', gap: '0', overflow: 'hidden' })}
					>
						<span class={css({ color: 'fg.muted' })}>/</span>
						<span
							class={css({
								color: 'fg.primary',
								overflow: 'hidden',
								textOverflow: 'ellipsis',
								whiteSpace: 'nowrap',
								textDecoration: 'underline',
								textDecorationColor: 'fg.muted',
								textUnderlineOffset: '3px'
							})}
						>
							{namespace}
						</span>
					</span>
				</span></button
			>
		{/if}
	</div>

	<div
		class={css({
			display: 'flex',
			flexDirection: 'column',
			flex: '1',
			minHeight: '0'
		})}
	>
		<nav
			class={css({
				display: 'flex',
				flexDirection: 'column',
				gap: '0.5',
				paddingY: '2'
			})}
			aria-label="Primary"
		>
			{#each navItems as item (item.href)}
				{@const active = isActive(item)}
				<a
					href={resolve(item.href as '/')}
					class={navLinkClass(active)}
					title={collapsed ? item.label : undefined}
					aria-current={active ? 'page' : undefined}
				>
					<span
						class={css({
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'center',
							flexShrink: 0,
							width: '5',
							height: '5'
						})}
					>
						<item.icon size={16} />
					</span>
					{#if !collapsed}
						<span>{item.label}</span>
					{/if}
				</a>
			{/each}
		</nav>

		<div
			class={css({
				display: 'flex',
				flexDirection: 'column',
				gap: '2',
				flex: '1',
				minHeight: '0',
				paddingX: collapsed ? '0' : '3',
				paddingTop: collapsed ? '0' : '3',
				paddingBottom: collapsed ? '0' : '2',
				overflow: 'hidden'
			})}
			role="group"
			aria-label="Favorite analyses"
		>
			{#if !collapsed}
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						gap: '2',
						paddingBottom: '1',
						color: 'fg.muted',
						fontSize: '2xs2',
						fontWeight: 'semibold',
						letterSpacing: 'widest',
						textTransform: 'uppercase'
					})}
				>
					<Star size={12} />
					<span>Favorites</span>
				</div>

				{#if analysesQuery.isLoading}
					<div class={css({ fontSize: 'xs', color: 'fg.muted' })}>Loading…</div>
				{:else if favoriteAnalyses.length === 0}
					<p
						class={css({
							margin: '0',
							fontSize: 'xs',
							lineHeight: '1.5',
							color: 'fg.faint'
						})}
					>
						Star analyses to pin them here.
					</p>
				{:else}
					<div
						class={css({
							display: 'flex',
							flexDirection: 'column',
							gap: '1',
							overflowY: 'auto',
							paddingRight: '1'
						})}
						data-testid="favorite-analyses"
					>
						{#each favoriteAnalyses as analysis (analysis.id)}
							<a
								href={resolve(`/analysis/${analysis.id}`)}
								class={css({
									display: 'flex',
									alignItems: 'center',
									gap: '2',
									minWidth: '0',
									paddingX: '2',
									paddingY: '1.5',
									fontSize: 'sm',
									color: currentPath === `/analysis/${analysis.id}` ? 'fg.primary' : 'fg.tertiary',
									backgroundColor:
										currentPath === `/analysis/${analysis.id}` ? 'bg.hover' : 'transparent',
									textDecoration: 'none',
									transitionProperty: 'color, background-color',
									transitionDuration: '160ms',
									transitionTimingFunction: 'ease',
									_hover: { color: 'fg.primary', backgroundColor: 'bg.hover' }
								})}
								data-testid={`favorite-analysis-link-${analysis.id}`}
							>
								<Star size={12} fill="currentColor" />
								<span
									class={css({
										minWidth: '0',
										overflow: 'hidden',
										textOverflow: 'ellipsis',
										whiteSpace: 'nowrap'
									})}
								>
									{analysis.name}
								</span>
							</a>
						{/each}
					</div>
				{/if}
			{/if}
		</div>
	</div>

	<div
		class={css({
			display: 'flex',
			flexDirection: 'column',
			gap: '0.5',
			paddingY: '2',
			borderTopWidth: '1'
		})}
		role="group"
		aria-label="Tools"
	>
		<button
			class={sidebarBtnClass}
			onclick={onOpenChat}
			title={collapsed ? 'Chat' : 'AI Assistant'}
			aria-label="AI Assistant"
			type="button"
		>
			<span
				class={css({
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
					flexShrink: 0,
					width: '5',
					height: '5'
				})}
			>
				<MessageSquare size={16} />
			</span>
			{#if !collapsed}
				<span>Chat</span>
			{/if}
		</button>

		<div class={css({ position: 'relative' })}>
			<button
				class={[
					sidebarBtnClass,
					css({
						color: enginesStore.count > 0 ? 'fg.secondary' : 'fg.tertiary'
					})
				]}
				title={collapsed ? 'Engines' : 'Engine Monitor'}
				aria-label="Engine Monitor"
				aria-expanded={enginesOpen}
				type="button"
				onclick={openEngines}
				bind:this={enginesTrigger}
			>
				<span
					class={css({
						position: 'relative',
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						flexShrink: 0,
						width: '5',
						height: '5'
					})}
				>
					<Cpu size={16} />
					{#if enginesStore.count > 0}
						<span
							data-testid="engine-monitor-count"
							class={css({
								position: 'absolute',
								top: '-2px',
								right: '-4px',
								minWidth: '3',
								height: '3',
								display: 'flex',
								alignItems: 'center',
								justifyContent: 'center',
								fontSize: '2xs',
								fontWeight: 'bold',
								backgroundColor: 'accent.primary',
								color: 'fg.inverse'
							})}
						>
							{enginesStore.count}
						</span>
					{/if}
				</span>
				{#if !collapsed}
					<span>Engines</span>
				{/if}
			</button>

			<EnginesPopup bind:open={enginesOpen} anchor={enginesTrigger} />
		</div>

		<button
			class={sidebarBtnClass}
			onclick={onToggleTheme}
			title={collapsed ? (theme === 'light' ? 'Light' : 'Dark') : 'Toggle theme'}
			aria-label="Toggle theme"
			type="button"
		>
			<span
				class={css({
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
					flexShrink: 0,
					width: '5',
					height: '5'
				})}
			>
				{#if theme === 'light'}
					<Sun size={16} />
				{:else}
					<Moon size={16} />
				{/if}
			</span>
			{#if !collapsed}
				<span>{theme === 'light' ? 'Light' : 'Dark'}</span>
			{/if}
		</button>
	</div>

	{#if authenticated || !authRequired}
		<div
			class={css({
				display: 'flex',
				flexDirection: 'column',
				gap: '0.5',
				paddingY: '2',
				borderTopWidth: '1'
			})}
			role="group"
			aria-label="Account"
		>
			<a
				href={resolve('/profile' as '/')}
				class={navLinkClass(profileActive)}
				title={collapsed ? 'Profile' : undefined}
				aria-current={profileActive ? 'page' : undefined}
			>
				<span
					class={css({
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						flexShrink: 0,
						width: '5',
						height: '5'
					})}
				>
					{#if avatarUrl}
						<img
							src={avatarUrl}
							alt=""
							class={css({
								width: '5',
								height: '5',
								borderRadius: 'full',
								objectFit: 'cover'
							})}
						/>
					{:else}
						<User size={16} />
					{/if}
				</span>
				{#if !collapsed}
					<span>Profile</span>
				{/if}
			</a>

			{#if authRequired}
				<button
					class={sidebarBtnClass}
					onclick={onSignOut}
					title={collapsed ? 'Sign out' : 'Sign out'}
					aria-label="Sign out"
					type="button"
				>
					<span
						class={css({
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'center',
							flexShrink: 0,
							width: '5',
							height: '5'
						})}
					>
						<LogOut size={16} />
					</span>
					{#if !collapsed}
						<span>Sign out</span>
					{/if}
				</button>
			{/if}
		</div>
	{/if}
</aside>
