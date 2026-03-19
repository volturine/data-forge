import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	resolve: {
		dedupe: [
			'@codemirror/state',
			'@codemirror/view',
			'@codemirror/language',
			'@lezer/common',
			'@lezer/lr'
		]
	},
	plugins: [sveltekit()],

	server: {
		host: '0.0.0.0',
		port: 3000,
		allowedHosts: true,
		fs: {
			allow: ['styled-system']
		},
		proxy: {
			'/api': 'http://localhost:8000'
		},
		hmr: {
			host: '0.0.0.0'
		}
	}
});
