<script lang="ts">
	import { X, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from 'lucide-svelte';
	import { css, spinner as spinnerRecipe } from '$lib/styles/panda';
	import type { Snippet } from 'svelte';

	type PanelWidth = 'panelSm' | 'panelMd' | 'panelLg';

	interface Props {
		title: string;
		width?: PanelWidth;
		collapsible?: boolean;
		collapsed?: boolean;
		position?: 'left' | 'right';
		loading?: boolean;
		onClose?: () => void;
		children: Snippet;
		empty?: Snippet;
		header?: Snippet;
	}

	let {
		title,
		width = 'panelMd',
		collapsible = true,
		collapsed = $bindable(false),
		position = 'left',
		loading = false,
		onClose,
		children,
		empty,
		header
	}: Props = $props();

	const CollapseIcon = $derived(
		position === 'left'
			? collapsed
				? PanelLeftOpen
				: PanelLeftClose
			: collapsed
				? PanelRightOpen
				: PanelRightClose
	);

	const panelClass = $derived(
		css({
			display: 'flex',
			flexDirection: 'column',
			height: '100%',
			backgroundColor: 'bg.panel',
			borderLeftWidth: position === 'right' ? '1' : '0',
			borderRightWidth: position === 'left' ? '1' : '0',
			flexShrink: 0,
			width: collapsed ? '0px' : width,
			minWidth: collapsed ? '0px' : width,
			overflow: 'hidden',
			transitionProperty: 'width, min-width',
			transitionDuration: '200ms',
			transitionTimingFunction: 'ease'
		})
	);

	function handleClose() {
		if (onClose) return onClose();
		collapsed = true;
	}
</script>

<div class={panelClass} aria-label={`${title} panel`}>
	{#if !collapsed}
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'space-between',
				gap: '2',
				position: 'sticky',
				top: '0',
				zIndex: 'header',
				borderBottomWidth: '1',
				paddingX: '4',
				paddingY: '3',
				backgroundColor: 'bg.panel'
			})}
		>
			<div
				class={css({ display: 'flex', alignItems: 'center', gap: '2', minWidth: '0', flex: '1' })}
			>
				<h2
					class={css({
						margin: '0',
						fontSize: 'sm',
						fontWeight: 'semibold',
						whiteSpace: 'nowrap',
						overflow: 'hidden',
						textOverflow: 'ellipsis'
					})}
				>
					{title}
				</h2>
				{#if header}
					{@render header()}
				{/if}
			</div>
			<div class={css({ display: 'flex', alignItems: 'center', gap: '1', flexShrink: 0 })}>
				{#if collapsible}
					<button
						class={css({
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'center',
							borderWidth: '0',
							backgroundColor: 'transparent',
							padding: '1',
							color: 'fg.muted',
							transitionProperty: 'color, background-color',
							transitionDuration: '160ms',
							transitionTimingFunction: 'ease',
							_hover: { color: 'fg.primary', backgroundColor: 'bg.hover' }
						})}
						onclick={() => (collapsed = true)}
						title="Collapse panel"
						aria-label="Collapse panel"
						type="button"
					>
						<CollapseIcon size={16} />
					</button>
				{/if}
				{#if onClose}
					<button
						class={css({
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'center',
							borderWidth: '0',
							backgroundColor: 'transparent',
							padding: '1',
							color: 'fg.muted',
							transitionProperty: 'color, background-color',
							transitionDuration: '160ms',
							transitionTimingFunction: 'ease',
							_hover: { color: 'fg.primary', backgroundColor: 'bg.hover' }
						})}
						onclick={handleClose}
						title="Close panel"
						aria-label="Close panel"
						type="button"
					>
						<X size={16} />
					</button>
				{/if}
			</div>
		</div>

		{#if loading}
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
					flex: '1',
					padding: '8'
				})}
			>
				<div class={spinnerRecipe()}></div>
			</div>
		{:else if empty}
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
					flex: '1',
					padding: '8',
					color: 'fg.muted',
					fontSize: 'sm',
					textAlign: 'center'
				})}
			>
				{@render empty()}
			</div>
		{:else}
			<div
				class={css({
					flex: '1',
					overflowY: 'auto',
					minHeight: '0'
				})}
			>
				{@render children()}
			</div>
		{/if}
	{/if}
</div>
