import { ESLint } from 'eslint';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const frontendRoot = resolve(import.meta.dirname, '../../..');
const eslint = new ESLint({
	cwd: frontendRoot,
	overrideConfigFile: resolve(frontendRoot, 'eslint.config.js')
});
const probePath = resolve(frontendRoot, 'tests/api-mutation-policy-probe.test.ts');
const mutationExamples = [
	{
		name: 'bare request fixture',
		source: `
declare const request: { post(url: string): Promise<unknown> };
export async function probe(): Promise<void> { await request.post('/api/v1/analysis'); }
`
	},
	{
		name: 'API request context',
		source: `
declare const apiContext: { request: { post(url: string): Promise<unknown> } };
export async function probe(): Promise<void> { await apiContext.request.post('/api/v1/analysis'); }
`
	},
	{
		name: 'page request context',
		source: `
declare const page: { request: { put(url: string): Promise<unknown> } };
export async function probe(): Promise<void> { await page.request.put('/api/v1/analysis'); }
`
	},
	{
		name: 'page context request',
		source: `
declare const page: { context(): { request: { patch(url: string): Promise<unknown> } } };
export async function probe(): Promise<void> { await page.context().request.patch('/api/v1/analysis'); }
`
	},
	{
		name: 'context request',
		source: `
declare const context: { request: { post(url: string): Promise<unknown> } };
export async function probe(): Promise<void> { await context.request.post('/api/v1/analysis'); }
`
	},
	{
		name: 'first context request',
		source: `
declare const firstContext: { request: { delete(url: string): Promise<unknown> } };
export async function probe(): Promise<void> { await firstContext.request.delete('/api/v1/analysis/1'); }
`
	},
	{
		name: 'non-GET fetch',
		source: `
declare const request: { fetch(url: string, options: { method: string }): Promise<unknown> };
export async function probe(): Promise<void> { await request.fetch('/api/v1/analysis', { method: 'POST' }); }
`
	}
];

async function lintMessages(source: string, filePath = probePath) {
	const results = await eslint.lintText(source, { filePath });
	const result = results[0];
	if (!result) throw new Error('ESLint returned no lint result');
	return result.messages;
}

describe('Playwright API mutation ESLint policy', () => {
	it.each(mutationExamples)('rejects $name', async ({ source }) => {
		const messages = await lintMessages(source);
		expect(messages.filter((message) => message.ruleId === 'no-restricted-syntax')).toHaveLength(1);
	});

	it('allows read-only fetch calls', async () => {
		const messages = await lintMessages(`
declare const request: { fetch(url: string, options: { method: string }): Promise<unknown> };
export async function probe(): Promise<void> { await request.fetch('/api/v1/analysis', { method: 'GET' }); }
`);
		expect(messages.filter((message) => message.ruleId === 'no-restricted-syntax')).toHaveLength(0);
	});

	it.each([
		'tests/utils/api.test.ts',
		'tests/runtime-architecture.test.ts',
		'tests/datasource-compute-isolation.test.ts',
		'tests/concurrency.test.ts'
	])('keeps the explicit exemption %s', async (filePath) => {
		const messages = await lintMessages(
			mutationExamples[0].source,
			resolve(frontendRoot, filePath)
		);
		expect(messages.filter((message) => message.ruleId === 'no-restricted-syntax')).toHaveLength(0);
	});
});
