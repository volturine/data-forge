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
		backdropLabel?: string;
		onBackdropKeydown?: (event: KeyboardEvent) => void;
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
		ariaDescribedby,
		backdropLabel = 'Close modal',
		onBackdropKeydown
	}: Props = $props();

	function handleClose() {
		onClose?.();
	}

	function handleKeydown(event: KeyboardEvent) {
		if (!open) return;
		if (!closeOnEscape) return;
		if (event.key !== 'Escape') return;
		event.preventDefault();
		handleClose();
	}

	function handleBackdropClick() {
		if (!closeOnBackdrop) return;
		handleClose();
	}

	function handleBackdropKeydown(event: KeyboardEvent) {
		onBackdropKeydown?.(event);
	}

	// DOM: $derived can't lock body scroll.
	$effect(() => {
		if (!open) return;
		document.body.style.overflow = 'hidden';
		return () => {
			document.body.style.overflow = '';
		};
	});
</script>

<svelte:window onkeydown={handleKeydown} />

{#if open}
	<div
		class={overlayClass}
		onclick={handleBackdropClick}
		onkeydown={handleBackdropKeydown}
		role="button"
		tabindex="0"
		aria-label={backdropLabel}
	>
		<div
			class={panelClass}
			{role}
			aria-modal={ariaModal}
			aria-labelledby={ariaLabelledby}
			aria-describedby={ariaDescribedby}
			tabindex="-1"
			onclick={(event) => event.stopPropagation()}
			onkeydown={(event) => event.stopPropagation()}
			use:panelAction={panelActionValue}
		>
			{@render content()}
		</div>
	</div>
{/if}
