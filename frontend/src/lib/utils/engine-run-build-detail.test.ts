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
		execution_entries: [
			{
				key: 'initial_read',
				label: 'Initial Read',
				category: 'read',
				order: 0,
				duration_ms: 12,
				share_pct: 6.0,
				optimized_plan: null,
				unoptimized_plan: null,
				metadata: null
			},
			{
				key: 'view_0',
				label: 'View',
				category: 'step',
				order: 1,
				duration_ms: 0,
				share_pct: 0,
				optimized_plan: null,
				unoptimized_plan: null,
				metadata: { step_type: 'view' }
			},
			{
				key: 'write_output',
				label: 'Write Output',
				category: 'write',
				order: 2,
				duration_ms: 13,
				share_pct: 6.5,
				optimized_plan: null,
				unoptimized_plan: null,
				metadata: null
			}
		],
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
		expect(detail.steps).toHaveLength(3);
		expect(detail.current_engine_run_id).toBe('run-1');
		expect(detail.steps).toHaveLength(3);
		expect(detail.steps[0]?.step_name).toBe('Initial Read');
		expect(detail.steps[0]?.duration_ms).toBe(12);
		expect(detail.steps[1]?.step_name).toBe('View');
		expect(detail.steps[2]?.step_name).toBe('Write Output');
		expect(detail.latest_resources?.cpu_percent).toBe(25);
		expect(detail.logs[0]?.message).toBe('Running build');
		expect(detail.resource_config).toEqual({
			max_threads: 8,
			max_memory_mb: 512,
			streaming_chunk_size: 1000
		});
		expect(detail.results[0]?.output_name).toBe('output_salary_predictions');
		expect(detail.cancelled_at).toBeNull();
		expect(detail.cancelled_by).toBeNull();
	});

	it('maps failed rows to failed detail state', () => {
		const run = makeRun({ status: 'failed', error_message: 'boom' });
		const detail = engineRunBuildDetail(run);

		expect(engineRunStatus(run)).toBe('failed');
		expect(detail.status).toBe('failed');
		expect(detail.error).toBe('boom');
	});

	it('maps cancelled rows to cancelled detail state', () => {
		const run = makeRun({
			status: 'cancelled',
			error_message: 'Cancelled by test@example.com',
			result_json: {
				cancelled_at: '2026-04-10T10:15:00Z',
				cancelled_by: 'test@example.com',
				last_completed_step: 'Filter rows',
				results: []
			}
		});
		const detail = engineRunBuildDetail(run);

		expect(engineRunStatus(run)).toBe('cancelled');
		expect(detail.status).toBe('cancelled');
		expect(detail.cancelled_at).toBe('2026-04-10T10:15:00Z');
		expect(detail.cancelled_by).toBe('test@example.com');
	});

	it('uses persisted latest_resources when full resource history is absent', () => {
		const run = makeRun({
			status: 'success',
			result_json: {
				current_output_id: 'output-ds-1',
				current_output_name: 'output_salary_predictions',
				latest_resources: {
					sampled_at: '2026-04-08T12:01:00Z',
					cpu_percent: 62,
					memory_mb: 256,
					memory_limit_mb: 512,
					active_threads: 6,
					max_threads: 8
				},
				resources: []
			}
		});
		const detail = engineRunBuildDetail(run);

		expect(detail.status).toBe('completed');
		expect(detail.resources).toEqual([]);
		expect(detail.latest_resources?.cpu_percent).toBe(62);
		expect(detail.latest_resources?.memory_mb).toBe(256);
	});

	it('ignores incomplete persisted resource and log entries instead of defaulting fields', () => {
		const run = makeRun({
			result_json: {
				resources: [
					{
						cpu_percent: 62,
						memory_mb: 256,
						active_threads: 6
					}
				],
				latest_resources: {
					cpu_percent: 30,
					memory_mb: 120,
					active_threads: 2
				},
				logs: [
					{
						message: 'missing required fields'
					}
				],
				results: [
					{
						status: 'success',
						output_name: 'missing tab metadata'
					}
				]
			}
		});
		const detail = engineRunBuildDetail(run);

		expect(detail.resources).toEqual([]);
		expect(detail.latest_resources).toBeNull();
		expect(detail.logs).toEqual([]);
		expect(detail.results).toEqual([]);
	});

	it('does not fall back output name from datasource_name', () => {
		const run = makeRun({
			result_json: {
				datasource_name: 'should-not-be-used'
			}
		});

		expect(engineRunOutputName(run)).toBeNull();
	});
});
