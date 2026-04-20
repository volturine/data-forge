import { defineConfig, devices } from '@playwright/test';

const port = parseInt(process.env.FRONTEND_PORT || '3000', 10);
const baseURL = `http://localhost:${port}`;

export default defineConfig({
	testDir: './tests',
	globalSetup: './tests/global-setup.ts',
	globalTeardown: './tests/global-teardown.ts',
	timeout: 30_000,
	expect: { timeout: 10_000 },
	fullyParallel: true,
	workers: 3,
	retries: 1,
	outputDir: './tests/test-results',
	reporter: [['html', { open: 'never', outputFolder: 'tests/playwright-report' }], ['line']],
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
