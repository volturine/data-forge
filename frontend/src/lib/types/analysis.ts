export interface PipelineStep {
	id: string;
	type: string;
	config: Record<string, unknown>;
	depends_on: string[];
}

export type AnalysisTabType = 'datasource' | 'derived';

export interface AnalysisTab {
	id: string;
	name: string;
	type: AnalysisTabType;
	parent_id: string | null;
	datasource_id: string | null;
}

export interface AnalysisCreate {
	name: string;
	description?: string | null;
	datasource_ids: string[];
	pipeline_steps: PipelineStep[];
	tabs: AnalysisTab[];
}

export interface AnalysisUpdate {
	name?: string | null;
	description?: string | null;
	pipeline_steps?: PipelineStep[] | null;
	status?: string | null;
	tabs?: AnalysisTab[] | null;
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
	tabs: AnalysisTab[];
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
