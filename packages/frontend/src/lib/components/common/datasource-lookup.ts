import { createQuery } from '@tanstack/svelte-query';
import { listDatasources } from '#lib/api/datasource.js';
import type { useNamespace } from '#lib/stores/namespace.svelte.js';

export function createDatasourceLookupQuery(ns: ReturnType<typeof useNamespace>) {
	return createQuery(() => ({
		queryKey: ['datasources-lookup', ns.value, 'include-hidden'],
		queryFn: async () => {
			const result = await listDatasources(true, { cache: 'no-store' });
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		staleTime: 0,
		refetchOnMount: 'always',
		enabled: !ns.switching
	}));
}
