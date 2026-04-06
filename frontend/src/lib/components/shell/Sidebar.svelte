<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import {
		LayoutGrid,
		Database,
		Activity,
		GitBranch,
		Code2,
		PanelLeftOpen,
		Sun,
		Moon,
		Settings,
		MessageSquare,
		Cpu,
		LogOut,
		User
	} from 'lucide-svelte';
	import { css, cx } from '$lib/styles/panda';
	import { enginesStore } from '$lib/stores/engines.svelte';
	import { untrack } from 'svelte';

	interface Props {
		collapsed: boolean;
		onToggle: () => void;
		theme: 'light' | 'dark';
		onToggleTheme: () => void;
		onOpenSettings: () => void;
		onOpenEngines: () => void;
		onOpenChat: () => void;
		onOpenNamespace: () => void;
		onSignOut: () => void;
		namespace: string;
		authenticated: boolean;
		authRequired: boolean;
		avatarUrl: string | null;
		namespaceTrigger?: HTMLButtonElement;
		enginesTrigger?: HTMLButtonElement;
	}

	let {
		collapsed,
		onToggle,
		theme,
		onToggleTheme,
		onOpenSettings,
		onOpenEngines,
		onOpenChat,
		onOpenNamespace,
		onSignOut,
		namespace,
		authenticated,
		authRequired,
		avatarUrl,
		namespaceTrigger = $bindable(),
		enginesTrigger = $bindable()
	}: Props = $props();

	const currentPath = $derived(page.url.pathname);

	// Subscription: $derived can't manage polling lifecycle.
	$effect(() => {
		untrack(() => void enginesStore.startPolling());
		return () => enginesStore.stopPolling();
	});

	const navItems = [
		{ href: '/', label: 'Analyses', icon: LayoutGrid, prefix: '/analysis' },
		{ href: '/datasources', label: 'Data Sources', icon: Database, prefix: '/datasources' },
		{ href: '/monitoring', label: 'Monitoring', icon: Activity, prefix: '/monitoring' },
		{ href: '/lineage', label: 'Lineage', icon: GitBranch, prefix: '/lineage' },
		{ href: '/udfs', label: 'UDFs', icon: Code2, prefix: '/udfs' }
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
			overflow: 'hidden'
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

	const iconWrapClass = css({
		display: 'flex',
		alignItems: 'center',
		justifyContent: 'center',
		flexShrink: 0,
		width: '5',
		height: '5'
	});

	const profileActive = $derived(currentPath.startsWith('/profile'));

	const sectionClass = css({
		display: 'flex',
		flexDirection: 'column',
		gap: '0.5',
		paddingY: '2',
		borderTopWidth: '1'
	});
</script>

<aside class={sidebarClass} aria-label="Main navigation">
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
				class={cx(
					sidebarBtnClass,
					css({
						paddingX: '0',
						borderLeftWidth: '0',
						justifyContent: 'center'
					})
				)}
				onclick={onToggle}
				type="button"
				aria-label="Expand sidebar"
			>
				<span class={iconWrapClass}>
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

	<nav
		class={css({
			display: 'flex',
			flexDirection: 'column',
			gap: '0.5',
			paddingY: '2',
			flex: '1'
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
				<span class={iconWrapClass}>
					<item.icon size={16} />
				</span>
				{#if !collapsed}
					<span>{item.label}</span>
				{/if}
			</a>
		{/each}
	</nav>

	<div class={sectionClass} role="group" aria-label="Tools">
		<button
			class={sidebarBtnClass}
			onclick={onOpenChat}
			title={collapsed ? 'Chat' : 'AI Assistant'}
			aria-label="AI Assistant"
			type="button"
		>
			<span class={iconWrapClass}>
				<MessageSquare size={16} />
			</span>
			{#if !collapsed}
				<span>Chat</span>
			{/if}
		</button>

		<button
			class={cx(
				sidebarBtnClass,
				css({
					color: enginesStore.count > 0 ? 'fg.secondary' : 'fg.tertiary'
				})
			)}
			title={collapsed ? 'Engines' : 'Engine Monitor'}
			aria-label="Engine Monitor"
			type="button"
			onclick={onOpenEngines}
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

		<button
			class={sidebarBtnClass}
			onclick={onOpenSettings}
			title={collapsed ? 'Settings' : 'Settings'}
			aria-label="Settings"
			type="button"
		>
			<span class={iconWrapClass}>
				<Settings size={16} />
			</span>
			{#if !collapsed}
				<span>Settings</span>
			{/if}
		</button>

		<button
			class={sidebarBtnClass}
			onclick={onToggleTheme}
			title={collapsed ? (theme === 'light' ? 'Light' : 'Dark') : 'Toggle theme'}
			aria-label="Toggle theme"
			type="button"
		>
			<span class={iconWrapClass}>
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
		<div class={sectionClass} role="group" aria-label="Account">
			<a
				href={resolve('/profile' as '/')}
				class={navLinkClass(profileActive)}
				title={collapsed ? 'Profile' : undefined}
				aria-current={profileActive ? 'page' : undefined}
			>
				<span class={iconWrapClass}>
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
					<span class={iconWrapClass}>
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
