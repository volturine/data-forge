<script lang="ts">
	import { X } from 'lucide-svelte';
	import { onClickOutside } from 'runed';

	interface Props {
		show: boolean;
		title: string;
		message: string;
		confirmText?: string;
		cancelText?: string;
		onConfirm: () => void;
		onCancel: () => void;
	}

	let {
		show,
		title,
		message,
		confirmText = 'Confirm',
		cancelText = 'Cancel',
		onConfirm,
		onCancel
	}: Props = $props();

	let dialogEl = $state<HTMLElement | null>(null);
	let dialogRef = $state<HTMLElement>();

	onClickOutside(
		() => dialogRef,
		() => onCancel(),
		{ immediate: true }
	);

	function handleKeydown(e: KeyboardEvent) {
		if (!show) return;

		if (e.key === 'Escape') {
			e.preventDefault();
			onCancel();
		} else if (e.key === 'Enter') {
			e.preventDefault();
			onConfirm();
		}
	}

	$effect(() => {
		if (show && dialogEl) {
			dialogEl.focus();
			document.body.style.overflow = 'hidden';
		} else {
			document.body.style.overflow = '';
		}

		return () => {
			document.body.style.overflow = '';
		};
	});
</script>

<svelte:window onkeydown={handleKeydown} />

{#if show}
	<div
		class="fixed inset-0 z-1000 flex animate-fade-in items-center justify-center p-4 bg-overlay"
		role="presentation"
	>
		<div
			class="w-full max-w-100 animate-slide-up overflow-hidden border max-sm:max-w-full bg-dialog border-tertiary focus:outline-none"
			role="dialog"
			aria-modal="true"
			aria-labelledby="dialog-title"
			aria-describedby="dialog-message"
			tabindex="-1"
			bind:this={dialogRef}
		>
			<div class="flex items-center justify-between border-b p-4 border-tertiary">
				<h2 id="dialog-title" class="m-0 text-base font-semibold text-fg-primary">
					{title}
				</h2>
				<button
					class="flex cursor-pointer items-center justify-center border-none bg-transparent p-1 text-fg-muted hover:bg-hover hover:text-fg-primary"
					onclick={onCancel}
					aria-label="Close dialog"
				>
					<X size={16} />
				</button>
			</div>

			<div class="p-6">
				<p id="dialog-message" class="m-0 text-sm leading-relaxed text-fg-secondary">
					{message}
				</p>
			</div>

			<div class="flex justify-end gap-3 border-t p-4 max-sm:flex-col-reverse border-tertiary">
				<button
					class="cursor-pointer border bg-transparent px-4 py-2 font-mono text-sm font-medium max-sm:w-full text-fg-primary border-tertiary hover:bg-hover"
					onclick={onCancel}
				>
					{cancelText}
				</button>
				<button
					class="cursor-pointer border px-4 py-2 font-mono text-sm font-medium max-sm:w-full bg-error text-error-fg border-error hover:opacity-85"
					onclick={onConfirm}
				>
					{confirmText}
				</button>
			</div>
		</div>
	</div>
{/if}
