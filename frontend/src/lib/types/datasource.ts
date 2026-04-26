export interface ColumnSchema {
	name: string;
	dtype: string;
	nullable: boolean;
	sample_value?: string | null;
	description?: string | null;
}

export interface SchemaInfo {
	columns: ColumnSchema[];
	row_count: number | null;
	sheet_names?: string[] | null;
}

export interface CSVOptions {
	delimiter: string;
	quote_char: string;
	has_header: boolean;
	skip_rows: number;
	encoding: string;
}

export interface FileDataSourceConfig {
	[key: string]: unknown;
	file_path: string;
	file_type: string;
	options?: Record<string, unknown>;
	csv_options?: CSVOptions | null;
	sheet_name?: string | null;
	start_row?: number | null;
	start_col?: number | null;
	end_col?: number | null;
	end_row?: number | null;
	has_header?: boolean | null;
	table_name?: string | null;
	named_range?: string | null;
	cell_range?: string | null;
}

export interface DatabaseDataSourceConfig {
	[key: string]: unknown;
	connection_string: string;
	query: string;
	branch?: string | null;
}

export interface IcebergDataSourceConfig {
	[key: string]: unknown;
	metadata_path: string;
	branch?: string | null;
	branches?: string[] | null;
	snapshot_id?: string | null;
	snapshot_timestamp_ms?: number | null;
	storage_options?: Record<string, string> | null;
	reader?: string | null;
	catalog_type?: string | null;
	catalog_uri?: string | null;
	warehouse?: string | null;
	namespace?: string | null;
	table?: string | null;
	source?: Record<string, unknown> | null;
	refresh?: Record<string, unknown> | null;
}

export interface AnalysisDataSourceConfig {
	[key: string]: unknown;
	analysis_id: string;
	analysis_tab_id?: string | null;
}

export type SourceType = 'file' | 'database' | 'iceberg' | 'analysis';

export type DataSourceConfig =
	| FileDataSourceConfig
	| DatabaseDataSourceConfig
	| IcebergDataSourceConfig
	| AnalysisDataSourceConfig;

interface DataSourceBase {
	id: string;
	name: string;
	description: string | null;
	schema_cache?: Record<string, unknown> | null;
	created_by_analysis_id?: string | null;
	created_by: string;
	is_hidden: boolean;
	created_at: string;
	output_of_tab_id?: string | null;
}

export interface FileDataSource extends DataSourceBase {
	source_type: 'file';
	config: FileDataSourceConfig;
}

export interface DatabaseDataSource extends DataSourceBase {
	source_type: 'database';
	config: DatabaseDataSourceConfig;
}

export interface IcebergDataSource extends DataSourceBase {
	source_type: 'iceberg';
	config: IcebergDataSourceConfig;
}

export interface AnalysisDataSource extends DataSourceBase {
	source_type: 'analysis';
	config: AnalysisDataSourceConfig;
}

export type DataSource =
	| FileDataSource
	| DatabaseDataSource
	| IcebergDataSource
	| AnalysisDataSource;

export interface DataSourceCreate {
	name: string;
	description?: string | null;
	source_type: SourceType;
	config: DataSourceConfig;
}
