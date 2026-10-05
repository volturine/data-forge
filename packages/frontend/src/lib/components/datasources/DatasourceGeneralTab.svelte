<script lang="ts">
	import { resolve } from '$app/paths';
	import { GitBranch, Loader, RefreshCw, Save, Upload } from '@lucide/svelte';
	import type { DataSource, IcebergDataSource, SchemaInfo } from '$lib/types/datasource';
	import {
		datasourceExternalSourceConfig,
		datasourceExternalSourceType,
		datasourceIsAnalysisOutput,
		datasourceIsIceberg,
		datasourceRowCount
	} from '$lib/types/datasource';
	import FileTypeBadge from '$lib/components/common/FileTypeBadge.svelte';
	import RelativeTime from '$lib/components/common/RelativeTime.svelte';
	import { formatDateDisplay } from '$lib/utils/datetime';
	import { css, input, chip } from '$lib/styles/panda';

	interface Props {
		datasourceId: string;
		ds: DataSource;
		schema: SchemaInfo | null | undefined;
		name?: string;
		description?: string;
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
		savePending,
		hasChanges,
		isRefreshing,
		refreshActionLabel,
		refreshBusyLabel,
		onDirty,
		onIngest,
		onSave
	}: Props = $props();

	function isIceberg(value: DataSource): value is IcebergDataSource {
		return datasourceIsIceberg(value);
	}

	const isOutputDatasource = $derived(datasourceIsAnalysisOutput(ds));
	const rowCount = $derived(schema?.row_count ?? datasourceRowCount(ds));

	function getExternalSource(value: DataSource) {
		return datasourceExternalSourceConfig(value);
	}

	function getExternalSourceType(value: DataSource) {
		return datasourceExternalSourceType(value);
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
			class={input({ variant: 'textarea' })}></textarea>
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
			{#if ds.is_hidden}
				<div class={css({ display: 'flex', alignItems: 'center', gap: '1.5' })}>
					<span class={chip({ tone: 'warning' })}> Hidden </span>
				</div>
			{/if}

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

			<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
				<span
					class={css({
						textTransform: 'uppercase',
						letterSpacing: 'wide',
						color: 'fg.muted'
					})}>Datasource ID</span
				>
				<span class={css({ fontFamily: 'mono', fontSize: '2xs' })}>{ds.id}</span>
			</div>

			{#if isIceberg(ds)}
				{@const externalSource = getExternalSource(ds)}
				{@const externalSourceType = getExternalSourceType(ds)}
				{#if externalSourceType || externalSource}
					<div
						class={css({
							display: 'flex',
							flexDirection: 'column',
							gap: '2',
							paddingY: '2',
							borderTopWidth: '1',
							borderBottomWidth: '1',
							borderColor: 'border.primary'
						})}
					>
						<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
							<span
								class={css({
									textTransform: 'uppercase',
									letterSpacing: 'wide',
									color: 'fg.muted'
								})}>Original source type</span
							>
							<span class={css({ fontWeight: 'medium', textTransform: 'uppercase' })}>
								{externalSourceType ?? 'unknown'}
							</span>
						</div>
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
										fontFamily: 'mono',
										fontSize: '2xs',
										overflow: 'hidden',
										textOverflow: 'ellipsis',
										whiteSpace: 'nowrap'
									})}>{externalSource.file_path}</span
								>
							</div>
						{/if}
						{#if typeof externalSource?.database === 'string'}
							<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
								<span
									class={css({
										textTransform: 'uppercase',
										letterSpacing: 'wide',
										color: 'fg.muted'
									})}>Database</span
								>
								<span class={css({ fontWeight: 'medium' })}>{externalSource.database}</span>
							</div>
						{/if}
						{#if typeof externalSource?.table_name === 'string'}
							<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
								<span
									class={css({
										textTransform: 'uppercase',
										letterSpacing: 'wide',
										color: 'fg.muted'
									})}>Table</span
								>
								<span class={css({ fontWeight: 'medium' })}>{externalSource.table_name}</span>
							</div>
						{/if}
					</div>
				{/if}
			{/if}

			{#if ds.created_at}
				<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
					<span
						class={css({
							textTransform: 'uppercase',
							letterSpacing: 'wide',
							color: 'fg.muted'
						})}>Created</span
					>
					<span class={css({ fontWeight: 'medium' })}>
						{formatDateDisplay(ds.created_at)}
					</span>
				</div>
			{/if}

			<div class={css({ display: 'flex', alignItems: 'center', gap: '4' })}>
				<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
					<span
						class={css({
							textTransform: 'uppercase',
							letterSpacing: 'wide',
							color: 'fg.muted'
						})}>Rows</span
					>
					<span data-testid="datasource-row-count" class={css({ fontWeight: 'medium' })}
						>{rowCount != null ? rowCount.toLocaleString() : '—'}</span
					>
				</div>
				{#if schema?.columns}
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
					{#if ds.last_data_update}
						<span class={css({ fontWeight: 'medium' })}>
							<RelativeTime timestamp={ds.last_data_update} />
						</span>
					{:else}
						<span class={css({ fontWeight: 'medium', color: 'fg.muted' })}>Never</span>
					{/if}
				</div>
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
