import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { sveltekit } from '@sveltejs/kit/vite';
import type { ProxyOptions } from 'vite';
import { createLogger, defineConfig } from 'vite';

type ProxyServer = Parameters<NonNullable<ProxyOptions['configure']>>[0];

const port = parseInt(process.env.FRONTEND_PORT || '3000', 10);
const apiPort = parseInt(process.env.BACKEND_PORT || process.env.PORT || '8000', 10);
const apiHost = process.env.BACKEND_HOST || '127.0.0.1';
const disableHmr = process.env.DATAFORGE_DISABLE_VITE_HMR === 'true';

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
	plugins: [
		sveltekit({
			preprocess: [vitePreprocess()],
			// Enable runes for all project files; leave dependencies as-is
			dynamicCompileOptions({ filename }) {
				if (!filename || filename.includes('node_modules')) return;
				return { runes: true };
			},
			onwarn: (warning, handler) => {
				// Panda selectors are consumed at runtime and cannot be resolved statically.
				if (warning.code === 'css_unused_selector') return;
				handler(warning);
			},

			adapter: adapter({
				pages: 'build',
				assets: 'build',
				fallback: '200.html',
				precompress: false,
				strict: true
			}),
			paths: { base: '' }
		})
	],
	build: {
		rolldownOptions: {
			output: {
				codeSplitting: {
					groups: [
						{ name: 'svelte-runtime', test: /\/node_modules\/svelte\// },
						{
							name: 'code-editor',
							test: /\/node_modules\/(?:codemirror|@codemirror|@lezer)\//
						},
						{
							name: 'charts',
							test: /\/node_modules\/@tanstack\/charts\//
						}
					]
				}
			}
		}
	},

	server: {
		host: '0.0.0.0',
		port,
		strictPort: true,
		allowedHosts: true,
		hmr: disableHmr ? false : undefined,
		watch: {
			ignored: ['**/.artifacts/**', '**/tests/ci-artifacts/**']
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
