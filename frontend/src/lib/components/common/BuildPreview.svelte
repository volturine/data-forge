<script lang="ts">
	import type { BuildStreamStore } from '$lib/stores/build-stream.svelte';
	import type { QueryPlan, BuildLogEntry } from '$lib/types/build-stream';
	import {
		CheckCircle,
		XCircle,
		Loader,
		Clock,
		Cpu,
		MemoryStick,
		FileText,
		ListOrdered,
		Activity,
		ScrollText,
		Terminal,
		AlertTriangle,
		Copy,
		Settings,
		PauseCircle,
		PlayCircle
	} from 'lucide-svelte';
	import { css, cx, tabButton, chip, callout, spinner } from '$lib/styles/panda';
	import { buildStepLabel } from '$lib/utils/build-step-label';

	interface Props {
		store: BuildStreamStore;
		title?: string;
	}

	const { store, title = 'Build' }: Props = $props();

	type PreviewTab = 'steps' | 'plan' | 'config' | 'resources' | 'logs' | 'results';
	let activeTab = $state<PreviewTab>('steps');
	let logsRef = $state<HTMLElement>();
	let planView = $state<'optimized' | 'unoptimized'>('optimized');
	let logLevel = $state<'all' | 'warning' | 'error'>('all');
	let scrollPaused = $state(false);
	let copied = $state(false);

	const MEMORY_WARN_THRESHOLD = 80;
	const rowClass = css({ display: 'flex', alignItems: 'center' });

	const elapsedSec = $derived(store.elapsed > 0 ? (store.elapsed / 1000).toFixed(1) : '0.0');
	const remainingSec = $derived(
		store.remaining !== null && store.remaining > 0 ? (store.remaining / 1000).toFixed(0) : null
	);
	const durationSec = $derived(store.duration !== null ? (store.duration / 1000).toFixed(2) : null);
	const hasConfig = $derived(store.resourceConfig !== null);
	const hasResources = $derived(store.latestResources !== null || store.resourceHistory.length > 0);
	const hasPlans = $derived(store.queryPlans.length > 0);
	const hasLogs = $derived(store.status !== 'connecting');
	const hasResults = $derived(store.results.length > 0);

	const filteredLogs = $derived.by((): BuildLogEntry[] => {
		if (logLevel === 'all') return store.logs;
		if (logLevel === 'error') return store.logs.filter((e) => e.level === 'error');
		return store.logs.filter((e) => e.level === 'warning' || e.level === 'error');
	});

	const errorLogCount = $derived(store.logs.filter((e) => e.level === 'error').length);
	const warnLogCount = $derived(
		store.logs.filter((e) => e.level === 'warning' || e.level === 'error').length
	);

	const statusLabel = $derived.by(() => {
		if (store.status === 'connecting') return 'Connecting';
		if (store.status === 'running') return store.currentStep ?? 'Running';
		if (store.status === 'completed') return 'Complete';
		if (store.status === 'failed') return 'Failed';
		return 'Disconnected';
	});

	const statusTone = $derived.by(() => {
		if (store.status === 'completed') return 'success' as const;
		if (store.status === 'failed' || store.status === 'disconnected') return 'error' as const;
		return 'accent' as const;
	});

	const memoryWarning = $derived(store.memoryPercent > MEMORY_WARN_THRESHOLD);

	const tabSteps = $derived.by(() => {
		let lastTab: string | null = null;
		return store.steps.map((step) => {
			const showTab = step.tabName !== null && step.tabName !== lastTab;
			if (step.tabName !== null) lastTab = step.tabName;
			return { ...step, showTabHeader: showTab };
		});
	});

	const sparklineCpu = $derived(store.resourceHistory.map((r) => r.cpu_percent));
	const sparklineMem = $derived(
		store.resourceHistory.map((r) => {
			if (!r.memory_limit_mb || r.memory_limit_mb <= 0) return 0;
			return (r.memory_mb / r.memory_limit_mb) * 100;
		})
	);

	function planText(plan: QueryPlan): string {
		if (planView === 'optimized') return plan.optimized;
		return plan.unoptimized;
	}

	function handleLogScroll(): void {
		if (!logsRef) return;
		const threshold = 30;
		const atBottom = logsRef.scrollHeight - logsRef.scrollTop - logsRef.clientHeight < threshold;
		scrollPaused = !atBottom;
	}

	async function copyLogs(): Promise<void> {
		const text = filteredLogs
			.map((e) => `[${e.level}]${e.step_name ? `[${e.step_name}]` : ''} ${e.message}`)
			.join('\n');
		await navigator.clipboard.writeText(text);
		copied = true;
		setTimeout(() => (copied = false), 2000);
	}

	function scrollToBottom(): void {
		if (!logsRef) return;
		logsRef.scrollTop = logsRef.scrollHeight;
		scrollPaused = false;
	}

	function levelColor(level: string): string {
		if (level === 'error') return 'fg.error';
		if (level === 'warning') return 'fg.warning';
		return 'fg.muted';
	}

	// DOM: scroll logs to bottom when new entries arrive, unless user paused
	$effect(() => {
		if (store.logs.length > 0 && logsRef && activeTab === 'logs' && !scrollPaused) {
			logsRef.scrollTop = logsRef.scrollHeight;
		}
	});

	// DOM: must imperatively reset activeTab because $derived cannot write to local mutable state
	$effect(() => {
		const invalid =
			(activeTab === 'plan' && !hasPlans) ||
			(activeTab === 'config' && !hasConfig) ||
			(activeTab === 'resources' && !hasResources) ||
			(activeTab === 'results' && !hasResults);
		if (invalid) activeTab = 'steps';
	});
</script>

{#snippet sparkline(data: number[], max: number, warn: number)}
	{@const width = 120}
	{@const height = 24}
	{@const count = data.length}
	{#if count >= 2}
		{@const step = width / (count - 1)}
		{@const points = data
			.map((v, i) => `${i * step},${height - (Math.min(v, max) / max) * height}`)
			.join(' ')}
		{@const warnY = height - (warn / max) * height}
		<svg
			viewBox={`0 0 ${width} ${height}`}
			class={css({ width: 'full', height: '6' })}
			preserveAspectRatio="none"
			data-testid="sparkline"
		>
			<line
				x1="0"
				y1={warnY}
				x2={width}
				y2={warnY}
				stroke="var(--colors-fg-warning)"
				stroke-width="0.5"
				stroke-dasharray="2 2"
			/>
			<polyline fill="none" stroke="var(--colors-accent-primary)" stroke-width="1.5" {points} />
		</svg>
	{/if}
{/snippet}

<div
	class={css({
		display: 'flex',
		flexDirection: 'column',
		gap: '0',
		borderWidth: '1',
		backgroundColor: 'bg.primary',
		overflow: 'hidden'
	})}
	data-testid="build-preview"
>
	<div
		class={css({
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'space-between',
			paddingX: '4',
			paddingY: '3',
			borderBottomWidth: '1',
			backgroundColor: 'bg.secondary'
		})}
	>
		<div class={cx(rowClass, css({ gap: '2' }))}>
			{#if store.status === 'connecting' || store.status === 'running'}
				<Loader
					size={14}
					class={css({ color: 'accent.primary', animation: 'spin 1s linear infinite' })}
				/>
			{:else if store.status === 'completed'}
				<CheckCircle size={14} class={css({ color: 'fg.success' })} />
			{:else if store.status === 'failed'}
				<XCircle size={14} class={css({ color: 'fg.error' })} />
			{:else}
				<AlertTriangle size={14} class={css({ color: 'fg.warning' })} />
			{/if}
			<span class={css({ fontSize: 'sm', fontWeight: 'semibold' })}>
				{title}
				{#if store.buildId}
					<span
						class={css({ fontFamily: 'mono', fontSize: 'xs', color: 'fg.muted', marginLeft: '2' })}
					>
						{store.buildId.slice(0, 8)}
					</span>
				{/if}
			</span>
		</div>
		<span class={chip({ tone: statusTone })}>{statusLabel}</span>
	</div>

	<div
		class={css({
			paddingX: '4',
			paddingY: '3',
			borderBottomWidth: '1'
		})}
	>
		<div class={cx(rowClass, css({ justifyContent: 'space-between', marginBottom: '2' }))}>
			<span class={css({ fontSize: 'xs', color: 'fg.secondary' })}>
				{#if store.status === 'completed'}
					Finished in {durationSec}s
				{:else if store.status === 'running'}
					Step {store.currentStepIndex !== null
						? store.currentStepIndex + 1
						: '?'}/{store.totalSteps || '?'}
				{:else if store.status === 'connecting'}
					Preparing...
				{:else if store.status === 'failed'}
					Build failed
				{:else}
					Disconnected
				{/if}
			</span>
			<div class={cx(rowClass, css({ gap: '3', fontSize: 'xs', color: 'fg.muted' }))}>
				<span class={cx(rowClass, css({ gap: '1' }))}>
					<Clock size={11} />
					{elapsedSec}s
				</span>
				{#if remainingSec}
					<span class={cx(rowClass, css({ gap: '1' }))}>
						~{remainingSec}s left
					</span>
				{/if}
			</div>
		</div>
		<div
			class={css({
				position: 'relative',
				height: 'bar',
				width: '100%',
				backgroundColor: 'bg.tertiary',
				overflow: 'hidden'
			})}
			role="progressbar"
			aria-valuenow={store.progressPct}
			aria-valuemin={0}
			aria-valuemax={100}
			aria-label="Build progress"
			data-testid="build-progress-bar"
		>
			<div
				class={css({
					position: 'absolute',
					top: '0',
					left: '0',
					bottom: '0',
					backgroundColor: store.status === 'failed' ? 'fg.error' : 'accent.primary',
					transitionProperty: 'width',
					transitionDuration: '300ms',
					transitionTimingFunction: 'ease'
				})}
				style={`width: ${store.progressPct}%`}
			></div>
		</div>
	</div>

	<div
		role="tablist"
		aria-label="Build details"
		class={css({
			display: 'flex',
			gap: '0',
			borderBottomWidth: '1',
			paddingX: '4'
		})}
	>
		<button
			role="tab"
			aria-selected={activeTab === 'steps'}
			aria-controls="build-panel-steps"
			class={tabButton({ active: activeTab === 'steps' })}
			onclick={() => (activeTab = 'steps')}
		>
			<span class={cx(rowClass, css({ gap: '1' }))}>
				<ListOrdered size={12} />
				Steps
			</span>
		</button>
		{#if hasPlans}
			<button
				role="tab"
				aria-selected={activeTab === 'plan'}
				aria-controls="build-panel-plan"
				class={tabButton({ active: activeTab === 'plan' })}
				onclick={() => (activeTab = 'plan')}
			>
				<span class={cx(rowClass, css({ gap: '1' }))}>
					<FileText size={12} />
					Plan
				</span>
			</button>
		{/if}
		{#if hasConfig}
			<button
				role="tab"
				aria-selected={activeTab === 'config'}
				aria-controls="build-panel-config"
				class={tabButton({ active: activeTab === 'config' })}
				onclick={() => (activeTab = 'config')}
			>
				<span class={cx(rowClass, css({ gap: '1' }))}>
					<Settings size={12} />
					Config
				</span>
			</button>
		{/if}
		{#if hasResources}
			<button
				role="tab"
				aria-selected={activeTab === 'resources'}
				aria-controls="build-panel-resources"
				class={tabButton({ active: activeTab === 'resources' })}
				onclick={() => (activeTab = 'resources')}
			>
				<span class={cx(rowClass, css({ gap: '1' }))}>
					<Activity size={12} />
					Resources
					{#if memoryWarning}
						<AlertTriangle size={10} class={css({ color: 'fg.warning' })} />
					{/if}
				</span>
			</button>
		{/if}
		{#if hasLogs}
			<button
				role="tab"
				aria-selected={activeTab === 'logs'}
				aria-controls="build-panel-logs"
				class={tabButton({ active: activeTab === 'logs' })}
				onclick={() => (activeTab = 'logs')}
			>
				<span class={cx(rowClass, css({ gap: '1' }))}>
					<Terminal size={12} />
					Logs
					<span class={chip({ tone: 'neutral' })}>{store.logs.length}</span>
				</span>
			</button>
		{/if}
		{#if hasResults}
			<button
				role="tab"
				aria-selected={activeTab === 'results'}
				aria-controls="build-panel-results"
				class={tabButton({ active: activeTab === 'results' })}
				onclick={() => (activeTab = 'results')}
			>
				<span class={cx(rowClass, css({ gap: '1' }))}>
					<FileText size={12} />
					Results
					<span class={chip({ tone: 'neutral' })}>{store.results.length}</span>
				</span>
			</button>
		{/if}
	</div>

	<div class={css({ maxHeight: 'listLg', overflowY: 'auto' })}>
		{#if activeTab === 'steps'}
			<div
				id="build-panel-steps"
				role="tabpanel"
				aria-labelledby="tab-steps"
				class={css({ padding: '4' })}
				data-testid="build-steps-panel"
			>
				{#if store.steps.length === 0}
					{#if store.status === 'connecting'}
						<div
							class={cx(
								rowClass,
								css({
									gap: '2',
									justifyContent: 'center',
									padding: '4',
									color: 'fg.muted',
									fontSize: 'sm'
								})
							)}
						>
							<div class={spinner({ size: 'sm' })}></div>
							Waiting for build to start...
						</div>
					{:else}
						<div
							class={css({ padding: '4', textAlign: 'center', fontSize: 'sm', color: 'fg.muted' })}
						>
							No steps reported yet
						</div>
					{/if}
				{:else}
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
						{#each tabSteps as step (step.buildStepIndex)}
							{#if step.showTabHeader}
								<div
									class={css({
										display: 'flex',
										alignItems: 'center',
										gap: '2',
										paddingY: '1.5',
										paddingX: '2',
										marginTop: step.buildStepIndex > 0 ? '2' : '0',
										borderBottomWidth: '1',
										fontSize: '2xs',
										textTransform: 'uppercase',
										letterSpacing: 'widest',
										color: 'fg.faint'
									})}
								>
									<ScrollText size={10} />
									{step.tabName}
								</div>
							{/if}
							<div
								class={cx(
									rowClass,
									css({
										gap: '3',
										paddingY: '1.5',
										paddingX: '2',
										fontSize: 'sm'
									}),
									step.state === 'running' && css({ backgroundColor: 'bg.accent' })
								)}
								data-testid={`build-step-${step.buildStepIndex}`}
								data-step-state={step.state}
							>
								<div
									class={css({
										width: 'iconMd',
										flexShrink: '0',
										display: 'flex',
										alignItems: 'center',
										justifyContent: 'center'
									})}
								>
									{#if step.state === 'pending' || step.state === 'skipped'}
										<div
											class={css({ width: 'dot', height: 'dot', backgroundColor: 'bg.muted' })}
										></div>
									{:else if step.state === 'running'}
										<Loader
											size={12}
											class={css({ color: 'accent.primary', animation: 'spin 1s linear infinite' })}
										/>
									{:else if step.state === 'completed'}
										<CheckCircle size={12} class={css({ color: 'fg.success' })} />
									{:else}
										<XCircle size={12} class={css({ color: 'fg.error' })} />
									{/if}
								</div>
								<span
									class={css({
										flex: '1',
										overflow: 'hidden',
										textOverflow: 'ellipsis',
										whiteSpace: 'nowrap',
										fontSize: 'sm',
										fontWeight: 'medium'
									})}
									title={buildStepLabel(step.name, step.stepType)}
								>
									{buildStepLabel(step.name, step.stepType)}
								</span>
								{#if step.rowCount !== null}
									<span
										class={css({
											flexShrink: '0',
											fontFamily: 'mono',
											fontSize: 'xs',
											color: 'fg.muted'
										})}
									>
										{step.rowCount.toLocaleString()} rows
									</span>
								{/if}
								{#if step.duration !== null}
									<span
										class={css({
											flexShrink: '0',
											fontFamily: 'mono',
											fontSize: 'xs',
											color: 'fg.muted'
										})}
									>
										{step.duration < 1000
											? `${step.duration}ms`
											: `${(step.duration / 1000).toFixed(2)}s`}
									</span>
								{/if}
								{#if step.error}
									<span
										class={css({ flexShrink: '0', fontSize: 'xs', color: 'fg.error' })}
										title={step.error}
									>
										error
									</span>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{:else if activeTab === 'plan' && hasPlans}
			<div
				id="build-panel-plan"
				role="tabpanel"
				aria-labelledby="tab-plan"
				class={css({ padding: '4' })}
				data-testid="build-plan-panel"
			>
				<div class={cx(rowClass, css({ gap: '2', marginBottom: '3' }))}>
					<button
						type="button"
						class={tabButton({ active: planView === 'optimized' })}
						onclick={() => (planView = 'optimized')}
					>
						Optimized
					</button>
					<button
						type="button"
						class={tabButton({ active: planView === 'unoptimized' })}
						onclick={() => (planView = 'unoptimized')}
					>
						Unoptimized
					</button>
				</div>
				{#each store.queryPlans as plan (plan.tabId ?? '__default')}
					{#if store.queryPlans.length > 1 && plan.tabName}
						<div
							class={css({
								fontSize: '2xs',
								textTransform: 'uppercase',
								letterSpacing: 'widest',
								color: 'fg.faint',
								marginBottom: '1',
								marginTop: '2'
							})}
						>
							{plan.tabName}
						</div>
					{/if}
					<pre
						class={css({
							maxHeight: 'list',
							overflowX: 'auto',
							whiteSpace: 'pre-wrap',
							borderWidth: '1',
							backgroundColor: 'bg.tertiary',
							padding: '3',
							fontFamily: 'mono',
							fontSize: 'xs',
							marginBottom: '2'
						})}>{planText(plan)}</pre>
				{/each}
			</div>
		{:else if activeTab === 'config' && hasConfig}
			<div
				id="build-panel-config"
				role="tabpanel"
				aria-labelledby="tab-config"
				class={css({ padding: '4' })}
				data-testid="build-config-panel"
			>
				{#if store.resourceConfig}
					<div
						class={css({
							display: 'grid',
							gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
							gap: '3'
						})}
					>
						<div
							class={css({
								borderWidth: '1',
								backgroundColor: 'bg.tertiary',
								padding: '3',
								display: 'flex',
								flexDirection: 'column',
								gap: '1'
							})}
						>
							<span class={css({ fontSize: '2xs', color: 'fg.muted', textTransform: 'uppercase' })}
								>Max Threads</span
							>
							<span class={css({ fontFamily: 'mono', fontSize: 'sm' })}
								>{store.resourceConfig.max_threads ?? 'auto'}</span
							>
						</div>
						<div
							class={css({
								borderWidth: '1',
								backgroundColor: 'bg.tertiary',
								padding: '3',
								display: 'flex',
								flexDirection: 'column',
								gap: '1'
							})}
						>
							<span class={css({ fontSize: '2xs', color: 'fg.muted', textTransform: 'uppercase' })}
								>Max Memory</span
							>
							<span class={css({ fontFamily: 'mono', fontSize: 'sm' })}
								>{store.resourceConfig.max_memory_mb ?? 'auto'} MB</span
							>
						</div>
						<div
							class={css({
								borderWidth: '1',
								backgroundColor: 'bg.tertiary',
								padding: '3',
								display: 'flex',
								flexDirection: 'column',
								gap: '1'
							})}
						>
							<span class={css({ fontSize: '2xs', color: 'fg.muted', textTransform: 'uppercase' })}
								>Chunk Size</span
							>
							<span class={css({ fontFamily: 'mono', fontSize: 'sm' })}
								>{store.resourceConfig.streaming_chunk_size ?? 'auto'}</span
							>
						</div>
					</div>
				{/if}
			</div>
		{:else if activeTab === 'resources' && hasResources}
			<div
				id="build-panel-resources"
				role="tabpanel"
				aria-labelledby="tab-resources"
				class={css({ padding: '4' })}
				data-testid="build-resources-panel"
			>
				{#if memoryWarning}
					<div
						class={cx(callout({ tone: 'warn' }), css({ marginBottom: '3' }))}
						data-testid="memory-warning"
					>
						<AlertTriangle size={12} />
						Memory usage at {store.memoryPercent}% of allocated — exceeds {MEMORY_WARN_THRESHOLD}%
						threshold
					</div>
				{/if}

				{#if store.latestResources}
					<div
						class={css({
							display: 'grid',
							gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
							gap: '3'
						})}
					>
						<div
							class={css({
								borderWidth: '1',
								backgroundColor: 'bg.tertiary',
								padding: '3',
								display: 'flex',
								flexDirection: 'column',
								gap: '2'
							})}
						>
							<div class={cx(rowClass, css({ gap: '2', fontSize: 'xs', color: 'fg.muted' }))}>
								<Cpu size={12} />
								CPU
							</div>
							<span class={css({ fontFamily: 'mono', fontSize: 'sm', fontWeight: 'semibold' })}>
								{store.latestResources.cpu_percent.toFixed(1)}%
							</span>
							<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>
								{store.latestResources.active_threads}/{store.latestResources.max_threads ?? '?'} threads
								in use
							</span>
							<span class={css({ fontSize: '2xs', color: 'fg.faint' })}>
								Share of allocated CPU capacity
							</span>
							{#if sparklineCpu.length >= 2}
								{@render sparkline(sparklineCpu, 100, MEMORY_WARN_THRESHOLD)}
							{/if}
						</div>
						<div
							class={css({
								borderWidth: '1',
								backgroundColor: 'bg.tertiary',
								padding: '3',
								display: 'flex',
								flexDirection: 'column',
								gap: '2'
							})}
						>
							<div class={cx(rowClass, css({ gap: '2', fontSize: 'xs', color: 'fg.muted' }))}>
								<MemoryStick size={12} />
								Memory
							</div>
							<span class={css({ fontFamily: 'mono', fontSize: 'sm', fontWeight: 'semibold' })}>
								{store.latestResources.memory_mb.toFixed(0)} MB
							</span>
							{#if store.latestResources.memory_limit_mb}
								<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
									<div
										class={css({
											position: 'relative',
											height: 'bar',
											width: '100%',
											backgroundColor: 'bg.muted'
										})}
									>
										<div
											class={css({
												position: 'absolute',
												top: '0',
												left: '0',
												bottom: '0',
												backgroundColor: memoryWarning ? 'fg.error' : 'accent.primary'
											})}
											style={`width: ${store.memoryPercent}%`}
										></div>
									</div>
									<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>
										{store.memoryPercent}% of {store.latestResources.memory_limit_mb} MB
									</span>
								</div>
							{/if}
							{#if sparklineMem.length >= 2}
								{@render sparkline(sparklineMem, 100, MEMORY_WARN_THRESHOLD)}
							{/if}
						</div>
					</div>
				{:else}
					<div
						class={css({ padding: '4', textAlign: 'center', fontSize: 'sm', color: 'fg.muted' })}
					>
						No resource samples captured
					</div>
				{/if}
			</div>
		{:else if activeTab === 'logs'}
			<div
				id="build-panel-logs"
				role="tabpanel"
				aria-labelledby="tab-logs"
				class={css({ padding: '0' })}
				data-testid="build-logs-panel"
			>
				<div
					class={cx(
						rowClass,
						css({
							justifyContent: 'space-between',
							paddingX: '3',
							paddingY: '2',
							borderBottomWidth: '1',
							backgroundColor: 'bg.secondary'
						})
					)}
				>
					<div class={cx(rowClass, css({ gap: '1' }))} data-testid="log-level-filter">
						<button
							type="button"
							class={tabButton({ active: logLevel === 'all' })}
							onclick={() => (logLevel = 'all')}
						>
							All ({store.logs.length})
						</button>
						<button
							type="button"
							class={tabButton({ active: logLevel === 'warning' })}
							onclick={() => (logLevel = 'warning')}
						>
							Warn+ ({warnLogCount})
						</button>
						<button
							type="button"
							class={tabButton({ active: logLevel === 'error' })}
							onclick={() => (logLevel = 'error')}
						>
							Errors ({errorLogCount})
						</button>
					</div>
					<div class={cx(rowClass, css({ gap: '2' }))}>
						{#if scrollPaused}
							<button
								type="button"
								class={cx(
									rowClass,
									css({
										gap: '1',
										fontSize: 'xs',
										color: 'fg.muted',
										cursor: 'pointer',
										border: 'none',
										backgroundColor: 'transparent',
										_hover: { color: 'fg.secondary' }
									})
								)}
								onclick={scrollToBottom}
								title="Resume auto-scroll"
								data-testid="log-resume-scroll"
							>
								<PlayCircle size={12} />
								Resume
							</button>
						{:else if store.status === 'running'}
							<span
								class={cx(rowClass, css({ gap: '1', fontSize: 'xs', color: 'fg.muted' }))}
								data-testid="log-auto-scroll"
							>
								<PauseCircle size={12} />
								Auto-scroll
							</span>
						{/if}
						<button
							type="button"
							class={cx(
								rowClass,
								css({
									gap: '1',
									fontSize: 'xs',
									color: 'fg.muted',
									cursor: 'pointer',
									border: 'none',
									backgroundColor: 'transparent',
									_hover: { color: 'fg.secondary' }
								})
							)}
							onclick={copyLogs}
							title="Copy logs to clipboard"
							data-testid="log-copy"
						>
							<Copy size={12} />
							{copied ? 'Copied' : 'Copy'}
						</button>
					</div>
				</div>
				<div
					bind:this={logsRef}
					onscroll={handleLogScroll}
					class={css({
						maxHeight: 'listLg',
						overflowY: 'auto',
						overflowX: 'auto',
						backgroundColor: 'bg.tertiary',
						padding: '3',
						fontFamily: 'mono',
						fontSize: 'xs',
						scrollbarWidth: 'thin',
						scrollbarColor: '{colors.border.primary} transparent'
					})}
				>
					{#if filteredLogs.length === 0}
						<div class={css({ color: 'fg.muted' })}>No logs captured</div>
					{:else}
						{#each filteredLogs as entry, i (i)}
							<div class={css({ paddingY: '0.5', whiteSpace: 'pre-wrap', wordBreak: 'break-all' })}>
								<span class={css({ color: levelColor(entry.level) })}>[{entry.level}]</span>
								{#if entry.step_name}
									<span class={css({ color: 'fg.faint' })}>[{entry.step_name}]</span>
								{/if}
								&nbsp;{entry.message}
							</div>
						{/each}
					{/if}
				</div>
			</div>
		{:else if activeTab === 'results' && hasResults}
			<div
				id="build-panel-results"
				role="tabpanel"
				aria-labelledby="tab-results"
				class={css({ padding: '4' })}
				data-testid="build-results"
			>
				<div
					class={css({
						display: 'flex',
						flexDirection: 'column',
						gap: '2'
					})}
				>
					{#each store.results as result (result.tab_id)}
						<div class={cx(rowClass, css({ gap: '2', fontSize: 'sm' }))}>
							{#if result.status === 'success'}
								<CheckCircle size={12} class={css({ color: 'fg.success' })} />
							{:else}
								<XCircle size={12} class={css({ color: 'fg.error' })} />
							{/if}
							<span>{result.tab_name}</span>
							<span
								class={chip({
									tone: result.status === 'success' ? 'success' : 'error'
								})}
							>
								{result.status}
							</span>
							{#if result.output_name}
								<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>{result.output_name}</span>
							{/if}
							{#if result.error}
								<span class={css({ fontSize: 'xs', color: 'fg.error' })}>{result.error}</span>
							{/if}
						</div>
					{/each}
				</div>
			</div>
		{/if}
	</div>

	{#if store.error}
		<div
			class={cx(callout({ tone: 'error' }), css({ borderTopWidth: '1', margin: '0' }))}
			data-testid="build-error"
		>
			{store.error}
		</div>
	{/if}
</div>
