<script lang="ts">
	import { X } from 'lucide-svelte';
	import BaseModal from '$lib/components/ui/BaseModal.svelte';
	import PanelHeader from '$lib/components/ui/PanelHeader.svelte';
	import PanelFooter from '$lib/components/ui/PanelFooter.svelte';
	import { css } from '$lib/styles/panda';

	interface Props {
		show: boolean;
		heading: string;
		message: string;
		confirmText?: string;
		cancelText?: string;
		onConfirm: () => void;
		onCancel: () => void;
	}

	let {
		show,
		heading,
		message,
		confirmText = 'Confirm',
		cancelText = 'Cancel',
		onConfirm,
		onCancel
	}: Props = $props();

	let confirmRef = $state<HTMLButtonElement>();

	function handleKeydown(e: KeyboardEvent) {
		if (!show) return;
		if (e.key !== 'Enter') return;
		if (document.activeElement !== confirmRef) return;
		e.preventDefault();
		onConfirm();
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<BaseModal
	open={show}
	onClose={onCancel}
	closeOnEscape={true}
	closeOnBackdrop={true}
	panelClass={css({
		width: 'full',
		maxWidth: 'panel',
		overflow: 'hidden',
		borderWidth: '1',
		_focus: { outline: 'none' },
		smDown: { maxWidth: 'full' },
		backgroundColor: 'bg.primary'
	})}
	ariaLabelledby="dialog-title"
	ariaDescribedby="dialog-message"
	{content}
/>

{#snippet content()}
	<PanelHeader>
		{#snippet title()}
			<h2 id="dialog-title" class={css({ margin: '0', fontSize: 'md', fontWeight: 'semibold' })}>
				{heading}
			</h2>
		{/snippet}
		{#snippet actions()}
			<button
				class={css({
					display: 'flex',
					cursor: 'pointer',
					alignItems: 'center',
					justifyContent: 'center',
					borderStyle: 'none',
					backgroundColor: 'transparent',
					padding: '1',
					color: 'fg.muted',
					_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
				})}
				onclick={onCancel}
				aria-label="Close dialog"
				type="button"
			>
				<X size={16} />
			</button>
		{/snippet}
	</PanelHeader>

	<div class={css({ padding: '6' })}>
		<p
			id="dialog-message"
			class={css({ margin: '0', fontSize: 'sm', lineHeight: 'relaxed', color: 'fg.secondary' })}
		>
			{message}
		</p>
	</div>

	<PanelFooter>
		<button
			class={css({
				borderWidth: '1',
				backgroundColor: 'transparent',
				color: 'fg.primary',
				smDown: { width: 'full' },
				'&:hover:not(:disabled)': { backgroundColor: 'bg.hover', color: 'fg.secondary' }
			})}
			onclick={onCancel}
			type="button"
		>
			{cancelText}
		</button>
		<button
			bind:this={confirmRef}
			class={css({
				borderWidth: '1',
				backgroundColor: 'bg.error',
				color: 'fg.error',
				borderColor: 'border.error',
				smDown: { width: 'full' },
				'&:hover:not(:disabled)': { opacity: '0.85' }
			})}
			onclick={onConfirm}
			type="button"
		>
			{confirmText}
		</button>
	</PanelFooter>
{/snippet}
