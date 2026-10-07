import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import RelativeTime from './RelativeTime.svelte';

const NOW = Date.parse('2026-06-01T12:00:00.000Z');
const HOUR = 60 * 60_000;
const DAY = 24 * HOUR;

function isoAgo(ms: number): string {
	return new Date(NOW - ms).toISOString();
}

beforeEach(() => {
	vi.useFakeTimers();
	vi.setSystemTime(NOW);
});

afterEach(() => {
	vi.useRealTimers();
});

describe('RelativeTime', () => {
	test('renders relative minutes', () => {
		render(RelativeTime, { props: { timestamp: isoAgo(5 * 60_000), live: false } });
		expect(screen.getByText('5 minutes ago')).toBeInTheDocument();
	});

	test('renders relative hours', () => {
		render(RelativeTime, { props: { timestamp: isoAgo(3 * HOUR), live: false } });
		expect(screen.getByText('3 hours ago')).toBeInTheDocument();
	});

	test('renders relative days', () => {
		render(RelativeTime, { props: { timestamp: isoAgo(2 * DAY), live: false } });
		expect(screen.getByText('2 days ago')).toBeInTheDocument();
	});

	test('renders just now under a minute', () => {
		render(RelativeTime, { props: { timestamp: isoAgo(10_000), live: false } });
		expect(screen.getByText('just now')).toBeInTheDocument();
	});

	test('falls back to an absolute date at 30 days', () => {
		render(RelativeTime, { props: { timestamp: isoAgo(45 * DAY), live: false } });
		const time = screen.getByRole('time');
		expect(time.textContent).not.toContain('ago');
		expect(time.textContent).toMatch(/\d{4}/);
	});

	test('sets the ISO datetime attribute', () => {
		render(RelativeTime, { props: { timestamp: isoAgo(3 * HOUR), live: false } });
		expect(screen.getByRole('time')).toHaveAttribute(
			'datetime',
			new Date(NOW - 3 * HOUR).toISOString()
		);
	});
});
