import fs from 'node:fs';
import path from 'node:path';
import { request } from '@playwright/test';
import { API_BASE, AUTH_FILE } from './utils/api.js';

const port = process.env.FRONTEND_PORT || '3000';
const origin = `http://localhost:${port}`;
const E2E_EMAIL = 'e2e-test@example.com';
const E2E_PASSWORD = 'E2eTestPw12345';

export default async function globalSetup() {
	fs.mkdirSync(path.dirname(AUTH_FILE), { recursive: true });

	const ctx = await request.newContext();

	const configResp = await ctx.get(`${API_BASE}/config`);
	const authRequired = configResp.ok()
		? ((await configResp.json()) as { auth_required?: boolean }).auth_required !== false
		: true;

	if (authRequired) {
		const reg = await ctx.post(`${API_BASE}/auth/register`, {
			data: { email: E2E_EMAIL, password: E2E_PASSWORD, display_name: 'E2E Test' }
		});

		if (!reg.ok()) {
			const login = await ctx.post(`${API_BASE}/auth/login`, {
				data: { email: E2E_EMAIL, password: E2E_PASSWORD }
			});
			if (!login.ok()) {
				throw new Error(`E2E auth failed: register=${reg.status()}, login=${login.status()}`);
			}
		}
	}

	await ctx.storageState({ path: AUTH_FILE });
	await ctx.dispose();

	const state = JSON.parse(fs.readFileSync(AUTH_FILE, 'utf-8'));
	const match = state.origins?.find((o: { origin: string }) => o.origin === origin);
	const entry = { name: 'debug:prefer-http', value: 'true' };
	if (match) {
		match.localStorage = [...(match.localStorage ?? []), entry];
	} else {
		state.origins = [...(state.origins ?? []), { origin, localStorage: [entry] }];
	}
	fs.writeFileSync(AUTH_FILE, JSON.stringify(state, null, 2));
}
