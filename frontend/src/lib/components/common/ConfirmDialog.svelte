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
		class="fixed inset-0 z-[1000] flex animate-[fadeIn_160ms_ease] items-center justify-center p-4 bg-[var(--overlay-bg)]"
		role="presentation"
	>
		<div
			class="w-full max-w-[400px] animate-[slideIn_160ms_ease] overflow-hidden rounded-sm border max-sm:max-w-full bg-[var(--dialog-bg)] border-[var(--border-primary)] shadow-[var(--dialog-shadow)] focus:outline-none"
			role="dialog"
			aria-modal="true"
			aria-labelledby="dialog-title"
			aria-describedby="dialog-message"
			tabindex="-1"
			bind:this={dialogRef}
		>
			<div class="flex items-center justify-between border-b p-4 border-[var(--border-primary)]">
				<h2 id="dialog-title" class="m-0 text-base font-semibold text-[var(--fg-primary)]">
					{title}
				</h2>
				<button
					class="flex cursor-pointer items-center justify-center rounded-sm border-none bg-transparent p-1 transition-all text-[var(--fg-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--fg-primary)]"
					onclick={onCancel}
					aria-label="Close dialog"
				>
					<X size={16} />
				</button>
			</div>

			<div class="p-6">
				<p id="dialog-message" class="m-0 text-sm leading-relaxed text-[var(--fg-secondary)]">
					{message}
				</p>
			</div>

			<div
				class="flex justify-end gap-3 border-t p-4 max-sm:flex-col-reverse border-[var(--border-primary)]"
			>
				<button
					class="cursor-pointer rounded-sm border bg-transparent px-4 py-2 font-mono text-sm font-medium transition-all max-sm:w-full text-[var(--fg-primary)] border-[var(--border-secondary)] hover:bg-[var(--bg-hover)]"
					onclick={onCancel}
				>
					{cancelText}
				</button>
				<button
					class="cursor-pointer rounded-sm border px-4 py-2 font-mono text-sm font-medium transition-all max-sm:w-full bg-[var(--error-bg)] text-[var(--error-fg)] border-[var(--error-border)] hover:opacity-85"
					onclick={onConfirm}
				>
					{confirmText}
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	@keyframes fadeIn {
		from {
			opacity: 0;
		}
		to {
			opacity: 1;
		}
	}

	@keyframes slideIn {
		from {
			transform: translateY(-10px);
			opacity: 0;
		}
		to {
			transform: translateY(0);
			opacity: 1;
		}
	}
</style>
