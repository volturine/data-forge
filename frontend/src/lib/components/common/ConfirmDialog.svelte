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
	<div class="backdrop" role="presentation">
		<div
			class="dialog"
			role="dialog"
			aria-modal="true"
			aria-labelledby="dialog-title"
			aria-describedby="dialog-message"
			tabindex="-1"
			bind:this={dialogRef}
		>
			<div class="dialog-header">
				<h2 id="dialog-title">{title}</h2>
				<button class="close-btn" onclick={onCancel} aria-label="Close dialog">
					<X size={16} />
				</button>
			</div>

			<div class="dialog-body">
				<p id="dialog-message">{message}</p>
			</div>

			<div class="dialog-footer">
				<button class="btn btn-cancel" onclick={onCancel}>
					{cancelText}
				</button>
				<button class="btn btn-confirm" onclick={onConfirm}>
					{confirmText}
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.backdrop {
		position: fixed;
		inset: 0;
		background-color: var(--overlay-bg);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 1000;
		padding: var(--space-4);
		animation: fadeIn var(--transition);
	}
	@keyframes fadeIn {
		from {
			opacity: 0;
		}
		to {
			opacity: 1;
		}
	}
	.dialog {
		background-color: var(--dialog-bg);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		box-shadow: var(--dialog-shadow);
		max-width: 400px;
		width: 100%;
		animation: slideIn var(--transition);
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
	.dialog:focus {
		outline: none;
	}
	.dialog-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-4);
		border-bottom: 1px solid var(--border-primary);
	}
	.dialog-header h2 {
		margin: 0;
		font-size: var(--text-base);
		font-weight: 600;
		color: var(--fg-primary);
	}
	.close-btn {
		background: transparent;
		border: none;
		padding: var(--space-1);
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: var(--radius-sm);
		color: var(--fg-muted);
		transition: all var(--transition);
	}
	.close-btn:hover {
		background-color: var(--bg-hover);
		color: var(--fg-primary);
	}
	.dialog-body {
		padding: var(--space-6);
	}
	.dialog-body p {
		margin: 0;
		font-size: var(--text-sm);
		line-height: 1.6;
		color: var(--fg-secondary);
	}
	.dialog-footer {
		display: flex;
		justify-content: flex-end;
		gap: var(--space-3);
		padding: var(--space-4);
		border-top: 1px solid var(--border-primary);
	}
	.btn {
		border: 1px solid transparent;
		border-radius: var(--radius-sm);
		padding: var(--space-2) var(--space-4);
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		font-weight: 500;
		cursor: pointer;
		transition: all var(--transition);
	}
	.btn-cancel {
		background-color: transparent;
		color: var(--fg-primary);
		border-color: var(--border-secondary);
	}
	.btn-cancel:hover {
		background-color: var(--bg-hover);
	}
	.btn-confirm {
		background-color: var(--error-bg);
		color: var(--error-fg);
		border-color: var(--error-border);
	}
	.btn-confirm:hover {
		opacity: 0.85;
	}
	@media (max-width: 640px) {
		.dialog {
			max-width: 100%;
		}
		.dialog-footer {
			flex-direction: column-reverse;
		}
		.btn {
			width: 100%;
		}
	}
</style>
