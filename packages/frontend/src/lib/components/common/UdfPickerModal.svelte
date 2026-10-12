<script lang="ts">
	import { untrack } from 'svelte';
	import { X } from '@lucide/svelte';
	import type { Udf, UdfCreate } from '$lib/types/udf';
	import UdfEditor from '$lib/components/udfs/UdfEditor.svelte';
	import UdfLibrary from '$lib/components/udfs/UdfLibrary.svelte';
	import BaseModal from '$lib/components/ui/BaseModal.svelte';
	import PanelHeader from '$lib/components/ui/PanelHeader.svelte';
	import { css, button } from '$lib/styles/panda';

	interface Props {
		show: boolean;
		onSelect: (udf: Udf) => void;
		onClose: () => void;
		initialUdf?: Udf;
		initialDraft?: UdfCreate;
		onApply?: (draft: UdfCreate) => void;
	}

	const { show, onSelect, onClose, initialUdf, initialDraft, onApply }: Props = $props();
	type View = 'library' | 'editor';
	type DiscardIntent = 'close' | 'back' | null;

	let view = $state<View>(untrack(() => (initialUdf || initialDraft ? 'editor' : 'library')));
	let selectedUdf = $state(untrack(() => initialUdf));
	let selectedDraft = $state(untrack(() => initialDraft));
	let dirty = $state(false);
	let saving = $state(false);
	let discardIntent = $state<DiscardIntent>(null);

	function requestClose() {
		if (saving) return;
		if (dirty) {
			discardIntent = 'close';
			return;
		}
		resetToInitialView();
		onClose();
	}

	function requestBack() {
		if (saving) return;
		if (dirty) {
			discardIntent = 'back';
			return;
		}
		showLibrary();
	}

	function showLibrary() {
		view = 'library';
		selectedUdf = undefined;
		selectedDraft = undefined;
		dirty = false;
		discardIntent = null;
	}

	function resetToInitialView() {
		view = initialUdf || initialDraft ? 'editor' : 'library';
		selectedUdf = initialUdf;
		selectedDraft = initialDraft;
		dirty = false;
		discardIntent = null;
	}

	function confirmDiscard() {
		if (!discardIntent || saving) return;
		const intent = discardIntent;
		if (intent === 'back') {
			showLibrary();
			return;
		}
		resetToInitialView();
		onClose();
	}

	function cancelDiscard() {
		if (saving) return;
		discardIntent = null;
	}

	function handleCreate() {
		selectedUdf = undefined;
		selectedDraft = undefined;
		dirty = false;
		discardIntent = null;
		view = 'editor';
	}

	function handleEdit(udf: Udf) {
		selectedUdf = udf;
		selectedDraft = undefined;
		dirty = false;
		discardIntent = null;
		view = 'editor';
	}

	function handleSaved(udf: Udf) {
		showLibrary();
		onSelect(udf);
	}

	function handleApply(draft: UdfCreate) {
		if (saving) return;
		dirty = false;
		onApply?.(draft);
	}

	function focusHeading(node: HTMLHeadingElement, currentView: View) {
		node.tabIndex = -1;
		return {
			update(nextView: View) {
				if (nextView === currentView) return;
				currentView = nextView;
				node.focus();
			}
		};
	}

	function focusDiscard(node: HTMLElement): () => void {
		const previousFocus = document.activeElement;
		node.querySelector<HTMLButtonElement>('button')?.focus({ preventScroll: true });
		return () => {
			if (previousFocus instanceof HTMLElement && previousFocus.isConnected) {
				previousFocus.focus({ preventScroll: true });
			}
		};
	}
</script>

<BaseModal
	open={show}
	{content}
	onClose={requestClose}
	closeOnEscape={true}
	closeOnBackdrop={true}
	size="large"
	ariaLabelledby="udf-modal-title"
/>

{#snippet content()}
	<PanelHeader>
		{#snippet title()}
			<h2 id="udf-modal-title" class={css({ margin: '0', fontSize: 'md' })} use:focusHeading={view}>
				{view === 'library' ? 'UDF Library' : selectedUdf ? 'Edit UDF' : 'New UDF'}
			</h2>
		{/snippet}
		{#snippet actions()}
			<button
				class={css({
					background: 'transparent',
					border: 'none',
					color: 'fg.muted',
					cursor: 'pointer',
					padding: '1',
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
					_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' },
					_disabled: { opacity: '0.5', cursor: 'not-allowed' }
				})}
				onclick={requestClose}
				aria-label="Close UDF dialog"
				disabled={saving}
				type="button"
			>
				<X size={16} />
			</button>
		{/snippet}
	</PanelHeader>

	{#if discardIntent}
		<div
			role="alertdialog"
			aria-labelledby="udf-discard-heading"
			{@attach focusDiscard}
			class={css({
				display: 'flex',
				flexWrap: 'wrap',
				alignItems: 'center',
				justifyContent: 'space-between',
				gap: '3',
				margin: '4',
				padding: '4',
				borderWidth: '1',
				borderColor: 'border.warning',
				backgroundColor: 'bg.secondary'
			})}
		>
			<div>
				<h3 id="udf-discard-heading" class={css({ margin: '0', fontSize: 'sm' })}>
					Discard unsaved changes?
				</h3>
				<p class={css({ margin: '1 0 0', color: 'fg.tertiary', fontSize: 'sm' })}>
					Your edits will be lost if you leave the editor.
				</p>
			</div>
			<div class={css({ display: 'flex', gap: '2' })}>
				<button
					class={button({ variant: 'secondary' })}
					onclick={cancelDiscard}
					disabled={saving}
					type="button"
				>
					Keep editing
				</button>
				<button
					class={button({ variant: 'danger' })}
					onclick={confirmDiscard}
					disabled={saving}
					type="button"
				>
					Discard changes
				</button>
			</div>
		</div>
	{/if}

	{#if view === 'library'}
		<UdfLibrary {onSelect} onEdit={handleEdit} onCreate={handleCreate} />
	{:else}
		{#key selectedUdf?.id ?? (selectedDraft ? 'draft' : 'new')}
			<UdfEditor
				initialUdf={selectedUdf}
				initialDraft={selectedDraft}
				onSave={handleSaved}
				onBack={requestBack}
				onApply={selectedDraft && onApply ? handleApply : undefined}
				bind:dirty
				bind:saving
			/>
		{/key}
	{/if}
{/snippet}
