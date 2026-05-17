import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderMarkdown, timeAgo } from './markdown';

describe('renderMarkdown', () => {
	test('renders plain text as paragraph', () => {
		const result = renderMarkdown('hello world');
		expect(result).toContain('<p>hello world</p>');
	});

	test('renders bold text', () => {
		const result = renderMarkdown('**bold**');
		expect(result).toContain('<strong>bold</strong>');
	});

	test('renders italic text', () => {
		const result = renderMarkdown('*italic*');
		expect(result).toContain('<em>italic</em>');
	});

	test('renders inline code', () => {
		const result = renderMarkdown('`code`');
		expect(result).toContain('<code>code</code>');
	});

	test('renders fenced code blocks', () => {
		const result = renderMarkdown('```\nconst x = 1;\n```');
		expect(result).toContain('<code>');
		expect(result).toContain('const x = 1;');
	});

	test('renders unordered lists', () => {
		const result = renderMarkdown('- item 1\n- item 2');
		expect(result).toContain('<li>item 1</li>');
		expect(result).toContain('<li>item 2</li>');
	});

	test('renders links', () => {
		const result = renderMarkdown('[link](https://example.com)');
		expect(result).toContain('href="https://example.com"');
		expect(result).toContain('link</a>');
	});

	test('renders headers', () => {
		const result = renderMarkdown('# Title');
		expect(result).toContain('<h1');
		expect(result).toContain('Title');
	});

	test('renders GFM tables', () => {
		const result = renderMarkdown('| a | b |\n|---|---|\n| 1 | 2 |');
		expect(result).toContain('<table>');
		expect(result).toContain('<td>1</td>');
	});

	test('handles line breaks (breaks: true)', () => {
		const result = renderMarkdown('line1\nline2');
		expect(result).toContain('<br');
	});

	test('returns original text for empty string', () => {
		const result = renderMarkdown('');
		expect(result).toBe('');
	});

	test('strips script tags from output', () => {
		const result = renderMarkdown('<script>alert("xss")</script>hello');
		expect(result).not.toContain('<script');
		expect(result).not.toContain('alert');
		expect(result).toContain('hello');
	});

	test('strips inline event handlers', () => {
		const result = renderMarkdown('<img src="x" onerror="alert(1)">');
		expect(result).not.toContain('onerror');
		expect(result).not.toContain('alert');
	});

	test('strips javascript: links from markdown', () => {
		const result = renderMarkdown('[click me](javascript:alert(1))');
		expect(result).not.toContain('javascript:');
	});

	test('strips javascript: links from raw HTML', () => {
		const result = renderMarkdown('<a href="javascript:alert(1)">click</a>');
		expect(result).not.toContain('javascript:');
	});

	test('preserves safe HTML within markdown', () => {
		const result = renderMarkdown('**bold** and [link](https://safe.com)');
		expect(result).toContain('<strong>bold</strong>');
		expect(result).toContain('href="https://safe.com"');
	});
});

describe('timeAgo', () => {
	let now: Date;

	beforeEach(() => {
		now = new Date('2025-06-15T14:30:00.000Z');
		vi.useFakeTimers();
		vi.setSystemTime(now);
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	test('returns time only for today', () => {
		const today = new Date('2025-06-15T10:05:00.000Z');
		const result = timeAgo(today.getTime());
		expect(result).toMatch(/\d{1,2}:\d{2}/);
		expect(result).not.toContain('Yesterday');
	});

	test('returns "Yesterday" prefix for yesterday', () => {
		const yesterday = new Date('2025-06-14T09:00:00.000Z');
		const result = timeAgo(yesterday.getTime());
		expect(result).toContain('Yesterday');
		expect(result).toMatch(/\d{1,2}:\d{2}/);
	});

	test('returns date + time for older dates', () => {
		const older = new Date('2025-06-10T12:00:00.000Z');
		const result = timeAgo(older.getTime());
		expect(result).not.toContain('Yesterday');
		expect(result).toMatch(/\d{1,2}:\d{2}/);
		expect(result).toMatch(/Jun|10/);
	});

	test('handles timestamps at midnight boundary', () => {
		const midnight = new Date('2025-06-15T00:00:00.000Z');
		const result = timeAgo(midnight.getTime());
		expect(result).toMatch(/\d{1,2}:\d{2}/);
	});
});
