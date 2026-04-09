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

export type AnalysisVariableType =
	| 'string'
	| 'number'
	| 'boolean'
	| 'single_select'
	| 'multi_select'
	| 'date'
	| 'date_range';

export interface AnalysisVariableOption {
	label: string;
	value: string | number | boolean;
}

export interface AnalysisVariableOptionSource {
	tab_id: string;
	column: string;
	limit: number;
}

export interface AnalysisDateRangeValue {
	start: string;
	end: string;
}

export interface AnalysisVariableDefinition {
	id: string;
	label: string;
	type: AnalysisVariableType;
	default_value:
		| string
		| number
		| boolean
		| Array<string | number | boolean>
		| AnalysisDateRangeValue;
	required: boolean;
	options: AnalysisVariableOption[];
	option_source?: AnalysisVariableOptionSource | null;
}

export interface DashboardLayoutItem {
	widget_id: string;
	x: number;
	y: number;
	w: number;
	h: number;
}

export type DashboardWidgetType = 'dataset_preview' | 'chart' | 'metric_kpi' | 'text_header';
export type DashboardSelectionValue = string | number | boolean;

export interface DashboardWidget {
	id: string;
	type: DashboardWidgetType;
	title: string;
	description?: string | null;
	source_tab_id?: string | null;
	config: Record<string, unknown>;
}

export interface DashboardDefinition {
	id: string;
	name: string;
	description: string | null;
	layout: DashboardLayoutItem[];
	widgets: DashboardWidget[];
}

export interface AnalysisVariableRef {
	kind: 'variable_ref';
	variable_id: string;
	value_key?: 'start' | 'end';
}

export interface DashboardWidgetPage {
	page: number;
	page_size: number;
}

export interface DashboardSelectionFilter {
	column: string;
	values: DashboardSelectionValue[];
}

export interface DashboardDetailResponse {
	analysis_id: string;
	dashboard: DashboardDefinition;
	variables: AnalysisVariableDefinition[];
	widget_dependencies: Record<string, string[]>;
}

export interface DashboardDatasetResult {
	columns: string[];
	column_types: Record<string, string>;
	rows: Array<Record<string, unknown>>;
	row_count: number;
	page: number;
	page_size: number;
}

export interface DashboardChartResult {
	schema: Record<string, string>;
	data: Array<Record<string, unknown>>;
	config: Record<string, unknown>;
	metadata: Record<string, unknown>;
}

export interface DashboardMetricResult {
	label: string;
	value: string | number;
	comparison?: string | number | null;
}

export interface DashboardHeaderResult {
	text: string;
	level: number;
}

export interface DashboardWidgetRunResult {
	widget_id: string;
	type: DashboardWidgetType;
	title: string;
	source_tab_id?: string | null;
	variable_ids: string[];
	status: 'success' | 'empty' | 'error';
	last_refresh_at: string;
	variable_state: Record<string, unknown>;
	dataset?: DashboardDatasetResult | null;
	chart?: DashboardChartResult | null;
	metric?: DashboardMetricResult | null;
	header?: DashboardHeaderResult | null;
	error?: string | null;
}

export interface DashboardRunResponse {
	analysis_id: string;
	dashboard_id: string;
	variable_state: Record<string, unknown>;
	widget_dependencies: Record<string, string[]>;
	widgets: DashboardWidgetRunResult[];
}

export interface AnalysisCreate {
	name: string;
	description?: string | null;
	tabs: AnalysisTab[];
	variables?: AnalysisVariableDefinition[];
	dashboards?: DashboardDefinition[];
}

export interface AnalysisUpdate {
	name?: string | null;
	description?: string | null;
	status?: string | null;
	tabs: AnalysisTab[];
	variables?: AnalysisVariableDefinition[];
	dashboards?: DashboardDefinition[];
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
