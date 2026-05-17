import { beforeEach, describe, expect, test } from 'vitest';

const { FavoriteStore } = await import('./favorites.svelte');

describe('FavoriteStore', () => {
	let store: InstanceType<typeof FavoriteStore>;

	beforeEach(() => {
		store = new FavoriteStore();
	});

	test('setNamespace resets ids when namespace changes', () => {
		store.sync([{ id: 'a-1', is_favorite: true } as { id: string; is_favorite: boolean }]);

		store.setNamespace('team-a');
		store.apply('a-1', true);
		store.setNamespace('team-b');

		expect(store.namespace).toBe('team-b');
		expect(store.ids).toEqual([]);
	});

	test('sync keeps only favorite ids', () => {
		store.sync([
			{ id: 'a-1', is_favorite: true } as { id: string; is_favorite: boolean },
			{ id: 'a-2', is_favorite: false } as { id: string; is_favorite: boolean },
			{ id: 'a-3', is_favorite: true } as { id: string; is_favorite: boolean }
		]);

		expect(store.ids).toEqual(['a-1', 'a-3']);
	});

	test('apply adds a favorite id once', () => {
		store.apply('a-1', true);
		store.apply('a-1', true);

		expect(store.ids).toEqual(['a-1']);
	});

	test('apply removes an existing favorite id', () => {
		store.sync([{ id: 'a-1', is_favorite: true } as { id: string; is_favorite: boolean }]);

		store.apply('a-1', false);

		expect(store.ids).toEqual([]);
	});
});
