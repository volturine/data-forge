<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';
	import { css } from '$lib/styles/panda';

	interface Props {
		schema: Schema;
	}

	let { schema }: Props = $props();
</script>

<div
	class={[
		'schema-viewer',
		css({
			overflow: 'hidden',
			borderWidth: '1',
			backgroundColor: 'bg.primary'
		})
	]}
>
	<div
		class={css({
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'space-between',
			paddingX: '5',
			paddingY: '4',
			borderBottomWidth: '1',
			backgroundColor: 'bg.tertiary'
		})}
	>
		<h3 class={css({ margin: '0', fontSize: 'lg', fontWeight: 'semibold' })}>Schema</h3>
		{#if schema.row_count !== null}
			<span class={css({ fontSize: 'sm', color: 'fg.muted' })}>
				{schema.row_count.toLocaleString()} rows
			</span>
		{/if}
	</div>

	<div class={css({ maxHeight: 'listTall', overflowY: 'auto' })}>
		<div
			class={css({
				display: 'grid',
				gridTemplateColumns: '2fr 1.5fr 1fr',
				gap: '4',
				paddingX: '5',
				paddingY: '3',
				borderBottomWidth: '1',
				fontSize: 'xs',
				fontWeight: 'semibold',
				textTransform: 'uppercase',
				letterSpacing: 'wider',
				color: 'fg.muted',
				backgroundColor: 'bg.tertiary'
			})}
		>
			<div>Column</div>
			<div>Type</div>
			<div>Nullable</div>
		</div>

		{#each schema.columns as column (column.name)}
			<div
				class={css({
					display: 'grid',
					gridTemplateColumns: '2fr 1.5fr 1fr',
					gap: '4',
					paddingX: '5',
					paddingY: '3.5',
					borderBottomWidth: '1',
					_hover: { backgroundColor: 'bg.hover' }
				})}
			>
				<div class={css({ display: 'flex', alignItems: 'center', gap: '2', fontWeight: 'medium' })}>
					<span class={css({ fontFamily: 'mono', fontSize: 'sm' })}>{column.name}</span>
				</div>
				<div class={css({ display: 'flex', alignItems: 'center' })}>
					<ColumnTypeBadge columnType={column.dtype} size="sm" showIcon={true} />
				</div>
				<div class={css({ display: 'flex', alignItems: 'center', fontSize: 'sm' })}>
					{#if column.nullable}
						<span class={css({ color: 'fg.muted' })}>Yes</span>
					{:else}
						<span class={css({ fontWeight: 'medium', color: 'fg.secondary' })}>No</span>
					{/if}
				</div>
			</div>
		{/each}
	</div>
</div>
