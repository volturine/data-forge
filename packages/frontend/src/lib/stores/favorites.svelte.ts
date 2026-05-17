type FavoriteAnalysis = {
	id: string;
	is_favorite?: boolean;
};

function favoriteIds(items: FavoriteAnalysis[]): string[] {
	return items.filter((item) => item.is_favorite === true).map((item) => item.id);
}

export class FavoriteStore {
	namespace = $state<string | null>(null);
	ids = $state.raw<string[]>([]);

	setNamespace(ns: string): void {
		const next = ns.trim() || null;
		if (this.namespace === next) return;
		this.namespace = next;
		this.ids = [];
	}

	sync(items: FavoriteAnalysis[]): void {
		this.ids = favoriteIds(items);
	}

	isFavorite(id: string): boolean {
		return this.ids.includes(id);
	}

	apply(id: string, isFavorite: boolean): void {
		const next = id.trim();
		if (!next) return;
		if (isFavorite) {
			if (this.ids.includes(next)) return;
			this.ids = [next, ...this.ids];
			return;
		}
		this.ids = this.ids.filter((item) => item !== next);
	}

	reset(): void {
		this.namespace = null;
		this.ids = [];
	}
}

export const favoriteStore = new FavoriteStore();
