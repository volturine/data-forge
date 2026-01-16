import prettier from 'eslint-config-prettier';
import { fileURLToPath } from 'node:url';
import { includeIgnoreFile } from '@eslint/compat';
import js from '@eslint/js';
import svelte from 'eslint-plugin-svelte';
import { defineConfig } from 'eslint/config';
import globals from 'globals';
import ts from 'typescript-eslint';
import svelteConfig from './svelte.config.js';

const gitignorePath = fileURLToPath(new URL('./.gitignore', import.meta.url));

export default defineConfig(
	includeIgnoreFile(gitignorePath),
	js.configs.recommended,
	...ts.configs.recommended,
	...svelte.configs.recommended,
	prettier,
	...svelte.configs.prettier,
	{
		languageOptions: { globals: { ...globals.browser, ...globals.node } },

		rules: {
			// typescript-eslint strongly recommend that you do not use the no-undef lint rule on TypeScript projects.
			// see: https://typescript-eslint.io/troubleshooting/faqs/eslint/#i-get-errors-from-the-no-undef-rule-about-global-variables-not-being-defined-even-though-there-are-no-typescript-errors
			'no-undef': 'off',
			// Allow unused vars that start with underscore
			'@typescript-eslint/no-unused-vars': [
				'error',
				{ argsIgnorePattern: '^_', varsIgnorePattern: '^_' }
			],
			// Allow any type in API and utility code where needed for flexibility
			'@typescript-eslint/no-explicit-any': 'warn',
			// Allow lexical declarations in case blocks (common pattern)
			'no-case-declarations': 'off',
			// Allow useless catch when logging/cleanup is needed
			'no-useless-catch': 'warn',
			// Svelte-specific: allow navigation without resolve in this project
			'svelte/no-navigation-without-resolve': 'warn',
			// Svelte-specific: allow each blocks without keys (performance tradeoff)
			'svelte/require-each-key': 'warn',
			// Svelte-specific: allow built-in reactive types where SvelteSet/Map not needed
			'svelte/prefer-svelte-reactivity': 'warn',
			// Allow unnecessary state wrap in some edge cases
			'svelte/no-unnecessary-state-wrap': 'warn',
			// Allow mustache with string literals for clarity
			'svelte/no-useless-mustaches': 'warn',
			// Allow $state + $effect pattern instead of writable $derived
			'svelte/prefer-writable-derived': 'warn'
		}
	},
	{
		files: ['**/*.svelte', '**/*.svelte.ts', '**/*.svelte.js'],

		languageOptions: {
			parserOptions: {
				projectService: true,
				extraFileExtensions: ['.svelte'],
				parser: ts.parser,
				svelteConfig
			}
		}
	}
);
