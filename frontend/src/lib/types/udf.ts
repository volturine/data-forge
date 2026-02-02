export interface UdfInput {
	position: number;
	dtype: string;
	label?: string | null;
}

export interface UdfSignature {
	inputs: UdfInput[];
	output_dtype?: string | null;
}

export interface Udf {
	id: string;
	name: string;
	description?: string | null;
	signature: UdfSignature;
	code: string;
	tags?: string[] | null;
	source: string;
	created_at: string;
	updated_at: string;
}

export interface UdfCreate {
	name: string;
	description?: string | null;
	signature: UdfSignature;
	code: string;
	tags?: string[] | null;
	source?: string | null;
}

export interface UdfUpdate {
	name?: string | null;
	description?: string | null;
	signature?: UdfSignature | null;
	code?: string | null;
	tags?: string[] | null;
	source?: string | null;
}

export interface UdfClone {
	name?: string | null;
}

export interface UdfExport {
	udfs: Udf[];
}

export interface UdfImportItem {
	name: string;
	description?: string | null;
	signature: UdfSignature;
	code: string;
	tags?: string[] | null;
	source?: string | null;
}

export interface UdfImport {
	udfs: UdfImportItem[];
	overwrite?: boolean;
}
