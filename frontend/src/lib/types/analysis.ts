import type { Schema } from './schema';
import type { PipelineStepType } from './pipeline-step';

export interface AnalysisTabTimeTravelUIConfig {
	open?: boolean;
	month?: string;
	day?: string;
	[key: string]: unknown;
}

export interface AnalysisTabDatasourceConfig {
	branch: string;
	time_travel_snapshot_id?: string | null;
	time_travel_snapshot_timestamp_ms?: number | null;
	time_travel_ui?: AnalysisTabTimeTravelUIConfig;
	snapshot_id?: string | null;
	snapshot_timestamp_ms?: number | null;
	[key: string]: unknown;
}

export interface AnalysisTabIcebergConfig {
	namespace?: string;
	table_name?: string;
	branch?: string;
	[key: string]: unknown;
}

export interface AnalysisTabNotificationConfig {
	method?: string;
	body_template?: string;
	[key: string]: unknown;
}

export interface PipelineStep {
	id: string;
	type: PipelineStepType;
	config: Record<string, unknown>;
	depends_on?: string[];
	is_applied?: boolean;
	inputSchema?: Schema;
	outputSchema?: Schema;
}

export interface AnalysisTabDatasource {
	id: string;
	analysis_tab_id: string | null;
	config: AnalysisTabDatasourceConfig;
}

export interface AnalysisTabOutput {
	result_id: string;
	format: string;
	filename: string;
	build_mode?: string;
	iceberg?: AnalysisTabIcebergConfig;
	notification?: AnalysisTabNotificationConfig | null;
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
	tabs: AnalysisTab[];
}

export interface Analysis {
	id: string;
	name: string;
	description: string | null;
	pipeline_definition: Record<string, unknown>;
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
