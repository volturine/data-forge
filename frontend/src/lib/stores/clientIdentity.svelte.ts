import { browser } from '$app/environment';
import { idbGet, idbSet } from '$lib/utils/indexeddb';

export interface Fingerprint {
	screen: string;
	timezone: string;
	language: string;
	platform: string;
}

// Generate UUID that works in both secure and non-secure contexts
function generateUUID(): string {
	// Use crypto.randomUUID if available (secure contexts)
	if (typeof crypto !== 'undefined' && crypto.randomUUID) {
		return crypto.randomUUID();
	}

	// Fallback for non-secure contexts (HTTP)
	return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
		const r = (Math.random() * 16) | 0;
		const v = c === 'x' ? r : (r & 0x3) | 0x8;
		return v.toString(16);
	});
}

let clientIdValue = '';

async function initClientId(): Promise<void> {
	if (!browser) return;
	const existing = await idbGet<string>('lock_client_id');
	if (existing) {
		clientIdValue = existing;
		return;
	}
	const id = generateUUID();
	clientIdValue = id;
	await idbSet('lock_client_id', id);
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
