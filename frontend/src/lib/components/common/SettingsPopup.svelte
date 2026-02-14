<script lang="ts">
	import { X, Mail, MessageCircle, Database, CheckCircle, XCircle } from 'lucide-svelte';
	import { configStore } from '$lib/stores/config.svelte';

	interface Props {
		open: boolean;
	}

	let { open = $bindable() }: Props = $props();

	const smtp = $derived(configStore.smtpEnabled);
	const telegram = $derived(configStore.telegramEnabled);
	const idb = $derived(configStore.publicIdbDebug);

	function close() {
		open = false;
	}

	function handleBackdropClick(e: MouseEvent) {
		if (e.target === e.currentTarget) close();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (!open) return;
		if (e.key === 'Escape') {
			e.preventDefault();
			close();
		}
	}

	function toggleIdb() {
		if (!configStore.config) return;
		configStore.config.public_idb_debug = !configStore.config.public_idb_debug;
	}

	// DOM side-effect: lock body scroll when modal is open — $derived can't perform DOM mutations
	$effect(() => {
		if (open) {
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

{#if open}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-overlay animate-fade-in"
		onclick={handleBackdropClick}
		onkeydown={(e) => {
			if (e.key === 'Enter' || e.key === ' ') {
				e.preventDefault();
				close();
			}
		}}
		role="button"
		tabindex="0"
		aria-label="Close settings"
	>
		<div
			class="w-full max-w-100 border animate-slide-up bg-dialog border-tertiary focus:outline-none"
			onclick={(e) => e.stopPropagation()}
			onkeydown={(e) => e.stopPropagation()}
			role="dialog"
			aria-modal="true"
			aria-labelledby="settings-title"
			tabindex="-1"
		>
			<!-- Header -->
			<div class="flex items-center justify-between border-b p-4 border-tertiary">
				<h2 id="settings-title" class="m-0 text-sm font-semibold text-fg-primary">Settings</h2>
				<button
					class="flex cursor-pointer items-center justify-center border-none bg-transparent p-1 text-fg-muted hover:bg-hover hover:text-fg-primary"
					onclick={close}
					aria-label="Close settings"
					type="button"
				>
					<X size={16} />
				</button>
			</div>

			<!-- Content -->
			<div class="flex flex-col gap-4 p-4">
				<!-- Notifications heading -->
				<span class="text-xs font-semibold uppercase tracking-wider text-fg-tertiary">
					Notifications
				</span>

				<!-- SMTP -->
				<div class="flex items-center justify-between border-b pb-4 border-tertiary">
					<div class="flex items-center gap-3">
						<Mail size={16} class="text-fg-secondary" />
						<div class="flex flex-col gap-0.5">
							<span class="text-sm font-medium text-fg-primary">SMTP</span>
							<span class="text-xs text-fg-tertiary">Email notifications</span>
						</div>
					</div>
					{#if smtp}
						<span
							class="flex items-center gap-1.5 rounded-sm px-2 py-1 text-xs font-medium bg-success text-success"
						>
							<CheckCircle size={12} />
							Configured
						</span>
					{:else}
						<span
							class="flex items-center gap-1.5 rounded-sm px-2 py-1 text-xs font-medium bg-error text-error"
						>
							<XCircle size={12} />
							Not configured
						</span>
					{/if}
				</div>

				<!-- Telegram -->
				<div class="flex items-center justify-between border-b pb-4 border-tertiary">
					<div class="flex items-center gap-3">
						<MessageCircle size={16} class="text-fg-secondary" />
						<div class="flex flex-col gap-0.5">
							<span class="text-sm font-medium text-fg-primary">Telegram</span>
							<span class="text-xs text-fg-tertiary">Bot notifications</span>
						</div>
					</div>
					{#if telegram}
						<span
							class="flex items-center gap-1.5 rounded-sm px-2 py-1 text-xs font-medium bg-success text-success"
						>
							<CheckCircle size={12} />
							Configured
						</span>
					{:else}
						<span
							class="flex items-center gap-1.5 rounded-sm px-2 py-1 text-xs font-medium bg-error text-error"
						>
							<XCircle size={12} />
							Not configured
						</span>
					{/if}
				</div>

				<!-- Debug heading -->
				<span class="text-xs font-semibold uppercase tracking-wider text-fg-tertiary">Debug</span>

				<!-- IndexedDB Debug -->
				<div class="flex items-center justify-between">
					<div class="flex items-center gap-3">
						<Database size={16} class="text-fg-secondary" />
						<div class="flex flex-col gap-0.5">
							<span class="text-sm font-medium text-fg-primary">IndexedDB Inspector</span>
							<span class="text-xs text-fg-tertiary">Show cache debug button in header</span>
						</div>
					</div>
					<button
						class="relative h-5 w-9 cursor-pointer rounded-full border-none transition-colors"
						class:bg-accent-primary={idb}
						class:bg-tertiary={!idb}
						onclick={toggleIdb}
						type="button"
						role="switch"
						aria-checked={idb}
						aria-label="Toggle IndexedDB inspector"
					>
						<span
							class="absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-fg-primary transition-transform"
							class:translate-x-4={idb}
						></span>
					</button>
				</div>
			</div>

			<!-- Footer -->
			<div class="border-t p-4 border-tertiary">
				<p class="m-0 text-xs text-fg-tertiary">
					SMTP and Telegram settings are configured via environment variables and cannot be changed
					here.
				</p>
			</div>
		</div>
	</div>
{/if}
