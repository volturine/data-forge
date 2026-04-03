import fs from 'node:fs';
import path from 'node:path';
import {
	API_BASE,
	AUTH_FILE,
	E2E_DISPLAY_NAME,
	E2E_EMAIL,
	E2E_PASSWORD,
	deleteAccount,
	login,
	parseSessionToken,
	readStoredSessionToken
} from './utils/api.js';

const port = process.env.FRONTEND_PORT || '3000';
const origin = `http://localhost:${port}`;

function buildStorageState(
	sessionToken: string | undefined,
	apiOrigin: string
): Record<string, unknown> {
	const cookies = sessionToken
		? [
				{
					name: 'session_token',
					value: sessionToken,
					domain: 'localhost',
					path: '/',
					expires: -1,
					httpOnly: true,
					secure: false,
					sameSite: 'Lax'
				}
			]
		: [];

	return {
		cookies,
		origins: [
			{
				origin: apiOrigin,
				localStorage: []
			},
			{
				origin,
				localStorage: [{ name: 'debug:prefer-http', value: 'true' }]
			}
		]
	};
}

async function register(): Promise<string> {
	const resp = await fetch(`${API_BASE}/auth/register`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			email: E2E_EMAIL,
			password: E2E_PASSWORD,
			display_name: E2E_DISPLAY_NAME
		})
	});
	if (!resp.ok) {
		throw new Error(`E2E register failed: ${resp.status} ${await resp.text()}`);
	}
	const token = parseSessionToken(resp);
	if (!token) {
		throw new Error('E2E register succeeded but no session_token cookie received');
	}
	return token;
}

/**
 * Ensure no leftover E2E account exists before registering fresh.
 *
 * Strategy:
 * 1. Try deleting via stored session token.
 * 2. If unauthenticated or no stored token, try login to get a fresh token, then delete.
 * 3. If login returns invalid_credentials, account doesn't exist — clean state confirmed.
 * 4. Forbidden (default user) and unexpected errors are fatal.
 */
async function ensureCleanState(): Promise<void> {
	const stored = readStoredSessionToken();

	if (stored) {
		const outcome = await deleteAccount(stored);
		if (outcome === 'deleted') return;
		if (outcome === 'forbidden') {
			throw new Error('[setup] cannot delete default/protected account — fix test config');
		}
		if (outcome === 'error') {
			throw new Error('[setup] unexpected error deleting account with stored token');
		}
		// unauthenticated — stored token is stale, fall through to login path
	}

	const result = await login();
	if (result.status === 'invalid_credentials') return;
	if (result.status === 'error') {
		throw new Error(`[setup] login probe failed with status ${result.code}`);
	}

	const outcome = await deleteAccount(result.token);
	if (outcome === 'deleted') return;
	if (outcome === 'forbidden') {
		throw new Error('[setup] cannot delete default/protected account — fix test config');
	}
	throw new Error(
		`[setup] delete after login returned '${outcome}' — cannot establish clean state`
	);
}

export default async function globalSetup(): Promise<void> {
	fs.mkdirSync(path.dirname(AUTH_FILE), { recursive: true });

	const configResp = await fetch(`${API_BASE}/config`);
	const authRequired = configResp.ok
		? ((await configResp.json()) as { auth_required?: boolean }).auth_required !== false
		: true;

	let sessionToken: string | undefined;

	if (authRequired) {
		await ensureCleanState();
		sessionToken = await register();
	}

	const apiOrigin = new URL(API_BASE).origin;
	const state = buildStorageState(sessionToken, apiOrigin);
	fs.writeFileSync(AUTH_FILE, JSON.stringify(state, null, 2));
}
