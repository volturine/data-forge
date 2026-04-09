import type {
	BuildEvent,
	BuildStatus,
	StepInfo,
	BuildTabResult,
	BuildResourceSnapshot,
	BuildResourceConfigSummary,
	BuildLogEntry,
	ActiveBuildDetail,
	QueryPlan,
	BuildStepState
} from '$lib/types/build-stream';
import { connectBuildStream } from '$lib/api/build-stream';

const MAX_LOGS = 500;
const MAX_RESOURCE_HISTORY = 120;

function wireStepState(raw: string): BuildStepState {
	if (
		raw === 'pending' ||
		raw === 'running' ||
		raw === 'completed' ||
		raw === 'failed' ||
		raw === 'skipped'
	)
		return raw;
	return 'pending';
}

export class BuildStreamStore {
	status = $state<BuildStatus>('connecting');
	buildId = $state<string | null>(null);
	analysisId = $state<string | null>(null);
	progress = $state(0);
	elapsed = $state(0);
	remaining = $state<number | null>(null);
	currentStep = $state<string | null>(null);
	currentStepIndex = $state<number | null>(null);
	totalSteps = $state(0);
	totalTabs = $state(0);
	steps = $state<StepInfo[]>([]);
	logs = $state<BuildLogEntry[]>([]);
	queryPlans = $state<QueryPlan[]>([]);
	latestResources = $state<BuildResourceSnapshot | null>(null);
	resourceHistory = $state<BuildResourceSnapshot[]>([]);
	resourceConfig = $state<BuildResourceConfigSummary | null>(null);
	results = $state<BuildTabResult[]>([]);
	error = $state<string | null>(null);
	duration = $state<number | null>(null);

	private connection: { close: () => void } | null = null;

	done = $derived(this.status === 'completed' || this.status === 'failed');
	succeeded = $derived(this.status === 'completed');
	memoryPercent = $derived(
		this.latestResources &&
			this.latestResources.memory_limit_mb &&
			this.latestResources.memory_limit_mb > 0
			? Math.round((this.latestResources.memory_mb / this.latestResources.memory_limit_mb) * 100)
			: 0
	);
	progressPct = $derived(Math.min(Math.max(Math.round(this.progress * 100), 0), 100));

	start(request: Record<string, unknown>): void {
		this.reset();
		this.status = 'connecting';
		this.connection = connectBuildStream(request, {
			onSnapshot: (build: ActiveBuildDetail) => this.applySnapshot(build),
			onEvent: (event: BuildEvent) => this.applyEvent(event),
			onError: (msg: string) => {
				this.error = msg;
				if (!this.done) this.status = 'disconnected';
			},
			onClose: () => {
				if (!this.done) this.status = 'disconnected';
			}
		});
	}

	close(): void {
		this.connection?.close();
		this.connection = null;
	}

	reset(): void {
		this.close();
		this.status = 'connecting';
		this.buildId = null;
		this.analysisId = null;
		this.progress = 0;
		this.elapsed = 0;
		this.remaining = null;
		this.currentStep = null;
		this.currentStepIndex = null;
		this.totalSteps = 0;
		this.totalTabs = 0;
		this.steps = [];
		this.logs = [];
		this.queryPlans = [];
		this.latestResources = null;
		this.resourceHistory = [];
		this.resourceConfig = null;
		this.results = [];
		this.error = null;
		this.duration = null;
	}

	applySnapshot(build: ActiveBuildDetail): void {
		this.buildId = build.build_id;
		this.analysisId = build.analysis_id;
		this.progress = build.progress;
		this.elapsed = build.elapsed_ms;
		this.remaining = build.estimated_remaining_ms;
		this.currentStep = build.current_step;
		this.currentStepIndex = build.current_step_index;
		this.totalSteps = build.total_steps;
		this.totalTabs = build.total_tabs;
		this.steps = (build.steps ?? []).map((s) => ({
			buildStepIndex: s.build_step_index,
			stepIndex: s.step_index,
			stepId: s.step_id,
			name: s.step_name,
			stepType: s.step_type,
			tabId: s.tab_id ?? null,
			tabName: s.tab_name ?? null,
			state: wireStepState(s.state),
			duration: s.duration_ms ?? null,
			rowCount: s.row_count ?? null,
			error: s.error ?? null
		}));
		this.queryPlans = (build.query_plans ?? []).map((p) => ({
			tabId: p.tab_id ?? null,
			tabName: p.tab_name ?? null,
			optimized: p.optimized_plan,
			unoptimized: p.unoptimized_plan
		}));
		this.latestResources = build.latest_resources ?? null;
		this.resourceHistory = build.resources ?? [];
		this.resourceConfig = build.resource_config ?? null;
		this.logs = build.logs ?? [];
		this.results = build.results ?? [];
		this.duration = build.duration_ms ?? null;
		this.error = build.error ?? null;
		this.status = build.error ? 'failed' : build.status === 'completed' ? 'completed' : 'running';
	}

	applyEvent(event: BuildEvent): void {
		this.buildId = event.build_id;
		this.analysisId = event.analysis_id;

		switch (event.type) {
			case 'plan':
				this.upsertPlan({
					tabId: event.tab_id ?? null,
					tabName: event.tab_name ?? null,
					optimized: event.optimized_plan,
					unoptimized: event.unoptimized_plan
				});
				this.status = 'running';
				break;

			case 'step_start':
				this.status = 'running';
				this.totalSteps = event.total_steps;
				this.updateStep(event.build_step_index, {
					buildStepIndex: event.build_step_index,
					stepIndex: event.step_index,
					stepId: event.step_id,
					name: event.step_name,
					stepType: event.step_type,
					tabId: event.tab_id ?? null,
					tabName: event.tab_name ?? null,
					state: 'running',
					duration: null,
					rowCount: null,
					error: null
				});
				break;

			case 'step_complete':
				this.totalSteps = event.total_steps;
				this.updateStep(event.build_step_index, {
					buildStepIndex: event.build_step_index,
					stepIndex: event.step_index,
					stepId: event.step_id,
					name: event.step_name,
					stepType: event.step_type,
					tabId: event.tab_id ?? null,
					tabName: event.tab_name ?? null,
					state: 'completed',
					duration: event.duration_ms,
					rowCount: event.row_count ?? null,
					error: null
				});
				break;

			case 'step_failed':
				this.totalSteps = event.total_steps;
				this.updateStep(event.build_step_index, {
					buildStepIndex: event.build_step_index,
					stepIndex: event.step_index,
					stepId: event.step_id,
					name: event.step_name,
					stepType: event.step_type,
					tabId: event.tab_id ?? null,
					tabName: event.tab_name ?? null,
					state: 'failed',
					duration: null,
					rowCount: null,
					error: event.error
				});
				break;

			case 'progress':
				this.progress = event.progress;
				this.elapsed = event.elapsed_ms;
				this.remaining = event.estimated_remaining_ms;
				this.currentStep = event.current_step;
				this.currentStepIndex = event.current_step_index;
				this.totalSteps = event.total_steps;
				break;

			case 'resources': {
				const snapshot: BuildResourceSnapshot = {
					sampled_at: event.emitted_at,
					cpu_percent: event.cpu_percent,
					memory_mb: event.memory_mb,
					memory_limit_mb: event.memory_limit_mb,
					active_threads: event.active_threads,
					max_threads: event.max_threads
				};
				this.latestResources = snapshot;
				this.pushResourceHistory(snapshot);
				break;
			}

			case 'log':
				this.addLog({
					timestamp: event.emitted_at,
					level: event.level,
					message: event.message,
					step_name: event.step_name,
					step_id: event.step_id,
					tab_id: event.tab_id ?? null,
					tab_name: event.tab_name ?? null
				});
				break;

			case 'complete':
				this.status = 'completed';
				this.progress = event.progress;
				this.elapsed = event.elapsed_ms;
				this.duration = event.duration_ms;
				this.totalSteps = event.total_steps;
				this.results = event.results;
				break;

			case 'failed':
				this.status = 'failed';
				this.progress = event.progress;
				this.elapsed = event.elapsed_ms;
				this.duration = event.duration_ms;
				this.totalSteps = event.total_steps;
				this.results = event.results;
				this.error = event.error;
				break;
		}
	}

	private upsertPlan(plan: QueryPlan): void {
		const next = this.queryPlans.filter(
			(p) => !(p.tabId === plan.tabId && p.tabName === plan.tabName)
		);
		this.queryPlans = [...next, plan];
	}

	private updateStep(buildStepIndex: number, info: StepInfo): void {
		const next = [...this.steps];
		const existing = next.findIndex((s) => s.buildStepIndex === buildStepIndex);
		if (existing >= 0) {
			next[existing] = info;
		} else {
			next.push(info);
			next.sort((a, b) => a.buildStepIndex - b.buildStepIndex);
		}
		this.steps = next;
	}

	private addLog(entry: BuildLogEntry): void {
		const next = [...this.logs, entry];
		if (next.length > MAX_LOGS) {
			this.logs = next.slice(next.length - MAX_LOGS);
			return;
		}
		this.logs = next;
	}

	private pushResourceHistory(snapshot: BuildResourceSnapshot): void {
		const next = [...this.resourceHistory, snapshot];
		if (next.length > MAX_RESOURCE_HISTORY) {
			this.resourceHistory = next.slice(next.length - MAX_RESOURCE_HISTORY);
			return;
		}
		this.resourceHistory = next;
	}
}
