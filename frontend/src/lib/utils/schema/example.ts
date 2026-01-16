// Example usage of the Schema Calculator
import type { Schema } from '$lib/types/schema';
import type { PipelineStep } from '$lib/types/analysis';
import { schemaCalculator } from './schema-calculator.svelte';

// Example base schema
const baseSchema: Schema = {
	columns: [
		{ name: 'id', dtype: 'Int64', nullable: false },
		{ name: 'name', dtype: 'String', nullable: false },
		{ name: 'age', dtype: 'Int64', nullable: true },
		{ name: 'salary', dtype: 'Float64', nullable: true },
		{ name: 'department', dtype: 'String', nullable: true },
		{ name: 'hire_date', dtype: 'Date', nullable: true }
	],
	row_count: 1000
};

// Example pipeline steps
const pipelineSteps: PipelineStep[] = [
	{
		id: 'step_1',
		type: 'filter',
		config: {
			conditions: [{ column: 'age', operator: '>', value: '25' }],
			logic: 'AND'
		},
		depends_on: []
	},
	{
		id: 'step_2',
		type: 'select',
		config: {
			columns: ['name', 'age', 'salary', 'department']
		},
		depends_on: ['step_1']
	},
	{
		id: 'step_3',
		type: 'group_by',
		config: {
			group_by: ['department'],
			aggregations: {
				salary: 'mean',
				age: 'max'
			}
		},
		depends_on: ['step_2']
	},
	{
		id: 'step_4',
		type: 'rename',
		config: {
			mapping: {
				salary_mean: 'avg_salary',
				age_max: 'max_age'
			}
		},
		depends_on: ['step_3']
	}
];

// Calculate final schema
const finalSchema = schemaCalculator.calculatePipelineSchema(baseSchema, pipelineSteps);

console.log('Final Schema:', finalSchema);
// Expected output:
// {
//   columns: [
//     { name: 'department', dtype: 'String', nullable: true },
//     { name: 'avg_salary', dtype: 'Float64', nullable: true },
//     { name: 'max_age', dtype: 'Int64', nullable: true }
//   ],
//   row_count: null
// }

// Get schema at a specific step
const step2Schema = schemaCalculator.getStepSchema(baseSchema, pipelineSteps, 'step_2');

console.log('Schema after step 2:', step2Schema);
// Expected output:
// {
//   columns: [
//     { name: 'name', dtype: 'String', nullable: false },
//     { name: 'age', dtype: 'Int64', nullable: true },
//     { name: 'salary', dtype: 'Float64', nullable: true },
//     { name: 'department', dtype: 'String', nullable: true }
//   ],
//   row_count: null
// }
