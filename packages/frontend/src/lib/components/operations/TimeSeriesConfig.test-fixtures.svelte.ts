import type { TimeSeriesConfigData } from '#lib/types/operation-config.js';

export function createConfig(
	operation_type: TimeSeriesConfigData['operation_type']
): TimeSeriesConfigData {
	const config = $state<TimeSeriesConfigData>({
		column: '',
		operation_type,
		new_column: 'result'
	});
	return config;
}
