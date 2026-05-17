<script lang="ts">
	type Action<T = unknown> = (
		node: HTMLElement,
		value: T
	) => {
		update?: (value: T) => void;
		destroy?: () => void;
	};

	import type { Snippet } from 'svelte';
	import { css } from '$lib/styles/panda';
	import { overlayStack } from '$lib/stores/overlay.svelte';
	import type { OverlayConfig } from '$lib/stores/overlay.svelte';

	interface Props {
		open: boolean;
		content: Snippet;
		onClose?: () => void;
		closeOnEscape?: boolean;
		closeOnBackdrop?: boolean;
		overlayClass?: string;
		panelClass?: string;
		panelAction?: Action<unknown>;
		panelActionValue?: unknown;
		role?: string;
		ariaModal?: boolean;
		ariaLabelledby?: string;
		ariaDescribedby?: string;
	}

	const noopAction: Action<unknown> = () => ({
		update: () => undefined,
		destroy: () => undefined
	});

	let {
		open,
		content,
		onClose,
		closeOnEscape = true,
		closeOnBackdrop = true,
		overlayClass = css({
			position: 'fixed',
			inset: '0',
			zIndex: 'modal',
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'center',
			padding: '4'
		}),
		panelClass = css({
			width: '100%',
			maxHeight: '90vh',
			overflowY: 'auto',
			borderWidth: '1'
		}),
		panelAction = noopAction,
		panelActionValue,
		role = 'dialog',
		ariaModal = true,
		ariaLabelledby,
		ariaDescribedby
	}: Props = $props();

	function handleClose() {
		onClose?.();
	}

	const overlayConfig = $derived<OverlayConfig>({
		onEscape: closeOnEscape ? handleClose : undefined,
		modal: true
	});

	function handleBackdropMousedown(event: MouseEvent) {
		if (!closeOnBackdrop) return;
		if (event.target !== event.currentTarget) return;
		handleClose();
	}

	function modalPanel(node: HTMLElement): () => void {
		document.body.style.overflow = 'hidden';
		node.focus();
		return () => {
			document.body.style.overflow = '';
		};
	}
</script>

{#if open}
	<div
		class={overlayClass}
		onmousedown={handleBackdropMousedown}
		role="presentation"
		use:overlayStack.action={overlayConfig}
	>
		<div
			class={panelClass}
			{role}
			aria-modal={ariaModal}
			aria-labelledby={ariaLabelledby}
			aria-describedby={ariaDescribedby}
			tabindex="-1"
			onmousedown={(event) => event.stopPropagation()}
			{@attach modalPanel}
			use:panelAction={panelActionValue}
		>
			{@render content()}
		</div>
	</div>
{/if}
