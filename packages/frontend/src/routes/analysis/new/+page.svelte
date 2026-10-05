<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page as pageState } from '$app/state';
	import { createQuery } from '@tanstack/svelte-query';
	import { createAnalysis, listAnalyses } from '$lib/api/analysis';
	import { listDatasources } from '$lib/api/datasource';
	import { ArrowLeft, ChevronDown, Search } from '@lucide/svelte';
	import DatasourcePreview from '$lib/components/datasources/DatasourcePreview.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { button, css, spinner } from '$lib/styles/panda';
	import { configStore } from '$lib/stores/config.svelte';
	import { useNamespace } from '$lib/stores/namespace.svelte';
	import type { AnalysisTab } from '$lib/types/analysis';
	import type { DataSource } from '$lib/types/datasource';
	import { nextAnalysisName } from '$lib/utils/analysis-name';
	import { buildOutputConfig } from '$lib/utils/analysis-tab';
	import { uuid } from '$lib/utils/uuid';

	const ns = useNamespace();
	// A datasource in the query means the user already asked to start an
	// analysis from it, so the page goes straight to the editor.
	const requestedDatasourceId = $derived(pageState.url.searchParams.get('datasource') ?? '');

	let expandedDatasourceId = $state('');
	let searchQuery = $state('');
	let creatingDatasource = $state<DataSource | null>(null);
	let createError = $state('');
	let autoStartAttempted = $state(false);

	const datasourcesQuery = createQuery(() => ({
		queryKey: ['datasources', ns.value],
		enabled: !ns.switching,
		queryFn: async () => {
			const result = await listDatasources();
			if (result.isErr()) throw new Error(result.error.message);
			return result.value.filter((datasource) => datasource.source_type !== 'analysis');
		}
	}));

	const datasources = $derived(datasourcesQuery.data ?? []);
	const filteredDatasources = $derived.by(() => {
		const query = searchQuery.trim().toLowerCase();
		if (!query) return datasources;
		return datasources.filter((datasource) => datasource.name.toLowerCase().includes(query));
	});
	const outputNamespace = $derived(configStore.config?.default_namespace ?? ns.value);

	function defaultBranch(datasource: DataSource): string {
		const config = datasource.config as Record<string, unknown>;
		const branches = config.branches;
		if (Array.isArray(branches)) {
			const firstBranch = branches.find(
				(branch): branch is string => typeof branch === 'string' && branch.trim().length > 0
			);
			if (firstBranch) return firstBranch.trim();
		}
		return typeof config.branch === 'string' && config.branch.trim()
			? config.branch.trim()
			: 'master';
	}

	function slugify(value: string): string {
		return (
			value
				.trim()
				.toLowerCase()
				.replace(/[^a-z0-9]+/g, '_')
				.replace(/^_+|_+$/g, '') || 'analysis_output'
		);
	}

	/** Opening an analysis from a datasource is the whole point of this page. */
	async function startAnalysis(datasource: DataSource): Promise<void> {
		if (creatingDatasource) return;
		creatingDatasource = datasource;
		createError = '';

		const branch = defaultBranch(datasource);
		const outputId = uuid();
		const tab: AnalysisTab = {
			id: uuid(),
			name: 'Source 1',
			parent_id: null,
			datasource: {
				id: datasource.id,
				analysis_tab_id: null,
				config: { branch }
			},
			output: buildOutputConfig({
				outputId,
				name: slugify(`${datasource.name}_output_${outputId.slice(0, 8)}`),
				branch,
				namespace: outputNamespace
			}),
			steps: []
		};

		try {
			const existing = await listAnalyses();
			const existingNames = existing.isOk() ? existing.value.map((analysis) => analysis.name) : [];
			const result = await createAnalysis({
				name: nextAnalysisName(`${datasource.name} Analysis`, existingNames),
				description: null,
				tabs: [tab]
			});
			if (result.isErr()) {
				createError = result.error.message;
				return;
			}
			await goto(resolve(`/analysis/${result.value.id}`));
		} catch (cause) {
			createError =
				cause instanceof Error ? cause.message : 'Could not start the analysis. Try again.';
		} finally {
			creatingDatasource = null;
		}
	}

	$effect(() => {
		if (autoStartAttempted || !requestedDatasourceId) return;
		if (datasourcesQuery.isPending) return;
		autoStartAttempted = true;
		const datasource = datasources.find((candidate) => candidate.id === requestedDatasourceId);
		if (!datasource) {
			createError = 'That datasource is no longer available.';
			return;
		}
		void startAnalysis(datasource);
	});

	function toggleExpanded(id: string): void {
		expandedDatasourceId = expandedDatasourceId === id ? '' : id;
	}

	function handleSearchKeydown(event: KeyboardEvent): void {
		if (event.key !== 'Enter') return;
		const firstMatch = filteredDatasources[0];
		if (firstMatch) expandedDatasourceId = firstMatch.id;
	}
</script>

<main
	class={css({
		boxSizing: 'border-box',
		width: 'full',
		marginX: 'auto',
		maxWidth: 'page',
		paddingX: '8',
		paddingY: '8',
		md: { paddingX: '4', paddingY: '4' }
	})}
>
	<a
		href={resolve('/')}
		aria-label="Back to analyses"
		class={css({
			display: 'inline-flex',
			alignItems: 'center',
			gap: '1.5',
			fontSize: 'xs',
			color: 'fg.muted',
			textDecoration: 'none',
			cursor: 'pointer',
			_hover: { color: 'fg.primary' }
		})}
	>
		<ArrowLeft size={13} />
		Analyses
	</a>

	<header
		class={css({ marginTop: '4', marginBottom: '5', paddingBottom: '5', borderBottomWidth: '1' })}
	>
		<h1 class={css({ margin: '0', fontSize: '2xl', fontWeight: 'semibold' })}>New analysis</h1>
		<p class={css({ margin: '2 0 0 0', fontSize: 'sm', color: 'fg.tertiary' })}>
			Pick a datasource to preview its data, then start building on it.
		</p>
	</header>

	{#if createError && !creatingDatasource}
		<div class={css({ marginBottom: '3' })}>
			<Callout tone="error">{createError}</Callout>
		</div>
	{/if}

	{#if datasources.length > 0}
		<div class={css({ position: 'relative', marginBottom: '3', maxWidth: 'panelMd' })}>
			<Search
				size={14}
				class={css({
					position: 'absolute',
					left: '3',
					top: '50%',
					transform: 'translateY(-50%)',
					color: 'fg.muted'
				})}
			/>
			<input
				type="text"
				id="new-analysis-ds-search"
				aria-label="Search datasources"
				placeholder="Search datasources..."
				class={css({
					width: 'full',
					fontSize: 'sm',
					color: 'fg.primary',
					backgroundColor: 'transparent',
					borderWidth: '1',
					paddingLeft: '9',
					paddingRight: '3',
					paddingY: '2',
					_focusVisible: { outline: 'none', borderColor: 'border.accent' },
					_placeholder: { color: 'fg.muted' }
				})}
				onkeydown={handleSearchKeydown}
				bind:value={searchQuery}
			/>
		</div>
	{/if}

	<section aria-label="Datasources">
		{#if datasourcesQuery.isPending}
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					gap: '2',
					padding: '6',
					fontSize: 'sm',
					color: 'fg.tertiary'
				})}
			>
				<div class={spinner({ size: 'sm' })}></div>
				Loading datasources…
			</div>
		{:else if datasourcesQuery.isError}
			<Callout tone="error">{datasourcesQuery.error.message}</Callout>
		{:else if datasources.length === 0}
			<div class={css({ padding: '8', textAlign: 'center' })}>
				<p class={css({ margin: '0 0 3 0', fontSize: 'sm', color: 'fg.muted' })}>
					No datasources yet.
				</p>
				<a
					href={resolve('/datasources/new')}
					class={css({
						display: 'inline-flex',
						alignItems: 'center',
						gap: '1',
						fontSize: 'xs',
						fontWeight: 'medium',
						paddingX: '3',
						paddingY: '2',
						textDecoration: 'none',
						backgroundColor: 'accent.primary',
						color: 'fg.inverse',
						borderWidth: '1',
						borderColor: 'border.accent'
					})}
				>
					Add a datasource
				</a>
			</div>
		{:else if filteredDatasources.length === 0}
			<div class={css({ padding: '4', fontSize: 'sm', color: 'fg.muted' })}>
				No datasources match "{searchQuery.trim()}"
			</div>
		{:else}
			<ul class={css({ listStyle: 'none', margin: '0', padding: '0' })}>
				{#each filteredDatasources as datasource (datasource.id)}
					{@const isExpanded = expandedDatasourceId === datasource.id}
					<li class={css({ borderBottomWidth: '1', borderColor: 'border.primary' })}>
						<div
							class={css({
								display: 'flex',
								alignItems: 'center',
								gap: '3',
								width: 'full',
								paddingX: '2',
								paddingY: '2.5',
								textAlign: 'left',
								border: 'none',
								borderLeftWidth: '2',
								background: 'transparent',
								_hover: { backgroundColor: 'bg.hover' },
								...(isExpanded
									? { backgroundColor: 'bg.accent', borderLeftColor: 'border.accent' }
									: { borderLeftColor: 'transparent' })
							})}
						>
							<button
								type="button"
								data-ds-option={datasource.name}
								aria-expanded={isExpanded}
								class={css({
									display: 'flex',
									flex: '1',
									minWidth: '0',
									alignItems: 'center',
									textAlign: 'left',
									cursor: 'pointer',
									backgroundColor: 'transparent',
									borderWidth: '0',
									padding: '0'
								})}
								onclick={() => toggleExpanded(datasource.id)}
							>
								<span
									class={css({
										overflow: 'hidden',
										textOverflow: 'ellipsis',
										whiteSpace: 'nowrap',
										fontFamily: 'mono',
										fontSize: 'sm',
										color: isExpanded ? 'accent.primary' : 'fg.primary'
									})}
								>
									{datasource.name}
								</span>
							</button>
							<button
								type="button"
								class={button({ variant: 'primary', size: 'sm' })}
								onclick={() => void startAnalysis(datasource)}
							>
								Create analysis
							</button>
							<button
								type="button"
								class={css({
									display: 'flex',
									alignItems: 'center',
									justifyContent: 'center',
									cursor: 'pointer',
									backgroundColor: 'transparent',
									borderWidth: '0',
									padding: '1'
								})}
								aria-label={isExpanded ? 'Collapse' : 'Expand'}
								onclick={() => toggleExpanded(datasource.id)}
							>
								<ChevronDown
									size={14}
									class={css({
										flexShrink: '0',
										color: 'fg.faint',
										transitionProperty: 'transform',
										transitionDuration: '160ms',
										transform: isExpanded ? 'rotate(180deg)' : 'none'
									})}
								/>
							</button>
						</div>

						{#if isExpanded}
							<div
								class={css({
									margin: '0 2 3 2',
									borderWidth: '1',
									borderColor: 'border.primary',
									backgroundColor: 'bg.primary',
									padding: '3'
								})}
							>
								{#if creatingDatasource?.id === datasource.id}
									<div
										class={css({
											display: 'flex',
											alignItems: 'center',
											justifyContent: 'center',
											gap: '2',
											padding: '8',
											fontSize: 'sm',
											color: 'fg.tertiary'
										})}
									>
										<div class={spinner({ size: 'sm' })}></div>
										Opening<strong class={css({ color: 'fg.primary' })}>{datasource.name}</strong>…
									</div>
								{:else}
									<div
										class={css({
											height: 'panel',
											width: '100%',
											overflow: 'hidden',
											borderWidth: '1',
											borderColor: 'border.secondary',
											borderRadius: 'sm'
										})}
									>
										<DatasourcePreview
											datasourceId={datasource.id}
											{datasource}
											datasourceConfig={datasource.config}
										/>
									</div>
								{/if}
							</div>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
	</section>
</main>
