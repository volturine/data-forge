import { SvelteMap } from 'svelte/reactivity';
import { idbGet, idbSet } from '$lib/utils/indexeddb';

export class PreviewState {
	runs = $state(new SvelteMap<string, boolean>());
	paused = $state(false);
	namespace = $state<string | null>(null);

	async initialize(namespace: string): Promise<void> {
		if (this.namespace === namespace) return;
		this.runs.clear();
		this.namespace = namespace;
		const stored = await idbGet<Array<[string, boolean]>>(`analysis_preview_runs:${namespace}`);
		if (!stored) return;
		for (const [key, value] of stored) this.runs.set(key, value);
	}

	setRun(key: string, value: boolean): void {
		this.runs.set(key, value);
		if (this.namespace) {
			void idbSet(`analysis_preview_runs:${this.namespace}`, Array.from(this.runs.entries()));
		}
	}

	reset(): void {
		this.runs.clear();
		this.paused = false;
		this.namespace = null;
	}
}
