<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';
	import { ArrowRight, X } from 'lucide-svelte';
	import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
	import { css, cx, emptyText, input, label, stepConfig } from '$lib/styles/panda';

	interface RenameConfigData {
		column_mapping: { [oldName: string]: string };
	}

	interface Props {
		schema: Schema;
		config?: RenameConfigData;
	}

	let { schema, config = $bindable({ column_mapping: {} }) }: Props = $props();

	let formOldName = $state('');
	let formNewName = $state('');

	const safeMapping = $derived(config?.column_mapping ?? {});

	const mappings = $derived(
		Object.entries(safeMapping).map(([oldName, newName]) => ({
			oldName,
			newName
		}))
	);

	const canAdd = $derived(!!formOldName && !!formNewName);

	function addMapping() {
		if (!canAdd) return;
		config = {
			column_mapping: {
				...safeMapping,
				[formOldName]: formNewName
			}
		};
		formOldName = '';
		formNewName = '';
	}

	function removeMapping(oldName: string) {
		const { [oldName]: _, ...rest } = safeMapping;
		config.column_mapping = rest;
	}
</script>

<div class={stepConfig()} role="region" aria-label="Rename configuration">
	<h3
		class={css({
			margin: '0',
			marginBottom: '5',
			fontSize: 'sm',
			textTransform: 'uppercase',
			letterSpacing: 'wider',
			color: 'fg.muted'
		})}
	>
		Rename Configuration
	</h3>

	<div class={css({ marginBottom: '5' })} role="group" aria-labelledby="rename-columns-heading">
		<span id="rename-columns-heading"><SectionHeader>Select Column to Rename</SectionHeader></span>
		<ColumnDropdown
			{schema}
			value={formOldName}
			onChange={(val) => (formOldName = val)}
			placeholder="Select column to rename..."
			filter={(col) => !safeMapping[col.name]}
		/>
		{#if schema.columns.filter((col) => !safeMapping[col.name]).length === 0}
			<p
				class={css({
					color: 'fg.muted',
					backgroundColor: 'transparent',
					border: '1px dashed',
					padding: '6',
					textAlign: 'center',
					marginBottom: '5'
				})}
			>
				All columns have been renamed.
			</p>
		{/if}
	</div>

	<div
		class={css({ display: 'grid', gap: '3', marginBottom: '5' })}
		role="group"
		aria-label="Add rename mapping form"
	>
		<label for="rename-input-new" class={label({ variant: 'hidden' })}>New column name</label>
		<input
			id="rename-input-new"
			data-testid="rename-new-name-input"
			type="text"
			class={cx(
				input(),
				css({
					backgroundColor: !formOldName ? 'bg.muted' : undefined,
					color: !formOldName ? 'fg.muted' : undefined
				})
			)}
			bind:value={formNewName}
			placeholder={formOldName ? `New name for ${formOldName}` : 'Select a column first'}
			aria-label="Enter new column name"
			disabled={!formOldName}
		/>

		<button
			id="rename-btn-add"
			data-testid="rename-add-button"
			type="button"
			class={css({
				backgroundColor: 'accent.primary',
				color: 'fg.inverse',
				borderWidth: '1',
				paddingY: '2',
				paddingX: '4',
				cursor: 'pointer',
				whiteSpace: 'nowrap',
				fontWeight: 'semibold',
				_hover: { opacity: '0.9' },
				_disabled: {
					backgroundColor: 'bg.tertiary',
					color: 'fg.muted',
					cursor: 'not-allowed'
				}
			})}
			onclick={addMapping}
			disabled={!canAdd}
			aria-label="Add rename mapping"
		>
			Add Rename
		</button>
	</div>

	{#if mappings.length > 0}
		<div
			id="rename-mappings-list"
			class={css({ display: 'flex', flexDirection: 'column' })}
			role="list"
			aria-label="Configured renames"
		>
			<SectionHeader>Renames</SectionHeader>
			{#each mappings as mapping (mapping.oldName)}
				<div
					class={css({
						backgroundColor: 'transparent',
						border: 'none',
						borderBottomWidth: '1',
						display: 'flex',
						justifyContent: 'space-between',
						alignItems: 'center',
						paddingY: '2',
						_last: { borderBottom: 'none' }
					})}
					role="listitem"
				>
					<div
						class={css({
							display: 'flex',
							alignItems: 'center',
							gap: '3',
							minWidth: '0',
							fontSize: 'sm',
							fontFamily: 'mono'
						})}
					>
						<span
							class={css({
								fontWeight: 'semibold',
								maxWidth: 'inputSm',
								overflow: 'hidden',
								textOverflow: 'ellipsis',
								whiteSpace: 'nowrap'
							})}
							title={mapping.oldName}>{mapping.oldName}</span
						>
						<ArrowRight size={12} class={css({ color: 'fg.muted' })} aria-hidden="true" />
						<span
							class={css({
								fontWeight: 'semibold',
								maxWidth: 'inputSm',
								overflow: 'hidden',
								textOverflow: 'ellipsis',
								whiteSpace: 'nowrap',
								color: 'accent.primary'
							})}
							title={mapping.newName}>{mapping.newName}</span
						>
					</div>
					<button
						id={`rename-btn-remove-${mapping.oldName}`}
						data-testid={`rename-remove-button-${mapping.oldName}`}
						type="button"
						class={css({
							width: 'row',
							height: 'row',
							display: 'inline-flex',
							alignItems: 'center',
							justifyContent: 'center',
							cursor: 'pointer',
							fontSize: 'lg',
							lineHeight: 'none',
							backgroundColor: 'transparent',
							color: 'fg.muted',
							borderWidth: '1',
							borderColor: 'border.transparent',
							_hover: {
								color: 'fg.primary',
								backgroundColor: 'bg.hover'
							}
						})}
						onclick={() => removeMapping(mapping.oldName)}
						aria-label={`Remove rename: ${mapping.oldName} to ${mapping.newName}`}
					>
						<X size={12} />
					</button>
				</div>
			{/each}
		</div>
	{:else}
		<p id="rename-empty-state" class={emptyText()} role="status">No renames yet.</p>
	{/if}
</div>
