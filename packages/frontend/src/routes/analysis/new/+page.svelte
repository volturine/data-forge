<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { createQuery } from '@tanstack/svelte-query';
	import { createAnalysis } from '$lib/api/analysis';
	import { listDatasources } from '$lib/api/datasource';
	import DatasourcePicker from '$lib/components/common/DatasourcePicker.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { button, css, spinner } from '$lib/styles/panda';
	import { configStore } from '$lib/stores/config.svelte';
	import { useNamespace } from '$lib/stores/namespace.svelte';
	import type { AnalysisTab } from '$lib/types/analysis';
	import type { DataSource } from '$lib/types/datasource';
	import { buildOutputConfig } from '$lib/utils/analysis-tab';
	import { uuid } from '$lib/utils/uuid';

	const ns = useNamespace();
	let selectedDatasourceId = $state('');
	let creating = $state(false);
	let error = $state('');

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
	const selectedDatasource = $derived(
		datasources.find((datasource) => datasource.id === selectedDatasourceId) ?? null
	);
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

	async function handleCreate(): Promise<void> {
		const datasource = selectedDatasource;
		if (!datasource || creating) return;

		creating = true;
		error = '';
		const branch = defaultBranch(datasource);
		const tabName = 'Source 1';
		const outputId = uuid();
		const tab: AnalysisTab = {
			id: uuid(),
			name: tabName,
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
			const result = await createAnalysis({
				name: `${datasource.name} Analysis`,
				description: null,
				tabs: [tab]
			});
			if (result.isErr()) {
				error = result.error.message;
				return;
			}
			await goto(resolve(`/analysis/${result.value.id}`));
		} catch (cause) {
			error = cause instanceof Error ? cause.message : 'Failed to open the new analysis';
		} finally {
			creating = false;
		}
	}
</script>

<main
	class={css({
		boxSizing: 'border-box',
		width: 'full',
		maxWidth: 'page',
		marginX: 'auto',
		paddingX: '6',
		paddingY: '8'
	})}
>
	<a
		href={resolve('/')}
		class={css({
			display: 'inline-flex',
			marginBottom: '5',
			color: 'fg.tertiary',
			fontSize: 'sm',
			textDecoration: 'none',
			_hover: { color: 'fg.primary' }
		})}
	>
		← Analyses
	</a>

	<header class={css({ marginBottom: '6' })}>
		<h1 class={css({ margin: '0', fontSize: '2xl', fontWeight: 'semibold' })}>New Analysis</h1>
		<p class={css({ marginTop: '2', marginBottom: '0', color: 'fg.tertiary', fontSize: 'sm' })}>
			Choose one datasource to start with. The analysis opens with an empty pipeline ready for you
			to build.
		</p>
	</header>

	{#if error}
		<div class={css({ marginBottom: '4' })}>
			<Callout tone="error">{error}</Callout>
		</div>
	{/if}

	<section
		class={css({
			maxWidth: 'panelLg',
			borderWidth: '1',
			backgroundColor: 'bg.primary',
			padding: '5'
		})}
		aria-labelledby="datasource-heading"
	>
		<h2
			id="datasource-heading"
			class={css({ marginTop: '0', marginBottom: '4', fontSize: 'lg', fontWeight: 'semibold' })}
		>
			Select a datasource
		</h2>

		{#if datasourcesQuery.isPending}
			<div class={css({ display: 'flex', alignItems: 'center', gap: '3', color: 'fg.tertiary' })}>
				<div class={spinner()}></div>
				Loading datasources…
			</div>
		{:else if datasourcesQuery.isError}
			<Callout tone="error">{datasourcesQuery.error.message}</Callout>
		{:else if datasources.length === 0}
			<p class={css({ margin: '0', color: 'fg.tertiary', fontSize: 'sm' })}>
				There are no datasources yet. <a href={resolve('/datasources/new')}>Create a datasource</a>
				first.
			</p>
		{:else}
			<DatasourcePicker
				{datasources}
				selected={selectedDatasourceId}
				mode="single"
				label="Available datasources"
				placeholder="Search datasources..."
				alwaysOpen
				showChips={false}
				showBulkActions={false}
				onSelect={(id) => (selectedDatasourceId = id)}
			/>
		{/if}

		{#if selectedDatasource}
			<p
				class={css({
					marginTop: '4',
					marginBottom: '0',
					borderLeftWidth: '2',
					borderColor: 'accent.primary',
					paddingLeft: '3',
					color: 'fg.tertiary',
					fontSize: 'sm'
				})}
			>
				Starting with <strong>{selectedDatasource.name}</strong>. You can add operations and
				configure its output in the editor.
			</p>
		{/if}
	</section>

	<footer
		class={css({
			maxWidth: 'panelLg',
			marginTop: '5',
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'space-between',
			gap: '4'
		})}
	>
		<a
			href={resolve('/')}
			class={css({
				borderWidth: '1',
				paddingX: '4',
				paddingY: '2',
				textDecoration: 'none',
				color: 'fg.primary',
				backgroundColor: 'bg.primary'
			})}
		>
			Cancel
		</a>
		<button
			type="button"
			class={button({ variant: 'primary' })}
			disabled={!selectedDatasource || creating}
			onclick={handleCreate}
		>
			{creating ? 'Creating…' : 'Create Analysis'}
		</button>
	</footer>
</main>
