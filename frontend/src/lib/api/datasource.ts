import type {
	CSVOptions,
	DataSource,
	IcebergDataSourceConfig,
	SchemaInfo
} from '$lib/types/datasource';
import { apiRequest } from './client';
import { ResultAsync } from 'neverthrow';
import type { ApiError } from './client';

function createApiError(
	type: 'network' | 'http' | 'parse',
	message: string,
	status?: number,
	statusText?: string
): ApiError {
	return { type, message, status, statusText };
}

export function uploadFile(
	file: File,
	name: string,
	csvOptions?: CSVOptions
): ResultAsync<DataSource, ApiError> {
	const formData = new FormData();
	formData.append('file', file);
	formData.append('name', name);

	if (csvOptions) {
		formData.append('delimiter', csvOptions.delimiter);
		formData.append('quote_char', csvOptions.quote_char);
		formData.append('has_header', String(csvOptions.has_header));
		formData.append('skip_rows', String(csvOptions.skip_rows));
		formData.append('encoding', csvOptions.encoding);
	}

	return apiRequest<DataSource>('/v1/datasource/upload', {
		method: 'POST',
		body: formData
	}).mapErr((error) => {
		if (error.type === 'network') {
			return createApiError('network', error.message || 'Upload failed');
		}
		return error;
	});
}

export interface BulkUploadResult {
	name: string;
	success: boolean;
	datasource?: DataSource;
	error?: string;
}

export interface BulkUploadResponse {
	results: BulkUploadResult[];
	total: number;
	successful: number;
	failed: number;
}

export function uploadBulkFiles(
	files: File[],
	csvOptions?: CSVOptions
): ResultAsync<BulkUploadResponse, ApiError> {
	const formData = new FormData();
	files.forEach((file) => formData.append('files', file));

	if (csvOptions) {
		formData.append('delimiter', csvOptions.delimiter);
		formData.append('quote_char', csvOptions.quote_char);
		formData.append('has_header', String(csvOptions.has_header));
		formData.append('skip_rows', String(csvOptions.skip_rows));
		formData.append('encoding', csvOptions.encoding);
	}

	return apiRequest<BulkUploadResponse>('/v1/datasource/upload/bulk', {
		method: 'POST',
		body: formData
	}).mapErr((error) => {
		if (error.type === 'network') {
			return createApiError('network', error.message || 'Bulk upload failed');
		}
		return error;
	});
}

export function connectIcebergPath(
	name: string,
	metadataPath: string
): ResultAsync<DataSource, ApiError> {
	return apiRequest<DataSource>('/v1/datasource/connect', {
		method: 'POST',
		body: JSON.stringify({
			name,
			source_type: 'iceberg',
			config: {
				metadata_path: metadataPath
			}
		})
	});
}

export interface FileListItem {
	name: string;
	path: string;
	is_dir: boolean;
}

export interface FileListResponse {
	base_path: string;
	entries: FileListItem[];
}

export function listDataFiles(path?: string): ResultAsync<FileListResponse, ApiError> {
	const params = new URLSearchParams();
	if (path) {
		params.set('path', path);
	}
	const suffix = params.toString() ? `?${params.toString()}` : '';
	return apiRequest<FileListResponse>(`/v1/datasource/file/list${suffix}`, {
		method: 'GET'
	});
}

export function connectDatabase(
	name: string,
	connectionString: string,
	query: string
): ResultAsync<DataSource, ApiError> {
	return apiRequest<DataSource>('/v1/datasource/connect', {
		method: 'POST',
		body: JSON.stringify({
			name,
			source_type: 'database',
			config: { connection_string: connectionString, query }
		})
	});
}

export function connectIceberg(
	name: string,
	config: IcebergDataSourceConfig
): ResultAsync<DataSource, ApiError> {
	return apiRequest<DataSource>('/v1/datasource/connect', {
		method: 'POST',
		body: JSON.stringify({
			name,
			source_type: 'iceberg',
			config
		})
	});
}

export function connectAnalysisDatasource(
	name: string,
	analysisId: string
): ResultAsync<DataSource, ApiError> {
	return apiRequest<DataSource>('/v1/datasource/connect', {
		method: 'POST',
		body: JSON.stringify({
			name,
			source_type: 'analysis',
			config: { analysis_id: analysisId }
		})
	});
}

export function resolveIcebergMetadata(
	metadataPath: string
): ResultAsync<{ metadata_path: string }, ApiError> {
	const params = new URLSearchParams({ metadata_path: metadataPath });
	return apiRequest<{ metadata_path: string }>(
		`/v1/datasource/iceberg/resolve?${params.toString()}`,
		{
			method: 'GET'
		}
	);
}

export function refreshDatasource(datasourceId: string): ResultAsync<DataSource, ApiError> {
	return apiRequest<DataSource>(`/v1/datasource/${datasourceId}/refresh`, {
		method: 'POST'
	});
}

export interface IcebergSnapshotInfo {
	snapshot_id: string;
	timestamp_ms: number;
	parent_snapshot_id?: string | null;
	operation?: string | null;
}

export interface IcebergSnapshotsResponse {
	datasource_id: string;
	table_path: string;
	snapshots: IcebergSnapshotInfo[];
}

export function listIcebergSnapshots(
	datasourceId: string
): ResultAsync<IcebergSnapshotsResponse, ApiError> {
	return apiRequest<IcebergSnapshotsResponse>(`/v1/compute/iceberg/${datasourceId}/snapshots`);
}

export interface SnapshotPreview {
	columns: string[];
	column_types: Record<string, string>;
	data: Array<Record<string, unknown>>;
	row_count: number;
}

export interface ColumnStats {
	column: string;
	dtype: string;
	null_count: number;
	unique_count?: number | null;
	min?: unknown | null;
	max?: unknown | null;
}

export interface SchemaDiff {
	column: string;
	status: 'added' | 'removed' | 'type_changed';
	type_a?: string | null;
	type_b?: string | null;
}

export interface SnapshotCompareResponse {
	datasource_id: string;
	snapshot_a: string;
	snapshot_b: string;
	row_count_a: number;
	row_count_b: number;
	row_count_delta: number;
	schema_diff: SchemaDiff[];
	stats_a: ColumnStats[];
	stats_b: ColumnStats[];
	preview_a: SnapshotPreview;
	preview_b: SnapshotPreview;
}

export function compareDatasourceSnapshots(
	datasourceId: string,
	snapshotA: string,
	snapshotB: string,
	rowLimit: number = 100
): ResultAsync<SnapshotCompareResponse, ApiError> {
	return apiRequest<SnapshotCompareResponse>(`/v1/datasource/${datasourceId}/compare-snapshots`, {
		method: 'POST',
		body: JSON.stringify({
			snapshot_a: snapshotA,
			snapshot_b: snapshotB,
			row_limit: rowLimit
		})
	});
}

export function listDatasources(includeHidden?: boolean): ResultAsync<DataSource[], ApiError> {
	const params = new URLSearchParams();
	if (includeHidden) {
		params.set('include_hidden', 'true');
	}
	const suffix = params.toString() ? `?${params.toString()}` : '';
	return apiRequest<DataSource[]>(`/v1/datasource${suffix}`);
}

export function getDatasource(id: string): ResultAsync<DataSource, ApiError> {
	return apiRequest<DataSource>(`/v1/datasource/${id}`);
}

export function getDatasourceSchema(id: string): ResultAsync<SchemaInfo, ApiError>;
export function getDatasourceSchema(
	id: string,
	options: { sheetName?: string; refresh?: boolean }
): ResultAsync<SchemaInfo, ApiError>;
export function getDatasourceSchema(
	id: string,
	options?: { sheetName?: string; refresh?: boolean }
): ResultAsync<SchemaInfo, ApiError> {
	const params = new URLSearchParams();
	if (options?.sheetName) {
		params.set('sheet_name', options.sheetName);
	}
	if (options?.refresh) {
		params.set('refresh', 'true');
	}
	const suffix = params.toString() ? `?${params.toString()}` : '';
	return apiRequest<SchemaInfo>(`/v1/datasource/${id}/schema${suffix}`);
}

export interface HistogramBin {
	start: number;
	end: number;
	count: number;
}

export interface ColumnStatsResponse {
	column: string;
	dtype: string;
	count: number;
	null_count: number;
	null_percentage: number;
	unique?: number | null;
	mean?: number | null;
	std?: number | null;
	min?: number | string | null;
	max?: number | string | null;
	median?: number | null;
	q25?: number | null;
	q75?: number | null;
	true_count?: number | null;
	false_count?: number | null;
	min_length?: number | null;
	max_length?: number | null;
	avg_length?: number | null;
	top_values?: Array<Record<string, unknown>> | null;
	histogram?: HistogramBin[] | null;
}

export function getColumnStats(
	datasourceId: string,
	columnName: string,
	options?: { sample?: boolean; datasource_config?: Record<string, unknown> }
): ResultAsync<ColumnStatsResponse, ApiError> {
	const params = new URLSearchParams();
	if (options?.sample === false) {
		params.set('sample', 'false');
	}
	const payload = options?.datasource_config ?? null;
	const suffix = params.toString() ? `?${params.toString()}` : '';
	if (!payload) {
		return apiRequest<ColumnStatsResponse>(
			`/v1/datasource/${datasourceId}/column/${encodeURIComponent(columnName)}/stats${suffix}`
		);
	}
	return apiRequest<ColumnStatsResponse>(
		`/v1/datasource/${datasourceId}/column/${encodeURIComponent(columnName)}/stats${suffix}`,
		{
			method: 'POST',
			body: JSON.stringify({ datasource_config: payload })
		}
	);
}

export function deleteDatasource(id: string): ResultAsync<void, ApiError> {
	return apiRequest<void>(`/v1/datasource/${id}`, {
		method: 'DELETE'
	});
}

export interface DataSourceUpdate {
	name?: string;
	config?: Record<string, unknown>;
	is_hidden?: boolean;
}

export function updateDatasource(
	id: string,
	update: DataSourceUpdate
): ResultAsync<DataSource, ApiError> {
	return apiRequest<DataSource>(`/v1/datasource/${id}`, {
		method: 'PUT',
		body: JSON.stringify(update)
	});
}
