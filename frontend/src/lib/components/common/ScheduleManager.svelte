<script lang="ts">
	import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { listSchedules, createSchedule, updateSchedule, deleteSchedule } from '$lib/api/schedule';
	import type { Schedule, ScheduleCreate, ScheduleUpdate } from '$lib/api/schedule';
	import { listDatasources } from '$lib/api/datasource';
	import type { DataSource } from '$lib/types/datasource';
	import {
		Plus,
		Trash2,
		Calendar,
		Clock,
		Power,
		PowerOff,
		ChevronDown,
		Pencil,
		Check,
		X,
		Link,
		Database,
		ArrowRight,
		HelpCircle,
		BarChart3,
		Search
	} from 'lucide-svelte';
	import { SvelteMap } from 'svelte/reactivity';

	interface Props {
		datasourceId?: string;
		compact?: boolean;
		searchQuery?: string;
	}

	let { datasourceId, compact = false, searchQuery: externalSearch }: Props = $props();

	const queryClient = useQueryClient();
	const defaultCron = '0 * * * *';

	let creating = $state(false);
	let triggerType = $state<'cron' | 'depends' | 'event'>('cron');
	let newCron = $state(defaultCron);
	let newDatasourceId = $state('');
	let newDependsOn = $state('');
	let newTrigger = $state('');
	let showHelp = $state(false);
	let expandedId = $state<string | null>(null);
	let editingCron = $state<string | null>(null);
	let editCronValue = $state('');
	let searchQuery = $state('');
	const effectiveSearch = $derived(externalSearch ?? searchQuery);

	const schedulesQuery = createQuery(() => ({
		queryKey: ['schedules', datasourceId ?? 'all'],
		queryFn: async () => {
			const result = await listSchedules(datasourceId);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		}
	}));

	const allSchedulesQuery = createQuery(() => ({
		queryKey: ['schedules', 'all'],
		queryFn: async () => {
			const result = await listSchedules();
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		staleTime: 30_000
	}));

	const datasourcesQuery = createQuery(() => ({
		queryKey: ['datasources-lookup', 'include-hidden'],
		queryFn: async () => {
			const result = await listDatasources(true);
			if (result.isErr()) return [] as DataSource[];
			return result.value;
		},
		staleTime: 60_000
	}));

	const datasourceMap = $derived.by(() => {
		const map = new SvelteMap<string, DataSource>();
		for (const ds of datasourcesQuery.data ?? []) {
			map.set(ds.id, ds);
		}
		return map;
	});

	const analysisOutputs = $derived.by(() => {
		return (datasourcesQuery.data ?? []).filter((ds) => ds.created_by === 'analysis');
	});

	const triggerables = $derived.by(() => {
		return (datasourcesQuery.data ?? []).filter((ds) => ds.source_type === 'iceberg');
	});

	const schedules = $derived(schedulesQuery.data ?? []);
	const allSchedules = $derived(allSchedulesQuery.data ?? []);
	const hasSearch = $derived(effectiveSearch.trim().length > 0);
	const visibleSchedules = $derived.by(() => {
		const q = effectiveSearch.trim().toLowerCase();
		if (!q) return schedules;
		return schedules.filter((schedule) => {
			const dsName = (datasourceMap.get(schedule.datasource_id)?.name ?? '').toLowerCase();
			const triggerDs = schedule.trigger_on_datasource_id
				? (datasourceMap.get(schedule.trigger_on_datasource_id)?.name ?? '')
				: '';
			const dep = schedule.depends_on
				? (allSchedules.find((s) => s.id === schedule.depends_on)?.analysis_name ?? '')
				: '';
			return (
				schedule.id.toLowerCase().includes(q) ||
				schedule.datasource_id.toLowerCase().includes(q) ||
				dsName.includes(q) ||
				(schedule.analysis_id ?? '').toLowerCase().includes(q) ||
				(schedule.analysis_name ?? '').toLowerCase().includes(q) ||
				(schedule.tab_name ?? '').toLowerCase().includes(q) ||
				triggerDs.toLowerCase().includes(q) ||
				dep.toLowerCase().includes(q) ||
				schedule.cron_expression.toLowerCase().includes(q)
			);
		});
	});

	const targetDatasource = $derived.by(() => {
		if (!datasourceId) return null;
		return datasourceMap.get(datasourceId) ?? null;
	});

	const scheduleBlocked = $derived.by(() => {
		if (!datasourceId) return false;
		if (!targetDatasource) return true;
		return targetDatasource.created_by !== 'analysis';
	});

	const showBlockedMessage = $derived.by(() => {
		if (!datasourceId) return false;
		if (!targetDatasource) return false;
		return targetDatasource.created_by !== 'analysis';
	});

	const currentTarget = $derived.by(() => {
		const ds = targetDatasource;
		if (!ds) return null;
		return {
			datasourceName: ds.name,
			analysisName: ds.created_by_analysis_id ? 'Analysis' : 'Unknown',
			tabName: ds.output_of_tab_id ? 'Tab' : null
		};
	});

	const selectedDatasource = $derived.by(() => {
		if (!newDatasourceId) return null;
		return datasourceMap.get(newDatasourceId) ?? null;
	});

	function getTriggerType(schedule: Schedule): 'cron' | 'depends' | 'event' {
		if (schedule.trigger_on_datasource_id) return 'event';
		if (schedule.depends_on) return 'depends';
		return 'cron';
	}

	function getTriggerLabel(type: 'cron' | 'depends' | 'event'): string {
		if (type === 'cron') return 'Cron';
		if (type === 'depends') return 'Depends';
		return 'Event';
	}

	function getTriggerDescription(schedule: Schedule): string {
		const type = getTriggerType(schedule);
		if (type === 'event') {
			const dsId = schedule.trigger_on_datasource_id;
			const dsName = dsId ? (datasourceMap.get(dsId)?.name ?? dsId.slice(0, 8) + '...') : 'Unknown';
			return `When ${dsName} updates`;
		}
		if (type === 'depends') {
			const depId = schedule.depends_on;
			const depSched = allSchedules.find((s) => s.id === depId);
			const depName = depSched
				? (depSched.analysis_name ?? depSched.analysis_id?.slice(0, 8) + '...')
				: depId?.slice(0, 8) + '...';
			return `After "${depName}" completes`;
		}
		return getCronDescription(schedule.cron_expression);
	}

	function getCronDescription(cron: string): string {
		const patterns: Record<string, string> = {
			'0 * * * *': 'Every hour',
			'0 0 * * *': 'Daily at midnight',
			'0 12 * * *': 'Daily at noon',
			'0 0 * * 0': 'Weekly on Sunday',
			'0 0 1 * *': 'Monthly on the 1st',
			'*/5 * * * *': 'Every 5 minutes',
			'*/15 * * * *': 'Every 15 minutes',
			'*/30 * * * *': 'Every 30 minutes',
			'0 9 * * 1': 'Weekly on Monday at 9am',
			'0 17 * * 5': 'Weekly on Friday at 5pm'
		};
		return patterns[cron] ?? `Cron: ${cron}`;
	}

	function depOptions(exclude?: string): Schedule[] {
		return allSchedules.filter((s) => s.id !== exclude);
	}

	function depLabel(id: string): string {
		const sched = allSchedules.find((s) => s.id === id);
		if (!sched) return id.slice(0, 8) + '...';
		const name =
			sched.analysis_name ??
			(sched.analysis_id ? sched.analysis_id.slice(0, 8) + '...' : 'Unknown');
		const label = `${name} (${sched.cron_expression})`;
		return label.length > 40 ? `${label.slice(0, 39)}…` : label;
	}

	function resolveDatasource(id: string | null): string {
		if (!id) return '-';
		const ds = datasourceMap.get(id);
		if (!ds) return id.slice(0, 8) + '...';
		return ds.name;
	}

	const createMut = createMutation(() => ({
		mutationFn: async (payload: ScheduleCreate) => {
			const result = await createSchedule(payload);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['schedules'] });
			creating = false;
			triggerType = 'cron';
			newCron = defaultCron;
			newDatasourceId = '';
			newDependsOn = '';
			newTrigger = '';
		}
	}));

	const toggleMut = createMutation(() => ({
		mutationFn: async (args: { id: string; enabled: boolean }) => {
			const result = await updateSchedule(args.id, { enabled: args.enabled });
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['schedules'] });
		}
	}));

	const cronMut = createMutation(() => ({
		mutationFn: async (args: { id: string; cron: string }) => {
			const result = await updateSchedule(args.id, {
				cron_expression: args.cron,
				depends_on: null,
				trigger_on_datasource_id: null
			});
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['schedules'] });
			editingCron = null;
			editCronValue = '';
		}
	}));

	const depMut = createMutation(() => ({
		mutationFn: async (args: { id: string; depends_on: string | null }) => {
			const result = await updateSchedule(args.id, {
				depends_on: args.depends_on,
				trigger_on_datasource_id: null
			});
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['schedules'] });
		}
	}));

	const triggerMut = createMutation(() => ({
		mutationFn: async (args: { id: string; trigger_on_datasource_id: string | null }) => {
			const payload: ScheduleUpdate = {
				trigger_on_datasource_id: args.trigger_on_datasource_id,
				depends_on: null
			};
			const result = await updateSchedule(args.id, payload);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['schedules'] });
		}
	}));

	const deleteMut = createMutation(() => ({
		mutationFn: async (id: string) => {
			const result = await deleteSchedule(id);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['schedules'] });
		}
	}));

	function handleCreate() {
		if (scheduleBlocked) return;
		const targetDs = datasourceId ?? newDatasourceId;
		if (!targetDs) return;

		const payload: ScheduleCreate = {
			datasource_id: targetDs,
			cron_expression: newCron
		};

		if (triggerType === 'depends' && newDependsOn) {
			payload.depends_on = newDependsOn;
		}

		if (triggerType === 'event' && newTrigger) {
			payload.trigger_on_datasource_id = newTrigger;
		}

		createMut.mutate(payload);
	}

	function handleToggle(schedule: Schedule) {
		if (scheduleBlocked) return;
		toggleMut.mutate({ id: schedule.id, enabled: !schedule.enabled });
	}

	function handleDelete(id: string) {
		deleteMut.mutate(id);
	}

	function startEditCron(schedule: Schedule) {
		if (scheduleBlocked) return;
		editingCron = schedule.id;
		editCronValue = schedule.cron_expression;
	}

	function saveCron(id: string) {
		if (scheduleBlocked) return;
		if (!editCronValue.trim()) return;
		cronMut.mutate({ id, cron: editCronValue.trim() });
	}

	function cancelEditCron() {
		editingCron = null;
		editCronValue = '';
	}

	function handleDepChange(id: string, value: string) {
		if (scheduleBlocked) return;
		depMut.mutate({ id, depends_on: value || null });
	}

	function handleTriggerChange(id: string, value: string) {
		if (scheduleBlocked) return;
		triggerMut.mutate({ id, trigger_on_datasource_id: value || null });
	}

	function openCreate() {
		if (scheduleBlocked) return;
		creating = true;
	}

	function toggleExpand(id: string) {
		expandedId = expandedId === id ? null : id;
	}

	function formatDate(iso: string | null): string {
		if (!iso) return '-';
		return new Date(iso).toLocaleString();
	}

	function getProvenanceDisplay(schedule: Schedule): string {
		if (schedule.analysis_name && schedule.tab_name) {
			return `${schedule.analysis_name} → ${schedule.tab_name}`;
		}
		if (schedule.analysis_name) {
			return schedule.analysis_name;
		}
		if (schedule.analysis_id) {
			return schedule.analysis_id.slice(0, 8) + '...';
		}
		return 'Unknown';
	}

	const colCount = $derived.by(() => {
		let count = 7;
		if (!datasourceId) count += 1;
		return count;
	});
</script>

<div class="flex flex-col h-full w-full">
	{#if !compact}
		<header class="mb-6 border-b border-tertiary pb-5">
			<div class="flex items-center justify-between">
				<div>
					<h1 class="m-0 mb-2 text-2xl">Schedules</h1>
					<p class="m-0 text-fg-tertiary">
						Manage automated dataset rebuilds via cron expressions, dependencies, or datasource
						events
					</p>
				</div>
				<button
					class="inline-flex items-center gap-1.5 border border-tertiary bg-accent-bg px-3 py-1.5 text-sm text-accent-primary hover:bg-accent-bg/80"
					onclick={openCreate}
					disabled={scheduleBlocked}
				>
					<Plus size={14} />
					New Schedule
				</button>
			</div>
			{#if externalSearch === undefined}
				<div class="mt-4 flex flex-wrap items-center gap-3">
					<div class="relative min-w-60 max-w-100 flex-1">
						<Search size={14} class="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-muted" />
						<input
							type="text"
							placeholder="Search schedules, datasources, or IDs..."
							class="w-full border border-tertiary bg-transparent px-3 py-1.5 pl-8 text-sm"
							bind:value={searchQuery}
						/>
					</div>
				</div>
			{/if}
		</header>
	{:else}
		<div class="mb-3 flex items-center justify-between">
			<span class="text-xs font-semibold uppercase tracking-wide text-fg-muted">
				Schedules
				{#if schedules.length > 0}
					<span class="text-fg-tertiary">({schedules.length})</span>
				{/if}
			</span>
			<div class="flex items-center gap-1">
				<button
					class="inline-flex items-center gap-1 border border-tertiary bg-accent-bg px-2 py-1 text-xs text-accent-primary hover:bg-accent-bg/80"
					onclick={openCreate}
					disabled={scheduleBlocked}
				>
					<Plus size={12} />
					Add
				</button>
				<button
					class="inline-flex items-center justify-center border-none bg-transparent p-0.5 text-fg-muted hover:text-fg-primary"
					onclick={() => (showHelp = !showHelp)}
					title="Show help"
				>
					<HelpCircle size={14} />
				</button>
			</div>
		</div>
		{#if showHelp}
			<div class="mb-3 border border-info bg-info-bg/50 p-2 text-xs text-fg-secondary">
				<p class="m-0 mb-1 font-medium">Schedule Triggers:</p>
				<ul class="m-0 list-none space-y-1 p-0">
					<li class="flex items-center gap-1">
						<Clock size={10} class="text-fg-muted" /> <strong>On a Schedule</strong> — runs on a cron
						interval
					</li>
					<li class="flex items-center gap-1">
						<Link size={10} class="text-fg-muted" /> <strong>After Another Schedule</strong> — runs when
						a dependency completes
					</li>
					<li class="flex items-center gap-1">
						<Database size={10} class="text-fg-muted" /> <strong>When Dataset Updates</strong> — runs
						on datasource change
					</li>
				</ul>
			</div>
		{/if}
	{/if}

	{#if showBlockedMessage}
		<div class="mb-3 border border-info bg-info-bg/50 p-2 text-xs text-fg-secondary">
			Scheduling is only available for analysis outputs. This datasource was created by
			<span class="font-medium">{targetDatasource?.created_by}</span>.
		</div>
	{/if}

	{#if creating}
		<div class="mb-4 border border-tertiary bg-bg-primary p-4" class:mb-6={!compact}>
			<h3 class="m-0 mb-4 text-sm font-medium">Create Schedule</h3>

			<!-- Target Section -->
			<div class="mb-5">
				<div class="mb-3 flex items-center gap-2 border-b border-tertiary pb-2">
					<Database size={14} class="text-accent-primary" />
					<span class="text-xs font-medium">Target Dataset — What gets rebuilt</span>
				</div>

				{#if currentTarget}
					<div class="bg-bg-secondary p-3 text-sm">
						<div class="flex items-center gap-2">
							<BarChart3 size={14} class="text-accent-primary" />
							<span class="font-medium">{currentTarget.datasourceName}</span>
						</div>
						<div class="mt-1 flex items-center gap-1 text-xs text-fg-muted">
							<span>└─ Produced by:</span>
							<span class="text-fg-secondary">{currentTarget.analysisName}</span>
							{#if currentTarget.tabName}
								<ArrowRight size={10} />
								<span class="text-fg-secondary">Tab "{currentTarget.tabName}"</span>
							{/if}
						</div>
					</div>
				{:else}
					<div class="flex flex-col gap-3">
						<div class="flex min-w-64 flex-1 flex-col gap-1.5">
							<label for="schedule-datasource" class="text-xs text-fg-muted">
								Select output dataset
							</label>
							<select
								id="schedule-datasource"
								class="border border-tertiary bg-transparent px-2 py-1.5 text-xs"
								bind:value={newDatasourceId}
								disabled={scheduleBlocked}
							>
								<option value="">Select output dataset...</option>
								{#each analysisOutputs as ds (ds.id)}
									<option value={ds.id}>{ds.name}</option>
								{/each}
							</select>
						</div>

						{#if selectedDatasource}
							<div class="bg-bg-secondary p-3 text-sm">
								<div class="flex items-center gap-2">
									<BarChart3 size={14} class="text-accent-primary" />
									<span class="font-medium">{selectedDatasource.name}</span>
								</div>
								<div class="mt-1 flex items-center gap-1 text-xs text-fg-muted">
									<span>└─ Produced by:</span>
									{#if selectedDatasource.created_by_analysis_id}
										<span class="text-fg-secondary">Analysis</span>
										{#if selectedDatasource.output_of_tab_id}
											<ArrowRight size={10} />
											<span class="text-fg-secondary">Tab</span>
										{/if}
									{:else}
										<span class="text-fg-secondary">Unknown</span>
									{/if}
								</div>
							</div>
						{/if}
					</div>
				{/if}
			</div>

			<!-- Trigger Section -->
			<div>
				<div class="mb-3 flex items-center gap-2 border-b border-tertiary pb-2">
					<Clock size={14} class="text-accent-primary" />
					<span class="text-xs font-medium">When to Run — What triggers the build</span>
				</div>

				<div class="space-y-3">
					<!-- Cron Option -->
					<label
						class="flex cursor-pointer items-start gap-3 border border-tertiary bg-bg-secondary p-3 hover:bg-bg-hover"
					>
						<input
							type="radio"
							name="triggerType"
							value="cron"
							bind:group={triggerType}
							class="mt-0.5"
							disabled={scheduleBlocked}
						/>
						<div class="flex-1">
							<div class="mb-1 text-xs font-medium">On a Schedule</div>
							<p class="m-0 text-xs text-fg-tertiary">Run on a recurring cron interval</p>
							{#if triggerType === 'cron'}
								<div class="mt-2 flex items-center gap-2">
									<input
										type="text"
										class="w-32 border border-tertiary bg-transparent px-2 py-1 font-mono text-xs"
										bind:value={newCron}
										placeholder="0 * * * *"
										disabled={scheduleBlocked}
									/>
									<span class="text-xs text-fg-muted">{getCronDescription(newCron)}</span>
								</div>
							{/if}
						</div>
					</label>

					<!-- Depends Option -->
					<label
						class="flex cursor-pointer items-start gap-3 border border-tertiary bg-bg-secondary p-3 hover:bg-bg-hover"
					>
						<input
							type="radio"
							name="triggerType"
							value="depends"
							bind:group={triggerType}
							class="mt-0.5"
							disabled={scheduleBlocked}
						/>
						<div class="flex-1">
							<div class="mb-1 flex items-center gap-1 text-xs font-medium">
								<Link size={12} class="text-fg-muted" />
								After Another Schedule
							</div>
							<p class="m-0 text-xs text-fg-tertiary">
								Run after another schedule completes successfully
							</p>
							{#if triggerType === 'depends'}
								<div class="mt-2">
									<select
										class="w-full border border-tertiary bg-transparent px-2 py-1 text-xs"
										bind:value={newDependsOn}
										disabled={scheduleBlocked}
									>
										<option value="">Select a schedule...</option>
										{#each depOptions() as dep (dep.id)}
											<option value={dep.id}>{depLabel(dep.id)}</option>
										{/each}
									</select>
								</div>
							{/if}
						</div>
					</label>

					<!-- Event Option -->
					<label
						class="flex cursor-pointer items-start gap-3 border border-tertiary bg-bg-secondary p-3 hover:bg-bg-hover"
					>
						<input
							type="radio"
							name="triggerType"
							value="event"
							bind:group={triggerType}
							class="mt-0.5"
							disabled={scheduleBlocked}
						/>
						<div class="flex-1">
							<div class="mb-1 flex items-center gap-1 text-xs font-medium">
								<Database size={12} class="text-fg-muted" />
								When Dataset Updates
							</div>
							<p class="m-0 text-xs text-fg-tertiary">Run when a specific datasource is updated</p>
							{#if triggerType === 'event'}
								<div class="mt-2">
									<select
										class="w-full border border-tertiary bg-transparent px-2 py-1 text-xs"
										bind:value={newTrigger}
										disabled={scheduleBlocked}
									>
										<option value="">Select a datasource...</option>
										{#each triggerables as ds (ds.id)}
											<option value={ds.id}>{ds.name}</option>
										{/each}
									</select>
								</div>
							{/if}
						</div>
					</label>
				</div>
			</div>

			<div class="mt-4 flex gap-2 border-t border-tertiary pt-4">
				<button
					class="border border-tertiary bg-accent-bg px-3 py-1.5 text-xs text-accent-primary hover:bg-accent-bg/80"
					onclick={handleCreate}
					disabled={(!datasourceId && !newDatasourceId) ||
						(triggerType === 'cron' && !newCron) ||
						(triggerType === 'depends' && !newDependsOn) ||
						(triggerType === 'event' && !newTrigger) ||
						createMut.isPending ||
						scheduleBlocked}
				>
					{createMut.isPending ? 'Creating...' : 'Create Schedule'}
				</button>
				<button
					class="border border-tertiary bg-transparent px-3 py-1.5 text-xs text-fg-tertiary hover:text-fg-primary"
					onclick={() => (creating = false)}
				>
					Cancel
				</button>
			</div>

			{#if createMut.isError}
				<p class="mt-3 text-xs text-error-fg">
					{createMut.error instanceof Error ? createMut.error.message : 'Failed to create schedule'}
				</p>
			{/if}
		</div>
	{/if}

	{#if schedulesQuery.isLoading}
		<div class="flex items-center justify-center py-6">
			<div class="spinner"></div>
		</div>
	{:else if schedulesQuery.isError}
		<div class="error-box">
			{schedulesQuery.error instanceof Error
				? schedulesQuery.error.message
				: 'Error loading schedules.'}
		</div>
	{:else if schedules.length === 0 && !creating}
		<div class="border border-dashed border-tertiary p-6 text-center" class:p-8={!compact}>
			<Calendar class="mx-auto mb-2 text-fg-muted" size={compact ? 20 : 32} />
			<p class="text-sm text-fg-muted">No schedules configured.</p>
			{#if !compact}
				<p class="text-xs text-fg-tertiary">
					Create a schedule to automatically rebuild datasets on a trigger.
				</p>
			{/if}
		</div>
	{:else if visibleSchedules.length === 0 && hasSearch}
		<div class="border border-dashed border-tertiary px-6 py-8 text-center">
			<p class="text-sm text-fg-tertiary">No schedules match your search.</p>
		</div>
	{:else if visibleSchedules.length > 0}
		{#if compact}
			<!-- Compact card list -->
			<div class="flex flex-col gap-1">
				{#each visibleSchedules as schedule (schedule.id)}
					{@const triggerTypeValue = getTriggerType(schedule)}
					{@const triggerDesc = getTriggerDescription(schedule)}
					<div class="group border border-tertiary bg-bg-primary">
						<div
							class="flex cursor-pointer items-center gap-2 p-2 hover:bg-bg-secondary/50"
							role="button"
							tabindex="0"
							onclick={() => toggleExpand(schedule.id)}
							onkeydown={(e) => {
								if (e.key === 'Enter' || e.key === ' ') {
									e.preventDefault();
									toggleExpand(schedule.id);
								}
							}}
						>
							<ChevronDown
								size={10}
								class="shrink-0 text-fg-muted {expandedId === schedule.id ? '' : '-rotate-90'}"
							/>
							{#if triggerTypeValue === 'cron'}
								<Clock size={12} class="shrink-0 text-fg-muted" />
							{:else if triggerTypeValue === 'depends'}
								<Link size={12} class="shrink-0 text-fg-muted" />
							{:else}
								<Database size={12} class="shrink-0 text-fg-muted" />
							{/if}
							<span class="min-w-0 flex-1 truncate text-xs text-fg-secondary" title={triggerDesc}>
								{triggerDesc}
							</span>
							<button
								class="inline-flex shrink-0 items-center gap-0.5 border-none bg-transparent p-0 text-[10px]"
								onclick={(e) => {
									e.stopPropagation();
									handleToggle(schedule);
								}}
								disabled={toggleMut.isPending || scheduleBlocked}
								title={schedule.enabled ? 'Click to disable' : 'Click to enable'}
							>
								{#if schedule.enabled}
									<Power size={10} class="text-success-fg" />
								{:else}
									<PowerOff size={10} class="text-fg-muted" />
								{/if}
							</button>
							<button
								class="shrink-0 border-none bg-transparent p-0 text-fg-tertiary opacity-0 group-hover:opacity-100 hover:text-error-fg"
								onclick={(e) => {
									e.stopPropagation();
									handleDelete(schedule.id);
								}}
								disabled={deleteMut.isPending}
								title="Delete schedule"
							>
								<Trash2 size={10} />
							</button>
						</div>
						{#if expandedId === schedule.id}
							<div class="border-t border-tertiary px-3 py-2">
								<div class="flex flex-col gap-2">
									{#if triggerTypeValue === 'cron'}
										<div class="flex flex-col gap-1">
											<span class="text-[10px] text-fg-muted">Cron Expression</span>
											{#if editingCron === schedule.id}
												<div class="flex items-center gap-1">
													<input
														type="text"
														class="w-full border border-tertiary bg-transparent px-1.5 py-0.5 font-mono text-[10px]"
														bind:value={editCronValue}
														onkeydown={(e) => {
															if (e.key === 'Enter') saveCron(schedule.id);
															if (e.key === 'Escape') cancelEditCron();
														}}
														disabled={scheduleBlocked}
													/>
													<button
														class="shrink-0 border-none bg-transparent p-0.5 text-success-fg"
														onclick={() => saveCron(schedule.id)}
														disabled={cronMut.isPending || scheduleBlocked}
														title="Save"
													>
														<Check size={12} />
													</button>
													<button
														class="shrink-0 border-none bg-transparent p-0.5 text-fg-muted hover:text-fg-primary"
														onclick={cancelEditCron}
														title="Cancel"
													>
														<X size={12} />
													</button>
												</div>
											{:else}
												<div class="flex items-center gap-1">
													<code class="bg-bg-tertiary px-1 py-0.5 text-[10px]">
														{schedule.cron_expression}
													</code>
													<button
														class="border-none bg-transparent p-0.5 text-fg-muted hover:text-fg-primary"
														onclick={() => startEditCron(schedule)}
														title="Edit"
														disabled={scheduleBlocked}
													>
														<Pencil size={10} />
													</button>
												</div>
											{/if}
										</div>
									{:else if triggerTypeValue === 'depends'}
										<div class="flex flex-col gap-1">
											<span class="text-[10px] text-fg-muted">Depends On</span>
											<select
												class="w-full border border-tertiary bg-transparent px-1.5 py-0.5 text-[10px]"
												value={schedule.depends_on ?? ''}
												onchange={(e) => handleDepChange(schedule.id, e.currentTarget.value)}
												onclick={(e) => e.stopPropagation()}
												disabled={scheduleBlocked}
											>
												<option value="">None</option>
												{#each depOptions(schedule.id) as dep (dep.id)}
													<option value={dep.id}>{depLabel(dep.id)}</option>
												{/each}
											</select>
										</div>
									{:else}
										<div class="flex flex-col gap-1">
											<span class="text-[10px] text-fg-muted">On Datasource Update</span>
											<select
												class="w-full border border-tertiary bg-transparent px-1.5 py-0.5 text-[10px]"
												value={schedule.trigger_on_datasource_id ?? ''}
												onchange={(e) => handleTriggerChange(schedule.id, e.currentTarget.value)}
												onclick={(e) => e.stopPropagation()}
												disabled={scheduleBlocked}
											>
												<option value="">None</option>
												{#each triggerables as ds (ds.id)}
													<option value={ds.id}>{ds.name}</option>
												{/each}
											</select>
										</div>
									{/if}
									{#if schedule.next_run}
										<div class="text-[10px] text-fg-muted">
											Next: {formatDate(schedule.next_run)}
										</div>
									{/if}
								</div>
							</div>
						{/if}
					</div>
				{/each}
			</div>
		{:else}
			<!-- Full table view -->
			<div class="overflow-x-auto border border-tertiary">
				<table class="w-full border-collapse text-xs">
					<thead>
						<tr class="bg-bg-tertiary">
							<th class="w-6 border-b border-tertiary px-2 py-1.5 text-left font-medium"></th>
							{#if !datasourceId}
								<th class="border-b border-tertiary px-2 py-1.5 text-left font-medium">Target</th>
							{/if}
							<th class="border-b border-tertiary px-2 py-1.5 text-left font-medium">Produced By</th
							>
							<th class="border-b border-tertiary px-2 py-1.5 text-left font-medium"
								>Trigger Type</th
							>
							<th class="border-b border-tertiary px-2 py-1.5 text-left font-medium">Trigger</th>
							<th class="border-b border-tertiary px-2 py-1.5 text-left font-medium">Status</th>
							<th class="border-b border-tertiary px-2 py-1.5 text-left font-medium">Next Run</th>
							<th class="w-16 border-b border-tertiary px-2 py-1.5 text-left font-medium"></th>
						</tr>
					</thead>
					<tbody>
						{#each visibleSchedules as schedule (schedule.id)}
							{@const triggerTypeValue = getTriggerType(schedule)}
							{@const triggerDesc = getTriggerDescription(schedule)}
							{@const provenanceDisplay = getProvenanceDisplay(schedule)}
							<tr
								class="cursor-pointer hover:bg-bg-hover"
								class:bg-bg-secondary={expandedId === schedule.id}
								onclick={() => toggleExpand(schedule.id)}
							>
								<td class="border-b border-tertiary px-2 py-1.5">
									<ChevronDown
										size={12}
										class="transition-transform {expandedId === schedule.id ? '' : '-rotate-90'}"
									/>
								</td>
								{#if !datasourceId}
									<td class="border-b border-tertiary px-2 py-1.5">
										<span
											class="inline-flex max-w-40 items-center gap-1 truncate text-fg-secondary"
											title={resolveDatasource(schedule.datasource_id)}
										>
											<BarChart3 size={10} class="shrink-0 text-fg-muted" />
											{resolveDatasource(schedule.datasource_id)}
										</span>
									</td>
								{/if}
								<td class="border-b border-tertiary px-2 py-1.5">
									<span class="block max-w-48 truncate text-fg-secondary" title={provenanceDisplay}>
										{provenanceDisplay}
									</span>
								</td>
								<td class="border-b border-tertiary px-2 py-1.5">
									<span class="text-fg-secondary">{getTriggerLabel(triggerTypeValue)}</span>
								</td>
								<td class="border-b border-tertiary px-2 py-1.5">
									<div class="flex items-center gap-1.5">
										{#if triggerTypeValue === 'cron'}
											<Clock size={12} class="shrink-0 text-fg-muted" />
										{:else if triggerTypeValue === 'depends'}
											<Link size={12} class="shrink-0 text-fg-muted" />
										{:else}
											<Database size={12} class="shrink-0 text-fg-muted" />
										{/if}
										<span class="truncate" title={triggerDesc}>
											{triggerDesc}
										</span>
									</div>
								</td>
								<td class="border-b border-tertiary px-2 py-1.5">
									<button
										class="inline-flex items-center gap-1 border-none bg-transparent p-0 text-xs"
										onclick={(e) => {
											e.stopPropagation();
											handleToggle(schedule);
										}}
										disabled={toggleMut.isPending || scheduleBlocked}
										title={schedule.enabled ? 'Click to disable' : 'Click to enable'}
									>
										{#if schedule.enabled}
											<Power size={12} class="text-success-fg" />
											<span class="text-success-fg">On</span>
										{:else}
											<PowerOff size={12} class="text-fg-muted" />
											<span class="text-fg-muted">Off</span>
										{/if}
									</button>
								</td>
								<td class="border-b border-tertiary px-2 py-1.5 text-fg-secondary">
									{formatDate(schedule.next_run)}
								</td>
								<td class="border-b border-tertiary px-2 py-1.5">
									<button
										class="inline-flex items-center justify-center border-none bg-transparent p-0.5 text-fg-muted hover:text-error-fg"
										onclick={(e) => {
											e.stopPropagation();
											handleDelete(schedule.id);
										}}
										disabled={deleteMut.isPending}
										title="Delete schedule"
									>
										<Trash2 size={12} />
									</button>
								</td>
							</tr>
							{#if expandedId === schedule.id}
								<tr>
									<td colspan={colCount} class="border-b border-tertiary bg-bg-primary p-0">
										<div class="flex flex-wrap items-start gap-4 px-4 py-3">
											<div class="flex flex-col gap-1">
												<span class="text-[10px] text-fg-muted">Target Datasource</span>
												<div class="flex items-center gap-1">
													<BarChart3 size={10} class="text-fg-muted" />
													<span class="text-[10px] text-fg-secondary">
														{resolveDatasource(schedule.datasource_id)}
													</span>
												</div>
											</div>
											<div class="flex flex-col gap-1">
												<span class="text-[10px] text-fg-muted">Produced By</span>
												<span class="text-[10px] text-fg-secondary">
													{provenanceDisplay}
												</span>
											</div>
											{#if triggerTypeValue === 'cron'}
												<div class="flex flex-col gap-1">
													<span class="text-[10px] text-fg-muted">Cron Expression</span>
													{#if editingCron === schedule.id}
														<div class="flex items-center gap-1">
															<input
																type="text"
																class="w-32 border border-tertiary bg-transparent px-1.5 py-0.5 font-mono text-[10px]"
																bind:value={editCronValue}
																onkeydown={(e) => {
																	if (e.key === 'Enter') saveCron(schedule.id);
																	if (e.key === 'Escape') cancelEditCron();
																}}
																disabled={scheduleBlocked}
															/>
															<button
																class="inline-flex items-center justify-center border-none bg-transparent p-0.5 text-success-fg hover:text-success-fg/80"
																onclick={() => saveCron(schedule.id)}
																disabled={cronMut.isPending || scheduleBlocked}
																title="Save"
															>
																<Check size={12} />
															</button>
															<button
																class="inline-flex items-center justify-center border-none bg-transparent p-0.5 text-fg-muted hover:text-fg-primary"
																onclick={cancelEditCron}
																title="Cancel"
															>
																<X size={12} />
															</button>
														</div>
													{:else}
														<div class="flex items-center gap-1">
															<code class="bg-bg-tertiary px-1 py-0.5 text-[10px]">
																{schedule.cron_expression}
															</code>
															<button
																class="inline-flex items-center justify-center border-none bg-transparent p-0.5 text-fg-muted hover:text-fg-primary"
																onclick={() => startEditCron(schedule)}
																title="Edit cron expression"
																disabled={scheduleBlocked}
															>
																<Pencil size={10} />
															</button>
														</div>
													{/if}
												</div>
											{:else if triggerTypeValue === 'depends'}
												<div class="flex flex-col gap-1">
													<span class="text-[10px] text-fg-muted">Depends On</span>
													<div class="flex items-center gap-1">
														<select
															class="border border-tertiary bg-transparent px-1.5 py-0.5 text-[10px]"
															value={schedule.depends_on ?? ''}
															onchange={(e) => handleDepChange(schedule.id, e.currentTarget.value)}
															onclick={(e) => e.stopPropagation()}
															disabled={scheduleBlocked}
														>
															<option value="">None</option>
															{#each depOptions(schedule.id) as dep (dep.id)}
																<option value={dep.id}>{depLabel(dep.id)}</option>
															{/each}
														</select>
														{#if schedule.depends_on}
															<Link size={10} class="text-fg-muted" />
														{/if}
													</div>
												</div>
											{:else}
												<div class="flex flex-col gap-1">
													<span class="text-[10px] text-fg-muted">On Datasource Update</span>
													<div class="flex items-center gap-1">
														<select
															class="border border-tertiary bg-transparent px-1.5 py-0.5 text-[10px]"
															value={schedule.trigger_on_datasource_id ?? ''}
															onchange={(e) =>
																handleTriggerChange(schedule.id, e.currentTarget.value)}
															onclick={(e) => e.stopPropagation()}
															disabled={scheduleBlocked}
														>
															<option value="">None</option>
															{#each triggerables as ds (ds.id)}
																<option value={ds.id}>{ds.name}</option>
															{/each}
														</select>
														{#if schedule.trigger_on_datasource_id}
															<Database size={10} class="text-fg-muted" />
														{/if}
													</div>
												</div>
											{/if}
											<div class="flex flex-col gap-1">
												<span class="text-[10px] text-fg-muted">Created</span>
												<span class="text-[10px] text-fg-secondary">
													{formatDate(schedule.created_at)}
												</span>
											</div>
											<div class="flex flex-col gap-1">
												<span class="text-[10px] text-fg-muted">Schedule ID</span>
												<span class="font-mono text-[10px] text-fg-secondary">
													{schedule.id}
												</span>
											</div>
										</div>
									</td>
								</tr>
							{/if}
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	{/if}
</div>
