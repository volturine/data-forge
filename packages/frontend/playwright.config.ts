/// <reference types="node" />
import path from 'node:path';
import { defineConfig, devices, type ReporterDescription } from '@playwright/test';

function resolveE2eWorkers(): number {
	const raw = process.env.PW_E2E_WORKERS;
	if (!raw) {
		throw new Error('PW_E2E_WORKERS must be set before running Playwright e2e tests');
	}

	const workers = Number.parseInt(raw, 10);
	if (!Number.isInteger(workers) || workers < 1 || workers.toString() !== raw) {
		throw new Error(`PW_E2E_WORKERS must be a positive integer, got "${raw}"`);
	}

	return workers;
}

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
const jsonReport = process.env.PLAYWRIGHT_JSON_REPORT;
const reporter: ReporterDescription[] = [['line']];
if (jsonReport) {
	reporter.push(['json', { outputFile: jsonReport }]);
}
const workers = resolveE2eWorkers();

export default defineConfig({
	testDir: './tests',
	timeout: 120_000,
	expect: { timeout: process.env.CI ? 10_000 : 5_000 },
	fullyParallel: false,
	globalSetup: './tests/global-setup.ts',
	workers,
	// Native Docker engines add cold-start jitter on shared CI hosts. Two
	// retries recover residual blank-shell flakes; the suite finishes in
	// ~27m with one retry when mostly green.
	retries: process.env.CI ? 2 : 0,
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
