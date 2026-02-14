<script lang="ts">
	import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { listSchedules, createSchedule, updateSchedule, deleteSchedule } from '$lib/api/schedule';
	import type { Schedule, ScheduleCreate } from '$lib/api/schedule';
	import { listAnalyses } from '$lib/api/analysis';
	import { Plus, Trash2, Calendar, Clock, Power, PowerOff } from 'lucide-svelte';
	import { SvelteMap } from 'svelte/reactivity';

	const queryClient = useQueryClient();

	let creating = $state(false);
	let newCron = $state('0 * * * *');
	let newAnalysisId = $state('');

	const schedulesQuery = createQuery(() => ({
		queryKey: ['schedules'],
		queryFn: async () => {
			const result = await listSchedules();
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		}
	}));

	const analysesQuery = createQuery(() => ({
		queryKey: ['analyses-lookup'],
		queryFn: async () => {
			const result = await listAnalyses();
			if (result.isErr()) return [];
			return result.value;
		},
		staleTime: 60_000
	}));

	const analysisNames = $derived.by(() => {
		const map = new SvelteMap<string, string>();
		for (const a of analysesQuery.data ?? []) {
			map.set(a.id, a.name);
		}
		return map;
	});

	const schedules = $derived(schedulesQuery.data ?? []);

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
		if (!newAnalysisId || !newCron) return;
		createMut.mutate({ analysis_id: newAnalysisId, cron_expression: newCron });
	}

	function handleToggle(schedule: Schedule) {
		toggleMut.mutate({ id: schedule.id, enabled: !schedule.enabled });
	}

	function handleDelete(id: string) {
		deleteMut.mutate(id);
	}

	function formatDate(iso: string | null): string {
		if (!iso) return '-';
		return new Date(iso).toLocaleString();
	}

	function resolveName(id: string): string {
		return analysisNames.get(id) ?? id.slice(0, 8) + '...';
	}
</script>

<div class="mx-auto max-w-300 px-6 py-7">
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

	{#if creating}
		<div class="mb-6 border border-tertiary bg-bg-primary p-4">
			<h3 class="m-0 mb-3 text-sm font-medium">Create Schedule</h3>
			<div class="flex flex-wrap items-end gap-3">
				<div class="flex min-w-50 flex-1 flex-col gap-1">
					<label for="schedule-analysis" class="text-xs text-fg-muted">Analysis</label>
					<select
						id="schedule-analysis"
						class="border border-tertiary bg-transparent px-3 py-1.5 text-sm"
						bind:value={newAnalysisId}
					>
						<option value="">Select analysis...</option>
						{#each analysesQuery.data ?? [] as analysis (analysis.id)}
							<option value={analysis.id}>{analysis.name}</option>
						{/each}
					</select>
				</div>
				<div class="flex min-w-40 flex-col gap-1">
					<label for="schedule-cron" class="text-xs text-fg-muted">Cron Expression</label>
					<input
						id="schedule-cron"
						type="text"
						class="border border-tertiary bg-transparent px-3 py-1.5 font-mono text-sm"
						bind:value={newCron}
						placeholder="0 * * * *"
					/>
				</div>
				<div class="flex gap-2">
					<button
						class="border border-tertiary bg-accent-bg px-3 py-1.5 text-sm text-accent-primary hover:bg-accent-bg/80"
						onclick={handleCreate}
						disabled={!newAnalysisId || !newCron || createMut.isPending}
					>
						{createMut.isPending ? 'Creating...' : 'Create'}
					</button>
					<button
						class="border border-tertiary bg-transparent px-3 py-1.5 text-sm text-fg-tertiary hover:text-fg-primary"
						onclick={() => (creating = false)}
					>
						Cancel
					</button>
				</div>
			</div>
			{#if createMut.isError}
				<p class="mt-2 text-sm text-error-fg">
					{createMut.error instanceof Error ? createMut.error.message : 'Failed to create schedule'}
				</p>
			{/if}
		</div>
	{/if}

	{#if schedulesQuery.isLoading}
		<div class="flex h-full items-center justify-center">
			<div class="spinner"></div>
		</div>
	{:else if schedulesQuery.isError}
		<div class="error-box">
			{schedulesQuery.error instanceof Error
				? schedulesQuery.error.message
				: 'Error loading schedules.'}
		</div>
	{:else if schedules.length === 0}
		<div class="rounded-sm border border-dashed border-tertiary p-8 text-center">
			<Calendar size={32} class="mx-auto mb-3 text-fg-muted" />
			<p class="text-fg-muted">No schedules configured yet.</p>
			<p class="text-sm text-fg-tertiary">
				Create a schedule to automatically build analyses on a cron-based interval.
			</p>
		</div>
	{:else}
		<div class="overflow-x-auto border border-tertiary">
			<table class="w-full border-collapse text-sm">
				<thead>
					<tr class="bg-bg-tertiary">
						<th class="border-b border-tertiary px-3 py-2 text-left font-medium">Analysis</th>
						<th class="border-b border-tertiary px-3 py-2 text-left font-medium">Cron</th>
						<th class="border-b border-tertiary px-3 py-2 text-left font-medium">Status</th>
						<th class="border-b border-tertiary px-3 py-2 text-left font-medium">Last Run</th>
						<th class="border-b border-tertiary px-3 py-2 text-left font-medium">Next Run</th>
						<th class="border-b border-tertiary px-3 py-2 text-left font-medium">Created</th>
						<th class="w-20 border-b border-tertiary px-3 py-2 text-left font-medium"></th>
					</tr>
				</thead>
				<tbody>
					{#each schedules as schedule (schedule.id)}
						<tr class="hover:bg-bg-hover">
							<td class="border-b border-tertiary px-3 py-2">
								<span class="text-fg-secondary" title={schedule.analysis_id}>
									{resolveName(schedule.analysis_id)}
								</span>
							</td>
							<td class="border-b border-tertiary px-3 py-2">
								<code class="bg-bg-tertiary px-1.5 py-0.5 text-xs">{schedule.cron_expression}</code>
							</td>
							<td class="border-b border-tertiary px-3 py-2">
								<button
									class="inline-flex items-center gap-1.5 border-none bg-transparent p-0 text-sm"
									onclick={() => handleToggle(schedule)}
									disabled={toggleMut.isPending}
									title={schedule.enabled ? 'Click to disable' : 'Click to enable'}
								>
									{#if schedule.enabled}
										<Power size={14} class="text-success-fg" />
										<span class="text-success-fg">Enabled</span>
									{:else}
										<PowerOff size={14} class="text-fg-muted" />
										<span class="text-fg-muted">Disabled</span>
									{/if}
								</button>
							</td>
							<td class="border-b border-tertiary px-3 py-2 text-fg-secondary">
								<span class="inline-flex items-center gap-1">
									<Clock size={12} class="text-fg-muted" />
									{formatDate(schedule.last_run)}
								</span>
							</td>
							<td class="border-b border-tertiary px-3 py-2 text-fg-secondary">
								{formatDate(schedule.next_run)}
							</td>
							<td class="border-b border-tertiary px-3 py-2 text-fg-secondary">
								{formatDate(schedule.created_at)}
							</td>
							<td class="border-b border-tertiary px-3 py-2">
								<button
									class="inline-flex items-center justify-center border-none bg-transparent p-1 text-fg-muted hover:text-error-fg"
									onclick={() => handleDelete(schedule.id)}
									disabled={deleteMut.isPending}
									title="Delete schedule"
								>
									<Trash2 size={14} />
								</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>
