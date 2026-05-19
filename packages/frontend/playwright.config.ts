/// <reference types="node" />
import path from 'node:path';
import { defineConfig, devices } from '@playwright/test';

const DEFAULT_E2E_WORKERS = 2;

function shardSuffixFromArgs(): string {
	const shardFlagIndex = process.argv.findIndex((arg) => arg === '--shard');
	if (shardFlagIndex === -1) return '';
	const shardValue = process.argv[shardFlagIndex + 1];
	if (!shardValue) return '';
	const [current, total] = shardValue.split('/');
	if (!current || !total) return '';
	return `-shard-${current}-of-${total}`;
}

const port = parseInt(process.env.FRONTEND_PORT || '3000', 10);
const baseURL = process.env.PLAYWRIGHT_BASE_URL || `http://localhost:${port}`;
const ciArgs = process.env.CI ? ['--disable-dev-shm-usage', '--disable-gpu'] : [];
const artifactsRoot = path.resolve(process.cwd(), 'tests', '.artifacts');
const shardSuffix = shardSuffixFromArgs();
const reporter = [['line'] as const];

export default defineConfig({
	testDir: './tests',
	timeout: 30_000,
	expect: { timeout: 10_000 },
	fullyParallel: false,
	globalSetup: './tests/global-setup.ts',
	workers: DEFAULT_E2E_WORKERS,
	retries: 1,
	outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR
		? path.resolve(process.env.PLAYWRIGHT_OUTPUT_DIR)
		: path.join(artifactsRoot, 'playwright', `test-results${shardSuffix}`),
	reporter,
	use: {
		baseURL,
		trace: 'on-first-retry',
		screenshot: 'only-on-failure'
	},
	projects: [
		{
			name: 'chromium',
			use: {
				...devices['Desktop Chrome'],
				viewport: { width: 1920, height: 1080 },
				launchOptions: ciArgs.length === 0 ? undefined : { args: ciArgs }
			}
		}
	]
});
