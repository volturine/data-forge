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

describe('protocol enum tokens', () => {
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
