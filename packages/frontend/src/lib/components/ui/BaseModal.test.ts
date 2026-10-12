import { describe, test, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import BaseModal from './BaseModal.svelte';

const emptySnippet = createRawSnippet(() => ({
	render: () => '<span>modal content</span>'
}));

function renderModal(props: Record<string, unknown> = {}) {
	return render(BaseModal, {
		props: {
			open: true,
			content: emptySnippet,
			...props
		}
	});
}

describe('BaseModal', () => {
	describe('visibility', () => {
		test('renders dialog when open is true', () => {
			renderModal();
			expect(screen.getByRole('dialog')).toBeInTheDocument();
		});

		test('does not render dialog when open is false', () => {
			renderModal({ open: false });
			expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
		});
	});

	describe('aria attributes', () => {
		test('sets aria-modal true by default', () => {
			renderModal();
			expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true');
		});

		test('sets custom aria-labelledby', () => {
			renderModal({ ariaLabelledby: 'title-id' });
			expect(screen.getByRole('dialog')).toHaveAttribute('aria-labelledby', 'title-id');
		});

		test('sets custom aria-describedby', () => {
			renderModal({ ariaDescribedby: 'desc-id' });
			expect(screen.getByRole('dialog')).toHaveAttribute('aria-describedby', 'desc-id');
		});

		test('allows overriding role', () => {
			renderModal({ role: 'alertdialog' });
			expect(screen.getByRole('alertdialog')).toBeInTheDocument();
		});
	});

	describe('escape key', () => {
		test('calls onClose on Escape when closeOnEscape is true', async () => {
			const onClose = vi.fn();
			renderModal({ onClose });
			await fireEvent.keyDown(window, { key: 'Escape' });
			expect(onClose).toHaveBeenCalledOnce();
		});

		test('does not call onClose on Escape when closeOnEscape is false', async () => {
			const onClose = vi.fn();
			renderModal({ onClose, closeOnEscape: false });
			await fireEvent.keyDown(window, { key: 'Escape' });
			expect(onClose).not.toHaveBeenCalled();
		});

		test('ignores non-Escape keys', async () => {
			const onClose = vi.fn();
			renderModal({ onClose });
			await fireEvent.keyDown(window, { key: 'Enter' });
			expect(onClose).not.toHaveBeenCalled();
		});

		test('ignores Escape when modal is closed', async () => {
			const onClose = vi.fn();
			renderModal({ open: false, onClose });
			await fireEvent.keyDown(window, { key: 'Escape' });
			expect(onClose).not.toHaveBeenCalled();
		});
	});

	describe('backdrop click', () => {
		test('calls onClose on backdrop mousedown when closeOnBackdrop is true', async () => {
			const onClose = vi.fn();
			renderModal({ onClose });
			const overlay = screen.getByRole('dialog').parentElement!;
			await fireEvent.mouseDown(overlay);
			expect(onClose).toHaveBeenCalledOnce();
		});

		test('does not call onClose on backdrop mousedown when closeOnBackdrop is false', async () => {
			const onClose = vi.fn();
			renderModal({ onClose, closeOnBackdrop: false });
			const overlay = screen.getByRole('dialog').parentElement!;
			await fireEvent.mouseDown(overlay);
			expect(onClose).not.toHaveBeenCalled();
		});

		test('does not call onClose when clicking inside the panel', async () => {
			const onClose = vi.fn();
			renderModal({ onClose });
			const panel = screen.getByRole('dialog');
			await fireEvent.mouseDown(panel);
			expect(onClose).not.toHaveBeenCalled();
		});
	});

	describe('body scroll lock', () => {
		test('sets body overflow to hidden when open', () => {
			renderModal();
			expect(document.body.style.overflow).toBe('hidden');
		});

		test('restores body overflow when unmounted', () => {
			const { unmount } = renderModal();
			expect(document.body.style.overflow).toBe('hidden');
			unmount();
			expect(document.body.style.overflow).toBe('');
		});

		test('keeps scrolling locked until every nested modal closes', () => {
			const outer = renderModal();
			const inner = renderModal();
			outer.unmount();
			expect(document.body.style.overflow).toBe('hidden');
			inner.unmount();
			expect(document.body.style.overflow).toBe('');
		});

		test('preserves the original body overflow', () => {
			document.body.style.overflow = 'clip';
			const modal = renderModal();
			modal.unmount();
			expect(document.body.style.overflow).toBe('clip');
			document.body.style.overflow = '';
		});
	});

	describe('focus management', () => {
		test('focuses the requested search field and returns to the trigger', () => {
			const trigger = document.createElement('button');
			document.body.append(trigger);
			trigger.focus();
			const content = createRawSnippet(() => ({
				render: () => '<div><input id="modal-search" aria-label="Search" /></div>'
			}));
			const modal = renderModal({ content, initialFocus: '#modal-search' });
			expect(screen.getByRole('textbox', { name: 'Search' })).toHaveFocus();
			modal.unmount();
			expect(trigger).toHaveFocus();
			trigger.remove();
		});

		test('panel has tabindex -1 for programmatic focus', () => {
			renderModal();
			expect(screen.getByRole('dialog')).toHaveAttribute('tabindex', '-1');
		});

		test('wraps Tab and Shift-Tab inside the dialog', async () => {
			const content = createRawSnippet(() => ({
				render: () => '<div><button>First</button><button>Last</button></div>'
			}));
			renderModal({ content });
			const first = screen.getByRole('button', { name: 'First' });
			const last = screen.getByRole('button', { name: 'Last' });
			first.focus();
			await fireEvent.keyDown(first, { key: 'Tab', shiftKey: true });
			expect(last).toHaveFocus();
			await fireEvent.keyDown(last, { key: 'Tab' });
			expect(first).toHaveFocus();
		});

		test('restores focus to the trigger after closing', () => {
			const trigger = document.createElement('button');
			document.body.append(trigger);
			trigger.focus();
			const modal = renderModal();
			expect(screen.getByRole('dialog')).toHaveFocus();
			modal.unmount();
			expect(trigger).toHaveFocus();
			trigger.remove();
		});

		test('allows a nested dialog to take focus and restores the parent', () => {
			const outer = renderModal();
			const outerPanel = screen.getByRole('dialog');
			const inner = renderModal();
			expect(screen.getAllByRole('dialog')[1]).toHaveFocus();
			inner.unmount();
			expect(outerPanel).toHaveFocus();
			outer.unmount();
		});

		test('keeps focus out of the analysis behind the dialog', () => {
			const background = document.createElement('button');
			document.body.append(background);
			renderModal();
			background.focus();
			expect(screen.getByRole('dialog')).toHaveFocus();
			background.remove();
		});
	});
});
