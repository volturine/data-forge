import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { svelteTesting } from '@testing-library/svelte/vite';
import { resolve } from 'path';

const stub = resolve(__dirname, 'src/lib/test-utils/stubs');

export default defineConfig({
	plugins: [svelte({ compilerOptions: { runes: true } }), svelteTesting()],
	resolve: {
		alias: {
			$lib: resolve(__dirname, 'src/lib'),
			'lucide-svelte': resolve(stub, 'lucide-svelte.ts'),
			'$app/environment': resolve(stub, 'app-environment.ts')
		}
	},
	test: {
		include: ['src/**/*.test.ts'],
		environment: 'jsdom',
		setupFiles: ['src/lib/test-utils/setup.ts']
	}
});
