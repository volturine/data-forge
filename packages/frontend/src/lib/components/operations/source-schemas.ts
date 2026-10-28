import { datasourceStore } from '#lib/stores/datasource.svelte.js';
import type { Schema } from '#lib/types/schema.js';

export async function fetchSourceSchema(
	datasourceId: string,
	options: { forceRefresh?: boolean } = {}
): Promise<Schema> {
	if (options.forceRefresh) {
		datasourceStore.clearSchemaCache(datasourceId);
	}
	// Cache-first: join/union config only needs column metadata, not re-ingest.
	const schemaInfo = await datasourceStore.getSchema(datasourceId, {
		refresh: options.forceRefresh === true
	});
	return {
		columns: schemaInfo.columns.map((c) => ({
			name: c.name,
			dtype: c.dtype,
			nullable: c.nullable
		})),
		row_count: schemaInfo.row_count
	};
}
