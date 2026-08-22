<script lang="ts">
	import BaseModal from '$lib/components/ui/BaseModal.svelte';
	import { X } from '@lucide/svelte';
	import { css, button } from '$lib/styles/panda';

	interface Props {
		open: boolean;
		description: string | null;
		editorReadOnly: boolean;
		onSave: (description: string | null) => void;
		onClose: () => void;
	}

	let { open, description, editorReadOnly, onSave, onClose }: Props = $props();

	let descriptionDraft = $state('');

	$effect(() => {
		if (open) {
			descriptionDraft = description ?? '';
		}
	});

	function closeDescriptionModal() {
		onClose();
		descriptionDraft = '';
	}

	function saveDescriptionDraft() {
		if (editorReadOnly || !open) return;
		const next = descriptionDraft.trim() || null;
		onSave(next);
		closeDescriptionModal();
	}
</script>

{#snippet descriptionModalContent()}
	<div
		class={css({
			display: 'flex',
			justifyContent: 'space-between',
			alignItems: 'center',
			paddingX: '4',
			paddingY: '3',
			borderBottomWidth: '1',
			'& h2': { margin: '0', fontSize: 'md', color: 'fg.primary' }
		})}
	>
		<h2 id="analysis-description-title">Edit description</h2>
		<button
			class={css({
				background: 'transparent',
				border: 'none',
				color: 'fg.muted',
				cursor: 'pointer',
				fontSize: 'xl',
				padding: '1',
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'center',
				transitionProperty: 'color, background-color',
				transitionDuration: 'normal',
				_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
			})}
			onclick={closeDescriptionModal}
			aria-label="Close description editor"
		>
			<X size={16} />
		</button>
	</div>
	<div class={css({ display: 'grid', gap: '3', padding: '4' })}>
		<p class={css({ margin: '0', fontSize: 'sm', color: 'fg.tertiary' })}>
			Add context for collaborators, saved versions, and your future self.
		</p>
		<textarea
			rows="5"
			class={css({
				width: 'full',
				borderWidth: '1',
				backgroundColor: 'bg.primary',
				paddingX: '3',
				paddingY: '2',
				fontSize: 'sm',
				resize: 'vertical'
			})}
			bind:value={descriptionDraft}
			placeholder="What is this analysis for?"
			data-testid="analysis-description-input"
		></textarea>
	</div>
	<div
		class={css({
			paddingX: '4',
			paddingY: '3',
			borderTopWidth: '1',
			display: 'flex',
			justifyContent: 'flex-end',
			gap: '2'
		})}
	>
		<button class={button({ variant: 'secondary' })} onclick={closeDescriptionModal} type="button"
			>Cancel</button
		>
		<button class={button({ variant: 'primary' })} onclick={saveDescriptionDraft} type="button"
			>Apply</button
		>
	</div>
{/snippet}

<BaseModal
	{open}
	onClose={closeDescriptionModal}
	closeOnEscape={true}
	closeOnBackdrop={true}
	panelClass={css({
		width: 'min(560px, 92vw)',
		maxHeight: '70vh',
		backgroundColor: 'bg.primary',
		borderWidth: '1',
		display: 'flex',
		flexDirection: 'column',
		_focus: { outline: 'none' }
	})}
	ariaLabelledby="analysis-description-title"
	content={descriptionModalContent}
/>
