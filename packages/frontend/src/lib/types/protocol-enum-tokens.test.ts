import { getOption } from '@bufbuild/protobuf';
import { describe, expect, test } from 'vitest';

import {
	dataforge_token,
	file_dataforge_protocol_enums
} from '$lib/protocol/dataforge_protocol/enums_pb';
import * as tokenTables from './protocol-enum-tokens';

function screamingSnake(name: string): string {
	return name
		.replace(/([a-z0-9])([A-Z])/g, '$1_$2')
		.replace(/([A-Z])([A-Z][a-z])/g, '$1_$2')
		.toUpperCase();
}

// Generated enums that intentionally have no frontend token table.
// Enum tables are only maintained for enums the frontend actually renders.
// These are consumed through hand-maintained literal unions today; migrating
// them to generated token tables is tracked in
// docs/prd/backlog/frontend-component-decomposition.md.
const TABLE_EXEMPTIONS: string[] = [
	'ANALYSIS_STATUS_TOKENS',
	'BUILD_EVENT_TYPE_TOKENS',
	'BUILD_JOB_STATUS_TOKENS',
	'BUILD_MODE_TOKENS',
	'BUILD_RUN_STATUS_TOKENS',
	'BUILD_STATUS_TOKENS',
	'COMPUTE_REQUEST_KIND_TOKENS',
	'COMPUTE_REQUEST_STATUS_TOKENS',
	'COMPUTE_RUN_STATUS_TOKENS',
	'DATA_SOURCE_CATEGORY_TOKENS',
	'DATA_SOURCE_CREATED_BY_TOKENS',
	'DATA_SOURCE_FILE_TYPE_TOKENS',
	'DATA_SOURCE_LOAD_TYPE_TOKENS',
	'DATA_SOURCE_TARGET_KIND_TOKENS',
	'DATA_SOURCE_TYPE_TOKENS',
	'ENGINE_RUN_STATUS_TOKENS',
	'HEALTH_CHECK_TYPE_TOKENS',
	'ICEBERG_READER_TOKENS',
	'RUNTIME_PAYLOAD_KIND_TOKENS',
	'RUNTIME_WORKER_KIND_TOKENS',
	'SCHEMA_DIFF_STATUS_TOKENS'
];

describe('protocol enum tokens', () => {
	test('every generated enum has a token table or is explicitly exempted', () => {
		const missing: string[] = [];
		for (const enumDescriptor of file_dataforge_protocol_enums.enums) {
			const exportName = `${screamingSnake(enumDescriptor.name)}_TOKENS`;
			if (tokenTables[exportName as keyof typeof tokenTables] === undefined) {
				if (!TABLE_EXEMPTIONS.includes(exportName)) missing.push(exportName);
			}
		}
		// A generated enum without a token table is only acceptable if it is
		// explicitly exempted; anything else means the tables drifted behind
		// the protocol and consumers will hand-roll their own literals.
		expect(missing, 'generated enums without token tables').toEqual([]);
	});

	test('match every token declared in generated protobuf descriptors', () => {
		for (const enumDescriptor of file_dataforge_protocol_enums.enums) {
			const exportName = `${screamingSnake(enumDescriptor.name)}_TOKENS`;
			const table = tokenTables[exportName as keyof typeof tokenTables];
			if (table === undefined) continue;
			expect(typeof table, exportName).toBe('object');
			for (const value of enumDescriptor.values) {
				const protocolToken = getOption(value, dataforge_token);
				if (protocolToken.length === 0) continue;
				expect((table as Record<number, string>)[value.number], `${exportName}.${value.name}`).toBe(
					protocolToken
				);
			}
		}
	});
});
