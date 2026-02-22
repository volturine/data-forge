<script lang="ts">
	import {
		createHealthCheck,
		deleteHealthCheck,
		listHealthChecks,
		listHealthCheckResults,
		updateHealthCheck,
		type HealthCheck,
		type HealthCheckCreate,
		type HealthCheckResult
	} from '$lib/api/healthcheck';
	import { listDatasources } from '$lib/api/datasource';
	import type { DataSource } from '$lib/types/datasource';
	import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
	import {
		Loader,
		Trash2,
		Check,
		X,
		AlertTriangle,
		HeartPulse,
		Plus,
		ChevronDown,
		Database,
		Search,
		Power,
		PowerOff
	} from 'lucide-svelte';
	import { SvelteMap } from 'svelte/reactivity';

	interface Props {
		datasourceId?: string;
		compact?: boolean;
		searchQuery?: string;
	}

	type HealthCheckItem = HealthCheck & { critical: boolean };

	let { datasourceId, compact = false, searchQuery }: Props = $props();
	const queryClient = useQueryClient();

	const datasourcesQuery = createQuery(() => ({
		queryKey: ['datasources-lookup', 'include-hidden'],
		queryFn: async () => {
			const result = await listDatasources(true);
			if (result.isErr()) return [] as DataSource[];
			return result.value;
		},
		staleTime: 60_000
	}));

	const datasourceMap = $derived.by(() => {
		const map = new SvelteMap<string, DataSource>();
		for (const ds of datasourcesQuery.data ?? []) {
			map.set(ds.id, ds);
		}
		return map;
	});

	const allDatasources = $derived(datasourcesQuery.data ?? []);

	function resolveDatasource(id: string): string {
		const ds = datasourceMap.get(id);
		if (ds) return ds.name;
		return `${id.slice(0, 8)}...`;
	}

	const listQuery = createQuery(() => ({
		queryKey: ['healthchecks', datasourceId ?? 'all', datasourcesQuery.data?.length ?? 0],
		queryFn: async (): Promise<HealthCheckItem[]> => {
			if (datasourceId) {
				const result = await listHealthChecks(datasourceId);
				if (result.isErr()) throw new Error(result.error.message);
				return result.value.map((check) => ({
					...check,
					critical: !!(check as { critical?: boolean }).critical
				}));
			}
			const sources = datasourcesQuery.data ?? [];
			if (sources.length === 0) return [];
			const all = await Promise.all(
				sources.map(async (ds) => {
					const result = await listHealthChecks(ds.id);
					if (result.isErr()) return [];
					return result.value;
				})
			);
			return all.flat().map((check) => ({
				...check,
				critical: !!(check as { critical?: boolean }).critical
			}));
		},
		enabled: !!datasourceId || datasourcesQuery.isSuccess
	}));

	const resultsQuery = createQuery(() => ({
		queryKey: ['healthcheck-results', datasourceId ?? 'all', datasourcesQuery.data?.length ?? 0],
		queryFn: async () => {
			if (datasourceId) {
				const result = await listHealthCheckResults(datasourceId, 50);
				if (result.isErr()) throw new Error(result.error.message);
				return result.value;
			}
			const sources = datasourcesQuery.data ?? [];
			if (sources.length === 0) return [];
			const all = await Promise.all(
				sources.map(async (ds) => {
					const result = await listHealthCheckResults(ds.id, 20);
					if (result.isErr()) return [];
					return result.value;
				})
			);
			return all.flat();
		},
		enabled: !!datasourceId || datasourcesQuery.isSuccess
	}));

	const latestResults = $derived.by(() => {
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
		mutationFn: async (payload: HealthCheckCreate) => {
			const result = await createHealthCheck(payload);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['healthchecks'] });
			queryClient.invalidateQueries({ queryKey: ['healthcheck-results'] });
			creating = false;
			resetForm();
			if (!datasourceId) targetDatasourceId = '';
		}
	}));

	const updateMutation = createMutation(() => ({
		mutationFn: async (payload: { id: string; update: Record<string, unknown> }) => {
			const result = await updateHealthCheck(payload.id, payload.update);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['healthchecks'] });
			queryClient.invalidateQueries({ queryKey: ['healthcheck-results'] });
		}
	}));

	const deleteMutation = createMutation(() => ({
		mutationFn: async (id: string) => {
			const result = await deleteHealthCheck(id);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['healthchecks'] });
			queryClient.invalidateQueries({ queryKey: ['healthcheck-results'] });
		}
	}));

	const checkTypes = [
		{ value: 'row_count', label: 'Row Count' },
		{ value: 'column_count', label: 'Column Count' },
		{ value: 'null_percentage', label: 'Null Percentage (All Columns)' },
		{ value: 'duplicate_percentage', label: 'Duplicate Percentage' },
		{ value: 'column_null', label: 'Null Percentage (Column)' },
		{ value: 'column_unique', label: 'Unique Values' },
		{ value: 'column_range', label: 'Value Range' }
	];

	const checks = $derived(listQuery.data ?? []);
	const colCount = $derived.by(() => {
		let count = 7;
		if (!datasourceId) count += 1;
		return count;
	});

	let creating = $state(false);
	let search = $state('');
	let name = $state('');
	let checkType = $state('row_count');
	let config = $state<Record<string, unknown>>({});
	let critical = $state(false);
	let duplicateColumns = $state('');
	let targetDatasourceId = $state('');
	let expandedId = $state<string | null>(null);
	const effectiveSearch = $derived(searchQuery ?? search);
	const effectiveDatasourceId = $derived(datasourceId ?? targetDatasourceId);
	const targetChecks = $derived.by(() => {
		const id = effectiveDatasourceId;
		if (!id) return [] as HealthCheckItem[];
		return checks.filter((check) => check.datasource_id === id);
	});
	const rowCountExists = $derived(targetChecks.some((check) => check.check_type === 'row_count'));
	const hasSearch = $derived(effectiveSearch.trim().length > 0);
	const visibleChecks = $derived.by(() => {
		let result = checks;
		const q = effectiveSearch.trim().toLowerCase();
		if (!q) return result;
		return result.filter((check) => {
			const dsName = (datasourceMap.get(check.datasource_id)?.name ?? '').toLowerCase();
			return (
				check.name.toLowerCase().includes(q) ||
				check.id.toLowerCase().includes(q) ||
				check.datasource_id.toLowerCase().includes(q) ||
				dsName.includes(q) ||
				check.check_type.toLowerCase().includes(q)
			);
		});
	});

	function toggleExpand(id: string): void {
		expandedId = expandedId === id ? null : id;
	}

	function formatConfig(cfg: Record<string, unknown>): string {
		const entries = Object.entries(cfg);
		if (entries.length === 0) return 'Default';
		return entries
			.map(([key, value]) => {
				const label = key.replace(/_/g, ' ');
				if (Array.isArray(value)) return `${label}: ${value.join(', ')}`;
				return `${label}: ${value}`;
			})
			.join(' · ');
	}

	function resetForm(): void {
		name = '';
		checkType = 'row_count';
		config = {};
		critical = false;
		duplicateColumns = '';
	}

	function updateConfig(key: string, value: unknown): void {
		config = { ...config, [key]: value };
	}

	function updateDuplicateColumns(value: string): void {
		duplicateColumns = value;
		const items = value
			.split(',')
			.map((item) => item.trim())
			.filter((item) => item.length > 0);
		updateConfig('columns', items);
	}

	function getTypeLabel(value: string): string {
		const match = checkTypes.find((type) => type.value === value);
		if (match) return match.label;
		return value;
	}

	function addHealthCheck(): void {
		const targetId = effectiveDatasourceId;
		if (!targetId) return;
		if (checkType === 'row_count' && rowCountExists) return;
		const payload = {
			datasource_id: targetId,
			name,
			check_type: checkType,
			config,
			enabled: true,
			critical
		};
		createCheckMutation.mutate(payload);
	}

	function toggleEnabled(check: HealthCheckItem): void {
		updateMutation.mutate({
			id: check.id,
			update: { enabled: !check.enabled }
		});
	}
</script>

{#snippet createForm()}
	<div class="mb-4 border border-tertiary bg-bg-secondary p-3 shadow-sm transition-opacity">
		<div class="mb-3 flex items-center justify-between border-b border-tertiary pb-2">
			<span class="text-xs font-semibold text-fg-primary">New Health Check</span>
			<button
				class="text-fg-tertiary hover:text-fg-primary"
				onclick={() => {
					creating = false;
					resetForm();
				}}
			>
				<X size={14} />
			</button>
		</div>

		{#if !datasourceId}
			<div class="mb-3 flex flex-col gap-1">
				<label for="hc-target" class="text-[10px] font-medium text-fg-secondary uppercase"
					>Datasource</label
				>
				<select
					id="hc-target"
					class="w-full appearance-none border border-tertiary bg-bg-primary px-2 py-1.5 text-xs text-fg-primary focus:border-info focus:outline-none"
					bind:value={targetDatasourceId}
				>
					<option value="">Select datasource...</option>
					{#each allDatasources as ds (ds.id)}
						<option value={ds.id}>{ds.name}</option>
					{/each}
				</select>
			</div>
		{/if}

		<div
			class="gap-3"
			class:flex={compact}
			class:flex-col={compact}
			class:grid={!compact}
			class:grid-cols-2={!compact}
		>
			<!-- Name Input -->
			<div class="flex flex-col gap-1">
				<label for="hc-name" class="text-[10px] font-medium text-fg-secondary uppercase">Name</label
				>
				<input
					id="hc-name"
					type="text"
					class="border border-tertiary bg-bg-primary px-2 py-1.5 text-xs text-fg-primary placeholder:text-fg-muted focus:border-info focus:outline-none"
					bind:value={name}
					placeholder="e.g. Row count guard"
				/>
			</div>

			<!-- Type Select -->
			<div class="flex flex-col gap-1">
				<label for="hc-type" class="text-[10px] font-medium text-fg-secondary uppercase">Type</label
				>
				<div class="relative">
					<select
						id="hc-type"
						class="w-full appearance-none border border-tertiary bg-bg-primary px-2 py-1.5 text-xs text-fg-primary focus:border-info focus:outline-none"
						bind:value={checkType}
						onchange={() => {
							config = {};
							duplicateColumns = '';
						}}
					>
						{#each checkTypes as type (type.value)}
							<option value={type.value} disabled={rowCountExists && type.value === 'row_count'}>
								{type.label}
							</option>
						{/each}
					</select>
					<ChevronDown
						size={12}
						class="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-fg-tertiary"
					/>
				</div>
				{#if rowCountExists && checkType === 'row_count'}
					<p class="mt-0.5 text-[10px] text-error-fg">Row count check already exists.</p>
				{/if}
			</div>

			<!-- Config Fields based on Type -->
			{#if checkType === 'row_count'}
				<div
					class="col-span-2 grid grid-cols-2 gap-3"
					class:flex={compact}
					class:flex-col={compact}
				>
					<div class="flex flex-col gap-1">
						<label for="hc-min-rows" class="text-[10px] font-medium text-fg-secondary uppercase"
							>Min Rows</label
						>
						<input
							id="hc-min-rows"
							type="number"
							class="border border-tertiary bg-bg-primary px-2 py-1.5 text-xs text-fg-primary focus:border-info focus:outline-none"
							oninput={(e) => updateConfig('min_rows', parseInt(e.currentTarget.value) || 0)}
						/>
					</div>
					<div class="flex flex-col gap-1">
						<label for="hc-max-rows" class="text-[10px] font-medium text-fg-secondary uppercase"
							>Max Rows</label
						>
						<input
							id="hc-max-rows"
							type="number"
							class="border border-tertiary bg-bg-primary px-2 py-1.5 text-xs text-fg-primary focus:border-info focus:outline-none"
							oninput={(e) => updateConfig('max_rows', parseInt(e.currentTarget.value) || 0)}
						/>
					</div>
				</div>
			{:else if checkType === 'column_count'}
				<div
					class="col-span-2 grid grid-cols-2 gap-3"
					class:flex={compact}
					class:flex-col={compact}
				>
					<div class="flex flex-col gap-1">
						<label for="hc-min-cols" class="text-[10px] font-medium text-fg-secondary uppercase"
							>Min Columns</label
						>
						<input
							id="hc-min-cols"
							type="number"
							class="border border-tertiary bg-bg-primary px-2 py-1.5 text-xs text-fg-primary focus:border-info focus:outline-none"
							oninput={(e) => updateConfig('min_columns', parseInt(e.currentTarget.value) || 0)}
						/>
					</div>
					<div class="flex flex-col gap-1">
						<label for="hc-max-cols" class="text-[10px] font-medium text-fg-secondary uppercase"
							>Max Columns</label
						>
						<input
							id="hc-max-cols"
							type="number"
							class="border border-tertiary bg-bg-primary px-2 py-1.5 text-xs text-fg-primary focus:border-info focus:outline-none"
							oninput={(e) => updateConfig('max_columns', parseInt(e.currentTarget.value) || 0)}
						/>
					</div>
				</div>
			{:else if checkType === 'null_percentage'}
				<div class="col-span-2 flex flex-col gap-1">
					<label for="hc-null-threshold" class="text-[10px] font-medium text-fg-secondary uppercase"
						>Threshold (%)</label
					>
					<input
						id="hc-null-threshold"
						type="number"
						class="border border-tertiary bg-bg-primary px-2 py-1.5 text-xs text-fg-primary focus:border-info focus:outline-none"
						oninput={(e) => updateConfig('threshold', parseFloat(e.currentTarget.value) || 0)}
					/>
				</div>
			{:else if checkType === 'duplicate_percentage'}
				<div
					class="col-span-2 grid grid-cols-2 gap-3"
					class:flex={compact}
					class:flex-col={compact}
				>
					<div class="flex flex-col gap-1">
						<label
							for="hc-dup-threshold"
							class="text-[10px] font-medium text-fg-secondary uppercase">Threshold (%)</label
						>
						<input
							id="hc-dup-threshold"
							type="number"
							class="border border-tertiary bg-bg-primary px-2 py-1.5 text-xs text-fg-primary focus:border-info focus:outline-none"
							oninput={(e) => updateConfig('threshold', parseFloat(e.currentTarget.value) || 0)}
						/>
					</div>
					<div class="flex flex-col gap-1">
						<label for="hc-dup-cols" class="text-[10px] font-medium text-fg-secondary uppercase"
							>Columns (optional, comma separated)</label
						>
						<input
							id="hc-dup-cols"
							type="text"
							class="border border-tertiary bg-bg-primary px-2 py-1.5 text-xs text-fg-primary placeholder:text-fg-muted focus:border-info focus:outline-none"
							value={duplicateColumns}
							placeholder="col_a, col_b"
							oninput={(e) => updateDuplicateColumns(e.currentTarget.value)}
						/>
					</div>
				</div>
			{:else if checkType === 'column_null'}
				<div
					class="col-span-2 grid grid-cols-2 gap-3"
					class:flex={compact}
					class:flex-col={compact}
				>
					<div class="flex flex-col gap-1">
						<label for="hc-column" class="text-[10px] font-medium text-fg-secondary uppercase"
							>Column Name</label
						>
						<input
							id="hc-column"
							type="text"
							class="border border-tertiary bg-bg-primary px-2 py-1.5 text-xs text-fg-primary focus:border-info focus:outline-none"
							oninput={(e) => updateConfig('column', e.currentTarget.value)}
						/>
					</div>
					<div class="flex flex-col gap-1">
						<label for="hc-threshold" class="text-[10px] font-medium text-fg-secondary uppercase"
							>Threshold (%)</label
						>
						<input
							id="hc-threshold"
							type="number"
							class="border border-tertiary bg-bg-primary px-2 py-1.5 text-xs text-fg-primary focus:border-info focus:outline-none"
							oninput={(e) => updateConfig('threshold', parseFloat(e.currentTarget.value) || 0)}
						/>
					</div>
				</div>
			{:else if checkType === 'column_unique'}
				<div
					class="col-span-2 grid grid-cols-2 gap-3"
					class:flex={compact}
					class:flex-col={compact}
				>
					<div class="flex flex-col gap-1">
						<label
							for="hc-unique-column"
							class="text-[10px] font-medium text-fg-secondary uppercase">Column Name</label
						>
						<input
							id="hc-unique-column"
							type="text"
							class="border border-tertiary bg-bg-primary px-2 py-1.5 text-xs text-fg-primary focus:border-info focus:outline-none"
							oninput={(e) => updateConfig('column', e.currentTarget.value)}
						/>
					</div>
					<div class="flex flex-col gap-1">
						<label for="hc-expected" class="text-[10px] font-medium text-fg-secondary uppercase"
							>Expected Unique Count</label
						>
						<input
							id="hc-expected"
							type="number"
							class="border border-tertiary bg-bg-primary px-2 py-1.5 text-xs text-fg-primary focus:border-info focus:outline-none"
							oninput={(e) => updateConfig('expected_unique', parseInt(e.currentTarget.value) || 0)}
						/>
					</div>
				</div>
			{:else if checkType === 'column_range'}
				<div
					class="col-span-2 grid grid-cols-3 gap-3"
					class:flex={compact}
					class:flex-col={compact}
				>
					<div class="flex flex-col gap-1">
						<label for="hc-range-column" class="text-[10px] font-medium text-fg-secondary uppercase"
							>Column Name</label
						>
						<input
							id="hc-range-column"
							type="text"
							class="border border-tertiary bg-bg-primary px-2 py-1.5 text-xs text-fg-primary focus:border-info focus:outline-none"
							oninput={(e) => updateConfig('column', e.currentTarget.value)}
						/>
					</div>
					<div class="flex flex-col gap-1">
						<label for="hc-min" class="text-[10px] font-medium text-fg-secondary uppercase"
							>Min Value</label
						>
						<input
							id="hc-min"
							type="number"
							class="border border-tertiary bg-bg-primary px-2 py-1.5 text-xs text-fg-primary focus:border-info focus:outline-none"
							oninput={(e) => updateConfig('min', parseFloat(e.currentTarget.value) || 0)}
						/>
					</div>
					<div class="flex flex-col gap-1">
						<label for="hc-max" class="text-[10px] font-medium text-fg-secondary uppercase"
							>Max Value</label
						>
						<input
							id="hc-max"
							type="number"
							class="border border-tertiary bg-bg-primary px-2 py-1.5 text-xs text-fg-primary focus:border-info focus:outline-none"
							oninput={(e) => updateConfig('max', parseFloat(e.currentTarget.value) || 0)}
						/>
					</div>
				</div>
			{/if}
		</div>

		<div class="mt-4 flex items-center justify-between border-t border-tertiary pt-3">
			<label class="flex items-center gap-2 text-xs text-fg-secondary cursor-pointer select-none">
				<input
					type="checkbox"
					class="border-tertiary text-accent-primary focus:ring-0"
					checked={critical}
					onchange={(e) => (critical = e.currentTarget.checked)}
				/>
				<span class="font-medium">Critical Check (fails pipeline)</span>
			</label>

			<div class="flex items-center gap-2">
				<button
					class="border border-tertiary bg-transparent px-3 py-1.5 text-xs text-fg-tertiary hover:bg-bg-tertiary transition-colors"
					onclick={() => {
						creating = false;
						resetForm();
					}}
				>
					Cancel
				</button>
				<button
					class="bg-accent-primary px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-accent-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
					disabled={!name ||
						!effectiveDatasourceId ||
						createCheckMutation.isPending ||
						(checkType === 'row_count' && rowCountExists)}
					onclick={addHealthCheck}
				>
					{#if createCheckMutation.isPending}
						<div class="flex items-center gap-1">
							<Loader size={12} class="animate-spin" />
							<span>Saving...</span>
						</div>
					{:else}
						Save Check
					{/if}
				</button>
			</div>
		</div>
	</div>
{/snippet}

<div class="flex flex-col h-full w-full">
	<!-- Header Section -->
	{#if !compact}
		<header class="mb-6 border-b border-tertiary pb-5">
			<div class="flex items-center justify-between">
				<div>
					<h1 class="m-0 mb-2 text-2xl">Health Checks</h1>
					<p class="m-0 text-fg-tertiary">Monitor data quality with automated validation rules</p>
				</div>
				{#if !creating}
					<button
						class="inline-flex items-center gap-1.5 border border-tertiary bg-accent-bg px-3 py-1.5 text-sm text-accent-primary hover:bg-accent-bg/80"
						onclick={() => (creating = true)}
					>
						<Plus size={14} />
						New Check
					</button>
				{/if}
			</div>
			<div class="mt-4 flex flex-wrap items-center gap-3">
				{#if searchQuery === undefined}
					<div class="relative min-w-60 max-w-100 flex-1">
						<Search size={14} class="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-muted" />
						<input
							type="text"
							placeholder="Search by check, datasource, or ID..."
							class="w-full border border-tertiary bg-transparent px-3 py-1.5 pl-8 text-sm"
							bind:value={search}
						/>
					</div>
				{/if}
			</div>
		</header>
	{:else}
		<div class="mb-2 flex items-center justify-between">
			<div class="flex items-center gap-2">
				<HeartPulse size={14} class="text-fg-muted" />
				<span class="text-xs font-semibold uppercase tracking-wide text-fg-muted">
					Health Checks
					{#if checks.length > 0}
						<span class="text-fg-tertiary">({checks.length})</span>
					{/if}
				</span>
			</div>
			{#if !creating}
				<button
					class="inline-flex items-center gap-1 border border-tertiary bg-accent-bg px-2 py-1 text-[10px] font-medium text-accent-primary hover:bg-accent-bg/80 transition-colors"
					onclick={() => (creating = true)}
				>
					<Plus size={12} />
					Add
				</button>
			{/if}
		</div>
	{/if}

	{#if !compact && creating}
		{#if !datasourceId && !targetDatasourceId}
			<div class="mb-4 border border-info bg-info-bg/50 p-2 text-xs text-fg-secondary">
				Select a datasource to add a health check.
			</div>
		{/if}
		{@render createForm()}
	{/if}

	<!-- Checks List -->
	{#if listQuery.isLoading}
		<div class="flex items-center justify-center py-8 text-fg-tertiary">
			<Loader size={20} class="animate-spin" />
		</div>
	{:else if listQuery.isError}
		<div class="border border-error-border bg-error-bg/10 p-4 text-center text-sm text-error-fg">
			Failed to load health checks.
		</div>
	{:else if checks.length === 0 && !creating}
		<div
			class="flex flex-col items-center justify-center border border-dashed border-tertiary bg-bg-secondary/50 py-8 text-center"
			class:py-4={compact}
		>
			<HeartPulse class="mb-2 text-fg-muted" size={compact ? 16 : 24} />
			<p class="text-xs text-fg-muted">No health checks configured.</p>
			{#if !compact}
				<p class="mt-1 text-[10px] text-fg-tertiary max-w-xs">
					Add checks to validate row counts, null values, uniqueness, and data quality.
				</p>
			{/if}
		</div>
	{:else if visibleChecks.length === 0 && hasSearch}
		<div class="border border-dashed border-tertiary px-6 py-8 text-center">
			<p class="text-sm text-fg-tertiary">No health checks match your search.</p>
		</div>
	{:else if visibleChecks.length > 0}
		{#if !compact}
			<div class="overflow-x-auto border border-tertiary">
				<table class="w-full border-collapse text-xs">
					<thead>
						<tr class="bg-bg-tertiary">
							<th class="w-6 border-b border-tertiary px-2 py-1.5 text-left font-medium"></th>
							<th class="w-8 border-b border-tertiary px-2 py-1.5 text-left font-medium">Status</th>
							<th class="border-b border-tertiary px-2 py-1.5 text-left font-medium">Name</th>
							{#if !datasourceId}
								<th class="border-b border-tertiary px-2 py-1.5 text-left font-medium"
									>Datasource</th
								>
							{/if}
							<th class="border-b border-tertiary px-2 py-1.5 text-left font-medium">Type</th>
							<th class="w-24 border-b border-tertiary px-2 py-1.5 text-left font-medium"
								>Critical</th
							>
							<th class="w-24 border-b border-tertiary px-2 py-1.5 text-left font-medium"
								>Enabled</th
							>
							<th class="w-16 border-b border-tertiary px-2 py-1.5 text-left font-medium"></th>
						</tr>
					</thead>
					<tbody>
						{#each visibleChecks as check (check.id)}
							{@const latest = latestResults.get(check.id)}
							<tr
								class="cursor-pointer hover:bg-bg-hover"
								class:bg-bg-secondary={expandedId === check.id}
								onclick={() => toggleExpand(check.id)}
							>
								<td class="border-b border-tertiary px-2 py-1.5">
									<ChevronDown
										size={12}
										class="transition-transform {expandedId === check.id ? '' : '-rotate-90'}"
									/>
								</td>
								<td class="border-b border-tertiary px-2 py-1.5">
									{#if latest}
										{#if latest.passed}
											<div class="flex h-5 w-5 items-center justify-center bg-success-bg/20">
												<Check size={12} class="text-success-fg" />
											</div>
										{:else}
											<div class="flex h-5 w-5 items-center justify-center bg-error-bg/20">
												<X size={12} class="text-error-fg" />
											</div>
										{/if}
									{:else}
										<div class="flex h-5 w-5 items-center justify-center bg-bg-tertiary">
											<AlertTriangle size={12} class="text-fg-muted" />
										</div>
									{/if}
								</td>
								<td class="border-b border-tertiary px-2 py-1.5">
									<span class="font-medium text-fg-primary">{check.name}</span>
								</td>
								{#if !datasourceId}
									<td class="border-b border-tertiary px-2 py-1.5">
										<span
											class="inline-flex items-center gap-1 text-fg-secondary"
											title={check.datasource_id}
										>
											<Database size={10} class="text-fg-muted" />
											{resolveDatasource(check.datasource_id)}
										</span>
									</td>
								{/if}
								<td class="border-b border-tertiary px-2 py-1.5 text-fg-secondary">
									{getTypeLabel(check.check_type)}
								</td>
								<td class="border-b border-tertiary px-2 py-1.5">
									{#if check.critical}
										<span
											class="inline-flex border border-info bg-accent-bg px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-accent-primary"
										>
											Critical
										</span>
									{:else}
										<span class="text-[10px] text-fg-tertiary">-</span>
									{/if}
								</td>
								<td class="border-b border-tertiary px-2 py-1.5">
									<button
										class="inline-flex items-center gap-1 border-none bg-transparent p-0 text-xs"
										onclick={(e) => {
											e.stopPropagation();
											toggleEnabled(check);
										}}
										title={check.enabled ? 'Click to disable' : 'Click to enable'}
									>
										{#if check.enabled}
											<Power size={12} class="text-success-fg" />
											<span class="text-success-fg">On</span>
										{:else}
											<PowerOff size={12} class="text-fg-muted" />
											<span class="text-fg-muted">Off</span>
										{/if}
									</button>
								</td>
								<td class="border-b border-tertiary px-2 py-1.5">
									<button
										class="inline-flex items-center justify-center border-none bg-transparent p-0.5 text-fg-muted hover:text-error-fg"
										onclick={(e) => {
											e.stopPropagation();
											deleteMutation.mutate(check.id);
										}}
										disabled={deleteMutation.isPending}
										title="Delete check"
									>
										<Trash2 size={12} />
									</button>
								</td>
							</tr>
							{#if expandedId === check.id}
								<tr>
									<td colspan={colCount} class="border-b border-tertiary bg-bg-primary p-0">
										<div class="flex flex-wrap items-start gap-4 px-4 py-3">
											<div class="flex flex-col gap-1">
												<span class="text-[10px] text-fg-muted">Check Type</span>
												<span class="text-[10px] text-fg-secondary">
													{getTypeLabel(check.check_type)}
												</span>
											</div>
											{#if !datasourceId}
												<div class="flex flex-col gap-1">
													<span class="text-[10px] text-fg-muted">Datasource</span>
													<span class="text-[10px] text-fg-secondary">
														{resolveDatasource(check.datasource_id)}
													</span>
												</div>
											{/if}
											<div class="flex flex-col gap-1">
												<span class="text-[10px] text-fg-muted">Configuration</span>
												<span class="text-[10px] text-fg-secondary">
													{formatConfig(check.config)}
												</span>
											</div>
											{#if latest}
												<div class="flex flex-col gap-1">
													<span class="text-[10px] text-fg-muted">Latest Result</span>
													<div class="flex items-center gap-1">
														{#if latest.passed}
															<Check size={10} class="text-success-fg" />
															<span class="text-[10px] text-success-fg">Passed</span>
														{:else}
															<X size={10} class="text-error-fg" />
															<span class="text-[10px] text-error-fg">Failed</span>
														{/if}
													</div>
													{#if latest.message}
														<span class="text-[10px] text-fg-muted">{latest.message}</span>
													{/if}
												</div>
											{/if}
											<div class="flex flex-col gap-1">
												<span class="text-[10px] text-fg-muted">Created</span>
												<span class="text-[10px] text-fg-secondary">
													{new Date(check.created_at).toLocaleString()}
												</span>
											</div>
											<div class="flex flex-col gap-1">
												<span class="text-[10px] text-fg-muted">Check ID</span>
												<span class="font-mono text-[10px] text-fg-secondary">
													{check.id}
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
		{:else}
			<!-- Compact List View -->
			<div class="flex flex-col gap-1">
				{#each visibleChecks as check (check.id)}
					{@const latest = latestResults.get(check.id)}
					<div
						class="group flex items-center gap-2 border border-tertiary bg-bg-primary p-2 hover:border-fg-tertiary transition-colors"
					>
						<!-- Status -->
						<div class="shrink-0">
							{#if latest}
								{#if latest.passed}
									<div class="h-2 w-2 bg-success-fg"></div>
								{:else}
									<div class="h-2 w-2 bg-error-fg"></div>
								{/if}
							{:else}
								<div class="h-2 w-2 bg-fg-muted"></div>
							{/if}
						</div>

						<!-- Name & Details -->
						<div class="flex min-w-0 flex-1 items-center gap-2">
							<span class="truncate text-xs font-medium text-fg-primary" title={check.name}>
								{check.name}
							</span>
							{#if !datasourceId}
								<span class="truncate text-[10px] text-fg-tertiary" title={check.datasource_id}>
									{resolveDatasource(check.datasource_id)}
								</span>
							{/if}
							{#if check.critical}
								<span
									class="shrink-0 bg-accent-bg px-1 py-0.5 text-[9px] font-bold uppercase leading-none text-accent-primary"
								>
									Crit
								</span>
							{/if}
						</div>

						<!-- Actions -->
						<div
							class="flex items-center gap-2 opacity-60 group-hover:opacity-100 transition-opacity"
						>
							<label class="flex cursor-pointer items-center">
								<input
									type="checkbox"
									class="h-3 w-3 border-tertiary text-success-fg focus:ring-0"
									checked={check.enabled}
									onchange={() => toggleEnabled(check)}
								/>
							</label>
							<button
								class="text-fg-tertiary hover:text-error-fg"
								onclick={() => deleteMutation.mutate(check.id)}
								disabled={deleteMutation.isPending}
								title="Delete check"
							>
								<Trash2 size={12} />
							</button>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	{/if}

	{#if compact && creating}
		{@render createForm()}
	{/if}
</div>
