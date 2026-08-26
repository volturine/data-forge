import { createAsyncGate } from '$lib/utils/async-gate';
import { idbGet, idbSet, idbDelete } from '$lib/utils/indexeddb';
import { ensureTabDefaults } from '$lib/utils/analysis-tab';
import type { AnalysisTab } from '$lib/types/analysis';
import type { EngineDefaults, EngineResourceConfig } from '$lib/types/compute';

export type AnalysisDraftSnapshot = {
	analysisId: string | null;
	version?: string | null;
	tabs: AnalysisTab[];
	activeTabId: string | null;
	resourceConfig: EngineResourceConfig | null;
	engineDefaults: EngineDefaults | null;
	selectedStepId: string | null;
	leftPaneCollapsed: boolean;
	rightPaneCollapsed: boolean;
	configPosition?: 'right' | 'bottom';
	bottomPaneHeight?: number;
};

export type DraftControllerDeps = {
	getStorageKey: () => string | null;
	getAnalysisId: () => string | null;
	// Lock/read-only conditions other than draftLoaded itself.
	blockedFromHydration: () => boolean;
	readOnly: () => boolean;
	hasTabs: () => boolean;
	getServerVersion: () => string | null;
	buildPayload: () => AnalysisDraftSnapshot;
	applyDraft: (draft: AnalysisDraftSnapshot) => void;
};

export function createDraftController(deps: DraftControllerDeps) {
	let draftLoaded = $state(false);
	let draftTimer: number | null = null;
	const draftLoadGate = createAsyncGate();

	function markLoaded() {
		draftLoaded = true;
	}

	function hydrate(): void {
		const storageKey = deps.getStorageKey();
		if (!storageKey || draftLoaded || deps.blockedFromHydration()) return;
		if (!deps.hasTabs()) return;
		const analysisId = deps.getAnalysisId();
		const currentStorageKey = storageKey;
		const currentAnalysisId = analysisId;
		const serverVersion = deps.getServerVersion();
		if (!serverVersion) {
			draftLoaded = true;
			return;
		}

		if (!analysisId) {
			void idbDelete(storageKey);
			draftLoaded = true;
			return;
		}

		const token = draftLoadGate.issue();
		void idbGet<string>(currentStorageKey)
			.then((raw) => {
				if (!draftLoadGate.isCurrent(token)) return;
				if (
					deps.getStorageKey() !== currentStorageKey ||
					deps.getAnalysisId() !== currentAnalysisId
				)
					return;
				if (!raw) {
					draftLoaded = true;
					return;
				}
				let parsed: AnalysisDraftSnapshot;
				try {
					parsed = JSON.parse(raw) as typeof parsed;
				} catch {
					void idbDelete(currentStorageKey);
					draftLoaded = true;
					return;
				}
				if (parsed.analysisId !== currentAnalysisId) {
					draftLoaded = true;
					return;
				}
				if ((parsed.version ?? null) !== serverVersion) {
					void idbDelete(currentStorageKey);
					draftLoaded = true;
					return;
				}
				if (!Array.isArray(parsed.tabs)) {
					draftLoaded = true;
					return;
				}
				parsed.tabs = parsed.tabs.map((tab, index) => ensureTabDefaults(tab, index));
				deps.applyDraft(parsed);
				draftLoaded = true;
			})
			.catch(() => {
				if (draftLoadGate.isCurrent(token)) draftLoaded = true;
			});
	}

	function schedulePersist(): void {
		const storageKey = deps.getStorageKey();
		if (!storageKey || !draftLoaded || deps.readOnly()) return;
		if (!deps.hasTabs()) return;
		const payload = deps.buildPayload();
		if (draftTimer) window.clearTimeout(draftTimer);
		draftTimer = window.setTimeout(() => {
			void idbSet(storageKey, JSON.stringify(payload));
			draftTimer = null;
		}, 400);
	}

	function flush(): void {
		if (draftTimer) window.clearTimeout(draftTimer);
		draftTimer = null;
		draftLoadGate.invalidate();
	}

	return {
		get draftLoaded() {
			return draftLoaded;
		},
		markLoaded,
		hydrate,
		schedulePersist,
		flush,
		reset() {
			draftLoaded = false;
			flush();
		},
		invalidate: () => draftLoadGate.invalidate()
	};
}
