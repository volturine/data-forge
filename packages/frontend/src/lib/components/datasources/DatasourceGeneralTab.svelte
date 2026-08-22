<script lang="ts" module>
	export const FRESHNESS_THRESHOLD_OPTIONS: { label: string; minutes: number | null }[] = [
		{ label: 'Default (24 hours)', minutes: null },
		{ label: '1 hour', minutes: 60 },
		{ label: '6 hours', minutes: 360 },
		{ label: '12 hours', minutes: 720 },
		{ label: '24 hours', minutes: 1440 },
		{ label: '7 days', minutes: 10080 },
		{ label: '30 days', minutes: 43200 }
	];
</script>

<script lang="ts">
	import { resolve } from '$app/paths';
	import { GitBranch, Loader, RefreshCw, Save, Upload } from '@lucide/svelte';
	import type {
		DataSource,
		DatabaseDataSource,
		FileDataSource,
		IcebergDataSource,
		SchemaInfo
	} from '$lib/types/datasource';
	import {
		datasourceExternalSourceConfig,
		datasourceExternalSourceType,
		datasourceIsAnalysisOutput,
		datasourceIsDatabase,
		datasourceIsFile,
		datasourceIsIceberg
	} from '$lib/types/datasource';
	import FileTypeBadge from '$lib/components/common/FileTypeBadge.svelte';
	import FreshnessBadge from '$lib/components/common/FreshnessBadge.svelte';
	import RelativeTime from '$lib/components/common/RelativeTime.svelte';
	import { formatDateDisplay } from '$lib/utils/datetime';
	import { css, input, chip, emptyText } from '$lib/styles/panda';

	interface Props {
		datasourceId: string;
		ds: DataSource;
		schema: SchemaInfo | null | undefined;
		name?: string;
		description?: string;
		freshnessThreshold?: number | null;
		customFreshnessThreshold?: string;
		isCustomFreshnessThreshold?: boolean;
		savePending: boolean;
		hasChanges: boolean;
		isRefreshing: boolean;
		refreshActionLabel: string;
		refreshBusyLabel: string;
		onDirty: () => void;
		onIngest: () => Promise<void> | void;
		onSave: () => Promise<void> | void;
	}

	let {
		datasourceId,
		ds,
		schema,
		name = $bindable(''),
		description = $bindable(''),
		freshnessThreshold = $bindable(null),
		customFreshnessThreshold = $bindable(''),
		isCustomFreshnessThreshold = $bindable(false),
		savePending,
		hasChanges,
		isRefreshing,
		refreshActionLabel,
		refreshBusyLabel,
		onDirty,
		onIngest,
		onSave
	}: Props = $props();

	function isFile(value: DataSource): value is FileDataSource {
		return datasourceIsFile(value);
	}

	function isDatabase(value: DataSource): value is DatabaseDataSource {
		return datasourceIsDatabase(value);
	}

	function isIceberg(value: DataSource): value is IcebergDataSource {
		return datasourceIsIceberg(value);
	}

	const isOutputDatasource = $derived(datasourceIsAnalysisOutput(ds));

	function getExternalSource(value: DataSource) {
		return datasourceExternalSourceConfig(value);
	}

	function getExternalSourceType(value: DataSource) {
		return datasourceExternalSourceType(value);
	}

	function handleThresholdChange(value: string) {
		if (value === 'custom') {
			isCustomFreshnessThreshold = true;
			customFreshnessThreshold = freshnessThreshold == null ? '' : String(freshnessThreshold);
			return;
		}
		if (value === '') {
			freshnessThreshold = null;
			isCustomFreshnessThreshold = false;
			onDirty();
			return;
		}
		const option = FRESHNESS_THRESHOLD_OPTIONS.find((opt) => opt.minutes === Number(value));
		if (!option) return;
		freshnessThreshold = option.minutes;
		isCustomFreshnessThreshold = false;
		onDirty();
	}

	function handleCustomThresholdChange(value: string) {
		customFreshnessThreshold = value;
		const minutes = Number(value);
		if (!Number.isInteger(minutes) || minutes <= 0) return;
		freshnessThreshold = minutes;
		onDirty();
	}
</script>

<div class={css({ display: 'flex', flexDirection: 'column', gap: '4' })}>
	<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
		<label
			for="datasource-name-{datasourceId}"
			class={css({
				display: 'block',
				fontSize: 'xs',
				fontWeight: 'medium',
				color: 'fg.secondary',
				textTransform: 'none',
				letterSpacing: 'normal',
				marginBottom: '1.5'
			})}>Name</label
		>
		<input
			id="datasource-name-{datasourceId}"
			type="text"
			value={name}
			oninput={(e) => {
				name = e.currentTarget.value;
				onDirty();
			}}
			placeholder="Data source name"
			class={input()}
		/>
	</div>

	<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
		<label
			for="datasource-description-{datasourceId}"
			class={css({
				display: 'block',
				fontSize: 'xs',
				fontWeight: 'medium',
				color: 'fg.secondary',
				textTransform: 'none',
				letterSpacing: 'normal',
				marginBottom: '1.5'
			})}>Description</label
		>
		<textarea
			id="datasource-description-{datasourceId}"
			value={description}
			oninput={(e) => {
				description = e.currentTarget.value;
				onDirty();
			}}
			placeholder="Add context about what this dataset represents, when to use it, and any caveats."
			rows="5"
			maxlength="4000"
			class={input({ variant: 'textarea' })}
		></textarea>
		{#if description.trim().length === 0}
			<p class={emptyText({ size: 'inline' })}>No description added yet.</p>
		{/if}
	</div>

	<div class={css({ paddingTop: '4' })}>
		<h3
			class={css({
				margin: '0',
				marginBottom: '3',
				fontSize: 'xs',
				fontWeight: 'semibold',
				color: 'fg.secondary'
			})}
		>
			Source Information
		</h3>
		<div class={css({ display: 'flex', flexDirection: 'column', gap: '3', fontSize: 'xs' })}>
			<div class={css({ display: 'flex', alignItems: 'center', gap: '4' })}>
				<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
					<span
						class={css({
							textTransform: 'uppercase',
							letterSpacing: 'wide',
							color: 'fg.muted'
						})}>Type</span
					>
					{#if isFile(ds)}
						{@const config = (ds as FileDataSource).config}
						<FileTypeBadge path={config.file_path} size="sm" />
					{:else}
						<FileTypeBadge sourceType={ds.source_type} size="sm" />
					{/if}
				</div>
				{#if ds.is_hidden}
					<div class={css({ display: 'flex', alignItems: 'center', gap: '1.5' })}>
						<span class={chip({ tone: 'warning' })}> Hidden </span>
					</div>
				{/if}
			</div>

			<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
				<span
					class={css({
						textTransform: 'uppercase',
						letterSpacing: 'wide',
						color: 'fg.muted'
					})}>Source</span
				>
				{#if isOutputDatasource}
					<span
						class={css({
							display: 'inline-flex',
							alignItems: 'center',
							gap: '1',
							color: 'accent.primary'
						})}
					>
						<GitBranch size={12} />
						<span class={css({ fontWeight: 'medium' })}>Analysis</span>
					</span>
					{#if ds.created_by_analysis_id}
						<a
							href={resolve(`/analysis/${ds.created_by_analysis_id}` as '/')}
							class={css({
								color: 'accent.primary',
								_hover: { textDecoration: 'underline' },
								fontFamily: 'mono',
								fontSize: '2xs'
							})}
						>
							Open Analysis
						</a>
					{/if}
				{:else}
					<span
						class={css({
							display: 'inline-flex',
							alignItems: 'center',
							gap: '1',
							color: 'fg.secondary'
						})}
					>
						<Upload size={12} />
						<span class={css({ fontWeight: 'medium' })}>Imported</span>
					</span>
				{/if}
			</div>

			<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
				<span
					class={css({
						textTransform: 'uppercase',
						letterSpacing: 'wide',
						color: 'fg.muted'
					})}>Datasource ID</span
				>
				<span
					class={css({
						wordBreak: 'break-all',
						color: 'fg.secondary',
						fontFamily: 'mono'
					})}>{ds.id}</span
				>
			</div>

			{#if isFile(ds)}
				{@const config = (ds as FileDataSource).config}
				<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
					<span
						class={css({
							textTransform: 'uppercase',
							letterSpacing: 'wide',
							color: 'fg.muted'
						})}>Location</span
					>
					<span
						class={css({
							wordBreak: 'break-all',
							color: 'fg.secondary',
							fontFamily: 'mono'
						})}>{config.file_path}</span
					>
				</div>
			{/if}

			{#if isDatabase(ds)}
				{@const config = ds.config}
				{#if config.connection_string}
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
						<span
							class={css({
								textTransform: 'uppercase',
								letterSpacing: 'wide',
								color: 'fg.muted'
							})}>Location</span
						>
						<span
							class={css({
								wordBreak: 'break-all',
								color: 'fg.secondary',
								fontFamily: 'mono'
							})}>{config.connection_string}</span
						>
					</div>
				{/if}
			{/if}

			{#if isIceberg(ds)}
				{@const config = (ds as IcebergDataSource).config}
				<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
					<span
						class={css({
							textTransform: 'uppercase',
							letterSpacing: 'wide',
							color: 'fg.muted'
						})}>Location</span
					>
					<span
						class={css({
							wordBreak: 'break-all',
							color: 'fg.secondary',
							fontFamily: 'mono'
						})}>{config.metadata_path}</span
					>
				</div>
				{#if getExternalSource(ds)}
					{@const externalSource = getExternalSource(ds)}
					{@const externalSourceType = getExternalSourceType(ds)}
					<div
						class={css({
							paddingTop: '2',
							marginTop: '1',
							display: 'flex',
							flexDirection: 'column',
							gap: '2'
						})}
					>
						<span
							class={css({
								fontSize: '2xs',
								textTransform: 'uppercase',
								letterSpacing: 'wider',
								color: 'fg.muted',
								fontWeight: 'semibold'
							})}>Original Source</span
						>
						<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
							<span
								class={css({
									textTransform: 'uppercase',
									letterSpacing: 'wide',
									color: 'fg.muted'
								})}>Type</span
							>
							<FileTypeBadge
								sourceType={externalSourceType ?? undefined}
								path={typeof externalSource?.file_path === 'string'
									? externalSource.file_path
									: undefined}
								size="sm"
							/>
						</div>
						{#if typeof externalSource?.file_path === 'string'}
							<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
								<span
									class={css({
										textTransform: 'uppercase',
										letterSpacing: 'wide',
										color: 'fg.muted'
									})}>File</span
								>
								<span
									class={css({
										wordBreak: 'break-all',
										color: 'fg.secondary',
										fontFamily: 'mono'
									})}>{externalSource.file_path}</span
								>
							</div>
						{/if}
						{#if typeof externalSource?.connection_string === 'string'}
							<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
								<span
									class={css({
										textTransform: 'uppercase',
										letterSpacing: 'wide',
										color: 'fg.muted'
									})}>Connection</span
								>
								<span
									class={css({
										wordBreak: 'break-all',
										color: 'fg.secondary',
										fontFamily: 'mono'
									})}>{externalSource.connection_string}</span
								>
							</div>
						{/if}
						{#if typeof externalSource?.query === 'string'}
							<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
								<span
									class={css({
										textTransform: 'uppercase',
										letterSpacing: 'wide',
										color: 'fg.muted'
									})}>Query</span
								>
								<span
									class={css({
										wordBreak: 'break-all',
										color: 'fg.secondary',
										fontFamily: 'mono'
									})}>{externalSource.query}</span
								>
							</div>
						{/if}
					</div>
				{/if}
			{/if}

			<div class={css({ display: 'flex', alignItems: 'center', gap: '4' })}>
				<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
					<span
						class={css({
							textTransform: 'uppercase',
							letterSpacing: 'wide',
							color: 'fg.muted'
						})}>Created</span
					>
					<span class={css({ fontWeight: 'medium' })}>{formatDateDisplay(ds.created_at)}</span>
				</div>
				{#if schema}
					<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
						<span
							class={css({
								textTransform: 'uppercase',
								letterSpacing: 'wide',
								color: 'fg.muted'
							})}>Rows</span
						>
						<span data-testid="datasource-row-count" class={css({ fontWeight: 'medium' })}
							>{schema.row_count?.toLocaleString() ?? 'Unknown'}</span
						>
					</div>
					<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
						<span
							class={css({
								textTransform: 'uppercase',
								letterSpacing: 'wide',
								color: 'fg.muted'
							})}>Columns</span
						>
						<span class={css({ fontWeight: 'medium' })}>{schema.columns.length}</span>
					</div>
				{/if}
			</div>

			<div class={css({ display: 'flex', alignItems: 'center', gap: '4' })}>
				<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
					<span
						class={css({
							textTransform: 'uppercase',
							letterSpacing: 'wide',
							color: 'fg.muted'
						})}>Last updated</span
					>
					<FreshnessBadge
						lastDataUpdate={ds.last_data_update}
						thresholdMinutes={ds.freshness_threshold_minutes ?? null}
					/>
					{#if ds.last_data_update}
						<span class={css({ fontWeight: 'medium' })}>
							<RelativeTime timestamp={ds.last_data_update} />
						</span>
					{:else}
						<span class={css({ fontWeight: 'medium', color: 'fg.muted' })}>Never</span>
					{/if}
				</div>
			</div>

			<div class={css({ display: 'flex', alignItems: 'center', gap: '4' })}>
				<label
					for="freshness-threshold-{datasourceId}"
					class={css({
						textTransform: 'uppercase',
						letterSpacing: 'wide',
						color: 'fg.muted',
						margin: '0'
					})}>Freshness threshold</label
				>
				<select
					id="freshness-threshold-{datasourceId}"
					value={isCustomFreshnessThreshold ? 'custom' : (freshnessThreshold ?? '')}
					onchange={(e) => handleThresholdChange(e.currentTarget.value)}
					class={input()}
					disabled={savePending}
				>
					{#each FRESHNESS_THRESHOLD_OPTIONS as option (option.minutes)}
						<option value={option.minutes ?? ''}>{option.label}</option>
					{/each}
					<option value="custom">Custom</option>
				</select>
				{#if isCustomFreshnessThreshold}
					<input
						type="number"
						min="1"
						step="1"
						aria-label="Custom freshness threshold in minutes"
						value={customFreshnessThreshold}
						oninput={(e) => handleCustomThresholdChange(e.currentTarget.value)}
						class={input()}
						disabled={savePending}
					/>
				{/if}
			</div>
		</div>
	</div>

	<div
		class={css({
			display: 'flex',
			alignItems: 'center',
			paddingTop: '4',
			justifyContent: 'space-between',
			gap: '3'
		})}
	>
		<button
			class={css({
				borderWidth: '1',
				backgroundColor: 'transparent',
				color: 'fg.primary',
				'&:hover:not(:disabled)': { backgroundColor: 'bg.hover', color: 'fg.secondary' },
				display: 'flex',
				alignItems: 'center',
				gap: '2'
			})}
			onclick={onIngest}
			disabled={isRefreshing || savePending}
		>
			{#if isRefreshing}
				<Loader size={16} class={css({ animation: 'spin 1s linear infinite' })} />
				{refreshBusyLabel}
			{:else}
				<RefreshCw size={16} />
				{refreshActionLabel}
			{/if}
		</button>
		{#if hasChanges}
			<button
				class={css({
					borderWidth: '1',
					backgroundColor: 'accent.primary',
					color: 'fg.inverse',
					'&:hover:not(:disabled)': { opacity: '0.9' },
					display: 'flex',
					alignItems: 'center',
					gap: '2'
				})}
				onclick={onSave}
				disabled={savePending}
			>
				{#if savePending}
					<Loader size={16} class={css({ animation: 'spin 1s linear infinite' })} />
					Saving...
				{:else}
					<Save size={16} />
					Save Changes
				{/if}
			</button>
		{/if}
	</div>
</div>
