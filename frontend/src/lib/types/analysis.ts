export interface PipelineStep {
	id: string;
	type: string;
	config: Record<string, unknown>;
	depends_on: string[];
}

export interface AnalysisCreate {
	name: string;
	description?: string | null;
	datasource_ids: string[];
	pipeline_steps: PipelineStep[];
}

export interface AnalysisUpdate {
	name?: string | null;
	description?: string | null;
	pipeline_steps?: PipelineStep[] | null;
	status?: string | null;
}

export interface Analysis {
	id: string;
	name: string;
	description: string | null;
	pipeline_definition: Record<string, unknown>;
	status: string;
	created_at: string;
	updated_at: string;
	result_path: string | null;
	thumbnail: string | null;
}

export interface AnalysisGalleryItem {
	id: string;
	name: string;
	thumbnail: string | null;
	created_at: string;
	updated_at: string;
	row_count: number | null;
	column_count: number | null;
}
