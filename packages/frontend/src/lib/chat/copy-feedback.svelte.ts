import { onDestroy } from 'svelte';

export interface CopyFeedback {
	readonly copiedId: string | null;
	copy(text: string, id: string): Promise<void>;
}

/** Briefly marks the last copied item so its button can confirm. Call during component init. */
export function createCopyFeedback(resetAfterMs: number): CopyFeedback {
	let copiedId = $state<string | null>(null);
	let timer: ReturnType<typeof setTimeout> | null = null;

	onDestroy(() => {
		if (timer) clearTimeout(timer);
	});

	return {
		get copiedId() {
			return copiedId;
		},
		async copy(text: string, id: string) {
			await navigator.clipboard.writeText(text).catch(() => {});
			copiedId = id;
			if (timer) clearTimeout(timer);
			timer = setTimeout(() => {
				timer = null;
				copiedId = null;
			}, resetAfterMs);
		}
	};
}
