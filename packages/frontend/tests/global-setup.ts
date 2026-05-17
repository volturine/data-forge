import fs from 'node:fs';
import type { FullConfig } from '@playwright/test';

export default async function globalSetup(config: FullConfig): Promise<void> {
	for (const project of config.projects) {
		fs.mkdirSync(project.outputDir, { recursive: true });
	}
}
