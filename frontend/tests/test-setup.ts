import { expect, afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/svelte';
import * as matchers from '@testing-library/svelte/vitest';

// Extend Vitest's expect with Testing Library matchers
expect.extend(matchers);

// Cleanup after each test
afterEach(() => {
	cleanup();
});

// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
	writable: true,
	value: vi.fn().mockImplementation((query) => ({
		matches: false,
		media: query,
		onchange: null,
		addListener: vi.fn(),
		removeListener: vi.fn(),
		addEventListener: vi.fn(),
		removeEventListener: vi.fn(),
		dispatchEvent: vi.fn()
	}))
});

// Mock IntersectionObserver
const IntersectionObserverMock = class implements IntersectionObserver {
	root: Element | Document | null = null;
	rootMargin = '';
	thresholds: number[] = [];

	constructor(_callback: IntersectionObserverCallback) {}

	disconnect() {}
	observe() {}
	takeRecords() {
		return [];
	}
	unobserve() {}
};
global.IntersectionObserver = IntersectionObserverMock;

// Mock ResizeObserver
global.ResizeObserver = class ResizeObserver {
	constructor(_callback: ResizeObserverCallback) {}
	disconnect() {}
	observe() {}
	unobserve() {}
};
