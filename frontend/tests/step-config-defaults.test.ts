import { describe, it, expect } from 'vitest';
import { getDefaultConfig, normalizeConfig } from '../src/lib/utils/step-config-defaults';

describe('step-config-defaults', () => {
	it('returns deep-cloned defaults', () => {
		const first = getDefaultConfig('filter');
		const second = getDefaultConfig('filter');
		if (typeof first === 'object' && first && typeof second === 'object' && second) {
			(first as { logic?: string }).logic = 'OR';
			expect((second as { logic?: string }).logic).toBe('AND');
		}
	});

	it('normalizes filter conditions', () => {
		const normalized = normalizeConfig('filter', {
			conditions: [{ column: 'a', value: 1 }]
		});
		const config = normalized as { conditions: Array<Record<string, unknown>> };
		expect(config.conditions[0].operator).toBe('=');
		expect(config.conditions[0].value_type).toBe('string');
	});

	it('forces export destination to download', () => {
		const normalized = normalizeConfig('export', {
			format: 'parquet',
			destination: 'datasource',
			datasource_type: 'iceberg'
		});
		const config = normalized as { destination: string };
		expect(config.destination).toBe('download');
	});

	it('normalizes notification fields', () => {
		const normalized = normalizeConfig('notification', { input_columns: null } as never);
		const config = normalized as {
			input_columns: unknown;
			recipient?: string;
			recipient_source?: string;
			recipient_column?: string;
		};
		expect(Array.isArray(config.input_columns)).toBe(true);
		expect(config.recipient).toBe('');
		expect(config.recipient_source).toBe('manual');
		expect(config.recipient_column).toBe('');
	});
});
