import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

const port = parseInt(process.env.FRONTEND_PORT || '3000', 10);
const apiPort = parseInt(process.env.PORT || '8000', 10);
const apiHost = process.env.VITE_BACKEND_HOST || '127.0.0.1';

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
		port,
		allowedHosts: true,
		fs: {
			allow: ['styled-system']
		},
		proxy: {
			'/api': {
				target: `http://${apiHost}:${apiPort}`,
				ws: true
			}
		},
		hmr: {
			host: '0.0.0.0'
		}
	}
});
