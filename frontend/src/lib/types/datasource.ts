export interface ColumnSchema {
	name: string;
	dtype: string;
	nullable: boolean;
	sample_value?: string | null;
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
}

export interface DatabaseDataSourceConfig {
	connection_string: string;
	query: string;
}

export interface APIDataSourceConfig {
	url: string;
	method?: string;
	headers?: Record<string, string> | null;
	auth?: Record<string, unknown> | null;
}

export interface DuckDBDataSourceConfig {
	db_path: string | null;
	query: string;
	read_only?: boolean;
}

export interface IcebergDataSourceConfig {
	metadata_path: string;
	snapshot_id?: string | null;
	snapshot_timestamp_ms?: number | null;
	storage_options?: Record<string, string> | null;
	reader?: string | null;
}

export interface AnalysisDataSourceConfig {
	analysis_id: string;
	analysis_tab_id?: string | null;
}

export interface DataSourceCreate {
	name: string;
	source_type: string;
	config: Record<string, unknown>;
}

export interface DataSource {
	id: string;
	name: string;
	source_type: string;
	config: Record<string, unknown>;
	schema_cache: Record<string, unknown> | null;
	created_by_analysis_id?: string | null;
	is_hidden: boolean;
	created_at: string;
}
