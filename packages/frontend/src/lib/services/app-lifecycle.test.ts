import { describe, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/svelte-query';
import { AppLifecycle, type NamespaceServices } from './app-lifecycle';

function services(): NamespaceServices {
	const resettable = () => ({ reset: vi.fn() });
	return {
		analysis: resettable(),
		chat: { reset: vi.fn(), destroy: vi.fn() },
		computeActivity: resettable(),
		datasource: resettable(),
		engines: resettable(),
		favorites: resettable(),
		schema: resettable()
	};
}

describe('AppLifecycle', () => {
	it('releases every namespace-scoped service before activating another namespace', async () => {
		const queryClient = new QueryClient();
		const cancelQueries = vi.spyOn(queryClient, 'cancelQueries');
		const removeQueries = vi.spyOn(queryClient, 'removeQueries');
		const resetQueries = vi.spyOn(queryClient, 'resetQueries');
		const scoped = services();
		const lifecycle = new AppLifecycle(queryClient, scoped);

		await lifecycle.releaseNamespace();
		await lifecycle.activateNamespace();

		expect(cancelQueries).toHaveBeenCalledOnce();
		for (const service of Object.values(scoped)) {
			expect(service.reset).toHaveBeenCalledOnce();
		}
		expect(removeQueries).toHaveBeenCalledWith({ type: 'inactive' });
		expect(resetQueries).toHaveBeenCalledWith({ type: 'active' });
	});

	it('destroys process resources when the app scope ends', () => {
		const scoped = services();
		const lifecycle = new AppLifecycle(new QueryClient(), scoped);

		lifecycle.destroy();

		expect(scoped.chat.destroy).toHaveBeenCalledOnce();
		expect(scoped.engines.reset).toHaveBeenCalledOnce();
	});
});
