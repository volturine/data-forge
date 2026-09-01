<script lang="ts">
	import { CircleAlert, Loader, Pencil } from '@lucide/svelte';
	import type { ColumnSchema } from '$lib/types/datasource';
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { css, emptyText } from '$lib/styles/panda';

	interface Props {
		columns: ColumnSchema[];
		loading: boolean;
		refreshError: string | null;
		schemaChanged: boolean;
		schemaDiff: { added: string[]; removed: string[]; types: string[] } | null;
		descriptionPending: boolean;
		descriptionDraft?: string;
		descriptionError: string | null;
		editingColumn: string | null;
		isDescriptionExpanded: (name: string) => boolean;
		onSelectColumn: (name: string) => void;
		onToggleDescription: (name: string) => void;
		onStartEdit: (column: ColumnSchema) => void;
		onCancelEdit: () => void;
		onSaveDescription: (columnName: string) => Promise<void> | void;
	}

	let {
		columns,
		loading,
		refreshError,
		schemaChanged,
		schemaDiff,
		descriptionPending,
		descriptionDraft = $bindable(''),
		descriptionError,
		editingColumn,
		isDescriptionExpanded,
		onSelectColumn,
		onToggleDescription,
		onStartEdit,
		onCancelEdit,
		onSaveDescription
	}: Props = $props();

	function isDescriptionLong(value: string | null | undefined): boolean {
		return (value?.length ?? 0) > 140;
	}

	function getDescriptionPreview(value: string | null | undefined, expanded: boolean): string {
		if (!value) return 'No description';
		if (expanded || !isDescriptionLong(value)) return value;
		return `${value.slice(0, 140).trimEnd()}...`;
	}
</script>

<div class={css({ display: 'flex', flexDirection: 'column', gap: '3' })}>
	{#if refreshError}
		<Callout tone="error">
			<div class={css({ display: 'flex', alignItems: 'flex-start', gap: '3' })}>
				<CircleAlert size={20} />
				<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
					<p class={css({ margin: '0', fontWeight: 'semibold' })}>Ingest failed</p>
					<p class={css({ margin: '0', fontSize: 'sm', opacity: '0.8' })}>{refreshError}</p>
				</div>
			</div>
		</Callout>
	{/if}
	{#if schemaChanged && schemaDiff}
		<Callout tone="warn">
			<div class={css({ display: 'flex', alignItems: 'flex-start', gap: '3' })}>
				<CircleAlert size={20} />
				<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
					<p class={css({ margin: '0', fontWeight: 'semibold' })}>Schema changed in source</p>
					{#if schemaDiff.added.length > 0}
						<p class={css({ margin: '0', fontSize: 'sm', opacity: '0.8' })}>
							Added: {schemaDiff.added.join(', ')}
						</p>
					{/if}
					{#if schemaDiff.removed.length > 0}
						<p class={css({ margin: '0', fontSize: 'sm', opacity: '0.8' })}>
							Removed: {schemaDiff.removed.join(', ')}
						</p>
					{/if}
					{#if schemaDiff.types.length > 0}
						<p class={css({ margin: '0', fontSize: 'sm', opacity: '0.8' })}>
							Type changes: {schemaDiff.types.join(', ')}
						</p>
					{/if}
				</div>
			</div>
		</Callout>
	{/if}
	{#if loading}
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				flexDirection: 'column',
				justifyContent: 'center',
				gap: '3',
				paddingY: '8',
				color: 'fg.muted'
			})}
		>
			<Loader size={24} class={css({ animation: 'spin 1s linear infinite' })} />
			<p class={css({ fontSize: 'sm' })}>Loading schema...</p>
		</div>
	{:else if columns.length > 0}
		<div
			class={css({
				borderWidth: '1'
			})}
		>
			<div
				class={css({
					display: 'grid',
					gridTemplateColumns: '24px minmax(0, 1fr) 140px minmax(0, 1.6fr)',
					alignItems: 'center',
					columnGap: '2',
					backgroundColor: 'bg.tertiary',
					paddingX: '3',
					paddingY: '2',
					fontSize: 'xs',
					fontWeight: 'semibold',
					textTransform: 'uppercase',
					letterSpacing: 'wide',
					color: 'fg.muted',
					borderBottomWidth: '1'
				})}
			>
				<span>#</span>
				<span>Column</span>
				<span>Type</span>
				<span>Description</span>
			</div>
			{#each columns as column, index (index)}
				<div
					class={css(
						{
							display: 'grid',
							gridTemplateColumns: '24px minmax(0, 1fr) 140px minmax(0, 1.6fr)',
							alignItems: 'center',
							columnGap: '2',
							paddingX: '3',
							paddingY: '1.5',
							backgroundColor: 'transparent'
						},
						index > 0 && { borderTopWidth: '1' }
					)}
				>
					<span class={css({ fontSize: 'xs', color: 'fg.faint' })}>{index + 1}</span>
					<button
						type="button"
						class={css({
							fontSize: 'xs',
							textAlign: 'left',
							backgroundColor: 'transparent',
							borderColor: 'transparent',
							padding: '0',
							minWidth: '0',
							overflow: 'hidden',
							textOverflow: 'ellipsis',
							whiteSpace: 'nowrap',
							_hover: { color: 'accent.primary' }
						})}
						data-schema-column={column.name}
						onclick={() => onSelectColumn(column.name)}
					>
						{column.name}
					</button>
					<div>
						<ColumnTypeBadge columnType={column.dtype} size="sm" showIcon={true} />
					</div>
					<div class={css({ minWidth: '0' })}>
						{#if editingColumn === column.name}
							<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
								<textarea
									value={descriptionDraft}
									oninput={(e) => (descriptionDraft = e.currentTarget.value)}
									rows="4"
									maxlength="2000"
									class={css({
										width: 'full',
										fontSize: 'xs',
										paddingX: '2',
										paddingY: '1.5',
										borderWidth: '1',
										backgroundColor: 'bg.primary',
										resize: 'vertical',
										_focus: { outline: 'none' },
										_focusVisible: { borderColor: 'border.accent' }
									})}></textarea>
								<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
									<button
										type="button"
										class={css({
											borderWidth: '1',
											backgroundColor: 'accent.primary',
											color: 'fg.inverse',
											fontSize: 'xs',
											paddingX: '2',
											paddingY: '1'
										})}
										onclick={() => onSaveDescription(column.name)}
										disabled={descriptionPending}
									>
										{#if descriptionPending}
											Saving...
										{:else}
											Save
										{/if}
									</button>
									<button
										type="button"
										class={css({
											borderWidth: '1',
											backgroundColor: 'transparent',
											fontSize: 'xs',
											paddingX: '2',
											paddingY: '1'
										})}
										onclick={onCancelEdit}
										disabled={descriptionPending}
									>
										Cancel
									</button>
									<span class={css({ fontSize: '2xs', color: 'fg.muted' })}>
										{descriptionDraft.length}/2000
									</span>
								</div>
								{#if descriptionError}
									<p class={css({ margin: '0', fontSize: '2xs', color: 'fg.error' })}>
										{descriptionError}
									</p>
								{/if}
							</div>
						{:else}
							<div class={css({ display: 'flex', alignItems: 'flex-start', gap: '2' })}>
								<div
									class={css({
										flex: '1',
										minWidth: '0',
										fontSize: 'xs',
										color: column.description ? 'fg.primary' : 'fg.muted',
										whiteSpace: 'pre-wrap',
										wordBreak: 'break-word'
									})}
									data-schema-description={column.name}
								>
									{getDescriptionPreview(
										column.description ?? null,
										isDescriptionExpanded(column.name)
									)}
									{#if column.description && isDescriptionLong(column.description)}
										<button
											type="button"
											class={css({
												marginLeft: '1',
												padding: '0',
												borderColor: 'transparent',
												backgroundColor: 'transparent',
												fontSize: '2xs',
												color: 'accent.primary'
											})}
											onclick={() => onToggleDescription(column.name)}
										>
											{#if isDescriptionExpanded(column.name)}
												Show less
											{:else}
												Show more
											{/if}
										</button>
									{/if}
								</div>
								<button
									type="button"
									class={css({
										display: 'inline-flex',
										alignItems: 'center',
										justifyContent: 'center',
										borderWidth: '1',
										backgroundColor: 'transparent',
										paddingX: '1.5',
										paddingY: '1',
										color: 'fg.secondary',
										_hover: { backgroundColor: 'bg.hover' }
									})}
									aria-label={`Edit description for ${column.name}`}
									onclick={() => onStartEdit(column)}
								>
									<Pencil size={12} />
								</button>
							</div>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	{:else}
		<div class={emptyText({ size: 'panel' })}>
			<p class={css({ margin: '0' })}>No schema information available.</p>
		</div>
	{/if}
</div>
