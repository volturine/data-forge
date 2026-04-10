import fs from 'node:fs';
import { AUTH_DIR, META_FILE } from './utils/api.js';

export default async function globalTeardown(): Promise<void> {
	for (const entry of fs.readdirSync(AUTH_DIR).filter((f) => f.startsWith('state-w'))) {
		try {
			fs.unlinkSync(`${AUTH_DIR}/${entry}`);
		} catch {
			// already removed by worker teardown
		}
	}

	try {
		fs.unlinkSync(META_FILE);
	} catch {
		// meta file may not exist if setup failed
	}
}
