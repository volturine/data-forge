import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import { cleanup, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import RelativeTime from './RelativeTime.svelte';

const NOW = Date.parse('2026-06-01T12:00:00.000Z');
const MINUTE = 60_000;
const DAY = 24 * 60 * MINUTE;

function isoAgo(ms: number): string {
	return new Date(NOW - ms).toISOString();
}

beforeEach(() => {
	vi.useFakeTimers();
	vi.setSystemTime(NOW);
	vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
});

afterEach(() => {
	cleanup();
	vi.restoreAllMocks();
	vi.useRealTimers();
});

describe('RelativeTime', () => {
	// Formatting boundaries belong to relative-time.test.ts; here test the DOM contract.
	test('renders a frozen label with an ISO datetime and absolute tooltip', () => {
		const timestamp = isoAgo(5 * MINUTE);
		render(RelativeTime, { props: { timestamp, live: false } });
		const time = screen.getByRole('time');
		expect(time).toHaveTextContent('5 minutes ago');
		expect(time).toHaveAttribute('datetime', timestamp);
		expect(time.getAttribute('title')).toBeTruthy();
		expect(vi.getTimerCount()).toBe(0);
	});

	test('falls back to an absolute date for old timestamps', () => {
		render(RelativeTime, { props: { timestamp: isoAgo(45 * DAY), live: false } });
		const time = screen.getByRole('time');
		expect(time.textContent).not.toContain('ago');
		expect(time.textContent).toMatch(/\d{4}/);
	});

	test('shares one timer across labels and releases it after the last unmount', async () => {
		const first = render(RelativeTime, { props: { timestamp: isoAgo(5 * MINUTE) } });
		const second = render(RelativeTime, { props: { timestamp: isoAgo(3 * MINUTE) } });
		expect(vi.getTimerCount()).toBe(1);
		vi.advanceTimersByTime(MINUTE);
		await tick();
		expect(screen.getByText('6 minutes ago')).toBeInTheDocument();
		expect(screen.getByText('4 minutes ago')).toBeInTheDocument();
		first.unmount();
		expect(vi.getTimerCount()).toBe(1);
		second.unmount();
		expect(vi.getTimerCount()).toBe(0);
	});

	test('pauses hidden tabs and immediately refreshes when visible', async () => {
		render(RelativeTime, { props: { timestamp: isoAgo(5 * MINUTE) } });
		vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
		document.dispatchEvent(new Event('visibilitychange'));
		expect(vi.getTimerCount()).toBe(0);
		vi.advanceTimersByTime(3 * MINUTE);
		await tick();
		expect(screen.getByText('5 minutes ago')).toBeInTheDocument();
		vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
		document.dispatchEvent(new Event('visibilitychange'));
		await tick();
		expect(screen.getByText('8 minutes ago')).toBeInTheDocument();
		expect(vi.getTimerCount()).toBe(1);
	});

	test('reacts to live and refresh interval changes without leaking timers', async () => {
		const view = render(RelativeTime, {
			props: { timestamp: isoAgo(5 * MINUTE), live: false }
		});
		expect(vi.getTimerCount()).toBe(0);
		await view.rerender({ live: true, refreshMs: 1_000 });
		expect(vi.getTimerCount()).toBe(1);
		vi.setSystemTime(NOW + MINUTE);
		vi.advanceTimersByTime(1_000);
		await tick();
		expect(screen.getByText('6 minutes ago')).toBeInTheDocument();
		await view.rerender({ refreshMs: 2 * MINUTE });
		expect(vi.getTimerCount()).toBe(1);
		vi.advanceTimersByTime(MINUTE);
		await tick();
		expect(screen.getByText('6 minutes ago')).toBeInTheDocument();
		await view.rerender({ live: false });
		expect(vi.getTimerCount()).toBe(0);
	});
});
