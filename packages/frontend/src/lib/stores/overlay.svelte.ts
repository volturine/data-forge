/**
 * Shared overlay stack for coordinating Escape / outside-click handling
 * across popups, modals, and panels.
 *
 * Only the topmost registered layer handles Escape and outside-click events.
 * Components register when they open and unregister when they close.
 */

let nextId = 0;

export interface OverlayEntry {
	id: number;
	onEscape?: () => void;
	onOutsideClick?: (target: Node) => void;
	/** When true, outside clicks are absorbed even without an onOutsideClick handler. */
	modal?: boolean;
}

export type OverlayConfig = Omit<OverlayEntry, 'id'>;

/**
 * Plain array — reassigned to trigger Svelte reactivity.
 * No Map/Set to satisfy svelte/prefer-svelte-reactivity.
 */
let stack = $state<OverlayEntry[]>([]);

function register(entry: OverlayConfig): number {
	const id = nextId++;
	stack = [...stack, { ...entry, id }];
	return id;
}

function unregister(id: number): void {
	stack = stack.filter((e) => e.id !== id);
}

function handleEscape(): boolean {
	for (let i = stack.length - 1; i >= 0; i--) {
		const entry = stack[i];
		if (entry.onEscape) {
			entry.onEscape();
			return true;
		}
	}
	return false;
}

/**
 * Dispatch outside-click to the topmost layer that cares.
 * If the topmost layer is modal (absorbs clicks), stop even without a handler.
 */
function handleOutsideClick(target: Node): boolean {
	for (let i = stack.length - 1; i >= 0; i--) {
		const entry = stack[i];
		if (entry.onOutsideClick) {
			entry.onOutsideClick(target);
			return true;
		}
		if (entry.modal) {
			return true;
		}
	}
	return false;
}

/**
 * Svelte action that registers an overlay entry on mount and unregisters on destroy.
 * Replaces per-component `$effect` blocks whose only job is register/unregister.
 *
 * Usage: `use:overlayAction={{ onEscape: close, modal: true }}`
 */
function overlayAction(_node: HTMLElement, config: OverlayConfig) {
	const id = register(config);
	return {
		update(next: OverlayConfig) {
			stack = stack.map((e) => (e.id === id ? { ...next, id } : e));
		},
		destroy() {
			unregister(id);
		}
	};
}

export const overlayStack = {
	get stack() {
		return stack;
	},
	register,
	unregister,
	handleEscape,
	handleOutsideClick,
	action: overlayAction
};
