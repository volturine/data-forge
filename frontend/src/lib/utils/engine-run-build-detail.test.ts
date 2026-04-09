import { describe, expect, it } from 'vitest';

import type { EngineRun } from '$lib/api/engine-runs';
import {
	engineRunBuildDetail,
	engineRunDatasourceId,
	engineRunDatasourceName,
	engineRunOutputName,
	engineRunStatus
} from '$lib/utils/engine-run-build-detail';

function makeRun(overrides: Partial<EngineRun> = {}): EngineRun {
	return {
		id: 'run-1',
		analysis_id: 'analysis-1',
		datasource_id: 'output-ds-1',
		kind: 'datasource_update',
		status: 'running',
		request_json: {},
		result_json: {
			current_output_id: 'output-ds-1',
			current_output_name: 'output_salary_predictions',
			source_datasource_id: 'input-ds-1',
			source_datasource_name: 'Source 1',
			current_tab_id: 'tab-1',
			current_tab_name: 'View',
			total_steps: 3,
			total_tabs: 1,
			current_step_index: 1,
			estimated_remaining_ms: 500,
			resource_config: {
				max_threads: 8,
				max_memory_mb: 512,
				streaming_chunk_size: 1000
			},
			steps: [
				{
					build_step_index: 0,
					step_index: 0,
					step_id: 'tab-1:initial_read',
					step_name: 'Initial Read',
					step_type: 'read',
					state: 'completed',
					duration_ms: 12
				}
			],
			resources: [
				{
					sampled_at: '2026-04-08T12:00:00Z',
					cpu_percent: 25,
					memory_mb: 128,
					memory_limit_mb: 512,
					active_threads: 4,
					max_threads: 8
				}
			],
			logs: [
				{
					timestamp: '2026-04-08T12:00:00Z',
					level: 'info',
					message: 'Running build'
				}
			],
			results: [
				{
					tab_id: 'tab-1',
					tab_name: 'View',
					status: 'success',
					output_id: 'output-ds-1',
					output_name: 'output_salary_predictions'
				}
			]
		},
		error_message: null,
		created_at: '2026-04-08T12:00:00Z',
		completed_at: null,
		duration_ms: 200,
		step_timings: {},
		query_plan: null,
		progress: 0.5,
		current_step: 'Filter rows',
		triggered_by: 'user',
		execution_entries: [],
		...overrides
	};
}

describe('engineRunBuildDetail', () => {
	it('maps persisted running rows into build preview detail', () => {
		const run = makeRun();
		const detail = engineRunBuildDetail(run);

		expect(engineRunStatus(run)).toBe('running');
		expect(engineRunOutputName(run)).toBe('output_salary_predictions');
		expect(engineRunDatasourceId(run)).toBe('input-ds-1');
		expect(engineRunDatasourceName(run)).toBe('Source 1');
		expect(detail.status).toBe('running');
		expect(detail.current_output_name).toBe('output_salary_predictions');
		expect(detail.steps[0]?.step_name).toBe('Initial Read');
		expect(detail.latest_resources?.cpu_percent).toBe(25);
		expect(detail.logs[0]?.message).toBe('Running build');
		expect(detail.resource_config).toEqual({
			max_threads: 8,
			max_memory_mb: 512,
			streaming_chunk_size: 1000
		});
		expect(detail.results[0]?.output_name).toBe('output_salary_predictions');
	});

	it('maps failed rows to failed detail state', () => {
		const run = makeRun({ status: 'failed', error_message: 'boom' });
		const detail = engineRunBuildDetail(run);

		expect(engineRunStatus(run)).toBe('failed');
		expect(detail.status).toBe('failed');
		expect(detail.error).toBe('boom');
	});
});
