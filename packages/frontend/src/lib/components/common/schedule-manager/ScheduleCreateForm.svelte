<script lang="ts">
	import { createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { createSchedule } from '$lib/api/schedule';
	import type { Schedule, ScheduleCreate } from '$lib/api/schedule';
	import type { DataSource } from '$lib/types/datasource';
	import { ArrowRight, ChartColumn, Clock, Database, FileText, Link } from '@lucide/svelte';
	import { css, label } from '$lib/styles/panda';
	import { getCronDescription, depLabel, depOptions } from './schedule-utils';

	const defaultCron = '0 * * * *';

	interface Props {
		datasourceId?: string;
		compact?: boolean;
		currentTarget: {
			datasourceName: string;
			analysisName: string;
			tabName: string | null;
		} | null;
		createDatasources: DataSource[];
		allDatasources: DataSource[];
		allSchedules: Schedule[];
		onclose: () => void;
		onCreated?: () => void;
	}

	let {
		datasourceId,
		compact = false,
		onclose,
		currentTarget,
		createDatasources,
		allDatasources,
		allSchedules,
		onCreated
	}: Props = $props();

	const queryClient = useQueryClient();

	let triggerType = $state<'cron' | 'depends' | 'event'>('cron');
	let newCron = $state(defaultCron);
	let newDatasourceId = $state('');
	let newDependsOn = $state('');
	let newTrigger = $state('');
	let newDescription = $state('');

	const selectedDatasource = $derived.by(() => {
		if (!newDatasourceId) return null;
		return allDatasources.find((ds) => ds.id === newDatasourceId) ?? null;
	});

	const createMut = createMutation(() => ({
		mutationFn: async (payload: ScheduleCreate) => {
			const result = await createSchedule(payload);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['schedules'] });
			resetForm();
			onCreated?.();
		}
	}));

	function resetForm() {
		triggerType = 'cron';
		newCron = defaultCron;
		newDatasourceId = '';
		newDependsOn = '';
		newTrigger = '';
		newDescription = '';
	}

	function handleCreate() {
		const targetDs = datasourceId ?? newDatasourceId;
		if (!targetDs) return;

		const payload: ScheduleCreate = {
			datasource_id: targetDs,
			cron_expression: newCron
		};

		const description = newDescription.trim();
		if (description) {
			payload.description = description;
		}

		if (triggerType === 'depends' && newDependsOn) {
			payload.depends_on = newDependsOn;
		}

		if (triggerType === 'event' && newTrigger) {
			payload.trigger_on_datasource_id = newTrigger;
		}

		createMut.mutate(payload);
	}
</script>

<div
	class={css(
		{
			marginBottom: '4',
			borderWidth: '1',
			backgroundColor: 'bg.primary',
			padding: '4'
		},
		!compact && { marginBottom: '6' }
	)}
>
	<h3 class={css({ margin: '0', marginBottom: '4', fontSize: 'sm', fontWeight: 'medium' })}>
		Create Schedule
	</h3>

	<!-- Target Section -->
	<div class={css({ marginBottom: '5' })}>
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				marginBottom: '3',
				gap: '2',
				borderBottomWidth: '1',
				paddingBottom: '2'
			})}
		>
			<Database size={14} class={css({ color: 'accent.primary' })} />
			<span class={css({ fontSize: 'xs', fontWeight: 'medium' })}>
				Target Dataset — What gets rebuilt
			</span>
		</div>

		{#if currentTarget}
			<div class={css({ backgroundColor: 'bg.secondary', padding: '3', fontSize: 'sm' })}>
				<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
					<ChartColumn size={14} class={css({ color: 'accent.primary' })} />
					<span class={css({ fontWeight: 'medium' })}>
						{currentTarget.datasourceName}
					</span>
				</div>
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						marginTop: '1',
						gap: '1',
						fontSize: 'xs',
						color: 'fg.muted'
					})}
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
							paddingX: '2',
							paddingY: '1.5',
							fontSize: 'xs'
						})}
						bind:value={newDatasourceId}
					>
						<option value="">Select output dataset...</option>
						{#each createDatasources as ds (ds.id)}
							<option value={ds.id}>{ds.name}</option>
						{/each}
					</select>
				</div>

				{#if selectedDatasource}
					<div class={css({ backgroundColor: 'bg.secondary', padding: '3', fontSize: 'sm' })}>
						<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
							<ChartColumn size={14} class={css({ color: 'accent.primary' })} />
							<span class={css({ fontWeight: 'medium' })}>{selectedDatasource.name}</span>
						</div>
						<div
							class={css({
								display: 'flex',
								alignItems: 'center',
								marginTop: '1',
								gap: '1',
								fontSize: 'xs',
								color: 'fg.muted'
							})}
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

	<!-- Description Section -->
	<div class={css({ marginBottom: '5' })}>
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				marginBottom: '3',
				gap: '2',
				borderBottomWidth: '1',
				paddingBottom: '2'
			})}
		>
			<FileText size={14} class={css({ color: 'accent.primary' })} />
			<span class={css({ fontSize: 'xs', fontWeight: 'medium' })}>
				Description — Why this schedule exists
			</span>
		</div>
		<label for="schedule-description" class={label()}>Description (optional)</label>
		<textarea
			id="schedule-description"
			rows="3"
			bind:value={newDescription}
			placeholder="Production nightly reporting, QA validation, or operational caveats..."
			class={css({
				width: 'full',
				resize: 'vertical',
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
				paddingX: '2',
				paddingY: '1.5',
				fontSize: 'xs'
			})}></textarea>
	</div>

	<!-- Trigger Section -->
	<div>
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				marginBottom: '3',
				gap: '2',
				borderBottomWidth: '1',
				paddingBottom: '2'
			})}
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
						<div class={css({ display: 'flex', alignItems: 'center', marginTop: '2', gap: '2' })}>
							<input
								type="text"
								class={css({
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
									width: 'colMd',
									backgroundColor: 'transparent',
									paddingX: '2',
									paddingY: '1',
									fontSize: 'xs'
								})}
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
						class={css({
							display: 'flex',
							alignItems: 'center',
							marginBottom: '1',
							gap: '1',
							fontSize: 'xs',
							fontWeight: 'medium'
						})}
					>
						<Link size={12} class={css({ color: 'fg.muted' })} />
						After Another Schedule
					</div>
					<p class={css({ margin: '0', fontSize: 'xs', color: 'fg.tertiary' })}>
						Run after another schedule completes successfully
					</p>
					{#if triggerType === 'depends'}
						<div class={css({ marginTop: '2' })}>
							<select
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
									paddingX: '2',
									paddingY: '1',
									fontSize: 'xs'
								})}
								name="depends_on"
								bind:value={newDependsOn}
							>
								<option value="">Select a schedule...</option>
								{#each depOptions(allSchedules) as dep (dep.id)}
									<option value={dep.id}>{depLabel(dep.id, allSchedules)}</option>
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
						class={css({
							display: 'flex',
							alignItems: 'center',
							marginBottom: '1',
							gap: '1',
							fontSize: 'xs',
							fontWeight: 'medium'
						})}
					>
						<Database size={12} class={css({ color: 'fg.muted' })} />
						When Dataset Updates
					</div>
					<p class={css({ margin: '0', fontSize: 'xs', color: 'fg.tertiary' })}>
						Run when a specific datasource is updated
					</p>
					{#if triggerType === 'event'}
						<div class={css({ marginTop: '2' })}>
							<select
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
									paddingX: '2',
									paddingY: '1',
									fontSize: 'xs'
								})}
								name="trigger_datasource"
								bind:value={newTrigger}
							>
								<option value="">Select a datasource...</option>
								{#each createDatasources as ds (ds.id)}
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
		class={css({
			borderTopWidth: '1',
			marginTop: '4',
			display: 'flex',
			gap: '2',
			paddingTop: '4'
		})}
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
			onclick={onclose}
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
