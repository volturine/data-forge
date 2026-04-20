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
import { connectBuildDetailStream, startActiveBuild } from '$lib/api/build-stream';
import type { BuildRequest } from '$lib/api/compute';

const MAX_LOGS = 500;
const MAX_RESOURCE_HISTORY = 120;
const RECONNECT_DELAY_MS = 1_000;
const MAX_RECONNECT_ATTEMPTS = 5;

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
	status = $state<BuildStatus>('disconnected');
	buildId = $state<string | null>(null);
	engineRunId = $state<string | null>(null);
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
	private generation = 0;
	private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	private shouldReconnect = false;
	private targetBuildId: string | null = null;
	private reconnectAttempts = 0;

	done = $derived(
		this.status === 'completed' || this.status === 'failed' || this.status === 'cancelled'
	);
	succeeded = $derived(this.status === 'completed');
	memoryPercent = $derived(
		this.latestResources &&
			this.latestResources.memory_limit_mb &&
			this.latestResources.memory_limit_mb > 0
			? Math.round((this.latestResources.memory_mb / this.latestResources.memory_limit_mb) * 100)
			: 0
	);
	progressPct = $derived(Math.min(Math.max(Math.round(this.progress * 100), 0), 100));

	start(request: BuildRequest): void {
		this.reset();
		const generation = ++this.generation;
		this.shouldReconnect = true;
		this.reconnectAttempts = 0;
		this.status = 'connecting';
		void startActiveBuild(request).match(
			(build) => {
				if (generation !== this.generation) return;
				this.applySnapshot(build);
				this.targetBuildId = build.build_id;
				this.openConnection(build.build_id, generation);
			},
			(err) => {
				if (generation !== this.generation) return;
				this.shouldReconnect = false;
				this.error = err.message;
				this.status = 'disconnected';
			}
		);
	}

	watch(buildId: string): void {
		this.reset();
		const generation = ++this.generation;
		this.shouldReconnect = true;
		this.reconnectAttempts = 0;
		this.targetBuildId = buildId;
		this.buildId = buildId;
		this.status = 'connecting';
		this.openConnection(buildId, generation);
	}

	close(): void {
		this.shouldReconnect = false;
		this.generation += 1;
		this.clearReconnectTimer();
		this.connection?.close();
		this.connection = null;
		this.status = 'disconnected';
	}

	reset(): void {
		this.close();
		this.status = 'disconnected';
		this.buildId = null;
		this.targetBuildId = null;
		this.engineRunId = null;
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

	private openConnection(buildId: string, generation: number): void {
		this.clearReconnectTimer();
		this.connection = connectBuildDetailStream(buildId, {
			onSnapshot: (build: ActiveBuildDetail) => {
				if (generation !== this.generation) return;
				this.reconnectAttempts = 0;
				this.applySnapshot(build);
			},
			onEvent: (event: BuildEvent) => {
				if (generation !== this.generation) return;
				this.reconnectAttempts = 0;
				this.applyEvent(event);
				if (!this.done) this.error = null;
			},
			onError: (msg: string) => {
				if (generation !== this.generation) return;
				if (!this.done && this.shouldReconnect) return;
				this.error = msg;
			},
			onClose: () => {
				if (generation !== this.generation) return;
				this.connection = null;
				if (!this.shouldReconnect || this.done) {
					if (!this.done) this.status = 'disconnected';
					return;
				}
				this.scheduleReconnect(buildId, generation);
			}
		});
	}

	private scheduleReconnect(buildId: string, generation: number): void {
		if (this.reconnectTimer !== null) return;
		this.reconnectAttempts++;
		if (this.reconnectAttempts > MAX_RECONNECT_ATTEMPTS) {
			this.shouldReconnect = false;
			this.status = 'disconnected';
			return;
		}
		this.reconnectTimer = setTimeout(() => {
			this.reconnectTimer = null;
			if (generation !== this.generation) return;
			if (!this.shouldReconnect || this.done) return;
			if (this.targetBuildId !== buildId) return;
			if (!this.buildId) this.buildId = buildId;
			if (this.status === 'disconnected') this.status = 'connecting';
			this.openConnection(buildId, generation);
		}, RECONNECT_DELAY_MS);
	}

	private clearReconnectTimer(): void {
		if (this.reconnectTimer === null) return;
		clearTimeout(this.reconnectTimer);
		this.reconnectTimer = null;
	}

	applySnapshot(build: ActiveBuildDetail): void {
		this.buildId = build.build_id;
		this.engineRunId = build.current_engine_run_id ?? null;
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
		if (build.status === 'cancelled') {
			this.status = 'cancelled';
		} else if (build.error) {
			this.status = 'failed';
		} else {
			this.status = build.status === 'completed' ? 'completed' : 'running';
		}
	}

	applyEvent(event: BuildEvent): void {
		this.buildId = event.build_id;
		if (event.engine_run_id) this.engineRunId = event.engine_run_id;
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

			case 'cancelled':
				this.status = 'cancelled';
				this.progress = event.progress;
				this.elapsed = event.elapsed_ms;
				this.duration = event.duration_ms;
				this.totalSteps = event.total_steps;
				this.results = event.results;
				this.error = `Cancelled${event.cancelled_by ? ` by ${event.cancelled_by}` : ''}`;
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
