<script lang="ts">
	import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { listSchedules, updateSchedule, deleteSchedule } from '$lib/api/schedule';
	import type { Schedule } from '$lib/api/schedule';
	import { listDatasources } from '$lib/api/datasource';
	import type { DataSource } from '$lib/types/datasource';
	import {
		Plus,
		Calendar,
		Clock,
		CircleQuestionMark,
		Link,
		Database,
		Search
	} from '@lucide/svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import ScheduleCreateForm from './schedule-manager/ScheduleCreateForm.svelte';
	import ScheduleList from './schedule-manager/ScheduleList.svelte';
	import { useNamespace } from '$lib/stores/namespace.svelte';
	import { SvelteMap } from 'svelte/reactivity';
	import { button, css, emptyText, spinner } from '$lib/styles/panda';

	interface Props {
		datasourceId?: string;
		compact?: boolean;
		searchQuery?: string;
	}

	let { datasourceId, compact = false, searchQuery: externalSearch }: Props = $props();

	const queryClient = useQueryClient();
	const ns = useNamespace();
	const schedLimit = 50;

	let creating = $state(false);
	let createDatasources = $state.raw<DataSource[]>([]);
	let showHelp = $state(false);
	let searchQuery = $state('');
	const effectiveSearch = $derived(externalSearch ?? searchQuery);
	let schedPage = $state(1);

	let deleteConfirmId = $state<string | null>(null);

	const schedulesQuery = createQuery(() => ({
		queryKey: [
			'schedules',
			ns.value,
			datasourceId ?? 'all',
			effectiveSearch.trim(),
			schedPage,
			schedLimit
		],
		queryFn: async () => {
			const result = await listSchedules({
				datasourceId,
				search: effectiveSearch.trim() || undefined,
				limit: schedLimit,
				offset: (schedPage - 1) * schedLimit
			});
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		enabled: !ns.switching
	}));

	const allSchedulesQuery = createQuery(() => ({
		queryKey: ['schedules', ns.value, 'all'],
		queryFn: async () => {
			const result = await listSchedules();
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		staleTime: 30_000,
		enabled: !ns.switching
	}));

	const datasourcesQuery = createQuery(() => ({
		queryKey: ['datasources-lookup', ns.value, 'include-hidden'],
		queryFn: async () => {
			const result = await listDatasources(true, { cache: 'no-store' });
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		staleTime: 0,
		refetchOnMount: 'always',
		enabled: !ns.switching
	}));

	const datasourceMap = $derived(
		new SvelteMap((datasourcesQuery.data ?? []).map((ds) => [ds.id, ds] as [string, DataSource]))
	);

	// Lookups may include hidden outputs (existing schedules); pickers never list them.
	const pickerDatasources = $derived((datasourcesQuery.data ?? []).filter((ds) => !ds.is_hidden));

	const schedules = $derived(schedulesQuery.data ?? []);
	const allSchedules = $derived(allSchedulesQuery.data ?? []);
	const hasSearch = $derived(effectiveSearch.trim().length > 0);

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

	function handleToggle(schedule: Schedule) {
		toggleMut.mutate({ id: schedule.id, enabled: !schedule.enabled });
	}

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

	function openCreate() {
		void listDatasources(true, { cache: 'no-store' }).match(
			(datasources) => {
				queryClient.setQueryData(['datasources-lookup', ns.value, 'include-hidden'], datasources);
				createDatasources = datasources.filter((ds) => !ds.is_hidden);
				creating = true;
			},
			() => {
				createDatasources = pickerDatasources;
				creating = true;
			}
		);
	}
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
			<div class={css({ display: 'flex', alignItems: 'center', justifyContent: 'space-between' })}>
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
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						marginTop: '4',
						flexWrap: 'wrap',
						gap: '3'
					})}
				>
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
							class={css({
								width: 'full',
								color: 'fg.primary',
								borderWidth: '1',
								borderRadius: '0',
								transitionProperty: 'border-color',
								transitionDuration: '160ms',
								transitionTimingFunction: 'ease',
								_focus: { outline: 'none' },
								_focusVisible: { borderColor: 'border.accent' },
								_disabled: {
									opacity: '0.5',
									cursor: 'not-allowed'
								},
								_placeholder: { color: 'fg.muted' },
								backgroundColor: 'transparent',
								paddingX: '3',
								paddingY: '1.5',
								paddingLeft: '8',
								fontSize: 'sm'
							})}
							bind:value={searchQuery}
						/>
					</div>
				</div>
			{/if}
		</header>
	{:else}
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				marginBottom: '3',
				justifyContent: 'space-between'
			})}
		>
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
			<div class={css({ display: 'flex', alignItems: 'center', gap: '1' })}>
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
					<CircleQuestionMark size={14} />
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
					<li class={css({ display: 'flex', alignItems: 'center', gap: '1' })}>
						<Clock size={10} class={css({ color: 'fg.muted' })} /> <strong>On a Schedule</strong> — runs
						on a cron interval
					</li>
					<li class={css({ display: 'flex', alignItems: 'center', gap: '1' })}>
						<Link size={10} class={css({ color: 'fg.muted' })} />
						<strong>After Another Schedule</strong> — runs when a dependency completes
					</li>
					<li class={css({ display: 'flex', alignItems: 'center', gap: '1' })}>
						<Database size={10} class={css({ color: 'fg.muted' })} />
						<strong>When Dataset Updates</strong> — runs on datasource change
					</li>
				</ul>
			</div>
		{/if}
	{/if}

	{#if creating}
		<ScheduleCreateForm
			{datasourceId}
			{compact}
			{currentTarget}
			{createDatasources}
			allDatasources={datasourcesQuery.data ?? []}
			{allSchedules}
			onclose={() => (creating = false)}
			onCreated={() => {
				createDatasources = [];
				creating = false;
			}}
		/>
	{/if}

	{#if schedulesQuery.isLoading}
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'center',
				paddingY: '6'
			})}
		>
			<div class={spinner()}></div>
		</div>
	{:else if datasourcesQuery.isError || allSchedulesQuery.isError || schedulesQuery.isError}
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
			{datasourcesQuery.error instanceof Error
				? datasourcesQuery.error.message
				: allSchedulesQuery.error instanceof Error
					? allSchedulesQuery.error.message
					: schedulesQuery.error instanceof Error
						? schedulesQuery.error.message
						: 'Error loading schedules.'}
		</div>
	{:else if schedules.length === 0 && !creating && !hasSearch}
		<div
			class={css(
				{
					borderWidth: '1',
					borderStyle: 'dashed',
					padding: '6',
					textAlign: 'center'
				},
				!compact && { padding: '8' }
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
	{:else if schedules.length === 0 && hasSearch}
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
	{:else if schedules.length > 0}
		<ScheduleList
			{schedules}
			{allSchedules}
			allDatasources={datasourcesQuery.data ?? []}
			{pickerDatasources}
			{datasourceId}
			{compact}
			togglePending={toggleMut.isPending}
			deletePending={deleteMut.isPending}
			onToggle={handleToggle}
			onDelete={handleDelete}
		/>
	{/if}

	{#if !compact && schedules.length > 0}
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				marginTop: '4',
				justifyContent: 'space-between'
			})}
		>
			<span class={css({ fontSize: 'sm', color: 'fg.tertiary' })}>
				Page {schedPage}
			</span>
			<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
				<button
					class={button({ variant: 'secondary', size: 'compact' })}
					onclick={() => {
						if (schedPage > 1) schedPage--;
					}}
					disabled={schedPage === 1}
				>
					Previous
				</button>
				<button
					class={button({ variant: 'secondary', size: 'compact' })}
					onclick={() => {
						schedPage++;
					}}
					disabled={schedules.length < schedLimit}
				>
					Next
				</button>
			</div>
		</div>
	{/if}
</div>
