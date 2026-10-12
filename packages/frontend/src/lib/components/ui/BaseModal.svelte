<script module lang="ts">
	let openModals = 0;
	let bodyOverflow = '';
</script>

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
		size?: 'default' | 'large';
		initialFocus?: string;
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
			zIndex: 'overlay',
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'center',
			padding: '4',
			backgroundColor: 'bg.overlay',
			backdropFilter: 'blur(6px)'
		}),
		panelClass,
		size = 'default',
		initialFocus,
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

	function absorbOutsideClick(): void {}

	const overlayConfig = $derived<OverlayConfig>({
		onEscape: closeOnEscape ? handleClose : undefined,
		onOutsideClick: absorbOutsideClick,
		modal: true
	});

	function handleBackdropMousedown(event: MouseEvent) {
		if (!closeOnBackdrop) return;
		if (event.target !== event.currentTarget) return;
		handleClose();
	}

	function modalPanel(node: HTMLElement): () => void {
		const previousFocus = document.activeElement;
		if (openModals === 0) bodyOverflow = document.body.style.overflow;
		openModals += 1;
		document.body.style.overflow = 'hidden';
		const focusTarget = initialFocus ? node.querySelector<HTMLElement>(initialFocus) : node;
		(focusTarget ?? node).focus({ preventScroll: true });

		function isTopModal(): boolean {
			return (
				overlayStack.stack.findLast((entry) => entry.modal)?.onOutsideClick === absorbOutsideClick
			);
		}

		function keepFocusInside(event: FocusEvent): void {
			if (!isTopModal() || !(event.target instanceof Node) || node.contains(event.target)) return;
			node.focus({ preventScroll: true });
		}

		function trapTab(event: KeyboardEvent): void {
			if (event.key !== 'Tab' || !isTopModal()) return;
			const focusable = Array.from(
				node.querySelectorAll<HTMLElement>(
					'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"]), [contenteditable="true"]'
				)
			).filter((element) => !element.closest('[hidden], [inert], [aria-hidden="true"]'));
			const first = focusable[0];
			const last = focusable.at(-1);
			const active = document.activeElement;
			if (!first || !last) {
				event.preventDefault();
				node.focus({ preventScroll: true });
				return;
			}
			if (event.shiftKey && (active === first || active === node)) {
				event.preventDefault();
				last.focus({ preventScroll: true });
				return;
			}
			if (!event.shiftKey && (active === last || active === node)) {
				event.preventDefault();
				first.focus({ preventScroll: true });
			}
		}

		document.addEventListener('focusin', keepFocusInside);
		document.addEventListener('keydown', trapTab, true);
		return () => {
			document.removeEventListener('focusin', keepFocusInside);
			document.removeEventListener('keydown', trapTab, true);
			openModals -= 1;
			if (openModals === 0) document.body.style.overflow = bodyOverflow;
			if (previousFocus instanceof HTMLElement && previousFocus.isConnected) {
				previousFocus.focus({ preventScroll: true });
			}
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
			class={panelClass ??
				(size === 'large'
					? css({
							width: 'full',
							maxWidth: 'pageWide',
							height: 'screenTall',
							maxHeight: 'screenTall',
							display: 'flex',
							flexDirection: 'column',
							minHeight: '0',
							overflow: 'hidden',
							borderWidth: '1',
							backgroundColor: 'bg.primary',
							boxShadow: 'panel'
						})
					: css({
							width: 'full',
							maxHeight: 'screenTall',
							overflowY: 'auto',
							borderWidth: '1'
						}))}
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
