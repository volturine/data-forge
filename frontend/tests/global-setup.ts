import fs from 'node:fs';
import path from 'node:path';
import { API_BASE, AUTH_FILE } from './utils/api.js';

const port = process.env.FRONTEND_PORT || '3000';
const origin = `http://localhost:${port}`;
const E2E_EMAIL = 'e2e-test@example.com';
const E2E_PASSWORD = 'E2eTestPw12345';

function parseSessionToken(response: Response): string | undefined {
	const raw = response.headers.getSetCookie?.();
	const entries = raw ?? [response.headers.get('set-cookie') ?? ''];
	for (const entry of entries) {
		const match = entry.match(/session_token=([^;]+)/);
		if (match) return match[1];
	}
	return undefined;
}

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

export default async function globalSetup() {
	fs.mkdirSync(path.dirname(AUTH_FILE), { recursive: true });

	const configResp = await fetch(`${API_BASE}/config`);
	const authRequired = configResp.ok
		? ((await configResp.json()) as { auth_required?: boolean }).auth_required !== false
		: true;

	let sessionToken: string | undefined;

	if (authRequired) {
		const regResp = await fetch(`${API_BASE}/auth/register`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ email: E2E_EMAIL, password: E2E_PASSWORD, display_name: 'E2E Test' })
		});

		if (regResp.ok) {
			sessionToken = parseSessionToken(regResp);
		} else {
			const loginResp = await fetch(`${API_BASE}/auth/login`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ email: E2E_EMAIL, password: E2E_PASSWORD })
			});
			if (!loginResp.ok) {
				throw new Error(`E2E auth failed: register=${regResp.status}, login=${loginResp.status}`);
			}
			sessionToken = parseSessionToken(loginResp);
		}

		if (!sessionToken) {
			throw new Error('E2E auth succeeded but no session_token cookie received');
		}
	}

	const apiOrigin = new URL(API_BASE).origin;
	const state = buildStorageState(sessionToken, apiOrigin);
	fs.writeFileSync(AUTH_FILE, JSON.stringify(state, null, 2));
}
