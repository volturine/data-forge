import type { QueryClient } from '@tanstack/svelte-query';

interface ResettableService {
	reset(): void;
}

interface DestroyableService {
	destroy(): void;
}

export interface NamespaceServices {
	analysis: ResettableService;
	chat: ResettableService & DestroyableService;
	computeActivity: ResettableService;
	datasource: ResettableService;
	engines: ResettableService;
	favorites: ResettableService;
	schema: ResettableService;
}

export class AppLifecycle {
	constructor(
		private readonly queryClient: QueryClient,
		private readonly services: NamespaceServices
	) {}

	async releaseNamespace(): Promise<void> {
		await this.queryClient.cancelQueries();
		this.services.computeActivity.reset();
		this.services.engines.reset();
		this.services.chat.reset();
		this.services.analysis.reset();
		this.services.datasource.reset();
		this.services.favorites.reset();
		this.services.schema.reset();
	}

	activateNamespace(): void {
		this.queryClient.clear();
	}

	destroy(): void {
		this.services.chat.destroy();
		this.services.engines.reset();
	}
}
