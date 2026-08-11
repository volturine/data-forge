import type { DataSource, SchemaInfo } from '$lib/types/datasource';
import {
	listDatasources,
	uploadFile as uploadFileApi,
	getDatasourceSchema,
	deleteDatasource as deleteDatasourceApi
} from '$lib/api/datasource';
import { SvelteMap } from 'svelte/reactivity';

export class DatasourceStore {
	datasources = $state.raw<DataSource[]>([]);
	schemas = $state(new SvelteMap<string, SchemaInfo>());
	loading = $state(false);
	loaded = $state(false);
	error = $state<string | null>(null);

	async loadDatasources(includeHidden: boolean = false): Promise<void> {
		this.loading = true;
		this.error = null;

		await listDatasources(includeHidden).match(
			(datasources) => {
				this.datasources = datasources;
				this.loading = false;
				this.loaded = true;
			},
			(err) => {
				this.error = err.message;
				this.loading = false;
				this.loaded = true;
			}
		);
	}

	async uploadFile(file: File, name: string): Promise<DataSource> {
		this.loading = true;
		this.error = null;

		return uploadFileApi(file, name).match(
			(datasource) => {
				this.datasources = [...this.datasources, datasource];
				this.loading = false;
				return datasource;
			},
			(err) => {
				this.error = err.message;
				this.loading = false;
				throw new Error(err.message);
			}
		);
	}

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

	async deleteDatasource(id: string): Promise<void> {
		this.loading = true;
		this.error = null;

		await deleteDatasourceApi(id).match(
			() => {
				this.datasources = this.datasources.filter((ds) => ds.id !== id);
				this.schemas.delete(id);
				this.loading = false;
			},
			(err) => {
				this.error = err.message;
				this.loading = false;
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
		this.error = null;
		this.loading = false;
		this.loaded = false;
	}
}

export const datasourceStore = new DatasourceStore();
