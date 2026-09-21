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

const baseURL = process.env.PLAYWRIGHT_BASE_URL;
if (!baseURL) {
	throw new Error('PLAYWRIGHT_BASE_URL must be set before running Playwright e2e tests');
}
const ciArgs = process.env.CI ? ['--disable-dev-shm-usage', '--disable-gpu'] : [];
const artifactsRoot = path.resolve(process.cwd(), 'tests', '.artifacts');
const testDir = process.env.E2E_BOOTSTRAP_SHARED_FIXTURES === '1' ? './e2e' : './tests';
const shardSuffix = shardSuffixFromArgs();
const jsonReport = process.env.PLAYWRIGHT_JSON_REPORT;
const reporter: ReporterDescription[] = [['line']];
if (jsonReport) {
	reporter.push(['json', { outputFile: jsonReport }]);
}
const workers = resolveE2eWorkers();
const testTimeoutMs = (() => {
	const raw = process.env.PLAYWRIGHT_TEST_TIMEOUT_MS;
	if (!raw) return 120_000;
	const timeout = Number.parseInt(raw, 10);
	if (!Number.isInteger(timeout) || timeout < 1_000 || timeout.toString() !== raw) {
		throw new Error(`PLAYWRIGHT_TEST_TIMEOUT_MS must be an integer >= 1000, got "${raw}"`);
	}
	return timeout;
})();

export default defineConfig({
	testDir,
	timeout: testTimeoutMs,
	expect: { timeout: process.env.CI ? 10_000 : 5_000 },
	fullyParallel: false,
	globalSetup: './tests/global-setup.ts',
	workers,
	retries: 0,
	outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR
		? path.resolve(process.env.PLAYWRIGHT_OUTPUT_DIR)
		: path.join(artifactsRoot, 'playwright', `test-results${shardSuffix}`),
	reporter,
	use: {
		baseURL,
		// Fail stuck clicks/gotos in seconds instead of sitting until the 120s
		// test wall (default 0 = unlimited until test timeout). 30s also bounds
		// response waits on runtime flows (engine spawn + preview) that
		// legitimately take 11-23s under parallel load.
		actionTimeout: 30_000,
		navigationTimeout: 30_000,
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
