import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { svelteTesting } from '@testing-library/svelte/vite';
import { resolve } from 'path';

const stub = resolve(import.meta.dirname, 'src/lib/test-utils/stubs');

export default defineConfig({
	plugins: [svelte({ compilerOptions: { runes: true } }), svelteTesting()],
	resolve: {
		alias: {
			$lib: resolve(import.meta.dirname, 'src/lib'),
			'@lucide/svelte': resolve(stub, 'lucide.ts'),
			'$app/environment': resolve(stub, 'app-environment.ts'),
			'$app/paths': resolve(stub, 'app-paths.ts'),
			'$app/navigation': resolve(stub, 'app-navigation.ts'),
			'$app/state': resolve(stub, 'app-state.ts')
		}
	},
	test: {
		include: ['src/**/*.test.ts'],
		environment: 'jsdom',
		setupFiles: ['src/lib/test-utils/setup.ts']
	}
});
