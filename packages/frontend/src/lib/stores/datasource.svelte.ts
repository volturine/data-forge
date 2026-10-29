import type { DataSource, SchemaInfo } from '#lib/types/datasource.js';
import { getDatasourceSchema } from '#lib/api/datasource.js';
import { SvelteMap } from 'svelte/reactivity';

export class DatasourceStore {
	datasources = $state.raw<DataSource[]>([]);
	schemas = $state(new SvelteMap<string, SchemaInfo>());
	loaded = $state(false);

	/**
	 * Fetch column schema for a datasource.
	 *
	 * Default is cache-first (`refresh: false`): memory cache, then the API
	 * which serves the DB `schema_cache` without re-ingest. Pass
	 * `refresh: true` only for explicit user-driven re-extract / re-ingest.
	 */
	async getSchema(
		id: string,
		options: { sheetName?: string; refresh?: boolean } = {}
	): Promise<SchemaInfo> {
		const sheetName = options.sheetName;
		const refresh = options.refresh === true;

		if (!refresh && !sheetName) {
			const cached = this.schemas.get(id);
			if (cached) return cached;
		}

		const datasource = this.getDatasource(id);
		if (datasource?.source_type === 'analysis') {
			throw new Error('Schema must be fetched via analysis output');
		}

		const result = await getDatasourceSchema(id, { sheetName, refresh });
		return result.match(
			(schema) => {
				if (!sheetName) {
					this.schemas.set(id, schema);
				}
				return schema;
			},
			(err) => {
				throw new Error(err.message || 'Failed to get schema');
			}
		);
	}

	getDatasource(id: string): DataSource | undefined {
		return this.datasources.find((ds) => ds.id === id);
	}

	clearSchemaCache(id?: string): void {
		if (id) this.schemas.delete(id);
		else this.schemas.clear();
	}

	reset(): void {
		this.datasources = [];
		this.schemas.clear();
		this.loaded = false;
	}
}

export const datasourceStore = new DatasourceStore();
