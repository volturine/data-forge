import { describe, expect, test } from 'vitest';
import {
	canQueryOutputDatasource,
	canQueryTabDatasource,
	isOutputMaterialized
} from './analysis-output-materialization';

const RESULT_ID = '550e8400-e29b-41d4-a716-446655440000';

describe('isOutputMaterialized', () => {
	test('true only for explicit true', () => {
		expect(isOutputMaterialized({ materialized: true })).toBe(true);
		expect(isOutputMaterialized({ materialized: false })).toBe(false);
		expect(isOutputMaterialized({ materialized: null })).toBe(false);
		expect(isOutputMaterialized({})).toBe(false);
		expect(isOutputMaterialized(null)).toBe(false);
		expect(isOutputMaterialized(undefined)).toBe(false);
	});
});

describe('canQueryOutputDatasource', () => {
	test('requires uuid result_id and materialized true', () => {
		expect(canQueryOutputDatasource({ resultId: RESULT_ID, materialized: true })).toBe(true);
	});

	test('blocks reserved-but-unmaterialized outputs', () => {
		expect(canQueryOutputDatasource({ resultId: RESULT_ID, materialized: false })).toBe(false);
		expect(canQueryOutputDatasource({ resultId: RESULT_ID })).toBe(false);
		expect(canQueryOutputDatasource({ resultId: RESULT_ID, materialized: null })).toBe(false);
	});

	test('blocks missing or non-uuid ids', () => {
		expect(canQueryOutputDatasource({ resultId: null, materialized: true })).toBe(false);
		expect(canQueryOutputDatasource({ resultId: '', materialized: true })).toBe(false);
		expect(canQueryOutputDatasource({ resultId: 'not-a-uuid', materialized: true })).toBe(false);
	});
});

describe('canQueryTabDatasource', () => {
	const tabs = [
		{
			id: 'tab-upstream',
			output: { materialized: false as boolean | undefined }
		},
		{
			id: 'tab-built',
			output: { materialized: true as boolean | undefined }
		}
	];

	test('allows raw inputs without analysis_tab_id', () => {
		expect(
			canQueryTabDatasource({
				datasourceId: 'ds-1',
				analysisTabId: null,
				tabs
			})
		).toBe(true);
	});

	test('blocks derived inputs until upstream output is materialized', () => {
		expect(
			canQueryTabDatasource({
				datasourceId: RESULT_ID,
				analysisTabId: 'tab-upstream',
				tabs
			})
		).toBe(false);
	});

	test('allows derived inputs after upstream materialization', () => {
		expect(
			canQueryTabDatasource({
				datasourceId: RESULT_ID,
				analysisTabId: 'tab-built',
				tabs
			})
		).toBe(true);
	});

	test('blocks when upstream tab is missing or datasource id empty', () => {
		expect(
			canQueryTabDatasource({
				datasourceId: RESULT_ID,
				analysisTabId: 'missing-tab',
				tabs
			})
		).toBe(false);
		expect(
			canQueryTabDatasource({
				datasourceId: null,
				analysisTabId: null,
				tabs
			})
		).toBe(false);
	});
});
