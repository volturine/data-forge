export interface ColumnSchema {
	name: string;
	dtype: string;
	nullable: boolean;
}

export interface SchemaInfo {
	columns: ColumnSchema[];
	row_count: number | null;
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
	created_at: string;
}
