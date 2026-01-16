export interface Column {
	name: string;
	dtype: string;
	nullable: boolean;
}

export interface Schema {
	columns: Column[];
	row_count: number | null;
}
