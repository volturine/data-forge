<script lang="ts">
	import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { listSchedules, createSchedule, updateSchedule, deleteSchedule } from '$lib/api/schedule';
	import type { Schedule, ScheduleCreate } from '$lib/api/schedule';
	import { listAnalyses } from '$lib/api/analysis';
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
		Database
	} from 'lucide-svelte';
	import { SvelteMap } from 'svelte/reactivity';

	interface Props {
		analysisId?: string;
		datasourceId?: string;
		compact?: boolean;
	}

	let { analysisId, datasourceId, compact = false }: Props = $props();

	const queryClient = useQueryClient();

	let creating = $state(false);
	let newCron = $state('0 * * * *');
	let newAnalysisId = $state('');
	let newDatasourceId = $state('');
	let newDependsOn = $state('');
	let expandedId = $state<string | null>(null);
	let editingCron = $state<string | null>(null);
	let editCronValue = $state('');

	const schedulesQuery = createQuery(() => ({
		queryKey: ['schedules', analysisId ?? 'all', datasourceId ?? 'all'],
		queryFn: async () => {
			const result = await listSchedules(analysisId, datasourceId);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		}
	}));

	// Fetch all schedules for the dependency dropdown
	const allSchedulesQuery = createQuery(() => ({
		queryKey: ['schedules', 'all', 'all'],
		queryFn: async () => {
			const result = await listSchedules();
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		staleTime: 30_000
	}));

	const analysesQuery = createQuery(() => ({
		queryKey: ['analyses-lookup'],
		queryFn: async () => {
			const result = await listAnalyses();
			if (result.isErr()) return [];
			return result.value;
		},
		staleTime: 60_000,
		enabled: !analysisId
	}));

	const datasourcesQuery = createQuery(() => ({
		queryKey: ['datasources-lookup'],
		queryFn: async () => {
			const result = await listDatasources();
			if (result.isErr()) return [] as DataSource[];
			return result.value;
		},
		staleTime: 60_000,
		enabled: !datasourceId
	}));

	const analysisNames = $derived.by(() => {
		const map = new SvelteMap<string, string>();
		for (const a of analysesQuery.data ?? []) {
			map.set(a.id, a.name);
		}
		return map;
	});

	const datasourceMap = $derived.by(() => {
		const map = new SvelteMap<string, DataSource>();
		for (const ds of datasourcesQuery.data ?? []) {
			map.set(ds.id, ds);
		}
		return map;
	});

	const schedules = $derived(schedulesQuery.data ?? []);
	const allSchedules = $derived(allSchedulesQuery.data ?? []);

	// Available dependency targets: all schedules except the one being created/edited
	function depOptions(exclude?: string): Schedule[] {
		return allSchedules.filter((s) => s.id !== exclude);
	}

	function depLabel(id: string): string {
		const sched = allSchedules.find((s) => s.id === id);
		if (!sched) return id.slice(0, 8) + '...';
		const name = resolveName(sched.analysis_id);
		return `${name} (${sched.cron_expression})`;
	}

	function resolveDatasource(id: string | null): string {
		if (!id) return '-';
		const ds = datasourceMap.get(id);
		if (!ds) return id.slice(0, 8) + '...';
		return `${ds.name} (${ds.source_type})`;
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
			newCron = '0 * * * *';
			newAnalysisId = '';
			newDatasourceId = '';
			newDependsOn = '';
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
			const result = await updateSchedule(args.id, { cron_expression: args.cron });
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
			const result = await updateSchedule(args.id, { depends_on: args.depends_on });
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['schedules'] });
		}
	}));

	const dsMut = createMutation(() => ({
		mutationFn: async (args: { id: string; datasource_id: string | null }) => {
			const result = await updateSchedule(args.id, { datasource_id: args.datasource_id });
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
		const targetId = analysisId ?? newAnalysisId;
		if (!targetId || !newCron) return;
		const payload: ScheduleCreate = { analysis_id: targetId, cron_expression: newCron };
		const targetDs = datasourceId ?? newDatasourceId;
		if (targetDs) payload.datasource_id = targetDs;
		if (newDependsOn) payload.depends_on = newDependsOn;
		createMut.mutate(payload);
	}

	function handleToggle(schedule: Schedule) {
		toggleMut.mutate({ id: schedule.id, enabled: !schedule.enabled });
	}

	function handleDelete(id: string) {
		deleteMut.mutate(id);
	}

	function startEditCron(schedule: Schedule) {
		editingCron = schedule.id;
		editCronValue = schedule.cron_expression;
	}

	function saveCron(id: string) {
		if (!editCronValue.trim()) return;
		cronMut.mutate({ id, cron: editCronValue.trim() });
	}

	function cancelEditCron() {
		editingCron = null;
		editCronValue = '';
	}

	function handleDepChange(id: string, value: string) {
		depMut.mutate({ id, depends_on: value || null });
	}

	function handleDsChange(id: string, value: string) {
		dsMut.mutate({ id, datasource_id: value || null });
	}

	function toggleExpand(id: string) {
		expandedId = expandedId === id ? null : id;
	}

	function formatDate(iso: string | null): string {
		if (!iso) return '-';
		return new Date(iso).toLocaleString();
	}

	function resolveName(id: string): string {
		return analysisNames.get(id) ?? id.slice(0, 8) + '...';
	}

	// Column count for expanded row colspan
	const colCount = $derived.by(() => {
		let count = 6; // expand + cron + status + last run + next run + actions
		if (!analysisId) count += 1;
		if (!datasourceId) count += 1;
		return count;
	});
</script>

<div class={compact ? '' : 'mx-auto max-w-300 px-6 py-7'}>
	{#if !compact}
		<header class="mb-6 border-b border-tertiary pb-5">
			<div class="flex items-center justify-between">
				<div>
					<h1 class="m-0 mb-2 text-2xl">Schedules</h1>
					<p class="m-0 text-fg-tertiary">Manage automated analysis builds via cron expressions</p>
				</div>
				<button
					class="inline-flex items-center gap-1.5 border border-tertiary bg-accent-bg px-3 py-1.5 text-sm text-accent-primary hover:bg-accent-bg/80"
					onclick={() => (creating = true)}
				>
					<Plus size={14} />
					New Schedule
				</button>
			</div>
		</header>
	{:else}
		<div class="mb-3 flex items-center justify-between">
			<span class="text-xs font-semibold uppercase tracking-wide text-fg-muted">
				Schedules
				{#if schedules.length > 0}
					<span class="text-fg-tertiary">({schedules.length})</span>
				{/if}
			</span>
			<button
				class="inline-flex items-center gap-1 border border-tertiary bg-accent-bg px-2 py-1 text-xs text-accent-primary hover:bg-accent-bg/80"
				onclick={() => (creating = true)}
			>
				<Plus size={12} />
				Add
			</button>
		</div>
	{/if}

	{#if creating}
		<div class="mb-4 border border-tertiary bg-bg-primary p-3" class:mb-6={!compact}>
			<h3 class="m-0 mb-2 text-xs font-medium">Create Schedule</h3>
			<div class="flex flex-wrap items-end gap-2" class:gap-3={!compact}>
				{#if !analysisId}
					<div class="flex min-w-40 flex-1 flex-col gap-1">
						<label for="schedule-analysis" class="text-xs text-fg-muted">Analysis</label>
						<select
							id="schedule-analysis"
							class="border border-tertiary bg-transparent px-2 py-1 text-xs"
							bind:value={newAnalysisId}
						>
							<option value="">Select analysis...</option>
							{#each analysesQuery.data ?? [] as analysis (analysis.id)}
								<option value={analysis.id}>{analysis.name}</option>
							{/each}
						</select>
					</div>
				{/if}
				{#if !datasourceId}
					<div class="flex min-w-40 flex-1 flex-col gap-1">
						<label for="schedule-datasource" class="text-xs text-fg-muted">Datasource</label>
						<select
							id="schedule-datasource"
							class="border border-tertiary bg-transparent px-2 py-1 text-xs"
							bind:value={newDatasourceId}
						>
							<option value="">All datasources</option>
							{#each datasourcesQuery.data ?? [] as ds (ds.id)}
								<option value={ds.id}>{ds.name} ({ds.source_type})</option>
							{/each}
						</select>
					</div>
				{/if}
				<div class="flex min-w-32 flex-col gap-1">
					<label for="schedule-cron" class="text-xs text-fg-muted">Cron Expression</label>
					<input
						id="schedule-cron"
						type="text"
						class="border border-tertiary bg-transparent px-2 py-1 font-mono text-xs"
						bind:value={newCron}
						placeholder="0 * * * *"
					/>
				</div>
				<div class="flex min-w-40 flex-col gap-1">
					<label for="schedule-depends" class="text-xs text-fg-muted">Depends On</label>
					<select
						id="schedule-depends"
						class="border border-tertiary bg-transparent px-2 py-1 text-xs"
						bind:value={newDependsOn}
					>
						<option value="">None</option>
						{#each depOptions() as dep (dep.id)}
							<option value={dep.id}>{depLabel(dep.id)}</option>
						{/each}
					</select>
				</div>
				<div class="flex gap-2">
					<button
						class="border border-tertiary bg-accent-bg px-2 py-1 text-xs text-accent-primary hover:bg-accent-bg/80"
						onclick={handleCreate}
						disabled={(!analysisId && !newAnalysisId) || !newCron || createMut.isPending}
					>
						{createMut.isPending ? 'Creating...' : 'Create'}
					</button>
					<button
						class="border border-tertiary bg-transparent px-2 py-1 text-xs text-fg-tertiary hover:text-fg-primary"
						onclick={() => (creating = false)}
					>
						Cancel
					</button>
				</div>
			</div>
			{#if createMut.isError}
				<p class="mt-2 text-xs text-error-fg">
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
			<Calendar size={compact ? 20 : 32} class="mx-auto mb-2 text-fg-muted" />
			<p class="text-sm text-fg-muted">No schedules configured.</p>
			{#if !compact}
				<p class="text-xs text-fg-tertiary">
					Create a schedule to automatically build analyses on a cron-based interval.
				</p>
			{/if}
		</div>
	{:else if schedules.length > 0}
		<div class="overflow-x-auto border border-tertiary">
			<table class="w-full border-collapse text-xs">
				<thead>
					<tr class="bg-bg-tertiary">
						<th class="w-6 border-b border-tertiary px-2 py-1.5 text-left font-medium"></th>
						{#if !analysisId}
							<th class="border-b border-tertiary px-2 py-1.5 text-left font-medium">Analysis</th>
						{/if}
						{#if !datasourceId}
							<th class="border-b border-tertiary px-2 py-1.5 text-left font-medium">Datasource</th>
						{/if}
						<th class="border-b border-tertiary px-2 py-1.5 text-left font-medium">Cron</th>
						<th class="border-b border-tertiary px-2 py-1.5 text-left font-medium">Status</th>
						<th class="border-b border-tertiary px-2 py-1.5 text-left font-medium">Last Run</th>
						<th class="border-b border-tertiary px-2 py-1.5 text-left font-medium">Next Run</th>
						<th class="w-16 border-b border-tertiary px-2 py-1.5 text-left font-medium"></th>
					</tr>
				</thead>
				<tbody>
					{#each schedules as schedule (schedule.id)}
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
							{#if !analysisId}
								<td class="border-b border-tertiary px-2 py-1.5">
									<span
										class="block max-w-40 truncate text-fg-secondary"
										title={resolveName(schedule.analysis_id)}
									>
										{resolveName(schedule.analysis_id)}
									</span>
								</td>
							{/if}
							{#if !datasourceId}
								<td class="border-b border-tertiary px-2 py-1.5">
									<span
										class="inline-flex max-w-40 items-center gap-1 truncate text-fg-secondary"
										title={resolveDatasource(schedule.datasource_id)}
									>
										{#if schedule.datasource_id}
											<Database size={10} class="shrink-0 text-fg-muted" />
											{resolveDatasource(schedule.datasource_id)}
										{:else}
											<span class="text-fg-muted">All</span>
										{/if}
									</span>
								</td>
							{/if}
							<td class="border-b border-tertiary px-2 py-1.5">
								<code class="bg-bg-tertiary px-1 py-0.5 text-[10px]"
									>{schedule.cron_expression}</code
								>
							</td>
							<td class="border-b border-tertiary px-2 py-1.5">
								<button
									class="inline-flex items-center gap-1 border-none bg-transparent p-0 text-xs"
									onclick={(e) => {
										e.stopPropagation();
										handleToggle(schedule);
									}}
									disabled={toggleMut.isPending}
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
								<span class="inline-flex items-center gap-1">
									<Clock size={10} class="text-fg-muted" />
									{formatDate(schedule.last_run)}
								</span>
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
										{#if !analysisId}
											<div class="flex flex-col gap-1">
												<span class="text-[10px] text-fg-muted">Analysis ID</span>
												<span class="font-mono text-[10px] text-fg-secondary">
													{schedule.analysis_id}
												</span>
											</div>
										{/if}
										<div class="flex flex-col gap-1">
											<span class="text-[10px] text-fg-muted">Datasource</span>
											<div class="flex items-center gap-1">
												{#if !datasourceId}
													<select
														class="border border-tertiary bg-transparent px-1.5 py-0.5 text-[10px]"
														value={schedule.datasource_id ?? ''}
														onchange={(e) => handleDsChange(schedule.id, e.currentTarget.value)}
														onclick={(e) => e.stopPropagation()}
													>
														<option value="">All</option>
														{#each datasourcesQuery.data ?? [] as ds (ds.id)}
															<option value={ds.id}>{ds.name} ({ds.source_type})</option>
														{/each}
													</select>
													{#if schedule.datasource_id}
														<Database size={10} class="text-fg-muted" />
													{/if}
												{:else}
													<span class="text-[10px] text-fg-secondary">
														{resolveDatasource(schedule.datasource_id)}
													</span>
												{/if}
											</div>
										</div>
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
													/>
													<button
														class="inline-flex items-center justify-center border-none bg-transparent p-0.5 text-success-fg hover:text-success-fg/80"
														onclick={() => saveCron(schedule.id)}
														disabled={cronMut.isPending}
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
													>
														<Pencil size={10} />
													</button>
												</div>
											{/if}
										</div>
										<div class="flex flex-col gap-1">
											<span class="text-[10px] text-fg-muted">Created</span>
											<span class="text-[10px] text-fg-secondary">
												{formatDate(schedule.created_at)}
											</span>
										</div>
										<div class="flex flex-col gap-1">
											<span class="text-[10px] text-fg-muted">Depends On</span>
											<div class="flex items-center gap-1">
												<select
													class="border border-tertiary bg-transparent px-1.5 py-0.5 text-[10px]"
													value={schedule.depends_on ?? ''}
													onchange={(e) => handleDepChange(schedule.id, e.currentTarget.value)}
													onclick={(e) => e.stopPropagation()}
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
</div>
