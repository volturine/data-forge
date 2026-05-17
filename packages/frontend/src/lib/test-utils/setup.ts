import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { overlayStack } from '$lib/stores/overlay.svelte';

/**
 * Install the same capture-phase Escape / outside-click arbiter that
 * +layout.svelte provides in the real app.  Without this, isolated
 * component tests that use `overlayStack.action` cannot dispatch
 * Escape or outside-click events through the stack.
 */
function onKeydown(event: KeyboardEvent) {
	if (event.key !== 'Escape') return;
	if (overlayStack.handleEscape()) {
		event.preventDefault();
		event.stopImmediatePropagation();
	}
}

function onMousedown(event: MouseEvent) {
	const target = event.target as Node | null;
	if (!target) return;
	overlayStack.handleOutsideClick(target);
}

window.addEventListener('keydown', onKeydown, true);
window.addEventListener('mousedown', onMousedown, true);

afterEach(() => {
	// Drain any overlay entries leaked by unmounted components
	for (const entry of [...overlayStack.stack]) {
		overlayStack.unregister(entry.id);
	}
});
