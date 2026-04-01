import type { PipelineStep } from '$lib/types/analysis';

export function applySteps(steps: PipelineStep[]): PipelineStep[] {
	const applied = steps.filter((step) => step.is_applied !== false);
	if (applied.length === 0) return [];

	const map = new Map(steps.map((step) => [step.id, step]));
	const appliedIds = new Set(applied.map((step) => step.id));

	const resolve = (stepId: string, seen = new Set<string>()): string | null => {
		const step = map.get(stepId);
		if (!step) return null;
		const deps = step.depends_on ?? [];
		const parentId = deps[0] ?? null;
		if (!parentId) return null;
		if (appliedIds.has(parentId)) return parentId;
		if (seen.has(parentId)) return null;
		seen.add(parentId);
		return resolve(parentId, seen);
	};

	return applied.map((step) => {
		const parentId = resolve(step.id);
		return { ...step, depends_on: parentId ? [parentId] : [] };
	});
}
