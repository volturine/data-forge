import { browser } from '$app/env';
import { idbGet, idbSet } from '#lib/utils/indexeddb.js';
import { uuid } from '#lib/utils/uuid.js';

export interface Fingerprint {
	screen: string;
	timezone: string;
	language: string;
	platform: string;
}

let clientIdValue = '';
let editorClientIdValue = '';

const EDITOR_CLIENT_ID_KEY = 'dataforge_editor_client_id';

/** Stable for one browser tab so opening an analysis elsewhere cannot take its lock. */
export function getEditorClientId(): string {
	if (!browser) return '';
	if (editorClientIdValue) return editorClientIdValue;

	try {
		const existing = window.sessionStorage.getItem(EDITOR_CLIENT_ID_KEY);
		if (existing) {
			editorClientIdValue = existing;
			return existing;
		}
		editorClientIdValue = uuid();
		window.sessionStorage.setItem(EDITOR_CLIENT_ID_KEY, editorClientIdValue);
		return editorClientIdValue;
	} catch {
		editorClientIdValue = uuid();
		return editorClientIdValue;
	}
}

let clientIdInitialization: Promise<void> | null = null;

function initClientId(): Promise<void> {
	if (!browser) return Promise.resolve();
	if (clientIdInitialization) return clientIdInitialization;
	if (clientIdValue) return Promise.resolve();

	const initialization = Promise.resolve().then(async () => {
		const existing = await idbGet<string>('client_id');
		if (existing) {
			clientIdValue = existing;
			return;
		}
		const id = uuid();
		clientIdValue = id;
		await idbSet('client_id', id);
	});
	clientIdInitialization = initialization;
	const clear = (): void => {
		if (clientIdInitialization === initialization) clientIdInitialization = null;
	};
	void initialization.then(clear, clear);
	return initialization;
}

// Generate a hash from fingerprint for server storage
export function hashFingerprint(fp: Fingerprint): string {
	const str = `${fp.screen}|${fp.timezone}|${fp.language}|${fp.platform}`;
	let hash = 0;
	for (let i = 0; i < str.length; i++) {
		const char = str.charCodeAt(i);
		hash = ((hash << 5) - hash + char) | 0;
	}
	return hash.toString(16);
}

// Client ID - persisted in IndexedDB
if (browser) {
	void initClientId();
}

// Fingerprint
const fingerprintValue: Fingerprint = browser
	? {
			screen: `${screen.width}x${screen.height}`,
			timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
			language: navigator.language,
			platform: navigator.platform
		}
	: { screen: '', timezone: '', language: '', platform: '' };

// Get current client identity for API calls
export function getClientIdentity(): { clientId: string; clientSignature: string } {
	if (!clientIdValue && browser) {
		void initClientId();
	}
	return {
		clientId: clientIdValue,
		clientSignature: hashFingerprint(fingerprintValue)
	};
}
