<script lang="ts">
	import {
		createHealthCheck,
		deleteHealthCheck,
		listHealthChecks,
		listHealthCheckResults,
		updateHealthCheck,
		type HealthCheck,
		type HealthCheckResult
	} from '$lib/api/healthcheck';
	import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { Loader, Trash2, Check, X, AlertTriangle } from 'lucide-svelte';
	import { SvelteMap } from 'svelte/reactivity';

	interface Props {
		datasourceId: string;
	}

	let { datasourceId }: Props = $props();
	const queryClient = useQueryClient();

	const listQuery = createQuery(() => ({
		queryKey: ['healthchecks', datasourceId],
		queryFn: async () => {
			const result = await listHealthChecks(datasourceId);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		enabled: !!datasourceId
	}));

	const resultsQuery = createQuery(() => ({
		queryKey: ['healthcheck-results', datasourceId],
		queryFn: async () => {
			const result = await listHealthCheckResults(datasourceId, 50);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		enabled: !!datasourceId
	}));

	const latestResults: SvelteMap<string, HealthCheckResult> = $derived.by(() => {
		const results = resultsQuery.data ?? [];
		const map = new SvelteMap<string, HealthCheckResult>();
		for (const r of results) {
			if (!map.has(r.healthcheck_id)) {
				map.set(r.healthcheck_id, r);
			}
		}
		return map;
	});

	const createCheckMutation = createMutation(() => ({
		mutationFn: async (payload: Omit<HealthCheck, 'id' | 'created_at'>) => {
			const result = await createHealthCheck(payload);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['healthchecks', datasourceId] });
			queryClient.invalidateQueries({ queryKey: ['healthcheck-results', datasourceId] });
		}
	}));

	const updateMutation = createMutation(() => ({
		mutationFn: async (payload: { id: string; update: Record<string, unknown> }) => {
			const result = await updateHealthCheck(payload.id, payload.update);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['healthchecks', datasourceId] });
			queryClient.invalidateQueries({ queryKey: ['healthcheck-results', datasourceId] });
		}
	}));

	const deleteMutation = createMutation(() => ({
		mutationFn: async (id: string) => {
			const result = await deleteHealthCheck(id);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['healthchecks', datasourceId] });
			queryClient.invalidateQueries({ queryKey: ['healthcheck-results', datasourceId] });
		}
	}));

	const checkTypes = [
		{ value: 'row_count', label: 'Row Count' },
		{ value: 'column_null', label: 'Null Percentage' },
		{ value: 'column_unique', label: 'Unique Values' },
		{ value: 'column_range', label: 'Value Range' }
	];

	let name = $state('');
	let checkType = $state('row_count');
	let config = $state<Record<string, unknown>>({});

	function resetForm(): void {
		name = '';
		checkType = 'row_count';
		config = {};
	}

	function updateConfig(key: string, value: unknown): void {
		config = { ...config, [key]: value };
	}

	function addHealthCheck(): void {
		createCheckMutation.mutate({
			datasource_id: datasourceId,
			name,
			check_type: checkType,
			config,
			enabled: true
		});
		resetForm();
	}
</script>

<div class="flex flex-col gap-4">
	<div class="rounded-sm border border-tertiary bg-bg-primary p-4">
		<h4 class="m-0 mb-3 text-sm font-semibold text-fg-primary">Add Health Check</h4>
		<div class="grid grid-cols-2 gap-3">
			<div class="flex flex-col gap-1">
				<label for="hc-name" class="text-xs font-medium text-fg-secondary">Name</label>
				<input id="hc-name" type="text" bind:value={name} placeholder="Row count guard" />
			</div>
			<div class="flex flex-col gap-1">
				<label for="hc-type" class="text-xs font-medium text-fg-secondary">Type</label>
				<select id="hc-type" bind:value={checkType}>
					{#each checkTypes as type (type.value)}
						<option value={type.value}>{type.label}</option>
					{/each}
				</select>
			</div>
		</div>

		{#if checkType === 'row_count'}
			<div class="mt-3 grid grid-cols-2 gap-3">
				<div class="flex flex-col gap-1">
					<label for="hc-min-rows" class="text-xs font-medium text-fg-secondary">Min Rows</label>
					<input
						id="hc-min-rows"
						type="number"
						oninput={(e) => updateConfig('min_rows', parseInt(e.currentTarget.value) || 0)}
					/>
				</div>
				<div class="flex flex-col gap-1">
					<label for="hc-max-rows" class="text-xs font-medium text-fg-secondary">Max Rows</label>
					<input
						id="hc-max-rows"
						type="number"
						oninput={(e) => updateConfig('max_rows', parseInt(e.currentTarget.value) || 0)}
					/>
				</div>
			</div>
		{:else if checkType === 'column_null'}
			<div class="mt-3 grid grid-cols-2 gap-3">
				<div class="flex flex-col gap-1">
					<label for="hc-column" class="text-xs font-medium text-fg-secondary">Column</label>
					<input
						id="hc-column"
						type="text"
						oninput={(e) => updateConfig('column', e.currentTarget.value)}
					/>
				</div>
				<div class="flex flex-col gap-1">
					<label for="hc-threshold" class="text-xs font-medium text-fg-secondary"
						>Threshold (%)</label
					>
					<input
						id="hc-threshold"
						type="number"
						oninput={(e) => updateConfig('threshold', parseFloat(e.currentTarget.value) || 0)}
					/>
				</div>
			</div>
		{:else if checkType === 'column_unique'}
			<div class="mt-3 grid grid-cols-2 gap-3">
				<div class="flex flex-col gap-1">
					<label for="hc-unique-column" class="text-xs font-medium text-fg-secondary">Column</label>
					<input
						id="hc-unique-column"
						type="text"
						oninput={(e) => updateConfig('column', e.currentTarget.value)}
					/>
				</div>
				<div class="flex flex-col gap-1">
					<label for="hc-expected" class="text-xs font-medium text-fg-secondary"
						>Expected Unique</label
					>
					<input
						id="hc-expected"
						type="number"
						oninput={(e) => updateConfig('expected_unique', parseInt(e.currentTarget.value) || 0)}
					/>
				</div>
			</div>
		{:else if checkType === 'column_range'}
			<div class="mt-3 grid grid-cols-2 gap-3">
				<div class="flex flex-col gap-1">
					<label for="hc-range-column" class="text-xs font-medium text-fg-secondary">Column</label>
					<input
						id="hc-range-column"
						type="text"
						oninput={(e) => updateConfig('column', e.currentTarget.value)}
					/>
				</div>
				<div class="flex flex-col gap-1">
					<label for="hc-min" class="text-xs font-medium text-fg-secondary">Min Value</label>
					<input
						id="hc-min"
						type="number"
						oninput={(e) => updateConfig('min', parseFloat(e.currentTarget.value) || 0)}
					/>
				</div>
				<div class="flex flex-col gap-1">
					<label for="hc-max" class="text-xs font-medium text-fg-secondary">Max Value</label>
					<input
						id="hc-max"
						type="number"
						oninput={(e) => updateConfig('max', parseFloat(e.currentTarget.value) || 0)}
					/>
				</div>
			</div>
		{/if}

		<button
			class="btn btn-primary mt-4"
			disabled={!name || createCheckMutation.isPending}
			onclick={addHealthCheck}
		>
			{#if createCheckMutation.isPending}
				<Loader size={14} class="spin" />
				Adding...
			{:else}
				Add Check
			{/if}
		</button>
	</div>

	<div class="rounded-sm border border-tertiary bg-bg-primary p-4">
		<h4 class="m-0 mb-3 text-sm font-semibold text-fg-primary">Existing Checks</h4>
		{#if listQuery.isLoading}
			<div class="flex items-center gap-2 text-fg-tertiary">
				<Loader size={16} class="spin" />
				Loading...
			</div>
		{:else if listQuery.isError}
			<p class="text-sm text-error-fg">Failed to load health checks.</p>
		{:else if listQuery.data && listQuery.data.length === 0}
			<p class="text-sm text-fg-tertiary">No health checks configured.</p>
		{:else}
			<div class="flex flex-col gap-2">
				{#each listQuery.data ?? [] as check (check.id)}
					{@const latest = latestResults.get(check.id)}
					<div class="flex items-center justify-between border border-tertiary bg-bg-secondary p-3">
						<div class="flex items-center gap-2">
							{#if latest}
								{#if latest.passed}
									<Check size={16} class="text-success-fg shrink-0" />
								{:else}
									<X size={16} class="text-error-fg shrink-0" />
								{/if}
							{:else}
								<AlertTriangle size={16} class="text-fg-muted shrink-0" />
							{/if}
							<div class="flex flex-col gap-1">
								<span class="text-sm font-semibold text-fg-primary">{check.name}</span>
								<span class="text-xs text-fg-tertiary">{check.check_type}</span>
								{#if latest}
									<span class="text-xs text-fg-muted">{latest.message}</span>
								{/if}
							</div>
						</div>
						<div class="flex items-center gap-2">
							<label class="flex items-center gap-2 text-xs text-fg-secondary">
								<input
									type="checkbox"
									checked={check.enabled}
									onchange={(e) =>
										updateMutation.mutate({
											id: check.id,
											update: { enabled: e.currentTarget.checked }
										})}
								/>
								<span>Enabled</span>
							</label>
							<button
								class="btn-ghost btn-sm"
								onclick={() => deleteMutation.mutate(check.id)}
								disabled={deleteMutation.isPending}
							>
								<Trash2 size={14} />
							</button>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>
