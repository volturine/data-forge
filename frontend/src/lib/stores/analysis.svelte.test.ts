import { describe, it, expect, vi, beforeEach } from 'vitest';
import { analysisStore } from './analysis.svelte';
import * as analysisApi from '$lib/api/analysis';
import { schemaCalculator } from '$lib/utils/schema';
import type { Analysis, PipelineStep } from '$lib/types/analysis';
import type { SchemaInfo } from '$lib/types/datasource';

// Mock the analysis API
vi.mock('$lib/api/analysis');

describe('analysis.svelte store', () => {
	const mockAnalysis: Analysis = {
		id: 'test-123',
		name: 'Test Analysis',
		description: 'A test analysis',
		pipeline_definition: {
			steps: [
				{
					id: 'step-1',
					type: 'filter',
					config: { conditions: [] },
					depends_on: []
				},
				{
					id: 'step-2',
					type: 'select',
					config: { columns: ['id', 'name'] },
					depends_on: ['step-1']
				}
			],
			datasource_ids: ['source-1'],
			tabs: [
				{
					id: 'tab-1',
					name: 'Source 1',
					type: 'datasource',
					parent_id: null,
					datasource_id: 'source-1'
				}
			]
		},
		status: 'active',
		created_at: '2024-01-15T10:00:00Z',
		updated_at: '2024-01-16T15:30:00Z',
		result_path: null,
		thumbnail: null,
		tabs: [
			{
				id: 'tab-1',
				name: 'Source 1',
				type: 'datasource',
				parent_id: null,
				datasource_id: 'source-1'
			}
		]
	};


	const mockSchema: SchemaInfo = {
		columns: [
			{ name: 'id', dtype: 'Int64', nullable: false },
			{ name: 'name', dtype: 'String', nullable: true },
			{ name: 'age', dtype: 'Int32', nullable: false }
		],
		row_count: 100
	};

	beforeEach(() => {
		// Reset store state
		analysisStore.reset();
		vi.clearAllMocks();
	});

	describe('loadAnalysis', () => {
		it('should load analysis and extract pipeline steps', async () => {
			vi.mocked(analysisApi.getAnalysis).mockResolvedValue(mockAnalysis);

			await analysisStore.loadAnalysis('test-123');

			expect(analysisApi.getAnalysis).toHaveBeenCalledWith('test-123');
			expect(analysisStore.current).toEqual(mockAnalysis);
			expect(analysisStore.pipeline).toHaveLength(2);
			expect(analysisStore.pipeline[0].id).toBe('step-1');
			expect(analysisStore.pipeline[1].id).toBe('step-2');
			expect(analysisStore.loading).toBe(false);
			expect(analysisStore.error).toBe(null);
		});

		it('should handle empty pipeline definition', async () => {
			const analysisWithoutSteps: Analysis = {
				...mockAnalysis,
				pipeline_definition: {},
				tabs: []
			};

			vi.mocked(analysisApi.getAnalysis).mockResolvedValue(analysisWithoutSteps);

			await analysisStore.loadAnalysis('test-456');

			expect(analysisStore.current).toEqual(analysisWithoutSteps);
			expect(analysisStore.pipeline).toHaveLength(0);
		});

		it('should set loading state during load', async () => {
			vi.mocked(analysisApi.getAnalysis).mockImplementation(
				() =>
					new Promise((resolve) => {
						setTimeout(() => resolve(mockAnalysis), 100);
					})
			);

			const loadPromise = analysisStore.loadAnalysis('test-123');
			expect(analysisStore.loading).toBe(true);

			await loadPromise;
			expect(analysisStore.loading).toBe(false);
		});

		it('should handle load errors', async () => {
			const error = new Error('Network error');
			vi.mocked(analysisApi.getAnalysis).mockRejectedValue(error);

			await expect(analysisStore.loadAnalysis('test-123')).rejects.toThrow('Network error');

			expect(analysisStore.error).toBe('Network error');
			expect(analysisStore.loading).toBe(false);
			expect(analysisStore.current).toBe(null);
		});

		it('should handle non-Error objects in catch', async () => {
			vi.mocked(analysisApi.getAnalysis).mockRejectedValue('String error');

			await expect(analysisStore.loadAnalysis('test-123')).rejects.toBe('String error');

			expect(analysisStore.error).toBe('Failed to load analysis');
		});
	});

	describe('addStep', () => {
		it('should add a step to the pipeline', () => {
			const newStep: PipelineStep = {
				id: 'step-new',
				type: 'sort',
				config: { columns: ['name'] },
				depends_on: []
			};

			analysisStore.addStep(newStep);

			expect(analysisStore.pipeline).toHaveLength(1);
			expect(analysisStore.pipeline[0]).toEqual(newStep);
		});

		it('should append step to existing pipeline', async () => {
			vi.mocked(analysisApi.getAnalysis).mockResolvedValue(mockAnalysis);
			await analysisStore.loadAnalysis('test-123');

			const newStep: PipelineStep = {
				id: 'step-3',
				type: 'sort',
				config: { columns: ['name'] },
				depends_on: ['step-2']
			};

			analysisStore.addStep(newStep);

			expect(analysisStore.pipeline).toHaveLength(3);
			expect(analysisStore.pipeline[2]).toEqual(newStep);
		});
	});

	describe('updateStep', () => {
		beforeEach(async () => {
			vi.mocked(analysisApi.getAnalysis).mockResolvedValue(mockAnalysis);
			await analysisStore.loadAnalysis('test-123');
		});

		it('should update a step config', () => {
			const invalidateSpy = vi.spyOn(schemaCalculator, 'invalidateCache');
			analysisStore.updateStep('step-1', { config: { conditions: [{ column: 'age' }] } });

			const updatedStep = analysisStore.pipeline.find((s) => s.id === 'step-1');
			expect(updatedStep?.config).toEqual({ conditions: [{ column: 'age' }] });
			expect(invalidateSpy).toHaveBeenCalledWith(analysisStore.pipeline, ['step-1']);
		});

		it('should update step type', () => {
			analysisStore.updateStep('step-1', { type: 'unique' });

			const updatedStep = analysisStore.pipeline.find((s) => s.id === 'step-1');
			expect(updatedStep?.type).toBe('unique');
		});

		it('should update step dependencies', () => {
			analysisStore.updateStep('step-2', { depends_on: ['step-1', 'step-0'] });

			const updatedStep = analysisStore.pipeline.find((s) => s.id === 'step-2');
			expect(updatedStep?.depends_on).toEqual(['step-1', 'step-0']);
		});

		it('should not affect other steps', () => {
			const originalStep2 = { ...analysisStore.pipeline[1] };

			analysisStore.updateStep('step-1', { config: { new: 'config' } });

			expect(analysisStore.pipeline[1]).toEqual(originalStep2);
		});

		it('should do nothing if step id not found', () => {
			const originalPipeline = [...analysisStore.pipeline];

			analysisStore.updateStep('non-existent', { config: { new: 'config' } });

			expect(analysisStore.pipeline).toEqual(originalPipeline);
		});
	});

	describe('deleteStep (removeStep)', () => {
		beforeEach(async () => {
			vi.mocked(analysisApi.getAnalysis).mockResolvedValue(mockAnalysis);
			await analysisStore.loadAnalysis('test-123');
		});

		it('should remove a step from the pipeline', () => {
			analysisStore.removeStep('step-1');

			expect(analysisStore.pipeline).toHaveLength(1);
			expect(analysisStore.pipeline[0].id).toBe('step-2');
		});

		it('should do nothing if step id not found', () => {
			const originalPipeline = [...analysisStore.pipeline];

			analysisStore.removeStep('non-existent');

			expect(analysisStore.pipeline).toEqual(originalPipeline);
		});

		it('should remove step by id correctly', () => {
			analysisStore.removeStep('step-2');

			expect(analysisStore.pipeline).toHaveLength(1);
			expect(analysisStore.pipeline.find((s) => s.id === 'step-2')).toBeUndefined();
		});
	});

	describe('reorderSteps', () => {
		beforeEach(async () => {
			const analysisWithMultipleSteps: Analysis = {
				...mockAnalysis,
				pipeline_definition: {
					steps: [
						{ id: 'step-1', type: 'filter', config: {}, depends_on: [] },
						{ id: 'step-2', type: 'select', config: {}, depends_on: [] },
						{ id: 'step-3', type: 'sort', config: {}, depends_on: [] }
					],
					datasource_ids: ['source-1'],
					tabs: mockAnalysis.tabs
				},
				tabs: mockAnalysis.tabs
			};

			vi.mocked(analysisApi.getAnalysis).mockResolvedValue(analysisWithMultipleSteps);
			await analysisStore.loadAnalysis('test-123');
		});

		it('should move step from index 0 to index 2', () => {
			analysisStore.reorderSteps(0, 2);

			expect(analysisStore.pipeline[0].id).toBe('step-2');
			expect(analysisStore.pipeline[1].id).toBe('step-3');
			expect(analysisStore.pipeline[2].id).toBe('step-1');
		});

		it('should move step from index 2 to index 0', () => {
			analysisStore.reorderSteps(2, 0);

			expect(analysisStore.pipeline[0].id).toBe('step-3');
			expect(analysisStore.pipeline[1].id).toBe('step-1');
			expect(analysisStore.pipeline[2].id).toBe('step-2');
		});

		it('should move step from index 1 to index 1 (no change)', () => {
			const originalPipeline = [...analysisStore.pipeline];

			analysisStore.reorderSteps(1, 1);

			expect(analysisStore.pipeline).toEqual(originalPipeline);
		});
	});

	describe('save', () => {
		beforeEach(async () => {
			vi.mocked(analysisApi.getAnalysis).mockResolvedValue(mockAnalysis);
			await analysisStore.loadAnalysis('test-123');
		});

		it('should save updated pipeline', async () => {
			const updatedAnalysis = { ...mockAnalysis, updated_at: '2024-01-17T10:00:00Z' };
			vi.mocked(analysisApi.updateAnalysis).mockResolvedValue(updatedAnalysis);

			await analysisStore.save();

			expect(analysisApi.updateAnalysis).toHaveBeenCalledWith('test-123', {
				pipeline_steps: analysisStore.pipeline,
				tabs: analysisStore.tabs
			});
			expect(analysisStore.current).toEqual(updatedAnalysis);
			expect(analysisStore.loading).toBe(false);
			expect(analysisStore.error).toBe(null);
		});

		it('should throw error if no analysis loaded', async () => {
			analysisStore.reset();

			await expect(analysisStore.save()).rejects.toThrow('No analysis loaded');
		});

		it('should handle save errors', async () => {
			const error = new Error('Save failed');
			vi.mocked(analysisApi.updateAnalysis).mockRejectedValue(error);

			await expect(analysisStore.save()).rejects.toThrow('Save failed');

			expect(analysisStore.error).toBe('Save failed');
			expect(analysisStore.loading).toBe(false);
		});

		it('should set loading state during save', async () => {
			vi.mocked(analysisApi.updateAnalysis).mockImplementation(
				() =>
					new Promise((resolve) => {
						setTimeout(() => resolve(mockAnalysis), 100);
					})
			);

			const savePromise = analysisStore.save();
			expect(analysisStore.loading).toBe(true);

			await savePromise;
			expect(analysisStore.loading).toBe(false);
		});
	});

	describe('schema calculation', () => {
		beforeEach(async () => {
			vi.mocked(analysisApi.getAnalysis).mockResolvedValue(mockAnalysis);
			await analysisStore.loadAnalysis('test-123');
		});

		it('should return null when no source schemas', () => {
			expect(analysisStore.calculatedSchema).toBe(null);
		});

		it('should return null when pipeline is empty', () => {
			analysisStore.pipeline = [];
			analysisStore.setSourceSchema('ds-1', mockSchema);

			expect(analysisStore.calculatedSchema).toBe(null);
		});

		it('should calculate schema with source schema and pipeline', () => {
			analysisStore.setSourceSchema('ds-1', mockSchema);

			// The schema calculator should process the pipeline
			const result = analysisStore.calculatedSchema;

			expect(result).not.toBe(null);
			// Schema should have columns based on the select step
			expect(result?.columns).toBeDefined();
		});
	});

	describe('setSourceSchema', () => {
		it('should add source schema to map', () => {
			analysisStore.setSourceSchema('ds-1', mockSchema);

			expect(analysisStore.sourceSchemas.get('ds-1')).toEqual(mockSchema);
		});

		it('should replace existing source schema', () => {
			const schema1: SchemaInfo = {
				columns: [{ name: 'a', dtype: 'Int64', nullable: false }],
				row_count: 10
			};
			const schema2: SchemaInfo = {
				columns: [{ name: 'b', dtype: 'String', nullable: false }],
				row_count: 20
			};

			analysisStore.setSourceSchema('ds-1', schema1);
			analysisStore.setSourceSchema('ds-1', schema2);

			expect(analysisStore.sourceSchemas.get('ds-1')).toEqual(schema2);
		});

		it('should trigger reactivity', () => {
			analysisStore.setSourceSchema('ds-1', mockSchema);

			// The store should create a new Map instance for reactivity
			expect(analysisStore.sourceSchemas.size).toBe(1);
		});
	});

	describe('clearSourceSchemas', () => {
		it('should clear all source schemas', () => {
			analysisStore.setSourceSchema('ds-1', mockSchema);
			analysisStore.setSourceSchema('ds-2', mockSchema);

			analysisStore.clearSourceSchemas();

			expect(analysisStore.sourceSchemas.size).toBe(0);
		});
	});

	describe('reset', () => {
		beforeEach(async () => {
			vi.mocked(analysisApi.getAnalysis).mockResolvedValue(mockAnalysis);
			await analysisStore.loadAnalysis('test-123');
			analysisStore.setSourceSchema('ds-1', mockSchema);
		});

		it('should reset all store state', () => {
			analysisStore.reset();

			expect(analysisStore.current).toBe(null);
			expect(analysisStore.pipeline).toHaveLength(0);
			expect(analysisStore.sourceSchemas.size).toBe(0);
			expect(analysisStore.error).toBe(null);
			expect(analysisStore.loading).toBe(false);
		});
	});
});
