import { sveltekit } from '@sveltejs/kit/vite';
import type { ProxyOptions } from 'vite';
import { createLogger, defineConfig } from 'vite';

type ProxyServer = Parameters<NonNullable<ProxyOptions['configure']>>[0];

const port = parseInt(process.env.FRONTEND_PORT || '3000', 10);
const apiPort = parseInt(process.env.BACKEND_PORT || process.env.PORT || '8000', 10);
const apiHost = process.env.BACKEND_HOST || '127.0.0.1';

const proxy = {
	'/api': {
		target: `http://${apiHost}:${apiPort}`,
		ws: true,
		configure(proxy: ProxyServer) {
			const listeners = proxy.listeners('error');
			proxy.removeAllListeners('error');
			proxy.on('error', (error, req, res, target) => {
				if (isExpectedProxySocketError(error)) return;
				for (const listener of listeners) {
					if (typeof listener !== 'function') continue;
					listener(error, req, res, target);
				}
			});
		}
	}
} satisfies Record<string, ProxyOptions>;

function isExpectedProxySocketError(error: NodeJS.ErrnoException): boolean {
	return error.code === 'EPIPE' || error.code === 'ECONNRESET';
}

function shouldIgnoreViteProxyLog(message: string): boolean {
	return (
		message.includes('[vite] ws proxy error') ||
		message.includes('[vite] ws proxy socket error') ||
		message.includes('Error: write EPIPE') ||
		message.includes('Error: read ECONNRESET')
	);
}

const logger = createLogger();
const baseError = logger.error;

logger.error = (message, options) => {
	if (shouldIgnoreViteProxyLog(String(message))) return;
	baseError(message, options);
};

export default defineConfig({
	customLogger: logger,
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

	build: {
		rollupOptions: {
			output: {
				manualChunks(id) {
					if (id.includes('/node_modules/svelte/')) return 'svelte-runtime';
				}
			}
		}
	},

	server: {
		host: '0.0.0.0',
		port,
		strictPort: true,
		allowedHosts: true,
		watch: {
			ignored: ['**/tests/.artifacts/**']
		},
		fs: {
			allow: ['styled-system']
		},
		proxy
	},

	preview: {
		host: '0.0.0.0',
		port,
		strictPort: true,
		allowedHosts: true,
		proxy
	}
});
