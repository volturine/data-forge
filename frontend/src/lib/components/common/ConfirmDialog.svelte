<script lang="ts">
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

	function handleBackdropClick(e: MouseEvent) {
		if (e.target === e.currentTarget) {
			onCancel();
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
	<div class="backdrop" onclick={handleBackdropClick} role="presentation">
		<div
			class="dialog"
			role="dialog"
			aria-modal="true"
			aria-labelledby="dialog-title"
			aria-describedby="dialog-message"
			tabindex="-1"
			bind:this={dialogEl}
		>
			<div class="dialog-header">
				<h2 id="dialog-title">{title}</h2>
				<button class="close-btn" onclick={onCancel} aria-label="Close dialog">
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
						<path d="M18 6L6 18M6 6l12 12" stroke-width="2" />
					</svg>
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
		background: rgba(0, 0, 0, 0.5);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 1000;
		padding: 16px;
		animation: fadeIn 0.2s ease-out;
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
		background: white;
		border-radius: 12px;
		box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
		max-width: 500px;
		width: 100%;
		animation: slideIn 0.2s ease-out;
	}

	@keyframes slideIn {
		from {
			transform: translateY(-20px);
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
		padding: 20px 24px;
		border-bottom: 1px solid #e0e0e0;
	}

	.dialog-header h2 {
		margin: 0;
		font-size: 20px;
		font-weight: 600;
		color: #212121;
	}

	.close-btn {
		background: none;
		border: none;
		padding: 6px;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: 4px;
		color: #757575;
		transition: all 0.2s;
	}

	.close-btn:hover {
		background: #f5f5f5;
		color: #424242;
	}

	.close-btn svg {
		width: 20px;
		height: 20px;
		stroke-width: 2;
	}

	.dialog-body {
		padding: 24px;
	}

	.dialog-body p {
		margin: 0;
		font-size: 15px;
		line-height: 1.6;
		color: #424242;
	}

	.dialog-footer {
		display: flex;
		justify-content: flex-end;
		gap: 12px;
		padding: 16px 24px;
		border-top: 1px solid #e0e0e0;
	}

	.btn {
		border: none;
		border-radius: 8px;
		padding: 10px 20px;
		font-size: 15px;
		font-weight: 500;
		cursor: pointer;
		transition: all 0.2s;
	}

	.btn-cancel {
		background: #f5f5f5;
		color: #424242;
	}

	.btn-cancel:hover {
		background: #e0e0e0;
	}

	.btn-confirm {
		background: #d32f2f;
		color: white;
	}

	.btn-confirm:hover {
		background: #b71c1c;
		box-shadow: 0 2px 8px rgba(211, 47, 47, 0.3);
	}

	@media (max-width: 640px) {
		.dialog {
			max-width: 100%;
			margin: 16px;
		}

		.dialog-header,
		.dialog-body,
		.dialog-footer {
			padding: 16px;
		}

		.dialog-footer {
			flex-direction: column-reverse;
		}

		.btn {
			width: 100%;
		}
	}
</style>
