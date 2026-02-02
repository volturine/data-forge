import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
	plugins: [
		svelte({
			preprocess: []
		})
	],
	resolve: {
		conditions: ['browser']
	},
	test: {
		include: ['src/**/*.{test,spec}.{js,ts}', 'tests/**/*.test.{js,ts}'],
		exclude: ['tests/e2e/**'],
		globals: true,
		environment: 'jsdom',
		setupFiles: ['./tests/test-setup.ts'],
		pool: 'forks',
		deps: {
			optimizer: {
				web: {
					include: ['svelte']
				}
			}
		},
		coverage: {
			provider: 'v8',
			reporter: ['text', 'json', 'html', 'lcov'],
			include: ['src/**/*.{js,ts,svelte}'],
			exclude: [
				'src/**/*.{test,spec}.{js,ts}',
				'tests/test-setup.ts',
				'tests/test-utils.ts',
				'**/*.d.ts',
				'**/node_modules/**'
			]
		}
	}
});
