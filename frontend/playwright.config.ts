import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
	testDir: './tests',
	globalSetup: './tests/global-setup.ts',
	timeout: 30_000,
	expect: { timeout: 10_000 },
	fullyParallel: false,
	workers: 1,
	retries: 1,
	outputDir: './tests/test-results',
	reporter: [['html', { open: 'never', outputFolder: 'tests/playwright-report' }], ['line']],
	use: {
		baseURL: 'http://localhost:3000',
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
		url: 'http://localhost:3000',
		reuseExistingServer: true,
		timeout: 60_000
	}
});
