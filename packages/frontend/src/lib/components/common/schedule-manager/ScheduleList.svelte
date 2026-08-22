<script lang="ts">
	import { createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { updateSchedule } from '$lib/api/schedule';
	import type { Schedule } from '$lib/api/schedule';
	import type { DataSource } from '$lib/types/datasource';
	import {
		ChartColumn,
		Check,
		ChevronDown,
		Clock,
		Database,
		Link,
		Pencil,
		Power,
		PowerOff,
		Trash2,
		X
	} from '@lucide/svelte';
	import { css, input } from '$lib/styles/panda';
	import CronField from './CronField.svelte';
	import {
		depLabel,
		depOptions,
		formatDate,
		getProvenanceDisplay,
		getTriggerDescription,
		getTriggerLabel,
		getTriggerType,
		resolveDatasource
	} from './schedule-utils';

	interface Props {
		schedules: Schedule[];
		allSchedules: Schedule[];
		allDatasources: DataSource[];
		pickerDatasources: DataSource[];
		datasourceId?: string;
		compact?: boolean;
		togglePending?: boolean;
		deletePending?: boolean;
		onToggle: (schedule: Schedule) => void;
		onDelete: (id: string) => void;
	}

	let {
		schedules,
		allSchedules,
		allDatasources,
		pickerDatasources,
		datasourceId,
		compact = false,
		togglePending = false,
		deletePending = false,
		onToggle,
		onDelete
	}: Props = $props();

	const queryClient = useQueryClient();

	let expandedId = $state<string | null>(null);
	let editingCron = $state<string | null>(null);
	let editCronValue = $state('');
	let editingDescription = $state<string | null>(null);
	let editDescriptionValue = $state('');

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

	const descriptionMut = createMutation(() => ({
		mutationFn: async (args: { id: string; description: string }) => {
			const result = await updateSchedule(args.id, { description: args.description || null });
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['schedules'] });
			editingDescription = null;
			editDescriptionValue = '';
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
			const result = await updateSchedule(args.id, {
				trigger_on_datasource_id: args.trigger_on_datasource_id,
				depends_on: null
			});
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['schedules'] });
		}
	}));

	function toggleExpand(id: string) {
		expandedId = expandedId === id ? null : id;
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

	function startEditDescription(schedule: Schedule) {
		editingDescription = schedule.id;
		editDescriptionValue = schedule.description ?? '';
	}

	function saveDescription(id: string) {
		descriptionMut.mutate({ id, description: editDescriptionValue.trim() });
	}

	function cancelEditDescription() {
		editingDescription = null;
		editDescriptionValue = '';
	}

	function handleDepChange(id: string, value: string) {
		depMut.mutate({ id, depends_on: value || null });
	}

	function handleTriggerChange(id: string, value: string) {
		triggerMut.mutate({ id, trigger_on_datasource_id: value || null });
	}

	const colCount = $derived.by(() => {
		let count = 7;
		if (!datasourceId) count += 1;
		return count;
	});
</script>

{#snippet descriptionBlock(schedule: Schedule)}
	<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
		<span class={css({ fontSize: '2xs', color: 'fg.muted' })}>Description</span>
		{#if editingDescription === schedule.id}
			<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
				<textarea
					class={input({ variant: 'micro' })}
					rows="3"
					id="sched-{schedule.id}-description"
					aria-label="Schedule description"
					bind:value={editDescriptionValue}
					onkeydown={(e) => {
						if (e.key === 'Escape') cancelEditDescription();
					}}
				></textarea>
				<div class={css({ display: 'flex', alignItems: 'center', gap: '1' })}>
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
						onclick={() => saveDescription(schedule.id)}
						disabled={descriptionMut.isPending}
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
						onclick={cancelEditDescription}
						title="Cancel"
					>
						<X size={12} />
					</button>
				</div>
			</div>
		{:else}
			<div class={css({ display: 'flex', alignItems: 'flex-start', gap: '1' })}>
				{#if schedule.description}
					<p class={css({ margin: '0', flex: '1', fontSize: '2xs', color: 'fg.secondary' })}>
						{schedule.description}
					</p>
				{:else}
					<span class={css({ flex: '1', fontSize: '2xs', color: 'fg.tertiary' })}>
						No description
					</span>
				{/if}
				<button
					class={css({
						flexShrink: '0',
						border: 'none',
						backgroundColor: 'transparent',
						padding: '0.5',
						color: 'fg.muted',
						_hover: { color: 'fg.primary' }
					})}
					onclick={() => startEditDescription(schedule)}
					title="Edit description"
				>
					<Pencil size={10} />
				</button>
			</div>
		{/if}
	</div>
{/snippet}

{#if compact}
	<!-- Compact card list -->
	<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
		{#each schedules as schedule (schedule.id)}
			{@const triggerTypeValue = getTriggerType(schedule)}
			{@const triggerDesc = getTriggerDescription(schedule, allDatasources, allSchedules)}
			<div
				class={[
					'group',
					css({
						borderWidth: '1',
						backgroundColor: 'bg.primary'
					})
				]}
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
						class={css(
							{ flexShrink: '0', color: 'fg.muted' },
							!(expandedId === schedule.id) && { transform: 'rotate(-90deg)' }
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
							onToggle(schedule);
						}}
						disabled={togglePending}
						title={schedule.enabled ? 'Click to disable' : 'Click to enable'}
					>
						{#if schedule.enabled}
							<Power size={10} class={css({ color: 'fg.success' })} />
						{:else}
							<PowerOff size={10} class={css({ color: 'fg.muted' })} />
						{/if}
					</button>
					<button
						class={css({
							flexShrink: '0',
							border: 'none',
							backgroundColor: 'transparent',
							padding: '0',
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
							onDelete(schedule.id);
						}}
						disabled={deletePending}
						aria-label="Delete schedule"
					>
						<Trash2 size={10} />
					</button>
				</div>
				{#if expandedId === schedule.id}
					<div class={css({ borderTopWidth: '1', paddingX: '3', paddingY: '2' })}>
						<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
							{@render descriptionBlock(schedule)}
							{#if triggerTypeValue === 'cron'}
								<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
									<span class={css({ fontSize: '2xs', color: 'fg.muted' })}> Cron Expression </span>
									<CronField
										variant="compact"
										scheduleId={schedule.id}
										cronExpression={schedule.cron_expression}
										editing={editingCron === schedule.id}
										bind:editValue={editCronValue}
										savePending={cronMut.isPending}
										onSave={() => saveCron(schedule.id)}
										onCancel={cancelEditCron}
										onEdit={() => startEditCron(schedule)}
									/>
								</div>
							{:else if triggerTypeValue === 'depends'}
								<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
									<span class={css({ fontSize: '2xs', color: 'fg.muted' })}>Depends On</span>
									<select
										class={input({ variant: 'micro' })}
										id="sched-{schedule.id}-depends"
										aria-label="Depends on schedule"
										value={schedule.depends_on ?? ''}
										onchange={(e) => handleDepChange(schedule.id, e.currentTarget.value)}
										onclick={(e) => e.stopPropagation()}
									>
										<option value="">None</option>
										{#each depOptions(allSchedules, schedule.id) as dep (dep.id)}
											<option value={dep.id}>{depLabel(dep.id, allSchedules)}</option>
										{/each}
									</select>
								</div>
							{:else}
								<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
									<span class={css({ fontSize: '2xs', color: 'fg.muted' })}
										>On Datasource Update</span
									>
									<select
										class={input({ variant: 'micro' })}
										id="sched-{schedule.id}-trigger"
										aria-label="Trigger datasource"
										value={schedule.trigger_on_datasource_id ?? ''}
										onchange={(e) => handleTriggerChange(schedule.id, e.currentTarget.value)}
										onclick={(e) => e.stopPropagation()}
									>
										<option value="">None</option>
										{#each pickerDatasources as ds (ds.id)}
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
				{#each schedules as schedule (schedule.id)}
					{@const triggerTypeValue = getTriggerType(schedule)}
					{@const triggerDesc = getTriggerDescription(schedule, allDatasources, allSchedules)}
					{@const provenanceDisplay = getProvenanceDisplay(schedule)}
					<tr
						data-schedule-row={schedule.id}
						data-datasource-id={schedule.datasource_id}
						data-datasource-name={resolveDatasource(schedule.datasource_id, allDatasources)}
						class={css({
							cursor: 'pointer',
							_hover: { backgroundColor: 'bg.hover' },
							_focusVisible: {
								outline: '2px solid',
								outlineColor: 'accent.primary',
								outlineOffset: '-1px'
							},
							...(expandedId === schedule.id ? { backgroundColor: 'bg.secondary' } : {})
						})}
						tabindex="0"
						aria-expanded={expandedId === schedule.id}
						onclick={() => toggleExpand(schedule.id)}
						onkeydown={(e) => {
							const target = e.target as HTMLElement;
							if (target.closest('button, input, select, textarea, a')) return;
							if (e.key === 'Enter' || e.key === ' ') {
								e.preventDefault();
								toggleExpand(schedule.id);
							}
						}}
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
								class={css(
									{ transition: 'transform 160ms' },
									!(expandedId === schedule.id) && { transform: 'rotate(-90deg)' }
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
									title={resolveDatasource(schedule.datasource_id, allDatasources)}
								>
									<ChartColumn size={10} class={css({ flexShrink: '0', color: 'fg.muted' })} />
									{resolveDatasource(schedule.datasource_id, allDatasources)}
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
							<div class={css({ display: 'flex', alignItems: 'center', gap: '1.5' })}>
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
									onToggle(schedule);
								}}
								disabled={togglePending}
								title={schedule.enabled ? 'Click to disable' : 'Click to enable'}
							>
								{#if schedule.enabled}
									<Power size={12} class={css({ color: 'fg.success' })} />
									<span class={css({ color: 'fg.success' })}>On</span>
								{:else}
									<PowerOff size={12} class={css({ color: 'fg.muted' })} />
									<span class={css({ color: 'fg.muted' })}>Off</span>
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
									onDelete(schedule.id);
								}}
								disabled={deletePending}
								aria-label="Delete schedule"
							>
								<Trash2 size={12} />
							</button>
						</td>
					</tr>
					{#if expandedId === schedule.id}
						<tr data-schedule-detail={schedule.id}>
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
										<div class={css({ display: 'flex', alignItems: 'center', gap: '1' })}>
											<ChartColumn size={10} class={css({ color: 'fg.muted' })} />
											<span class={css({ fontSize: '2xs', color: 'fg.secondary' })}>
												{resolveDatasource(schedule.datasource_id, allDatasources)}
											</span>
										</div>
									</div>
									<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
										<span class={css({ fontSize: '2xs', color: 'fg.muted' })}>Produced By</span>
										<span class={css({ fontSize: '2xs', color: 'fg.secondary' })}>
											{provenanceDisplay}
										</span>
									</div>
									{@render descriptionBlock(schedule)}
									{#if triggerTypeValue === 'cron'}
										<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
											<span class={css({ fontSize: '2xs', color: 'fg.muted' })}
												>Cron Expression</span
											>
											<CronField
												variant="table"
												scheduleId={schedule.id}
												cronExpression={schedule.cron_expression}
												editing={editingCron === schedule.id}
												bind:editValue={editCronValue}
												savePending={cronMut.isPending}
												onSave={() => saveCron(schedule.id)}
												onCancel={cancelEditCron}
												onEdit={() => startEditCron(schedule)}
											/>
										</div>
									{:else if triggerTypeValue === 'depends'}
										<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
											<span class={css({ fontSize: '2xs', color: 'fg.muted' })}>Depends On</span>
											<div class={css({ display: 'flex', alignItems: 'center', gap: '1' })}>
												<select
													class={input({ variant: 'micro' })}
													id="sched-{schedule.id}-depends"
													aria-label="Depends on schedule"
													value={schedule.depends_on ?? ''}
													onchange={(e) => handleDepChange(schedule.id, e.currentTarget.value)}
													onclick={(e) => e.stopPropagation()}
												>
													<option value="">None</option>
													{#each depOptions(allSchedules, schedule.id) as dep (dep.id)}
														<option value={dep.id}>{depLabel(dep.id, allSchedules)}</option>
													{/each}
												</select>
												{#if schedule.depends_on}
													<Link size={10} class={css({ color: 'fg.muted' })} />
												{/if}
											</div>
										</div>
									{:else}
										<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
											<span class={css({ fontSize: '2xs', color: 'fg.muted' })}
												>On Datasource Update</span
											>
											<div class={css({ display: 'flex', alignItems: 'center', gap: '1' })}>
												<select
													class={input({ variant: 'micro' })}
													id="sched-{schedule.id}-trigger"
													aria-label="Trigger datasource"
													value={schedule.trigger_on_datasource_id ?? ''}
													onchange={(e) => handleTriggerChange(schedule.id, e.currentTarget.value)}
													onclick={(e) => e.stopPropagation()}
												>
													<option value="">None</option>
													{#each pickerDatasources as ds (ds.id)}
														<option value={ds.id}>{ds.name}</option>
													{/each}
												</select>
												{#if schedule.trigger_on_datasource_id}
													<Database size={10} class={css({ color: 'fg.muted' })} />
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
