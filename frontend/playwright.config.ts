import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
	testDir: './e2e',
	timeout: 30_000,
	expect: { timeout: 10_000 },
	fullyParallel: false,
	retries: 1,
	reporter: [['html', { open: 'never', outputFolder: 'playwright-report' }], ['line']],
	use: {
		baseURL: 'http://localhost:3000',
		trace: 'on-first-retry'
	},
	projects: [
		{
			name: 'chromium',
			use: { ...devices['Desktop Chrome'] }
		}
	],
	webServer: {
		command: 'bun run dev',
		url: 'http://localhost:3000',
		reuseExistingServer: true,
		timeout: 60_000
	}
});
