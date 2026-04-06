import os from 'node:os';
import { defineConfig, devices } from '@playwright/test';

const port = parseInt(process.env.FRONTEND_PORT || '3000', 10);
const baseURL = `http://localhost:${port}`;
const parallelism =
	typeof os.availableParallelism === 'function' ? os.availableParallelism() : os.cpus().length;
const defaultWorkers = Math.min(6, Math.max(2, Math.floor(parallelism / 2)));
const workers = parseInt(process.env.PW_E2E_WORKERS || `${defaultWorkers}`, 10);

export default defineConfig({
	testDir: './tests',
	globalSetup: './tests/global-setup.ts',
	globalTeardown: './tests/global-teardown.ts',
	timeout: 30_000,
	expect: { timeout: 10_000 },
	fullyParallel: false,
	workers,
	retries: 1,
	outputDir: './tests/test-results',
	reporter: [['html', { open: 'never', outputFolder: 'tests/playwright-report' }], ['line']],
	use: {
		baseURL,
		storageState: 'tests/.auth/state.json',
		trace: 'on-first-retry',
		screenshot: 'only-on-failure'
	},
	projects: [
		{
			name: 'chromium',
			use: {
				...devices['Desktop Chrome'],
				viewport: { width: 1920, height: 1080 }
			}
		}
	],
	webServer: {
		command: 'bun run dev',
		url: baseURL,
		reuseExistingServer: true,
		timeout: 60_000
	}
});
