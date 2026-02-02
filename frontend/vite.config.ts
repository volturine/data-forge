import { sveltekit } from '@sveltejs/kit/vite';
import { VitePWA } from 'vite-plugin-pwa';
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
	plugins: [
		sveltekit(),
		VitePWA({
			registerType: 'autoUpdate',
			workbox: {
				globPatterns: ['**/*.{js,css,html,ico,png,svg,webmanifest,json,xml}']
			},
			manifest: {
				name: 'Myy app',
				short_name: 'My app',
				description: 'description',
				start_url: '/',
				display: 'standalone',
				background_color: '#ffffff',
				theme_color: '#6aaa64',
				orientation: 'portrait-primary',
				scope: '/',
				id: '/?source=pwa',
				lang: 'en',
				dir: 'ltr',
				categories: ['games', 'education'],
				icons: []
			}
		})
	],
	server: {
		host: '0.0.0.0',
		port: 3000,
		allowedHosts: true,
		proxy: {
			'/api': 'http://localhost:8000'
		},
		hmr: {
			host: '0.0.0.0'
		}
	}
});
