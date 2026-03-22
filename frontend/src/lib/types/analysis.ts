import type { Schema } from './schema';

export interface PipelineStep {
	id: string;
	type: string;
	config: Record<string, unknown>;
	depends_on?: string[];
	is_applied?: boolean;
	inputSchema?: Schema;
	outputSchema?: Schema;
}

export interface AnalysisTabDatasource {
	id: string;
	analysis_tab_id: string | null;
	config: { branch: string } & Record<string, unknown>;
}

export interface AnalysisTabOutput {
	result_id: string;
	format: string;
	filename: string;
	build_mode?: string;
	iceberg?: Record<string, unknown>;
	[key: string]: unknown;
}

export interface AnalysisTab {
	id: string;
	name: string;
	parent_id: string | null;
	datasource: AnalysisTabDatasource;
	output: AnalysisTabOutput;
	steps: PipelineStep[];
}

export interface AnalysisCreate {
	name: string;
	description?: string | null;
	tabs: AnalysisTab[];
}

export interface AnalysisUpdate {
	name?: string | null;
	description?: string | null;
	status?: string | null;
	tabs: AnalysisTab[];
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
	version?: string | null;
}

export interface AnalysisGalleryItem {
	id: string;
	name: string;
	thumbnail: string | null;
	created_at: string;
	updated_at: string;
}
