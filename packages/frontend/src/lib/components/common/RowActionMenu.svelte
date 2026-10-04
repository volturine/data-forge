<script lang="ts">
	import { onDestroy } from 'svelte';
	import { EllipsisVertical, Workflow } from '@lucide/svelte';
	import { overlayStack } from '$lib/stores/overlay.svelte';
	import { css } from '$lib/styles/panda';

	interface MenuItem {
		id: string;
		label: string;
		icon?: typeof Workflow;
		onSelect: () => void;
	}

	interface Props {
		label?: string;
		items: MenuItem[];
	}

	let { label = 'More actions', items }: Props = $props();

	let open = $state(false);
	let trigger: HTMLButtonElement | undefined = $state();
	let menu: HTMLDivElement | undefined = $state();
	const menuWidth = 180;
	let rect = $state({ left: 0, top: 0 });

	function updatePosition() {
		if (!trigger) return;
		const box = trigger.getBoundingClientRect();
		let left = box.right - menuWidth;
		left = Math.max(8, Math.min(left, window.innerWidth - menuWidth - 8));
		rect = { left, top: box.bottom + 4 };
	}

	function toggle() {
		if (open) {
			open = false;
			return;
		}
		open = true;
	}

	function handleResize() {
		if (open) updatePosition();
	}

	$effect(() => {
		if (!open) return;
		updatePosition();
		window.addEventListener('resize', handleResize);
		window.addEventListener('scroll', handleResize, true);
		return () => {
			window.removeEventListener('resize', handleResize);
			window.removeEventListener('scroll', handleResize, true);
		};
	});

	const outsideClickConfig = $derived(
		open
			? {
					onEscape: () => (open = false),
					onOutsideClick: (target: Node) => {
						if (menu?.contains(target)) return;
						if (trigger?.contains(target)) return;
						open = false;
					}
				}
			: null
	);

	onDestroy(() => {
		open = false;
	});
</script>

<button
	type="button"
	aria-label={label}
	aria-haspopup="menu"
	aria-expanded={open}
	class={css({
		display: 'inline-flex',
		alignItems: 'center',
		justifyContent: 'center',
		padding: '1.5',
		backgroundColor: 'transparent',
		borderWidth: '1',
		borderColor: 'transparent',
		color: open ? 'accent.primary' : 'fg.muted',
		cursor: 'pointer',
		transitionProperty: 'color, background-color',
		transitionDuration: '150ms',
		_hover: { color: 'fg.primary', backgroundColor: 'bg.hover' },
		flexShrink: '0'
	})}
	onclick={toggle}
	bind:this={trigger}
>
	<EllipsisVertical size={14} />
</button>

{#if open && outsideClickConfig}
	<div
		class={css({
			position: 'fixed',
			zIndex: 'popover',
			boxShadow: 'menu',
			backgroundColor: 'bg.primary',
			borderWidth: '1',
			borderColor: 'border.primary',
			minWidth: `${menuWidth}px`,
			paddingY: '1',
			display: 'flex',
			flexDirection: 'column'
		})}
		style={`left: ${rect.left}px; top: ${rect.top}px;`}
		role="menu"
		aria-label={label}
		use:overlayStack.action={outsideClickConfig}
		bind:this={menu}
	>
		{#each items as item (item.id)}
			<button
				type="button"
				role="menuitem"
				class={css({
					display: 'flex',
					alignItems: 'center',
					gap: '2',
					width: 'full',
					border: 'none',
					background: 'transparent',
					color: 'fg.primary',
					paddingX: '3',
					paddingY: '2',
					textAlign: 'left',
					fontSize: 'xs',
					cursor: 'pointer',
					_hover: { backgroundColor: 'bg.hover' }
				})}
				onclick={() => {
					open = false;
					item.onSelect();
				}}
			>
				{#if item.icon}
					<item.icon size={14} />
				{/if}
				{item.label}
			</button>
		{/each}
	</div>
{/if}
