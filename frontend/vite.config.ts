import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

const port = parseInt(process.env.FRONTEND_PORT || '3000', 10);
const apiPort = parseInt(process.env.PORT || '8000', 10);
const apiHost = process.env.VITE_BACKEND_HOST || '127.0.0.1';

const abortCodes = new Set(['EPIPE', 'ECONNRESET', 'ECONNREFUSED', 'ENOTFOUND']);

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
				ws: true,
				configure: (proxy) => {
					proxy.on('error', (err, _req, res) => {
						if (abortCodes.has((err as NodeJS.ErrnoException).code ?? '')) return;
						console.error('[proxy error]', err.message);
						if (res && 'writeHead' in res && !res.headersSent) {
							(res as import('node:http').ServerResponse).writeHead(502).end('Bad Gateway');
						}
					});
				}
			}
		},
		hmr: {
			host: '0.0.0.0'
		}
	}
});
