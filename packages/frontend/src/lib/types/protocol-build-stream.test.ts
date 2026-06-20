import { describe, expect, test } from 'vitest';
import type { BuildEventJson } from '$lib/protocol/dataforge_protocol/compute_pb';
import {
	BUILD_LOG_LEVEL_JSON_TOKENS,
	BUILD_TAB_STATUS_JSON_TOKENS,
	ENGINE_RUN_KIND_JSON_TOKENS
} from '$lib/types/protocol-enum-tokens';
import { isProtocolBuildEvent, protocolBuildEventToBuildEvent } from './protocol-build-stream';

const BASE_CONTEXT = {
	buildId: 'build-1',
	analysisId: 'analysis-1',
	emittedAt: '2025-01-01T00:00:00Z',
	sequence: 7,
	currentKind: 'ENGINE_RUN_KIND_BUILD',
	currentDatasourceId: 'ds-1',
	tabId: 'tab-1',
	tabName: 'Tab 1',
	currentOutputId: 'out-1',
	currentOutputName: 'Output 1',
	engineRunId: 'engine-1'
} satisfies NonNullable<BuildEventJson['context']>;

describe('protocol build stream conversion', () => {
	test('converts generated progress event JSON to UI build event shape', () => {
		const protocolEvent = {
			context: BASE_CONTEXT,
			namespace: 'default',
			progress: {
				progress: 0.5,
				elapsedMs: 1200,
				estimatedRemainingMs: 800,
				currentStep: 'Filter rows',
				currentStepIndex: 1,
				totalSteps: 4
			}
		} satisfies BuildEventJson;

		expect(isProtocolBuildEvent(protocolEvent)).toBe(true);
		expect(protocolBuildEventToBuildEvent(protocolEvent)).toEqual({
			type: 'progress',
			build_id: 'build-1',
			analysis_id: 'analysis-1',
			emitted_at: '2025-01-01T00:00:00Z',
			sequence: 7,
			current_kind: 'build',
			current_datasource_id: 'ds-1',
			tab_id: 'tab-1',
			tab_name: 'Tab 1',
			current_output_id: 'out-1',
			current_output_name: 'Output 1',
			engine_run_id: 'engine-1',
			progress: 0.5,
			elapsed_ms: 1200,
			estimated_remaining_ms: 800,
			current_step: 'Filter rows',
			current_step_index: 1,
			total_steps: 4
		});
	});

	test('rejects legacy flat build event JSON', () => {
		expect(
			isProtocolBuildEvent({
				type: 'progress',
				build_id: 'build-1',
				analysis_id: 'analysis-1',
				emitted_at: '2025-01-01T00:00:00Z'
			})
		).toBe(false);
	});

	test('uses protocol enum JSON token tables for generated build stream enums', () => {
		expect(ENGINE_RUN_KIND_JSON_TOKENS.ENGINE_RUN_KIND_ROW_COUNT).toBe('row_count');
		expect(ENGINE_RUN_KIND_JSON_TOKENS.ENGINE_RUN_KIND_UNSPECIFIED).toBeNull();
		expect(BUILD_TAB_STATUS_JSON_TOKENS.BUILD_TAB_STATUS_FAILED).toBe('failed');
		expect(BUILD_TAB_STATUS_JSON_TOKENS.BUILD_TAB_STATUS_UNSPECIFIED).toBeNull();
		expect(BUILD_LOG_LEVEL_JSON_TOKENS.BUILD_LOG_LEVEL_WARNING).toBe('warning');
		expect(BUILD_LOG_LEVEL_JSON_TOKENS.BUILD_LOG_LEVEL_UNSPECIFIED).toBeNull();
	});
});
