import fs from 'node:fs';
import { API_BASE, AUTH_DIR, META_FILE } from './utils/api.js';
import type { RunMeta } from './utils/api.js';

export default async function globalSetup(): Promise<void> {
	fs.mkdirSync(AUTH_DIR, { recursive: true });

	const configResp = await fetch(`${API_BASE}/config`);
	const authRequired = configResp.ok
		? ((await configResp.json()) as { auth_required?: boolean }).auth_required !== false
		: true;

	const meta: RunMeta = {
		authRequired,
		stamp: Date.now().toString(36)
	};

	fs.writeFileSync(META_FILE, JSON.stringify(meta, null, 2));
}
