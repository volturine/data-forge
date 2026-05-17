import { browser } from '$app/environment';
import { idbGet, idbSet } from '$lib/utils/indexeddb';
import { uuid } from '$lib/utils/uuid';

export interface Fingerprint {
	screen: string;
	timezone: string;
	language: string;
	platform: string;
}

let clientIdValue = '';

async function initClientId(): Promise<void> {
	if (!browser) return;
	const existing = await idbGet<string>('client_id');
	if (existing) {
		clientIdValue = existing;
		return;
	}
	const id = uuid();
	clientIdValue = id;
	await idbSet('client_id', id);
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
