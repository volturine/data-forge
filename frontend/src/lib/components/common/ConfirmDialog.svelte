<script lang="ts">
	import { X } from 'lucide-svelte';
	import BaseModal from '$lib/components/ui/BaseModal.svelte';

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

	function handleKeydown(e: KeyboardEvent) {
		if (!show) return;
		if (e.key === 'Enter') {
			e.preventDefault();
			onConfirm();
		}
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<BaseModal
	open={show}
	onClose={onCancel}
	closeOnEscape={true}
	closeOnBackdrop={true}
	panelClass="w-full max-w-100 animate-slide-up overflow-hidden border max-sm:max-w-full bg-dialog border-tertiary focus:outline-none"
	ariaLabelledby="dialog-title"
	ariaDescribedby="dialog-message"
	content={content}
/>

{#snippet content()}
	<div class="flex items-center justify-between border-b p-4 border-tertiary">
		<h2 id="dialog-title" class="m-0 text-base font-semibold text-fg-primary">
			{title}
		</h2>
		<button
			class="flex cursor-pointer items-center justify-center border-none bg-transparent p-1 text-fg-muted hover:bg-hover hover:text-fg-primary"
			onclick={onCancel}
			aria-label="Close dialog"
			type="button"
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
			type="button"
		>
			{cancelText}
		</button>
		<button
			class="cursor-pointer border px-4 py-2 font-mono text-sm font-medium max-sm:w-full bg-error text-error-fg border-error hover:opacity-85"
			onclick={onConfirm}
			type="button"
		>
			{confirmText}
		</button>
	</div>
{/snippet}
