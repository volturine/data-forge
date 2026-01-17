import { afterEach, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';

// Cleanup after each test - only import cleanup if needed
afterEach(async () => {
	// Dynamic import to avoid issues when not testing components
	try {
		const { cleanup } = await import('@testing-library/svelte');
		cleanup();
	} catch {
		// Cleanup not needed for non-component tests
	}
});

// Mock SvelteKit modules
vi.mock('$app/navigation', () => ({
	goto: vi.fn()
}));

vi.mock('$app/stores', () => ({
	page: { subscribe: vi.fn() },
	navigating: { subscribe: vi.fn() },
	updated: { subscribe: vi.fn() }
}));
