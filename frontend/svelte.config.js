import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

export default {
	preprocess: [vitePreprocess()],

	onwarn: (warning, handler) => {
		// Suppress specific warnings
		if (warning.code === 'state_referenced_locally') return;
		if (warning.code === 'css_unused_selector') return;
		if (warning.code === 'non_reactive_update') return;
		handler(warning);
	},

	kit: {
		adapter: adapter({
			pages: 'build',
			assets: 'build',
			fallback: '200.html',
			precompress: false,
			strict: true
		}),
		alias: {
			'styled-system': './styled-system/*'
		},
		// Ensure the app is served from the root path
		paths: {
			base: ''
		}
	}
};
