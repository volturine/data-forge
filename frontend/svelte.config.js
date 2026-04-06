import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

export default {
	preprocess: [vitePreprocess()],

	onwarn: (warning, handler) => {
		// css_unused_selector: Panda CSS generates selectors consumed at runtime — cannot be resolved statically
		if (warning.code === 'css_unused_selector') return;
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
		paths: {
			base: ''
		}
	},

	// Enable runes for all project files; leave dependencies as-is
	vitePlugin: {
		dynamicCompileOptions({ filename }) {
			if (!filename) return;
			if (filename.includes('node_modules')) return;
			return { runes: true };
		}
	}
};
