import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import FreshnessBadge from './FreshnessBadge.svelte';

const NOW = Date.parse('2026-06-01T12:00:00.000Z');
const HOUR = 60 * 60_000;

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

describe('FreshnessBadge', () => {
	test('shows Fresh within the threshold', () => {
		render(FreshnessBadge, {
			props: { lastDataUpdate: isoAgo(1 * HOUR), thresholdMinutes: 1440, live: false }
		});
		const badge = screen.getByRole('status');
		expect(badge).toHaveAttribute('data-freshness', 'fresh');
		expect(badge).toHaveTextContent('Fresh');
	});

	test('shows Stale between one and two thresholds', () => {
		render(FreshnessBadge, {
			props: { lastDataUpdate: isoAgo(25 * HOUR), thresholdMinutes: 1440, live: false }
		});
		expect(screen.getByRole('status')).toHaveAttribute('data-freshness', 'stale');
		expect(screen.getByRole('status')).toHaveTextContent('Stale');
	});

	test('shows Outdated past twice the threshold', () => {
		render(FreshnessBadge, {
			props: { lastDataUpdate: isoAgo(49 * HOUR), thresholdMinutes: 1440, live: false }
		});
		expect(screen.getByRole('status')).toHaveAttribute('data-freshness', 'outdated');
		expect(screen.getByRole('status')).toHaveTextContent('Outdated');
	});

	test('shows Unknown when never built', () => {
		render(FreshnessBadge, {
			props: { lastDataUpdate: null, thresholdMinutes: 1440, live: false }
		});
		expect(screen.getByRole('status')).toHaveAttribute('data-freshness', 'unknown');
		expect(screen.getByRole('status')).toHaveTextContent('Unknown');
	});

	test('applies the default 24-hour threshold when none is configured', () => {
		render(FreshnessBadge, { props: { lastDataUpdate: isoAgo(49 * HOUR), live: false } });
		expect(screen.getByRole('status')).toHaveAttribute('data-freshness', 'outdated');
	});
});
