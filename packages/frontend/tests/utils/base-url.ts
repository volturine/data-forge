/**
 * The app URL every e2e browser context uses.
 *
 * Runs are containerized and reach the app over Docker DNS, so there is no
 * host port to fall back to: an unset base URL is a harness bug, not a
 * situation to guess around.
 */
export function e2eBaseURL(): string {
	const baseURL = process.env.PLAYWRIGHT_BASE_URL;
	if (!baseURL) {
		throw new Error('PLAYWRIGHT_BASE_URL must be set before running Playwright e2e tests');
	}
	return baseURL;
}
