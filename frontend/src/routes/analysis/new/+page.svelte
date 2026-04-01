<script lang="ts">
	import { goto } from '$app/navigation';
	import { Check } from 'lucide-svelte';
	import { resolve } from '$app/paths';
	import { createQuery } from '@tanstack/svelte-query';
	import { listDatasources } from '$lib/api/datasource';
	import { createAnalysis } from '$lib/api/analysis';
	import DatasourcePicker from '$lib/components/common/DatasourcePicker.svelte';
	import FileTypeBadge from '$lib/components/common/FileTypeBadge.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import type { AnalysisCreate, PipelineStep } from '$lib/types/analysis';
	import { buildOutputConfig, generateOutputName } from '$lib/utils/analysis-tab';
	import { getDefaultConfig } from '$lib/utils/step-config-defaults';
	import { css, cx, spinner, button, label, input, row, divider } from '$lib/styles/panda';

	let step = $state(1);
	let name = $state('');
	let description = $state('');
	let selectedDatasourceIds = $state<string[]>([]);
	let error = $state('');
	let creating = $state(false);

	const datasourcesQuery = createQuery(() => ({
		queryKey: ['datasources'],
		queryFn: async () => {
			const result = await listDatasources();
			if (result.isErr()) {
				throw new Error(result.error.message);
			}
			return result.value;
		}
	}));

	const canProceedStep1 = $derived(name.trim().length > 0);
	const canProceedStep2 = $derived(selectedDatasourceIds.length > 0);
	const datasourceOptions = $derived(
		(datasourcesQuery.data ?? []).filter((ds) => ds.source_type !== 'analysis')
	);

	function buildInitialSteps(): PipelineStep[] {
		const step: PipelineStep = {
			id: crypto.randomUUID(),
			type: 'view',
			config: getDefaultConfig('view') as Record<string, unknown>,
			depends_on: [],
			is_applied: true
		};
		return [step];
	}

	async function handleCreate() {
		if (!canProceedStep1 || !canProceedStep2) return;

		creating = true;
		error = '';

		const tabs = selectedDatasourceIds.map((datasourceId, index) => {
			const name = `Source ${index + 1}`;
			const output = buildOutputConfig({
				outputId: crypto.randomUUID(),
				name: generateOutputName(),
				branch: 'master'
			});
			return {
				id: crypto.randomUUID(),
				name,
				parent_id: null,
				datasource: {
					id: datasourceId,
					analysis_tab_id: null,
					config: { branch: 'master' }
				},
				output,
				steps: buildInitialSteps()
			};
		});

		const payload: AnalysisCreate = {
			name: name.trim(),
			description: description.trim() || null,
			tabs
		};

		const result = await createAnalysis(payload);
		result.match(
			(analysis) => {
				goto(resolve(`/analysis/${analysis.id}`), { invalidateAll: true });
			},
			(err) => {
				error = err.message;
				creating = false;
			}
		);
	}
</script>

<div
	class={css({
		marginX: 'auto',
		display: 'flex',
		maxWidth: 'modal',
		flexDirection: 'column',
		gap: '6',
		paddingX: '6',
		paddingY: '7'
	})}
>
	<div class={css({ marginBottom: '8' })}>
		<h1 class={css({ margin: '0', marginBottom: '6', fontSize: '2xl', fontWeight: 'semibold' })}>
			New Analysis
		</h1>
		<div class={cx(row, css({ gap: '2' }))}>
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					gap: '2',
					color: 'fg.muted',
					backgroundColor: 'bg.primary'
				})}
			>
				<span
					class={css({
						display: 'flex',
						height: 'row',
						width: 'row',
						alignItems: 'center',
						justifyContent: 'center',
						borderWidth: '1',

						fontSize: 'xs',
						fontWeight: 'semibold',
						...(step === 1
							? { backgroundColor: 'accent.secondary', color: 'fg.inverse' }
							: step > 1
								? { backgroundColor: 'bg.success', color: 'fg.success' }
								: { color: 'fg.muted', backgroundColor: 'bg.primary' })
					})}
				>
					{#if step > 1}
						<Check size={12} />
					{:else}
						1
					{/if}
				</span>
				<span
					class={css({
						fontSize: 'sm',
						...(step === 1 ? { color: 'fg.primary', fontWeight: 'medium' } : { color: 'fg.muted' })
					})}
				>
					Details
				</span>
			</div>
			<div
				class={css({
					minWidth: 'spinner',
					flex: '1',
					height: 'px',
					backgroundColor: step > 1 ? 'accent.secondary' : 'border.primary'
				})}
			></div>
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					gap: '2',
					color: 'fg.muted',
					backgroundColor: 'bg.primary'
				})}
			>
				<span
					class={css({
						display: 'flex',
						height: 'row',
						width: 'row',
						alignItems: 'center',
						justifyContent: 'center',
						borderWidth: '1',
						fontSize: 'xs',
						fontWeight: 'semibold',
						...(step === 2
							? { backgroundColor: 'accent.secondary', color: 'fg.inverse' }
							: step > 2
								? { backgroundColor: 'bg.success', color: 'fg.success' }
								: { color: 'fg.muted', backgroundColor: 'bg.primary' })
					})}
				>
					{#if step > 2}
						<Check size={12} />
					{:else}
						2
					{/if}
				</span>
				<span
					class={css({
						fontSize: 'sm',
						...(step === 2 ? { color: 'fg.primary', fontWeight: 'medium' } : { color: 'fg.muted' })
					})}>Data Source</span
				>
			</div>
			<div
				class={css({
					minWidth: 'spinner',
					flex: '1',
					height: 'px',
					backgroundColor: step > 2 ? 'accent.secondary' : 'border.primary'
				})}
			></div>
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					gap: '2',
					color: 'fg.muted',
					backgroundColor: 'bg.primary'
				})}
			>
				<span
					class={css({
						display: 'flex',
						height: 'row',
						width: 'row',
						alignItems: 'center',
						justifyContent: 'center',
						borderWidth: '1',
						fontSize: 'xs',
						fontWeight: 'semibold',
						...(step === 3
							? { backgroundColor: 'accent.secondary', color: 'fg.inverse' }
							: { color: 'fg.muted', backgroundColor: 'bg.primary' })
					})}
				>
					3
				</span>
				<span
					class={css({
						fontSize: 'sm',
						...(step === 3 ? { color: 'fg.primary', fontWeight: 'medium' } : { color: 'fg.muted' })
					})}>Review</span
				>
			</div>
		</div>
	</div>

	<div class={css({ marginBottom: '6', flex: '1' })}>
		{#if step === 1}
			<div
				class={css({
					backgroundColor: 'bg.primary',
					borderWidth: '1',

					padding: '5'
				})}
			>
				<h2 class={css({ margin: '0', marginBottom: '2', fontSize: 'lg', fontWeight: 'semibold' })}>
					Analysis Details
				</h2>
				<p class={css({ marginBottom: '6', color: 'fg.tertiary' })}>
					Give your analysis a name and optional description.
				</p>

				<div class={css({ marginBottom: '5', display: 'flex', flexDirection: 'column', gap: '2' })}>
					<label for="name" class={label({ variant: 'field' })}>
						Name <span class={css({ color: 'fg.error' })}>*</span>
					</label>
					<input
						id="name"
						type="text"
						bind:value={name}
						placeholder="My Data Analysis"
						class={cx(input(), css({ padding: '3', fontSize: 'sm' }))}
					/>
				</div>
				<div class={css({ marginBottom: '5', display: 'flex', flexDirection: 'column', gap: '2' })}>
					<label for="description" class={label({ variant: 'field' })}> Description </label>
					<textarea
						id="description"
						bind:value={description}
						placeholder="Describe what this analysis does..."
						rows="4"
						class={cx(
							input(),
							css({ minHeight: 'fieldSm', resize: 'vertical', padding: '3', fontSize: 'sm' })
						)}
					></textarea>
				</div>
			</div>
		{:else if step === 2}
			<div
				class={css({
					backgroundColor: 'bg.primary',
					borderWidth: '1',

					padding: '5'
				})}
			>
				<h2 class={css({ margin: '0', marginBottom: '2', fontSize: 'lg', fontWeight: 'semibold' })}>
					Select Data Sources
				</h2>
				<p class={css({ marginBottom: '6', color: 'fg.tertiary' })}>
					Choose one or more data sources for this analysis.
				</p>

				{#if datasourcesQuery.isLoading}
					<div
						class={css({
							display: 'flex',
							height: '100%',
							alignItems: 'center',
							justifyContent: 'center'
						})}
					>
						<div class={spinner()}></div>
					</div>
				{:else if datasourcesQuery.error}
					<Callout tone="error">
						Error loading data sources: {datasourcesQuery.error.message}
					</Callout>
				{:else if datasourcesQuery.data && datasourcesQuery.data.length === 0}
					<div
						class={css({
							borderWidth: '1',
							borderStyle: 'dashed',
							padding: '8',
							textAlign: 'center',
							color: 'fg.tertiary'
						})}
					>
						<p>No data sources available.</p>
						<a
							href={resolve('/datasources/new')}
							class={button({ variant: 'secondary' })}
							data-sveltekit-reload
						>
							Create Data Source
						</a>
					</div>
				{:else if datasourcesQuery.data}
					<DatasourcePicker
						datasources={datasourceOptions}
						bind:selected={selectedDatasourceIds}
						mode="multi"
						id="new-analysis"
						showChips={true}
						searchFields={['name', 'source_type', 'file_type']}
					/>
				{/if}
			</div>
		{:else if step === 3}
			<div
				class={css({
					backgroundColor: 'bg.primary',
					borderWidth: '1',

					padding: '5'
				})}
			>
				<h2 class={css({ margin: '0', marginBottom: '2', fontSize: 'lg', fontWeight: 'semibold' })}>
					Review & Create
				</h2>
				<p class={css({ marginBottom: '6', color: 'fg.tertiary' })}>
					Review your analysis configuration before creating.
				</p>

				<div
					class={css({
						marginBottom: '6',
						borderBottomWidth: '1',
						paddingBottom: '6'
					})}
				>
					<h3
						class={css({
							margin: '0',
							marginBottom: '4',
							fontSize: 'sm',
							fontWeight: 'semibold',
							textTransform: 'uppercase',
							letterSpacing: 'wide',
							color: 'fg.tertiary'
						})}
					>
						Details
					</h3>
					<dl class={css({ margin: '0' })}>
						<div class={css({ marginBottom: '2', display: 'flex', gap: '4' })}>
							<dt class={css({ width: 'fieldSm', flexShrink: '0', color: 'fg.muted' })}>Name</dt>
							<dd class={css({ margin: '0' })}>{name}</dd>
						</div>
						{#if description}
							<div class={css({ marginBottom: '2', display: 'flex', gap: '4' })}>
								<dt class={css({ width: 'fieldSm', flexShrink: '0', color: 'fg.muted' })}>
									Description
								</dt>
								<dd class={css({ margin: '0' })}>{description}</dd>
							</div>
						{/if}
					</dl>
				</div>

				<div>
					<h3
						class={css({
							margin: '0',
							marginBottom: '4',
							fontSize: 'sm',
							fontWeight: 'semibold',
							textTransform: 'uppercase',
							letterSpacing: 'wide',
							color: 'fg.tertiary'
						})}
					>
						Data Sources ({selectedDatasourceIds.length})
					</h3>
					<ul class={css({ margin: '0', listStyle: 'none', padding: '0' })}>
						{#if datasourcesQuery.data}
							{#each datasourcesQuery.data.filter( (ds) => selectedDatasourceIds.includes(ds.id) ) as ds (ds.id)}
								<li
									class={css({
										display: 'flex',
										alignItems: 'center',
										gap: '3',
										borderBottomWidth: '1',
										paddingY: '2'
									})}
								>
									<span>{ds.name}</span>
									<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>
										{#if ds.source_type === 'file'}
											<FileTypeBadge
												path={(ds.config?.file_path as string) ?? ''}
												size="sm"
												showIcon={true}
											/>
										{:else}
											<FileTypeBadge
												sourceType={ds.source_type as 'database' | 'iceberg'}
												size="sm"
												showIcon={true}
											/>
										{/if}
									</span>
								</li>
							{/each}
						{/if}
					</ul>
				</div>

				{#if error}
					<Callout tone="error">
						{error}
					</Callout>
				{/if}
			</div>
		{/if}
	</div>

	<div
		class={cx(
			divider,
			css({
				display: 'flex',
				gap: '3',
				paddingTop: '6'
			})
		)}
	>
		{#if step > 1}
			<button
				class={button({ variant: 'secondary' })}
				onclick={() => (step -= 1)}
				disabled={creating}
			>
				Back
			</button>
		{:else}
			<a href={resolve('/')} class={button({ variant: 'secondary' })} data-sveltekit-reload
				>Cancel</a
			>
		{/if}

		<div class={css({ flex: '1' })}></div>

		{#if step < 3}
			<button
				class={button({ variant: 'primary' })}
				onclick={() => (step += 1)}
				disabled={(step === 1 && !canProceedStep1) || (step === 2 && !canProceedStep2)}
			>
				Next
			</button>
		{:else}
			<button class={button({ variant: 'primary' })} onclick={handleCreate} disabled={creating}>
				{creating ? 'Creating...' : 'Create Analysis'}
			</button>
		{/if}
	</div>
</div>
