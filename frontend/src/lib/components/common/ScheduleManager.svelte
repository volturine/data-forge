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
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import { SvelteMap } from 'svelte/reactivity';
	import {
		css,
		cx,
		spinner,
		emptyText,
		label,
		row,
		rowBetween,
		divider,
		muted,
		input
	} from '$lib/styles/panda';

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

	const datasourceMap = $derived(
		new SvelteMap((datasourcesQuery.data ?? []).map((ds) => [ds.id, ds] as [string, DataSource]))
	);

	const allDatasources = $derived(datasourcesQuery.data ?? []);

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

	const targetDatasource = $derived(
		datasourceId ? (datasourceMap.get(datasourceId) ?? null) : null
	);

	const currentTarget = $derived(
		targetDatasource
			? {
					datasourceName: targetDatasource.name,
					analysisName: targetDatasource.created_by_analysis_id ? 'Analysis' : 'Unknown',
					tabName: targetDatasource.output_of_tab_id ? 'Tab' : null
				}
			: null
	);

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
		toggleMut.mutate({ id: schedule.id, enabled: !schedule.enabled });
	}

	let deleteConfirmId = $state<string | null>(null);

	function handleDelete(id: string) {
		deleteConfirmId = id;
	}

	function confirmDelete() {
		if (!deleteConfirmId) return;
		deleteMut.mutate(deleteConfirmId);
		deleteConfirmId = null;
	}

	function cancelDelete() {
		deleteConfirmId = null;
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

	function handleTriggerChange(id: string, value: string) {
		triggerMut.mutate({ id, trigger_on_datasource_id: value || null });
	}

	function openCreate() {
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

<ConfirmDialog
	show={deleteConfirmId !== null}
	heading="Delete Schedule"
	message="Are you sure you want to delete this schedule? This action cannot be undone."
	confirmText="Delete"
	onConfirm={confirmDelete}
	onCancel={cancelDelete}
/>

<div class={css({ display: 'flex', flexDirection: 'column', height: '100%', width: '100%' })}>
	{#if !compact}
		<header
			class={css({
				marginBottom: '6',
				borderBottomWidth: '1',
				paddingBottom: '5'
			})}
		>
			<div class={rowBetween}>
				<div>
					<h1 class={css({ margin: '0', marginBottom: '2', fontSize: '2xl' })}>Schedules</h1>
					<p class={css({ margin: '0', color: 'fg.tertiary' })}>
						Manage automated dataset rebuilds via cron expressions, dependencies, or datasource
						events
					</p>
				</div>
				<button
					class={css({
						display: 'inline-flex',
						alignItems: 'center',
						gap: '1.5',
						borderWidth: '1',
						backgroundColor: 'bg.accent',
						paddingX: '3',
						paddingY: '1.5',
						fontSize: 'sm',
						color: 'accent.primary',
						_hover: { backgroundColor: 'bg.accent' }
					})}
					onclick={openCreate}
				>
					<Plus size={14} />
					New Schedule
				</button>
			</div>
			{#if externalSearch === undefined}
				<div class={cx(row, css({ marginTop: '4', flexWrap: 'wrap', gap: '3' }))}>
					<div
						class={css({
							position: 'relative',
							minWidth: 'list',
							maxWidth: 'panel',
							flex: '1'
						})}
					>
						<Search
							size={14}
							class={css({
								position: 'absolute',
								left: '2.5',
								top: '50%',
								transform: 'translateY(-50%)',
								color: 'fg.muted'
							})}
						/>
						<input
							type="text"
							id="sched-search"
							aria-label="Search schedules"
							placeholder="Search schedules, datasources, or IDs..."
							class={cx(
								input(),
								css({
									backgroundColor: 'transparent',
									paddingX: '3',
									paddingY: '1.5',
									paddingLeft: '8',
									fontSize: 'sm'
								})
							)}
							bind:value={searchQuery}
						/>
					</div>
				</div>
			{/if}
		</header>
	{:else}
		<div class={cx(row, css({ marginBottom: '3', justifyContent: 'space-between' }))}>
			<span
				class={css({
					fontSize: 'xs',
					fontWeight: 'semibold',
					textTransform: 'uppercase',
					letterSpacing: 'wide',
					color: 'fg.muted'
				})}
			>
				Schedules
				{#if schedules.length > 0}
					<span class={css({ color: 'fg.tertiary' })}>({schedules.length})</span>
				{/if}
			</span>
			<div class={cx(row, css({ gap: '1' }))}>
				<button
					class={css({
						display: 'inline-flex',
						alignItems: 'center',
						gap: '1',
						borderWidth: '1',
						backgroundColor: 'bg.accent',
						paddingX: '2',
						paddingY: '1',
						fontSize: 'xs',
						color: 'accent.primary',
						_hover: { backgroundColor: 'bg.accent' }
					})}
					onclick={openCreate}
				>
					<Plus size={12} />
					Add
				</button>
				<button
					class={css({
						display: 'inline-flex',
						alignItems: 'center',
						justifyContent: 'center',
						border: 'none',
						backgroundColor: 'transparent',
						padding: '0.5',
						color: 'fg.muted',
						_hover: { color: 'fg.primary' }
					})}
					onclick={() => (showHelp = !showHelp)}
					title="Show help"
				>
					<HelpCircle size={14} />
				</button>
			</div>
		</div>
		{#if showHelp}
			<div
				class={css({
					marginBottom: '3',
					borderWidth: '1',
					backgroundColor: 'bg.secondary',
					padding: '2',
					fontSize: 'xs',
					color: 'fg.secondary'
				})}
			>
				<p class={css({ margin: '0', marginBottom: '1', fontWeight: 'medium' })}>
					Schedule Triggers:
				</p>
				<ul
					class={css({
						margin: '0',
						listStyle: 'none',
						padding: '0',
						display: 'flex',
						flexDirection: 'column',
						gap: '1'
					})}
				>
					<li class={cx(row, css({ gap: '1' }))}>
						<Clock size={10} class={muted} /> <strong>On a Schedule</strong> — runs on a cron interval
					</li>
					<li class={cx(row, css({ gap: '1' }))}>
						<Link size={10} class={muted} />
						<strong>After Another Schedule</strong> — runs when a dependency completes
					</li>
					<li class={cx(row, css({ gap: '1' }))}>
						<Database size={10} class={muted} />
						<strong>When Dataset Updates</strong> — runs on datasource change
					</li>
				</ul>
			</div>
		{/if}
	{/if}

	{#if creating}
		<div
			class={cx(
				css({
					marginBottom: '4',
					borderWidth: '1',
					backgroundColor: 'bg.primary',
					padding: '4'
				}),
				!compact && css({ marginBottom: '6' })
			)}
		>
			<h3 class={css({ margin: '0', marginBottom: '4', fontSize: 'sm', fontWeight: 'medium' })}>
				Create Schedule
			</h3>

			<!-- Target Section -->
			<div class={css({ marginBottom: '5' })}>
				<div
					class={cx(
						row,
						css({
							marginBottom: '3',
							gap: '2',
							borderBottomWidth: '1',
							paddingBottom: '2'
						})
					)}
				>
					<Database size={14} class={css({ color: 'accent.primary' })} />
					<span class={css({ fontSize: 'xs', fontWeight: 'medium' })}>
						Target Dataset — What gets rebuilt
					</span>
				</div>

				{#if currentTarget}
					<div class={css({ backgroundColor: 'bg.secondary', padding: '3', fontSize: 'sm' })}>
						<div class={cx(row, css({ gap: '2' }))}>
							<BarChart3 size={14} class={css({ color: 'accent.primary' })} />
							<span class={css({ fontWeight: 'medium' })}>
								{currentTarget.datasourceName}
							</span>
						</div>
						<div
							class={cx(row, css({ marginTop: '1', gap: '1', fontSize: 'xs', color: 'fg.muted' }))}
						>
							<span>└─ Produced by:</span>
							<span class={css({ color: 'fg.secondary' })}>
								{currentTarget.analysisName}
							</span>
							{#if currentTarget.tabName}
								<ArrowRight size={10} />
								<span class={css({ color: 'fg.secondary' })}>
									Tab "{currentTarget.tabName}"
								</span>
							{/if}
						</div>
					</div>
				{:else}
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '3' })}>
						<div
							class={css({
								display: 'flex',
								minWidth: 'previewLg',
								flex: '1',
								flexDirection: 'column',
								gap: '1.5'
							})}
						>
							<label for="schedule-datasource" class={label()}> Select output dataset </label>
							<select
								id="schedule-datasource"
								class={cx(
									input(),
									css({
										backgroundColor: 'transparent',
										paddingX: '2',
										paddingY: '1.5',
										fontSize: 'xs'
									})
								)}
								bind:value={newDatasourceId}
							>
								<option value="">Select output dataset...</option>
								{#each allDatasources as ds (ds.id)}
									<option value={ds.id}>{ds.name}</option>
								{/each}
							</select>
						</div>

						{#if selectedDatasource}
							<div class={css({ backgroundColor: 'bg.secondary', padding: '3', fontSize: 'sm' })}>
								<div class={cx(row, css({ gap: '2' }))}>
									<BarChart3 size={14} class={css({ color: 'accent.primary' })} />
									<span class={css({ fontWeight: 'medium' })}>{selectedDatasource.name}</span>
								</div>
								<div
									class={cx(
										row,
										css({ marginTop: '1', gap: '1', fontSize: 'xs', color: 'fg.muted' })
									)}
								>
									<span>└─ Produced by:</span>
									{#if selectedDatasource.created_by_analysis_id}
										<span class={css({ color: 'fg.secondary' })}>Analysis</span>
										{#if selectedDatasource.output_of_tab_id}
											<ArrowRight size={10} />
											<span class={css({ color: 'fg.secondary' })}>Tab</span>
										{/if}
									{:else}
										<span class={css({ color: 'fg.secondary' })}>Unknown</span>
									{/if}
								</div>
							</div>
						{/if}
					</div>
				{/if}
			</div>

			<!-- Trigger Section -->
			<div>
				<div
					class={cx(
						row,
						css({
							marginBottom: '3',
							gap: '2',
							borderBottomWidth: '1',
							paddingBottom: '2'
						})
					)}
				>
					<Clock size={14} class={css({ color: 'accent.primary' })} />
					<span class={css({ fontSize: 'xs', fontWeight: 'medium' })}>
						When to Run — What triggers the build
					</span>
				</div>

				<div class={css({ display: 'flex', flexDirection: 'column', gap: '3' })}>
					<!-- Cron Option -->
					<label
						class={css({
							display: 'flex',
							cursor: 'pointer',
							alignItems: 'flex-start',
							gap: '3',
							borderWidth: '1',
							backgroundColor: 'bg.secondary',
							padding: '3',
							_hover: { backgroundColor: 'bg.hover' }
						})}
					>
						<input
							type="radio"
							name="triggerType"
							value="cron"
							bind:group={triggerType}
							class={css({ marginTop: '0.5' })}
						/>
						<div class={css({ flex: '1' })}>
							<div class={css({ marginBottom: '1', fontSize: 'xs', fontWeight: 'medium' })}>
								On a Schedule
							</div>
							<p class={css({ margin: '0', fontSize: 'xs', color: 'fg.tertiary' })}>
								Run on a recurring cron interval
							</p>
							{#if triggerType === 'cron'}
								<div class={cx(row, css({ marginTop: '2', gap: '2' }))}>
									<input
										type="text"
										class={cx(
											input(),
											css({
												width: 'colMd',
												backgroundColor: 'transparent',
												paddingX: '2',
												paddingY: '1',
												fontSize: 'xs'
											})
										)}
										name="cron"
										bind:value={newCron}
										placeholder="0 * * * *"
									/>
									<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>
										{getCronDescription(newCron)}
									</span>
								</div>
							{/if}
						</div>
					</label>

					<!-- Depends Option -->
					<label
						class={css({
							display: 'flex',
							cursor: 'pointer',
							alignItems: 'flex-start',
							gap: '3',
							borderWidth: '1',
							backgroundColor: 'bg.secondary',
							padding: '3',
							_hover: { backgroundColor: 'bg.hover' }
						})}
					>
						<input
							type="radio"
							name="triggerType"
							value="depends"
							bind:group={triggerType}
							class={css({ marginTop: '0.5' })}
						/>
						<div class={css({ flex: '1' })}>
							<div
								class={cx(
									row,
									css({ marginBottom: '1', gap: '1', fontSize: 'xs', fontWeight: 'medium' })
								)}
							>
								<Link size={12} class={muted} />
								After Another Schedule
							</div>
							<p class={css({ margin: '0', fontSize: 'xs', color: 'fg.tertiary' })}>
								Run after another schedule completes successfully
							</p>
							{#if triggerType === 'depends'}
								<div class={css({ marginTop: '2' })}>
									<select
										class={cx(
											input(),
											css({
												backgroundColor: 'transparent',
												paddingX: '2',
												paddingY: '1',
												fontSize: 'xs'
											})
										)}
										name="depends_on"
										bind:value={newDependsOn}
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
						class={css({
							display: 'flex',
							cursor: 'pointer',
							alignItems: 'flex-start',
							gap: '3',
							borderWidth: '1',
							backgroundColor: 'bg.secondary',
							padding: '3',
							_hover: { backgroundColor: 'bg.hover' }
						})}
					>
						<input
							type="radio"
							name="triggerType"
							value="event"
							bind:group={triggerType}
							class={css({ marginTop: '0.5' })}
						/>
						<div class={css({ flex: '1' })}>
							<div
								class={cx(
									row,
									css({ marginBottom: '1', gap: '1', fontSize: 'xs', fontWeight: 'medium' })
								)}
							>
								<Database size={12} class={muted} />
								When Dataset Updates
							</div>
							<p class={css({ margin: '0', fontSize: 'xs', color: 'fg.tertiary' })}>
								Run when a specific datasource is updated
							</p>
							{#if triggerType === 'event'}
								<div class={css({ marginTop: '2' })}>
									<select
										class={cx(
											input(),
											css({
												backgroundColor: 'transparent',
												paddingX: '2',
												paddingY: '1',
												fontSize: 'xs'
											})
										)}
										name="trigger_datasource"
										bind:value={newTrigger}
									>
										<option value="">Select a datasource...</option>
										{#each allDatasources as ds (ds.id)}
											<option value={ds.id}>{ds.name}</option>
										{/each}
									</select>
								</div>
							{/if}
						</div>
					</label>
				</div>
			</div>

			<div
				class={cx(
					divider,
					css({
						marginTop: '4',
						display: 'flex',
						gap: '2',
						paddingTop: '4'
					})
				)}
			>
				<button
					class={css({
						borderWidth: '1',
						backgroundColor: 'bg.accent',
						paddingX: '3',
						paddingY: '1.5',
						fontSize: 'xs',
						color: 'accent.primary',
						_hover: { backgroundColor: 'bg.accent' }
					})}
					onclick={handleCreate}
					disabled={(!datasourceId && !newDatasourceId) ||
						(triggerType === 'cron' && !newCron) ||
						(triggerType === 'depends' && !newDependsOn) ||
						(triggerType === 'event' && !newTrigger) ||
						createMut.isPending}
				>
					{createMut.isPending ? 'Creating...' : 'Create Schedule'}
				</button>
				<button
					class={css({
						borderWidth: '1',
						backgroundColor: 'transparent',
						paddingX: '3',
						paddingY: '1.5',
						fontSize: 'xs',
						color: 'fg.tertiary',
						_hover: { color: 'fg.primary' }
					})}
					onclick={() => (creating = false)}
				>
					Cancel
				</button>
			</div>

			{#if createMut.isError}
				<p class={css({ marginTop: '3', fontSize: 'xs', color: 'fg.error' })}>
					{createMut.error instanceof Error ? createMut.error.message : 'Failed to create schedule'}
				</p>
			{/if}
		</div>
	{/if}

	{#if schedulesQuery.isLoading}
		<div class={cx(row, css({ justifyContent: 'center', paddingY: '6' }))}>
			<div class={spinner()}></div>
		</div>
	{:else if schedulesQuery.isError}
		<div
			class={css({
				paddingX: '3',
				paddingY: '2.5',
				border: 'none',
				borderLeftWidth: '2',

				marginTop: '3',
				marginBottom: '0',
				fontSize: 'xs',
				lineHeight: '1.5',
				backgroundColor: 'transparent',
				borderLeftColor: 'border.error',
				color: 'fg.error'
			})}
		>
			{schedulesQuery.error instanceof Error
				? schedulesQuery.error.message
				: 'Error loading schedules.'}
		</div>
	{:else if schedules.length === 0 && !creating}
		<div
			class={cx(
				css({
					borderWidth: '1',
					borderStyle: 'dashed',
					padding: '6',
					textAlign: 'center'
				}),
				!compact && css({ padding: '8' })
			)}
		>
			<Calendar
				class={css({ marginX: 'auto', marginBottom: '2', color: 'fg.muted' })}
				size={compact ? 20 : 32}
			/>
			<p class={emptyText({ size: 'panel' })}>No schedules configured.</p>
			{#if !compact}
				<p class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>
					Create a schedule to automatically rebuild datasets on a trigger.
				</p>
			{/if}
		</div>
	{:else if visibleSchedules.length === 0 && hasSearch}
		<div
			class={css({
				borderWidth: '1',
				borderStyle: 'dashed',
				paddingX: '6',
				paddingY: '8',
				textAlign: 'center'
			})}
		>
			<p class={emptyText({ size: 'panel' })}>No schedules match your search.</p>
		</div>
	{:else if visibleSchedules.length > 0}
		{#if compact}
			<!-- Compact card list -->
			<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
				{#each visibleSchedules as schedule (schedule.id)}
					{@const triggerTypeValue = getTriggerType(schedule)}
					{@const triggerDesc = getTriggerDescription(schedule)}
					<div
						class={cx(
							'group',
							css({
								borderWidth: '1',
								backgroundColor: 'bg.primary'
							})
						)}
					>
						<div
							class={css({
								display: 'flex',
								cursor: 'pointer',
								alignItems: 'center',
								gap: '2',
								padding: '2',
								_hover: { backgroundColor: 'bg.secondary' }
							})}
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
								class={cx(
									css({ flexShrink: '0', color: 'fg.muted' }),
									expandedId === schedule.id ? '' : css({ transform: 'rotate(-90deg)' })
								)}
							/>
							{#if triggerTypeValue === 'cron'}
								<Clock size={12} class={css({ flexShrink: '0', color: 'fg.muted' })} />
							{:else if triggerTypeValue === 'depends'}
								<Link size={12} class={css({ flexShrink: '0', color: 'fg.muted' })} />
							{:else}
								<Database size={12} class={css({ flexShrink: '0', color: 'fg.muted' })} />
							{/if}
							<span
								class={css({
									minWidth: '0',
									flex: '1',
									overflow: 'hidden',
									textOverflow: 'ellipsis',
									whiteSpace: 'nowrap',
									fontSize: 'xs',
									color: 'fg.secondary'
								})}
								title={triggerDesc}
							>
								{triggerDesc}
							</span>
							<button
								class={css({
									display: 'inline-flex',
									flexShrink: '0',
									alignItems: 'center',
									gap: '0.5',
									border: 'none',
									backgroundColor: 'transparent',
									padding: '0',
									fontSize: '2xs'
								})}
								onclick={(e) => {
									e.stopPropagation();
									handleToggle(schedule);
								}}
								disabled={toggleMut.isPending}
								title={schedule.enabled ? 'Click to disable' : 'Click to enable'}
							>
								{#if schedule.enabled}
									<Power size={10} class={css({ color: 'fg.success' })} />
								{:else}
									<PowerOff size={10} class={muted} />
								{/if}
							</button>
							<button
								class={css({
									flexShrink: '0',
									border: 'none',
									backgroundColor: 'transparent',
									padding: '0',
									color: 'fg.tertiary',
									_hover: { color: 'fg.error' },
									_focusVisible: {
										color: 'fg.error',
										outline: '2px solid',
										outlineColor: 'accent.primary',
										outlineOffset: '1px'
									}
								})}
								onclick={(e) => {
									e.stopPropagation();
									handleDelete(schedule.id);
								}}
								disabled={deleteMut.isPending}
								aria-label="Delete schedule"
							>
								<Trash2 size={10} />
							</button>
						</div>
						{#if expandedId === schedule.id}
							<div
								class={cx(
									divider,
									css({
										paddingX: '3',
										paddingY: '2'
									})
								)}
							>
								<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
									{#if triggerTypeValue === 'cron'}
										<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
											<span class={css({ fontSize: '2xs', color: 'fg.muted' })}>
												Cron Expression
											</span>
											{#if editingCron === schedule.id}
												<div class={cx(row, css({ gap: '1' }))}>
													<input
														type="text"
														class={cx(
															input(),
															css({
																backgroundColor: 'transparent',
																paddingX: '1.5',
																paddingY: '0.5',
																fontSize: '2xs'
															})
														)}
														id="sched-{schedule.id}-cron"
														aria-label="Cron expression"
														bind:value={editCronValue}
														onkeydown={(e) => {
															if (e.key === 'Enter') saveCron(schedule.id);
															if (e.key === 'Escape') cancelEditCron();
														}}
													/>
													<button
														class={css({
															flexShrink: '0',
															border: 'none',
															backgroundColor: 'transparent',
															padding: '0.5',
															color: 'fg.success'
														})}
														onclick={() => saveCron(schedule.id)}
														disabled={cronMut.isPending}
														title="Save"
													>
														<Check size={12} />
													</button>
													<button
														class={css({
															flexShrink: '0',
															border: 'none',
															backgroundColor: 'transparent',
															padding: '0.5',
															color: 'fg.muted',
															_hover: { color: 'fg.primary' }
														})}
														onclick={cancelEditCron}
														title="Cancel"
													>
														<X size={12} />
													</button>
												</div>
											{:else}
												<div class={cx(row, css({ gap: '1' }))}>
													<code
														class={css({
															backgroundColor: 'bg.tertiary',
															paddingX: '1',
															paddingY: '0.5',
															fontSize: '2xs'
														})}
													>
														{schedule.cron_expression}
													</code>
													<button
														class={css({
															border: 'none',
															backgroundColor: 'transparent',
															padding: '0.5',
															color: 'fg.muted',
															_hover: { color: 'fg.primary' }
														})}
														onclick={() => startEditCron(schedule)}
														title="Edit"
													>
														<Pencil size={10} />
													</button>
												</div>
											{/if}
										</div>
									{:else if triggerTypeValue === 'depends'}
										<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
											<span class={css({ fontSize: '2xs', color: 'fg.muted' })}>Depends On</span>
											<select
												class={cx(
													input(),
													css({
														backgroundColor: 'transparent',
														paddingX: '1.5',
														paddingY: '0.5',
														fontSize: '2xs'
													})
												)}
												id="sched-{schedule.id}-depends"
												aria-label="Depends on schedule"
												value={schedule.depends_on ?? ''}
												onchange={(e) => handleDepChange(schedule.id, e.currentTarget.value)}
												onclick={(e) => e.stopPropagation()}
											>
												<option value="">None</option>
												{#each depOptions(schedule.id) as dep (dep.id)}
													<option value={dep.id}>{depLabel(dep.id)}</option>
												{/each}
											</select>
										</div>
									{:else}
										<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
											<span class={css({ fontSize: '2xs', color: 'fg.muted' })}
												>On Datasource Update</span
											>
											<select
												class={cx(
													input(),
													css({
														backgroundColor: 'transparent',
														paddingX: '1.5',
														paddingY: '0.5',
														fontSize: '2xs'
													})
												)}
												id="sched-{schedule.id}-trigger"
												aria-label="Trigger datasource"
												value={schedule.trigger_on_datasource_id ?? ''}
												onchange={(e) => handleTriggerChange(schedule.id, e.currentTarget.value)}
												onclick={(e) => e.stopPropagation()}
											>
												<option value="">None</option>
												{#each allDatasources as ds (ds.id)}
													<option value={ds.id}>{ds.name}</option>
												{/each}
											</select>
										</div>
									{/if}
									{#if schedule.next_run}
										<div class={css({ fontSize: '2xs', color: 'fg.muted' })}>
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
			<div
				class={css({
					overflowX: 'auto',
					borderWidth: '1'
				})}
			>
				<table class={css({ width: '100%', borderCollapse: 'collapse', fontSize: 'xs' })}>
					<thead>
						<tr class={css({ backgroundColor: 'bg.tertiary' })}>
							<th
								class={css({
									width: 'iconLg',
									borderBottomWidth: '1',
									paddingX: '2',
									paddingY: '1.5',
									textAlign: 'left',
									fontWeight: 'medium'
								})}
							></th>
							{#if !datasourceId}
								<th
									class={css({
										borderBottomWidth: '1',
										paddingX: '2',
										paddingY: '1.5',
										textAlign: 'left',
										fontWeight: 'medium'
									})}
								>
									Target
								</th>
							{/if}
							<th
								class={css({
									borderBottomWidth: '1',
									paddingX: '2',
									paddingY: '1.5',
									textAlign: 'left',
									fontWeight: 'medium'
								})}
							>
								Produced By
							</th>
							<th
								class={css({
									borderBottomWidth: '1',
									paddingX: '2',
									paddingY: '1.5',
									textAlign: 'left',
									fontWeight: 'medium'
								})}
							>
								Trigger Type
							</th>
							<th
								class={css({
									borderBottomWidth: '1',
									paddingX: '2',
									paddingY: '1.5',
									textAlign: 'left',
									fontWeight: 'medium'
								})}
							>
								Trigger
							</th>
							<th
								class={css({
									borderBottomWidth: '1',
									paddingX: '2',
									paddingY: '1.5',
									textAlign: 'left',
									fontWeight: 'medium'
								})}
							>
								Status
							</th>
							<th
								class={css({
									borderBottomWidth: '1',
									paddingX: '2',
									paddingY: '1.5',
									textAlign: 'left',
									fontWeight: 'medium'
								})}
							>
								Next Run
							</th>
							<th
								class={css({
									width: 'logoXl',
									borderBottomWidth: '1',
									paddingX: '2',
									paddingY: '1.5',
									textAlign: 'left',
									fontWeight: 'medium'
								})}
							></th>
						</tr>
					</thead>
					<tbody>
						{#each visibleSchedules as schedule (schedule.id)}
							{@const triggerTypeValue = getTriggerType(schedule)}
							{@const triggerDesc = getTriggerDescription(schedule)}
							{@const provenanceDisplay = getProvenanceDisplay(schedule)}
							<tr
								class={css({
									cursor: 'pointer',
									_hover: { backgroundColor: 'bg.hover' },
									...(expandedId === schedule.id ? { backgroundColor: 'bg.secondary' } : {})
								})}
								onclick={() => toggleExpand(schedule.id)}
							>
								<td
									class={css({
										borderBottomWidth: '1',
										paddingX: '2',
										paddingY: '1.5'
									})}
								>
									<ChevronDown
										size={12}
										class={cx(
											css({ transition: 'transform 160ms' }),
											expandedId === schedule.id ? '' : css({ transform: 'rotate(-90deg)' })
										)}
									/>
								</td>
								{#if !datasourceId}
									<td
										class={css({
											borderBottomWidth: '1',
											paddingX: '2',
											paddingY: '1.5'
										})}
									>
										<span
											class={css({
												display: 'inline-flex',
												maxWidth: 'inputSm',
												alignItems: 'center',
												gap: '1',
												overflow: 'hidden',
												textOverflow: 'ellipsis',
												whiteSpace: 'nowrap',
												color: 'fg.secondary'
											})}
											title={resolveDatasource(schedule.datasource_id)}
										>
											<BarChart3 size={10} class={css({ flexShrink: '0', color: 'fg.muted' })} />
											{resolveDatasource(schedule.datasource_id)}
										</span>
									</td>
								{/if}
								<td
									class={css({
										borderBottomWidth: '1',
										paddingX: '2',
										paddingY: '1.5'
									})}
								>
									<span
										class={css({
											display: 'block',
											maxWidth: 'colXl',
											overflow: 'hidden',
											textOverflow: 'ellipsis',
											whiteSpace: 'nowrap',
											color: 'fg.secondary'
										})}
										title={provenanceDisplay}
									>
										{provenanceDisplay}
									</span>
								</td>
								<td
									class={css({
										borderBottomWidth: '1',
										paddingX: '2',
										paddingY: '1.5'
									})}
								>
									<span class={css({ color: 'fg.secondary' })}>
										{getTriggerLabel(triggerTypeValue)}
									</span>
								</td>
								<td
									class={css({
										borderBottomWidth: '1',
										paddingX: '2',
										paddingY: '1.5'
									})}
								>
									<div class={cx(row, css({ gap: '1.5' }))}>
										{#if triggerTypeValue === 'cron'}
											<Clock size={12} class={css({ flexShrink: '0', color: 'fg.muted' })} />
										{:else if triggerTypeValue === 'depends'}
											<Link size={12} class={css({ flexShrink: '0', color: 'fg.muted' })} />
										{:else}
											<Database size={12} class={css({ flexShrink: '0', color: 'fg.muted' })} />
										{/if}
										<span
											class={css({
												overflow: 'hidden',
												textOverflow: 'ellipsis',
												whiteSpace: 'nowrap'
											})}
											title={triggerDesc}
										>
											{triggerDesc}
										</span>
									</div>
								</td>
								<td
									class={css({
										borderBottomWidth: '1',
										paddingX: '2',
										paddingY: '1.5'
									})}
								>
									<button
										class={css({
											display: 'inline-flex',
											alignItems: 'center',
											gap: '1',
											border: 'none',
											backgroundColor: 'transparent',
											padding: '0',
											fontSize: 'xs'
										})}
										onclick={(e) => {
											e.stopPropagation();
											handleToggle(schedule);
										}}
										disabled={toggleMut.isPending}
										title={schedule.enabled ? 'Click to disable' : 'Click to enable'}
									>
										{#if schedule.enabled}
											<Power size={12} class={css({ color: 'fg.success' })} />
											<span class={css({ color: 'fg.success' })}>On</span>
										{:else}
											<PowerOff size={12} class={muted} />
											<span class={muted}>Off</span>
										{/if}
									</button>
								</td>
								<td
									class={css({
										borderBottomWidth: '1',
										paddingX: '2',
										paddingY: '1.5',
										color: 'fg.secondary'
									})}
								>
									{formatDate(schedule.next_run)}
								</td>
								<td
									class={css({
										borderBottomWidth: '1',
										paddingX: '2',
										paddingY: '1.5'
									})}
								>
									<button
										class={css({
											display: 'inline-flex',
											alignItems: 'center',
											justifyContent: 'center',
											border: 'none',
											backgroundColor: 'transparent',
											padding: '0.5',
											color: 'fg.muted',
											_hover: { color: 'fg.error' },
											_focusVisible: {
												color: 'fg.error',
												outline: '2px solid',
												outlineColor: 'accent.primary',
												outlineOffset: '1px'
											}
										})}
										onclick={(e) => {
											e.stopPropagation();
											handleDelete(schedule.id);
										}}
										disabled={deleteMut.isPending}
										aria-label="Delete schedule"
									>
										<Trash2 size={12} />
									</button>
								</td>
							</tr>
							{#if expandedId === schedule.id}
								<tr>
									<td
										colspan={colCount}
										class={css({
											borderBottomWidth: '1',
											backgroundColor: 'bg.primary',
											padding: '0'
										})}
									>
										<div
											class={css({
												display: 'flex',
												flexWrap: 'wrap',
												alignItems: 'flex-start',
												gap: '4',
												paddingX: '4',
												paddingY: '3'
											})}
										>
											<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
												<span class={css({ fontSize: '2xs', color: 'fg.muted' })}
													>Target Datasource</span
												>
												<div class={cx(row, css({ gap: '1' }))}>
													<BarChart3 size={10} class={muted} />
													<span class={css({ fontSize: '2xs', color: 'fg.secondary' })}>
														{resolveDatasource(schedule.datasource_id)}
													</span>
												</div>
											</div>
											<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
												<span class={css({ fontSize: '2xs', color: 'fg.muted' })}>Produced By</span>
												<span class={css({ fontSize: '2xs', color: 'fg.secondary' })}>
													{provenanceDisplay}
												</span>
											</div>
											{#if triggerTypeValue === 'cron'}
												<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
													<span class={css({ fontSize: '2xs', color: 'fg.muted' })}
														>Cron Expression</span
													>
													{#if editingCron === schedule.id}
														<div class={cx(row, css({ gap: '1' }))}>
															<input
																type="text"
																class={cx(
																	input(),
																	css({
																		width: 'colMd',
																		backgroundColor: 'transparent',
																		paddingX: '1.5',
																		paddingY: '0.5',
																		fontSize: '2xs'
																	})
																)}
																id="sched-{schedule.id}-cron"
																aria-label="Cron expression"
																bind:value={editCronValue}
																onkeydown={(e) => {
																	if (e.key === 'Enter') saveCron(schedule.id);
																	if (e.key === 'Escape') cancelEditCron();
																}}
															/>
															<button
																class={css({
																	display: 'inline-flex',
																	alignItems: 'center',
																	justifyContent: 'center',
																	border: 'none',
																	backgroundColor: 'transparent',
																	padding: '0.5',
																	color: 'fg.success',
																	_hover: { color: 'fg.successMuted' }
																})}
																onclick={() => saveCron(schedule.id)}
																disabled={cronMut.isPending}
																title="Save"
															>
																<Check size={12} />
															</button>
															<button
																class={css({
																	display: 'inline-flex',
																	alignItems: 'center',
																	justifyContent: 'center',
																	border: 'none',
																	backgroundColor: 'transparent',
																	padding: '0.5',
																	color: 'fg.muted',
																	_hover: { color: 'fg.primary' }
																})}
																onclick={cancelEditCron}
																title="Cancel"
															>
																<X size={12} />
															</button>
														</div>
													{:else}
														<div class={cx(row, css({ gap: '1' }))}>
															<code
																class={css({
																	backgroundColor: 'bg.tertiary',
																	paddingX: '1',
																	paddingY: '0.5',
																	fontSize: '2xs'
																})}
															>
																{schedule.cron_expression}
															</code>
															<button
																class={css({
																	display: 'inline-flex',
																	alignItems: 'center',
																	justifyContent: 'center',
																	border: 'none',
																	backgroundColor: 'transparent',
																	padding: '0.5',
																	color: 'fg.muted',
																	_hover: { color: 'fg.primary' }
																})}
																onclick={() => startEditCron(schedule)}
																title="Edit cron expression"
															>
																<Pencil size={10} />
															</button>
														</div>
													{/if}
												</div>
											{:else if triggerTypeValue === 'depends'}
												<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
													<span class={css({ fontSize: '2xs', color: 'fg.muted' })}>Depends On</span
													>
													<div class={cx(row, css({ gap: '1' }))}>
														<select
															class={cx(
																input(),
																css({
																	backgroundColor: 'transparent',
																	paddingX: '1.5',
																	paddingY: '0.5',
																	fontSize: '2xs'
																})
															)}
															id="sched-{schedule.id}-depends"
															aria-label="Depends on schedule"
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
															<Link size={10} class={muted} />
														{/if}
													</div>
												</div>
											{:else}
												<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
													<span class={css({ fontSize: '2xs', color: 'fg.muted' })}
														>On Datasource Update</span
													>
													<div class={cx(row, css({ gap: '1' }))}>
														<select
															class={cx(
																input(),
																css({
																	backgroundColor: 'transparent',
																	paddingX: '1.5',
																	paddingY: '0.5',
																	fontSize: '2xs'
																})
															)}
															id="sched-{schedule.id}-trigger"
															aria-label="Trigger datasource"
															value={schedule.trigger_on_datasource_id ?? ''}
															onchange={(e) =>
																handleTriggerChange(schedule.id, e.currentTarget.value)}
															onclick={(e) => e.stopPropagation()}
														>
															<option value="">None</option>
															{#each allDatasources as ds (ds.id)}
																<option value={ds.id}>{ds.name}</option>
															{/each}
														</select>
														{#if schedule.trigger_on_datasource_id}
															<Database size={10} class={muted} />
														{/if}
													</div>
												</div>
											{/if}
											<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
												<span class={css({ fontSize: '2xs', color: 'fg.muted' })}>Created</span>
												<span class={css({ fontSize: '2xs', color: 'fg.secondary' })}>
													{formatDate(schedule.created_at)}
												</span>
											</div>
											<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
												<span class={css({ fontSize: '2xs', color: 'fg.muted' })}>Schedule ID</span>
												<span
													class={css({
														fontFamily: 'mono',
														fontSize: '2xs',
														color: 'fg.secondary'
													})}
												>
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
