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

		listDatasources().match(
			(datasources) => {
				this.datasources = datasources;
				this.loading = false;
			},
			(err) => {
				this.error = err.message;
				this.loading = false;
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

	async getSchema(id: string, sheetName?: string): Promise<SchemaInfo> {
		const cached = this.schemas.get(id);
		if (cached && !sheetName) return cached;

		const result = await getDatasourceSchema(id, sheetName);
		return result.match(
			(schema) => {
				if (!sheetName) {
					this.schemas.set(id, schema);
					this.schemas = new Map(this.schemas);
				}
				return schema;
			},
			(_err) => {
				throw new Error('Failed to get schema');
			}
		);
	}

	async deleteDatasource(id: string): Promise<void> {
		this.loading = true;
		this.error = null;

		deleteDatasourceApi(id).match(
			() => {
				this.datasources = this.datasources.filter((ds) => ds.id !== id);
				this.schemas.delete(id);
				this.schemas = new Map(this.schemas);
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
