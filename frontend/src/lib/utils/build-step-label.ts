import { getStepTypeConfig } from '$lib/components/pipeline/utils';

const UUID_LIKE_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const OPAQUE_ID_PATTERN = /^(step[-_][0-9a-f-]+|[0-9a-f]{16,})$/i;

function isOpaqueStepName(stepName: string): boolean {
	const trimmed = stepName.trim();
	if (!trimmed) return true;
	if (trimmed.includes(' ')) return false;
	return UUID_LIKE_PATTERN.test(trimmed) || OPAQUE_ID_PATTERN.test(trimmed);
}

export function buildStepTypeLabel(stepType: string): string {
	const label = getStepTypeConfig(stepType).label;
	if (label !== 'Unknown') return label;
	return (
		stepType
			.split('_')
			.filter(Boolean)
			.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
			.join(' ') || 'Unnamed Step'
	);
}

export function buildStepLabel(stepName: string | null | undefined, stepType: string): string {
	if (typeof stepName === 'string' && stepName.trim() && !isOpaqueStepName(stepName)) {
		if (stepName.trim().toLowerCase() === stepType.trim().toLowerCase()) {
			return buildStepTypeLabel(stepType);
		}
		return stepName;
	}
	return buildStepTypeLabel(stepType);
}
