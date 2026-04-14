<script lang="ts">
	import {
		createHealthCheck,
		deleteHealthCheck,
		listHealthChecks,
		listHealthCheckResults,
		updateHealthCheck,
		type CheckType,
		type HealthCheck,
		type HealthCheckConfig,
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
		TriangleAlert,
		HeartPulse,
		Plus,
		ChevronDown,
		Database,
		Search,
		Power,
		PowerOff
	} from 'lucide-svelte';
	import { SvelteMap } from 'svelte/reactivity';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import { css, cx, emptyText, input, label } from '$lib/styles/panda';

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
		queryKey: ['healthchecks', datasourceId ?? 'all'],
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
		queryKey: ['healthcheck-results', datasourceId ?? 'all'],
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
		onSuccess: (created) => {
			const listKey = ['healthchecks', datasourceId ?? 'all'];
			queryClient.setQueryData<HealthCheckItem[]>(listKey, (current) => {
				const next = current ?? [];
				return [...next, { ...created, critical: !!(created as { critical?: boolean }).critical }];
			});
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
		onMutate: async (payload) => {
			await queryClient.cancelQueries({ queryKey: ['healthchecks'] });
			const listKey = ['healthchecks', datasourceId ?? 'all'];
			const previous = queryClient.getQueryData<HealthCheckItem[]>(listKey);
			if (previous) {
				queryClient.setQueryData<HealthCheckItem[]>(
					listKey,
					previous.map((c) => (c.id === payload.id ? { ...c, ...payload.update } : c))
				);
			}
			return { previous, listKey };
		},
		onError: (_err, _payload, context) => {
			if (context?.previous) {
				queryClient.setQueryData(context.listKey, context.previous);
			}
		},
		onSettled: () => {
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
	let checkType = $state<CheckType>('row_count');
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

	function formatConfig(cfg: HealthCheckConfig): string {
		const entries = Object.entries(cfg as Record<string, unknown>);
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

	let deleteConfirmId = $state<string | null>(null);

	function handleDelete(id: string): void {
		deleteConfirmId = id;
	}

	function confirmDelete(): void {
		if (!deleteConfirmId) return;
		deleteMutation.mutate(deleteConfirmId);
		deleteConfirmId = null;
	}

	function cancelDelete(): void {
		deleteConfirmId = null;
	}
</script>

{#snippet createForm()}
	<div
		class={css({
			marginBottom: '4',
			borderWidth: '1',
			backgroundColor: 'bg.secondary',
			padding: '3',
			boxShadow: 'sm',
			transition: 'opacity 160ms'
		})}
	>
		<div
			class={css({
				marginBottom: '3',
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'space-between',
				borderBottomWidth: '1',
				paddingBottom: '2'
			})}
		>
			<span class={css({ fontSize: 'xs', fontWeight: 'semibold' })}>New Health Check</span>
			<button
				class={css({
					backgroundColor: 'bg.primary',
					color: 'fg.tertiary',
					_hover: { color: 'fg.primary' }
				})}
				onclick={() => {
					creating = false;
					resetForm();
				}}
			>
				<X size={14} />
			</button>
		</div>

		{#if !datasourceId}
			<div class={css({ marginBottom: '3', display: 'flex', flexDirection: 'column', gap: '1' })}>
				<label for="hc-target" class={label({ variant: 'compact' })}>Datasource</label>
				<select
					id="hc-target"
					class={cx(
						input(),
						css({
							appearance: 'none',
							paddingX: '2',
							paddingY: '1.5',
							fontSize: 'xs',
							_focus: { borderColor: 'border.accent' }
						})
					)}
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
			class={cx(
				css({ gap: '3' }),
				compact
					? css({ display: 'flex', flexDirection: 'column' })
					: css({ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' })
			)}
		>
			<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
				<label for="hc-name" class={label({ variant: 'compact' })}>Name</label>
				<input
					id="hc-name"
					type="text"
					class={cx(
						input(),
						css({
							paddingX: '2',
							paddingY: '1.5',
							fontSize: 'xs',
							_focus: { borderColor: 'border.accent' }
						})
					)}
					bind:value={name}
					placeholder="e.g. Row count guard"
				/>
			</div>

			<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
				<label for="hc-type" class={label({ variant: 'compact' })}>Type</label>
				<div class={css({ position: 'relative' })}>
					<select
						id="hc-type"
						class={cx(
							input(),
							css({
								appearance: 'none',
								paddingX: '2',
								paddingY: '1.5',
								fontSize: 'xs',
								_focus: { borderColor: 'border.accent' }
							})
						)}
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
						class={css({
							pointerEvents: 'none',
							position: 'absolute',
							right: '2',
							top: '50%',
							translate: '0 -50%',
							color: 'fg.tertiary'
						})}
					/>
				</div>
				{#if rowCountExists && checkType === 'row_count'}
					<p class={css({ marginTop: '0.5', fontSize: '2xs', color: 'fg.error' })}>
						Row count check already exists.
					</p>
				{/if}
			</div>

			{#if checkType === 'row_count'}
				<div
					class={cx(
						compact
							? css({ display: 'flex', flexDirection: 'column', gap: '3' })
							: css({
									gridColumn: 'span 2 / span 2',
									display: 'grid',
									gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
									gap: '3'
								})
					)}
				>
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
						<label for="hc-min-rows" class={label({ variant: 'compact' })}>Min Rows</label>
						<input
							id="hc-min-rows"
							type="number"
							class={cx(
								input(),
								css({
									paddingX: '2',
									paddingY: '1.5',
									fontSize: 'xs',
									_focus: { borderColor: 'border.accent' }
								})
							)}
							oninput={(e) => updateConfig('min_rows', parseInt(e.currentTarget.value) || 0)}
						/>
					</div>
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
						<label for="hc-max-rows" class={label({ variant: 'compact' })}>Max Rows</label>
						<input
							id="hc-max-rows"
							type="number"
							class={cx(
								input(),
								css({
									paddingX: '2',
									paddingY: '1.5',
									fontSize: 'xs',
									_focus: { borderColor: 'border.accent' }
								})
							)}
							oninput={(e) => updateConfig('max_rows', parseInt(e.currentTarget.value) || 0)}
						/>
					</div>
				</div>
			{:else if checkType === 'column_count'}
				<div
					class={cx(
						compact
							? css({ display: 'flex', flexDirection: 'column', gap: '3' })
							: css({
									gridColumn: 'span 2 / span 2',
									display: 'grid',
									gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
									gap: '3'
								})
					)}
				>
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
						<label for="hc-min-cols" class={label({ variant: 'compact' })}>Min Columns</label>
						<input
							id="hc-min-cols"
							type="number"
							class={cx(
								input(),
								css({
									paddingX: '2',
									paddingY: '1.5',
									fontSize: 'xs',
									_focus: { borderColor: 'border.accent' }
								})
							)}
							oninput={(e) => updateConfig('min_columns', parseInt(e.currentTarget.value) || 0)}
						/>
					</div>
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
						<label for="hc-max-cols" class={label({ variant: 'compact' })}>Max Columns</label>
						<input
							id="hc-max-cols"
							type="number"
							class={cx(
								input(),
								css({
									paddingX: '2',
									paddingY: '1.5',
									fontSize: 'xs',
									_focus: { borderColor: 'border.accent' }
								})
							)}
							oninput={(e) => updateConfig('max_columns', parseInt(e.currentTarget.value) || 0)}
						/>
					</div>
				</div>
			{:else if checkType === 'null_percentage'}
				<div
					class={css({
						gridColumn: 'span 2 / span 2',
						display: 'flex',
						flexDirection: 'column',
						gap: '1'
					})}
				>
					<label for="hc-null-threshold" class={label({ variant: 'compact' })}>Threshold (%)</label>
					<input
						id="hc-null-threshold"
						type="number"
						class={cx(
							input(),
							css({
								paddingX: '2',
								paddingY: '1.5',
								fontSize: 'xs',
								_focus: { borderColor: 'border.accent' }
							})
						)}
						oninput={(e) => updateConfig('threshold', parseFloat(e.currentTarget.value) || 0)}
					/>
				</div>
			{:else if checkType === 'duplicate_percentage'}
				<div
					class={cx(
						compact
							? css({ display: 'flex', flexDirection: 'column', gap: '3' })
							: css({
									gridColumn: 'span 2 / span 2',
									display: 'grid',
									gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
									gap: '3'
								})
					)}
				>
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
						<label for="hc-dup-threshold" class={label({ variant: 'compact' })}>Threshold (%)</label
						>
						<input
							id="hc-dup-threshold"
							type="number"
							class={cx(
								input(),
								css({
									paddingX: '2',
									paddingY: '1.5',
									fontSize: 'xs',
									_focus: { borderColor: 'border.accent' }
								})
							)}
							oninput={(e) => updateConfig('threshold', parseFloat(e.currentTarget.value) || 0)}
						/>
					</div>
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
						<label for="hc-dup-cols" class={label({ variant: 'compact' })}
							>Columns (optional, comma separated)</label
						>
						<input
							id="hc-dup-cols"
							type="text"
							class={cx(
								input(),
								css({
									paddingX: '2',
									paddingY: '1.5',
									fontSize: 'xs',
									_focus: { borderColor: 'border.accent' }
								})
							)}
							value={duplicateColumns}
							placeholder="col_a, col_b"
							oninput={(e) => updateDuplicateColumns(e.currentTarget.value)}
						/>
					</div>
				</div>
			{:else if checkType === 'column_null'}
				<div
					class={cx(
						compact
							? css({ display: 'flex', flexDirection: 'column', gap: '3' })
							: css({
									gridColumn: 'span 2 / span 2',
									display: 'grid',
									gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
									gap: '3'
								})
					)}
				>
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
						<label for="hc-column" class={label({ variant: 'compact' })}>Column Name</label>
						<input
							id="hc-column"
							type="text"
							class={cx(
								input(),
								css({
									paddingX: '2',
									paddingY: '1.5',
									fontSize: 'xs',
									_focus: { borderColor: 'border.accent' }
								})
							)}
							oninput={(e) => updateConfig('column', e.currentTarget.value)}
						/>
					</div>
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
						<label for="hc-threshold" class={label({ variant: 'compact' })}>Threshold (%)</label>
						<input
							id="hc-threshold"
							type="number"
							class={cx(
								input(),
								css({
									paddingX: '2',
									paddingY: '1.5',
									fontSize: 'xs',
									_focus: { borderColor: 'border.accent' }
								})
							)}
							oninput={(e) => updateConfig('threshold', parseFloat(e.currentTarget.value) || 0)}
						/>
					</div>
				</div>
			{:else if checkType === 'column_unique'}
				<div
					class={cx(
						compact
							? css({ display: 'flex', flexDirection: 'column', gap: '3' })
							: css({
									gridColumn: 'span 2 / span 2',
									display: 'grid',
									gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
									gap: '3'
								})
					)}
				>
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
						<label for="hc-unique-column" class={label({ variant: 'compact' })}>Column Name</label>
						<input
							id="hc-unique-column"
							type="text"
							class={cx(
								input(),
								css({
									paddingX: '2',
									paddingY: '1.5',
									fontSize: 'xs',
									_focus: { borderColor: 'border.accent' }
								})
							)}
							oninput={(e) => updateConfig('column', e.currentTarget.value)}
						/>
					</div>
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
						<label for="hc-expected" class={label({ variant: 'compact' })}
							>Expected Unique Count</label
						>
						<input
							id="hc-expected"
							type="number"
							class={cx(
								input(),
								css({
									paddingX: '2',
									paddingY: '1.5',
									fontSize: 'xs',
									_focus: { borderColor: 'border.accent' }
								})
							)}
							oninput={(e) => updateConfig('expected_unique', parseInt(e.currentTarget.value) || 0)}
						/>
					</div>
				</div>
			{:else if checkType === 'column_range'}
				<div
					class={cx(
						compact
							? css({ display: 'flex', flexDirection: 'column', gap: '3' })
							: css({
									gridColumn: 'span 2 / span 2',
									display: 'grid',
									gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
									gap: '3'
								})
					)}
				>
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
						<label for="hc-range-column" class={label({ variant: 'compact' })}>Column Name</label>
						<input
							id="hc-range-column"
							type="text"
							class={cx(
								input(),
								css({
									paddingX: '2',
									paddingY: '1.5',
									fontSize: 'xs',
									_focus: { borderColor: 'border.accent' }
								})
							)}
							oninput={(e) => updateConfig('column', e.currentTarget.value)}
						/>
					</div>
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
						<label for="hc-min" class={label({ variant: 'compact' })}>Min Value</label>
						<input
							id="hc-min"
							type="number"
							class={cx(
								input(),
								css({
									paddingX: '2',
									paddingY: '1.5',
									fontSize: 'xs',
									_focus: { borderColor: 'border.accent' }
								})
							)}
							oninput={(e) => updateConfig('min', parseFloat(e.currentTarget.value) || 0)}
						/>
					</div>
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
						<label for="hc-max" class={label({ variant: 'compact' })}>Max Value</label>
						<input
							id="hc-max"
							type="number"
							class={cx(
								input(),
								css({
									paddingX: '2',
									paddingY: '1.5',
									fontSize: 'xs',
									_focus: { borderColor: 'border.accent' }
								})
							)}
							oninput={(e) => updateConfig('max', parseFloat(e.currentTarget.value) || 0)}
						/>
					</div>
				</div>
			{/if}
		</div>

		<div
			class={css({
				marginTop: '4',
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'space-between',
				borderTopWidth: '1',
				paddingTop: '3'
			})}
		>
			<label
				class={cx(
					label({ variant: 'checkbox' }),
					css({ gap: '2', fontSize: 'xs', userSelect: 'none' })
				)}
			>
				<input
					type="checkbox"
					class={css({ color: 'accent.primary' })}
					id="hc-critical"
					checked={critical}
					onchange={(e) => (critical = e.currentTarget.checked)}
				/>
				<span class={css({ fontWeight: 'medium' })}>Critical Check (fails pipeline)</span>
			</label>

			<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
				<button
					class={css({
						borderWidth: '1',
						backgroundColor: 'transparent',
						paddingX: '3',
						paddingY: '1.5',
						fontSize: 'xs',
						color: 'fg.tertiary',
						_hover: { backgroundColor: 'bg.tertiary' },
						transition: 'color 160ms, background-color 160ms'
					})}
					onclick={() => {
						creating = false;
						resetForm();
					}}
				>
					Cancel
				</button>
				<button
					class={css({
						backgroundColor: 'accent.primary',
						paddingX: '3',
						paddingY: '1.5',
						fontSize: 'xs',
						fontWeight: 'semibold',
						color: 'fg.inverse',
						boxShadow: 'sm',
						_hover: { backgroundColor: 'accent.primary/90' },
						transition: 'color 160ms, background-color 160ms',
						_disabled: { opacity: '0.5', cursor: 'not-allowed' }
					})}
					disabled={!name ||
						!effectiveDatasourceId ||
						createCheckMutation.isPending ||
						(checkType === 'row_count' && rowCountExists)}
					onclick={addHealthCheck}
				>
					{#if createCheckMutation.isPending}
						<div class={css({ display: 'flex', alignItems: 'center', gap: '1' })}>
							<Loader size={12} class={css({ animation: 'spin 1s linear infinite' })} />
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

<ConfirmDialog
	show={deleteConfirmId !== null}
	heading="Delete Health Check"
	message="This health check will be permanently deleted. This action cannot be undone."
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
					<h1 class={css({ margin: '0', marginBottom: '2', fontSize: '2xl' })}>Health Checks</h1>
					<p class={css({ margin: '0', color: 'fg.tertiary' })}>
						Monitor data quality with automated validation rules
					</p>
				</div>
				{#if !creating}
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
							_hover: { backgroundColor: 'bg.accent/80' }
						})}
						onclick={() => (creating = true)}
					>
						<Plus size={14} />
						New Check
					</button>
				{/if}
			</div>
			<div
				class={css({
					marginTop: '4',
					display: 'flex',
					flexWrap: 'wrap',
					alignItems: 'center',
					gap: '3'
				})}
			>
				{#if searchQuery === undefined}
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
								translate: '0 -50%',
								color: 'fg.muted'
							})}
						/>
						<input
							type="text"
							id="hc-search"
							aria-label="Search health checks"
							placeholder="Search by check, datasource, or ID..."
							class={input({ variant: 'search' })}
							bind:value={search}
						/>
					</div>
				{/if}
			</div>
		</header>
	{:else}
		<div
			class={css({
				marginBottom: '2',
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'space-between'
			})}
		>
			<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
				<HeartPulse size={14} class={css({ color: 'fg.muted' })} />
				<span
					class={css({
						fontSize: 'xs',
						fontWeight: 'semibold',
						textTransform: 'uppercase',
						letterSpacing: 'wide',
						color: 'fg.muted'
					})}
				>
					Health Checks
					{#if checks.length > 0}
						<span class={css({ color: 'fg.tertiary' })}>({checks.length})</span>
					{/if}
				</span>
			</div>
			{#if !creating}
				<button
					class={css({
						display: 'inline-flex',
						alignItems: 'center',
						gap: '1',
						borderWidth: '1',
						backgroundColor: 'bg.accent',
						paddingX: '2',
						paddingY: '1',
						fontSize: '2xs',
						fontWeight: 'medium',
						color: 'accent.primary',
						_hover: { backgroundColor: 'bg.accent/80' },
						transition: 'color 160ms, background-color 160ms'
					})}
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
			<div
				class={css({
					marginBottom: '4',
					borderWidth: '1',
					backgroundColor: 'color-mix(in srgb, {colors.bg.secondary} 50%, transparent)',
					padding: '2',
					fontSize: 'xs',
					color: 'fg.secondary'
				})}
			>
				Select a datasource to add a health check.
			</div>
		{/if}
		{@render createForm()}
	{/if}

	{#if listQuery.isLoading}
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'center',
				paddingY: '8',
				color: 'fg.tertiary'
			})}
		>
			<Loader size={20} class={css({ animation: 'spin 1s linear infinite' })} />
		</div>
	{:else if listQuery.isError}
		<div
			class={css({
				borderWidth: '1',
				borderColor: 'border.error',
				backgroundColor: 'color-mix(in srgb, {colors.bg.error} 10%, transparent)',
				padding: '4',
				textAlign: 'center',
				fontSize: 'sm',
				color: 'fg.error'
			})}
		>
			Failed to load health checks.
		</div>
	{:else if checks.length === 0 && !creating}
		<div
			class={cx(
				css({
					display: 'flex',
					flexDirection: 'column',
					alignItems: 'center',
					justifyContent: 'center',
					borderWidth: '1',
					borderStyle: 'dashed',
					backgroundColor: 'bg.secondary/50',
					paddingY: compact ? '4' : '8',
					textAlign: 'center'
				})
			)}
		>
			<HeartPulse class={css({ marginBottom: '2', color: 'fg.muted' })} size={compact ? 16 : 24} />
			<p class={emptyText({ size: 'compact' })}>No health checks configured.</p>
			{#if !compact}
				<p class={css({ marginTop: '1', fontSize: '2xs', color: 'fg.tertiary', maxWidth: 'xs' })}>
					Add checks to validate row counts, null values, uniqueness, and data quality.
				</p>
			{/if}
		</div>
	{:else if visibleChecks.length === 0 && hasSearch}
		<div
			class={css({
				borderWidth: '1',
				borderStyle: 'dashed',
				paddingX: '6',
				paddingY: '8',
				textAlign: 'center'
			})}
		>
			<p class={emptyText({ size: 'panel' })}>No health checks match your search.</p>
		</div>
	{:else if visibleChecks.length > 0}
		{#if !compact}
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
							<th
								class={css({
									width: 'rowLg',
									borderBottomWidth: '1',
									paddingX: '2',
									paddingY: '1.5',
									textAlign: 'left',
									fontWeight: 'medium'
								})}>Status</th
							>
							<th
								class={css({
									borderBottomWidth: '1',
									paddingX: '2',
									paddingY: '1.5',
									textAlign: 'left',
									fontWeight: 'medium'
								})}>Name</th
							>
							{#if !datasourceId}
								<th
									class={css({
										borderBottomWidth: '1',
										paddingX: '2',
										paddingY: '1.5',
										textAlign: 'left',
										fontWeight: 'medium'
									})}>Datasource</th
								>
							{/if}
							<th
								class={css({
									borderBottomWidth: '1',
									paddingX: '2',
									paddingY: '1.5',
									textAlign: 'left',
									fontWeight: 'medium'
								})}>Type</th
							>
							<th
								class={css({
									width: 'colNarrow',
									borderBottomWidth: '1',
									paddingX: '2',
									paddingY: '1.5',
									textAlign: 'left',
									fontWeight: 'medium'
								})}>Critical</th
							>
							<th
								class={css({
									width: 'colNarrow',
									borderBottomWidth: '1',
									paddingX: '2',
									paddingY: '1.5',
									textAlign: 'left',
									fontWeight: 'medium'
								})}>Enabled</th
							>
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
						{#each visibleChecks as check (check.id)}
							{@const latest = latestResults.get(check.id)}
							<tr
								data-healthcheck-row={check.id}
								data-healthcheck-name={check.name}
								data-datasource-id={check.datasource_id}
								class={cx(
									css({ cursor: 'pointer', _hover: { backgroundColor: 'bg.hover' } }),
									expandedId === check.id ? css({ backgroundColor: 'bg.secondary' }) : ''
								)}
								onclick={() => toggleExpand(check.id)}
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
										class={css({
											transition: 'transform 160ms',
											transform: expandedId === check.id ? 'rotate(0deg)' : 'rotate(-90deg)'
										})}
									/>
								</td>
								<td
									class={css({
										borderBottomWidth: '1',
										paddingX: '2',
										paddingY: '1.5'
									})}
								>
									{#if latest}
										{#if latest.passed}
											<div
												class={css({
													display: 'flex',
													height: 'iconMd',
													width: 'iconMd',
													alignItems: 'center',
													justifyContent: 'center',
													backgroundColor: 'bg.success/20'
												})}
											>
												<Check size={12} class={css({ color: 'fg.success' })} />
											</div>
										{:else}
											<div
												class={css({
													display: 'flex',
													height: 'iconMd',
													width: 'iconMd',
													alignItems: 'center',
													justifyContent: 'center',
													backgroundColor: 'bg.error/20'
												})}
											>
												<X size={12} class={css({ color: 'fg.error' })} />
											</div>
										{/if}
									{:else}
										<div
											class={css({
												display: 'flex',
												height: 'iconMd',
												width: 'iconMd',
												alignItems: 'center',
												justifyContent: 'center',
												backgroundColor: 'bg.tertiary'
											})}
										>
											<TriangleAlert size={12} class={css({ color: 'fg.muted' })} />
										</div>
									{/if}
								</td>
								<td
									class={css({
										borderBottomWidth: '1',
										paddingX: '2',
										paddingY: '1.5'
									})}
								>
									<span class={css({ fontWeight: 'medium' })}>{check.name}</span>
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
												alignItems: 'center',
												gap: '1',
												color: 'fg.secondary'
											})}
											title={check.datasource_id}
										>
											<Database size={10} class={css({ color: 'fg.muted' })} />
											{resolveDatasource(check.datasource_id)}
										</span>
									</td>
								{/if}
								<td
									class={css({
										borderBottomWidth: '1',
										paddingX: '2',
										paddingY: '1.5',
										color: 'fg.secondary'
									})}
								>
									{getTypeLabel(check.check_type)}
								</td>
								<td
									class={css({
										borderBottomWidth: '1',
										paddingX: '2',
										paddingY: '1.5'
									})}
								>
									{#if check.critical}
										<span
											class={css({
												display: 'inline-flex',
												borderWidth: '1',
												borderColor: 'border.accent',
												backgroundColor: 'bg.accent',
												paddingX: '1.5',
												paddingY: '0.5',
												fontSize: '2xs',
												fontWeight: 'bold',
												textTransform: 'uppercase',
												letterSpacing: 'wide',
												color: 'accent.primary'
											})}
										>
											Critical
										</span>
									{:else}
										<span class={css({ fontSize: '2xs', color: 'fg.tertiary' })}>-</span>
									{/if}
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
											borderWidth: '0',
											backgroundColor: 'transparent',
											padding: '0',
											fontSize: 'xs'
										})}
										onclick={(e) => {
											e.stopPropagation();
											toggleEnabled(check);
										}}
										title={check.enabled ? 'Click to disable' : 'Click to enable'}
									>
										{#if check.enabled}
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
										paddingY: '1.5'
									})}
								>
									<button
										class={css({
											display: 'inline-flex',
											alignItems: 'center',
											justifyContent: 'center',
											borderWidth: '0',
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
											handleDelete(check.id);
										}}
										disabled={deleteMutation.isPending}
										aria-label="Delete check"
									>
										<Trash2 size={12} />
									</button>
								</td>
							</tr>
							{#if expandedId === check.id}
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
												<span class={css({ fontSize: '2xs', color: 'fg.muted' })}>Check Type</span>
												<span class={css({ fontSize: '2xs', color: 'fg.secondary' })}>
													{getTypeLabel(check.check_type)}
												</span>
											</div>
											{#if !datasourceId}
												<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
													<span class={css({ fontSize: '2xs', color: 'fg.muted' })}>Datasource</span
													>
													<span class={css({ fontSize: '2xs', color: 'fg.secondary' })}>
														{resolveDatasource(check.datasource_id)}
													</span>
												</div>
											{/if}
											<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
												<span class={css({ fontSize: '2xs', color: 'fg.muted' })}
													>Configuration</span
												>
												<span class={css({ fontSize: '2xs', color: 'fg.secondary' })}>
													{formatConfig(check.config)}
												</span>
											</div>
											{#if latest}
												<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
													<span class={css({ fontSize: '2xs', color: 'fg.muted' })}
														>Latest Result</span
													>
													<div class={css({ display: 'flex', alignItems: 'center', gap: '1' })}>
														{#if latest.passed}
															<Check size={10} class={css({ color: 'fg.success' })} />
															<span class={css({ fontSize: '2xs', color: 'fg.success' })}
																>Passed</span
															>
														{:else}
															<X size={10} class={css({ color: 'fg.error' })} />
															<span class={css({ fontSize: '2xs', color: 'fg.error' })}>Failed</span
															>
														{/if}
													</div>
													{#if latest.message}
														<span class={css({ fontSize: '2xs', color: 'fg.muted' })}
															>{latest.message}</span
														>
													{/if}
												</div>
											{/if}
											<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
												<span class={css({ fontSize: '2xs', color: 'fg.muted' })}>Created</span>
												<span class={css({ fontSize: '2xs', color: 'fg.secondary' })}>
													{new Date(check.created_at).toLocaleString()}
												</span>
											</div>
											<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
												<span class={css({ fontSize: '2xs', color: 'fg.muted' })}>Check ID</span>
												<span
													class={css({
														fontFamily: 'mono',
														fontSize: '2xs',
														color: 'fg.secondary'
													})}
												>
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
			<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
				{#each visibleChecks as check (check.id)}
					{@const latest = latestResults.get(check.id)}
					<div
						class={css({
							display: 'flex',
							alignItems: 'center',
							gap: '2',
							borderWidth: '1',
							backgroundColor: 'bg.primary',
							padding: '2',
							_hover: { backgroundColor: 'bg.hover' },
							transition: 'color 160ms, background-color 160ms, border-color 160ms'
						})}
					>
						<div class={css({ flexShrink: '0' })}>
							{#if latest}
								{#if latest.passed}
									<div
										class={css({ height: 'dot', width: 'dot', backgroundColor: 'fg.success' })}
									></div>
								{:else}
									<div
										class={css({ height: 'dot', width: 'dot', backgroundColor: 'fg.error' })}
									></div>
								{/if}
							{:else}
								<div
									class={css({ height: 'dot', width: 'dot', backgroundColor: 'bg.indicator' })}
								></div>
							{/if}
						</div>

						<div
							class={css({
								display: 'flex',
								minWidth: '0',
								flex: '1',
								alignItems: 'center',
								gap: '2'
							})}
						>
							<span
								class={css({
									overflow: 'hidden',
									textOverflow: 'ellipsis',
									whiteSpace: 'nowrap',
									fontSize: 'xs',
									fontWeight: 'medium'
								})}
								title={check.name}
							>
								{check.name}
							</span>
							{#if !datasourceId}
								<span
									class={css({
										overflow: 'hidden',
										textOverflow: 'ellipsis',
										whiteSpace: 'nowrap',
										fontSize: '2xs',
										color: 'fg.tertiary'
									})}
									title={check.datasource_id}
								>
									{resolveDatasource(check.datasource_id)}
								</span>
							{/if}
							{#if check.critical}
								<span
									class={css({
										flexShrink: '0',
										backgroundColor: 'bg.accent',
										paddingX: '1',
										paddingY: '0.5',
										fontSize: '2xs',
										fontWeight: 'bold',
										textTransform: 'uppercase',
										lineHeight: 'none',
										color: 'accent.primary'
									})}
								>
									Crit
								</span>
							{/if}
						</div>

						<div
							class={css({
								display: 'flex',
								alignItems: 'center',
								gap: '2'
							})}
						>
							<label class={label({ variant: 'checkbox' })}>
								<input
									type="checkbox"
									class={css({
										height: 'iconTiny',
										width: 'iconTiny',
										color: 'fg.success'
									})}
									id="check-{check.id}-enabled"
									aria-label="Enable check"
									checked={check.enabled}
									onchange={() => toggleEnabled(check)}
								/>
							</label>
							<button
								class={css({
									backgroundColor: 'bg.primary',
									color: 'fg.tertiary',
									_hover: { color: 'fg.error' },
									_focusVisible: {
										color: 'fg.error',
										outline: '2px solid',
										outlineColor: 'accent.primary',
										outlineOffset: '1px'
									}
								})}
								onclick={() => handleDelete(check.id)}
								disabled={deleteMutation.isPending}
								aria-label="Delete check"
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
