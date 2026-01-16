import type { DataSource, SchemaInfo } from '$lib/types/datasource';
import {
	listDatasources,
	uploadFile as uploadFileApi,
	getDatasourceSchema,
	deleteDatasource as deleteDatasourceApi
} from '$lib/api/datasource';

class DatasourceStore {
	datasources = $state<DataSource[]>([]);
	schemas = $state(new Map<string, SchemaInfo>());
	loading = $state(false);
	error = $state<string | null>(null);

	async loadDatasources(): Promise<void> {
		this.loading = true;
		this.error = null;

		try {
			const datasources = await listDatasources();
			this.datasources = datasources;
		} catch (err) {
			this.error = err instanceof Error ? err.message : 'Failed to load datasources';
			throw err;
		} finally {
			this.loading = false;
		}
	}

	async uploadFile(file: File, name: string): Promise<DataSource> {
		this.loading = true;
		this.error = null;

		try {
			const datasource = await uploadFileApi(file, name);
			this.datasources = [...this.datasources, datasource];
			return datasource;
		} catch (err) {
			this.error = err instanceof Error ? err.message : 'Failed to upload file';
			throw err;
		} finally {
			this.loading = false;
		}
	}

	async getSchema(id: string): Promise<SchemaInfo> {
		// Return cached schema if available
		const cached = this.schemas.get(id);
		if (cached) return cached;

		const schema = await getDatasourceSchema(id);
		this.schemas.set(id, schema);
		this.schemas = new Map(this.schemas);
		return schema;
	}

	async deleteDatasource(id: string): Promise<void> {
		this.loading = true;
		this.error = null;

		try {
			await deleteDatasourceApi(id);
			this.datasources = this.datasources.filter((ds) => ds.id !== id);

			// Remove cached schema
			this.schemas.delete(id);
			this.schemas = new Map(this.schemas);
		} catch (err) {
			this.error = err instanceof Error ? err.message : 'Failed to delete datasource';
			throw err;
		} finally {
			this.loading = false;
		}
	}

	getDatasource(id: string): DataSource | undefined {
		return this.datasources.find((ds) => ds.id === id);
	}

	clearSchemaCache(id?: string): void {
		if (id) {
			this.schemas.delete(id);
		} else {
			this.schemas.clear();
		}
		this.schemas = new Map(this.schemas);
	}

	reset(): void {
		this.datasources = [];
		this.schemas.clear();
		this.schemas = new Map();
		this.error = null;
		this.loading = false;
	}
}

export const datasourceStore = new DatasourceStore();
