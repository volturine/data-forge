<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';
	import { css, label, stepConfig, input } from '$lib/styles/panda';

	interface TimeSeriesConfigData {
		column: string;
		operation_type: string;
		new_column: string;
		component?: string;
		value?: number;
		unit?: string;
		column2?: string;
	}

	interface Props {
		schema: Schema;
		config?: TimeSeriesConfigData;
	}

	let {
		schema,
		config = $bindable({
			column: '',
			operation_type: 'extract',
			new_column: '',
			component: 'year',
			value: 1,
			unit: 'days',
			column2: ''
		})
	}: Props = $props();

	const operations = [
		{ value: 'extract', label: 'Extract Component' },
		{ value: 'timestamp', label: 'Convert to Timestamp' },
		{ value: 'add', label: 'Add Time Period' },
		{ value: 'subtract', label: 'Subtract Time Period' },
		{ value: 'diff', label: 'Date Difference' },
		{ value: 'truncate', label: 'Truncate to Boundary' },
		{ value: 'round', label: 'Round to Nearest' }
	];

	const extractComponents = [
		'year',
		'month',
		'day',
		'hour',
		'minute',
		'second',
		'quarter',
		'week',
		'dayofweek'
	];

	const timeUnits = ['seconds', 'minutes', 'hours', 'days', 'weeks', 'months'];

	const timestampUnits = ['ns', 'us', 'ms'];

	const dateColumns = $derived(
		schema.columns.filter(
			(col) =>
				col.dtype.toLowerCase().includes('date') ||
				col.dtype.toLowerCase().includes('time') ||
				col.dtype.toLowerCase() === 'date' ||
				col.dtype.toLowerCase() === 'datetime'
		)
	);
</script>

<div class={stepConfig()} role="region" aria-label="Time series configuration">
	<div
		class={css({
			marginBottom: '0',
			paddingBottom: '5',
			backgroundColor: 'transparent',

			border: 'none'
		})}
		role="group"
		aria-labelledby="ts-source-column-heading"
	>
		<h4
			id="ts-source-column-heading"
			class={css({
				marginTop: '0',
				marginBottom: '3',
				fontSize: 'xs',
				fontWeight: 'semibold',
				color: 'fg.muted',
				textTransform: 'uppercase',
				letterSpacing: 'wide3'
			})}
		>
			Source Column
		</h4>
		<ColumnDropdown
			{schema}
			value={config.column ?? ''}
			onChange={(val) => (config.column = val)}
			placeholder="Select date/time column..."
			filter={(col) =>
				col.dtype.toLowerCase().includes('date') ||
				col.dtype.toLowerCase().includes('time') ||
				col.dtype.toLowerCase() === 'date' ||
				col.dtype.toLowerCase() === 'datetime'}
		/>
		{#if dateColumns.length === 0}
			<p
				id="ts-no-columns-warning"
				class={css({ fontSize: 'sm', marginTop: '2', marginBottom: '0', color: 'fg.error' })}
				role="alert"
			>
				No date/time columns detected in schema
			</p>
		{/if}
	</div>

	<div
		class={css(
			{
				marginBottom: '0',
				paddingBottom: '5',
				backgroundColor: 'transparent',

				border: 'none'
			},
			{ borderTopWidth: '1', paddingTop: '5' }
		)}
		role="group"
		aria-labelledby="ts-operation-heading"
	>
		<h4
			id="ts-operation-heading"
			class={css({
				marginTop: '0',
				marginBottom: '3',
				fontSize: 'xs',
				fontWeight: 'semibold',
				color: 'fg.muted',
				textTransform: 'uppercase',
				letterSpacing: 'wide3'
			})}
		>
			Operation Type
		</h4>
		<label for="ts-select-operation" class={label({ variant: 'hidden' })}
			>Select operation type</label
		>
		<select
			id="ts-select-operation"
			data-testid="ts-operation-select"
			class={input()}
			bind:value={config.operation_type}
		>
			{#each operations as op (op.value)}
				<option value={op.value}>{op.label}</option>
			{/each}
		</select>
	</div>

	{#if config.operation_type === 'extract'}
		<div
			class={css({
				marginBottom: '0',
				paddingBottom: '5',
				backgroundColor: 'transparent',

				border: 'none'
			})}
			role="group"
			aria-labelledby="ts-component-heading"
		>
			<h4
				id="ts-component-heading"
				class={css({
					marginTop: '0',
					marginBottom: '3',
					fontSize: 'xs',
					fontWeight: 'semibold',
					color: 'fg.muted',
					textTransform: 'uppercase',
					letterSpacing: 'wide3'
				})}
			>
				Extract Component
			</h4>
			<label for="ts-select-component" class={label({ variant: 'hidden' })}
				>Select component to extract</label
			>
			<select
				id="ts-select-component"
				data-testid="ts-component-select"
				class={input()}
				bind:value={config.component}
			>
				{#each extractComponents as comp (comp)}
					<option value={comp}>{comp}</option>
				{/each}
			</select>
		</div>
	{:else if config.operation_type === 'timestamp'}
		<div
			class={css({
				marginBottom: '0',
				paddingBottom: '5',
				backgroundColor: 'transparent',

				border: 'none'
			})}
			role="group"
			aria-labelledby="ts-timestamp-unit-heading"
		>
			<h4
				id="ts-timestamp-unit-heading"
				class={css({
					marginTop: '0',
					marginBottom: '3',
					fontSize: 'xs',
					fontWeight: 'semibold',
					color: 'fg.muted',
					textTransform: 'uppercase',
					letterSpacing: 'wide3'
				})}
			>
				Timestamp Unit
			</h4>
			<label for="ts-select-timestamp-unit" class={label({ variant: 'hidden' })}
				>Select timestamp time unit</label
			>
			<select
				id="ts-select-timestamp-unit"
				data-testid="ts-timestamp-unit-select"
				class={input()}
				bind:value={config.unit}
			>
				{#each timestampUnits as unit (unit)}
					<option value={unit}
						>{unit} ({unit === 'ns'
							? 'nanoseconds'
							: unit === 'us'
								? 'microseconds'
								: 'milliseconds'})</option
					>
				{/each}
			</select>
			<p class={css({ fontSize: 'sm', marginTop: '2', marginBottom: '0', color: 'fg.muted' })}>
				Convert datetime to integer timestamp in the specified time unit.
			</p>
		</div>
	{:else if config.operation_type === 'add' || config.operation_type === 'subtract'}
		<div
			class={css({
				marginBottom: '0',
				paddingBottom: '5',
				backgroundColor: 'transparent',

				border: 'none'
			})}
			role="group"
			aria-labelledby="ts-period-heading"
		>
			<h4
				id="ts-period-heading"
				class={css({
					marginTop: '0',
					marginBottom: '3',
					fontSize: 'xs',
					fontWeight: 'semibold',
					color: 'fg.muted',
					textTransform: 'uppercase',
					letterSpacing: 'wide3'
				})}
			>
				Time Period
			</h4>
			<div class={css({ display: 'flex', gap: '3' })}>
				<div class={css({ flex: '1' })}>
					<label
						for="ts-input-value"
						class={css({
							display: 'block',
							fontSize: 'sm',
							fontWeight: 'medium',
							color: 'fg.secondary',
							textTransform: 'none',
							letterSpacing: 'normal',
							marginBottom: '1'
						})}>Value:</label
					>
					<input
						id="ts-input-value"
						data-testid="ts-value-input"
						type="number"
						class={css({
							width: 'full',
							fontSize: 'sm2',
							color: 'fg.primary',
							backgroundColor: 'bg.primary',
							borderWidth: '1',
							borderRadius: '0',
							paddingX: '3.5',
							paddingY: '2.25',
							flex: '1',
							transitionProperty: 'border-color',
							transitionDuration: '160ms',
							transitionTimingFunction: 'ease',
							_focus: { outline: 'none' },
							_focusVisible: { borderColor: 'border.accent' },
							_disabled: { opacity: '0.5', cursor: 'not-allowed', backgroundColor: 'bg.tertiary' },
							_placeholder: { color: 'fg.muted' }
						})}
						bind:value={config.value}
						min="0"
						aria-label="Time period value"
					/>
				</div>
				<div class={css({ flex: '1' })}>
					<label
						for="ts-select-unit"
						class={css({
							display: 'block',
							fontSize: 'sm',
							fontWeight: 'medium',
							color: 'fg.secondary',
							textTransform: 'none',
							letterSpacing: 'normal',
							marginBottom: '1'
						})}>Unit:</label
					>
					<select
						id="ts-select-unit"
						data-testid="ts-unit-select"
						class={css({
							width: 'full',
							fontSize: 'sm2',
							color: 'fg.primary',
							backgroundColor: 'bg.primary',
							borderWidth: '1',
							borderRadius: '0',
							paddingX: '3.5',
							paddingY: '2.25',
							flex: '1',
							transitionProperty: 'border-color',
							transitionDuration: '160ms',
							transitionTimingFunction: 'ease',
							_focus: { outline: 'none' },
							_focusVisible: { borderColor: 'border.accent' },
							_disabled: { opacity: '0.5', cursor: 'not-allowed', backgroundColor: 'bg.tertiary' },
							_placeholder: { color: 'fg.muted' }
						})}
						bind:value={config.unit}
					>
						{#each timeUnits as unit (unit)}
							<option value={unit}>{unit}</option>
						{/each}
					</select>
				</div>
			</div>
		</div>
	{:else if config.operation_type === 'diff'}
		<div
			class={css({
				marginBottom: '0',
				paddingBottom: '5',
				backgroundColor: 'transparent',

				border: 'none'
			})}
			role="group"
			aria-labelledby="ts-column2-heading"
		>
			<h4
				id="ts-column2-heading"
				class={css({
					marginTop: '0',
					marginBottom: '3',
					fontSize: 'xs',
					fontWeight: 'semibold',
					color: 'fg.muted',
					textTransform: 'uppercase',
					letterSpacing: 'wide3'
				})}
			>
				Second Date Column
			</h4>
			<ColumnDropdown
				{schema}
				value={config.column2 ?? ''}
				onChange={(val) => (config.column2 = val)}
				placeholder="Select column..."
				filter={(col) =>
					col.dtype.toLowerCase().includes('date') ||
					col.dtype.toLowerCase().includes('time') ||
					col.dtype.toLowerCase() === 'date' ||
					col.dtype.toLowerCase() === 'datetime'}
			/>
		</div>
	{:else if config.operation_type === 'truncate' || config.operation_type === 'round'}
		<div
			class={css({
				marginBottom: '0',
				paddingBottom: '5',
				backgroundColor: 'transparent',
				border: 'none'
			})}
			role="group"
			aria-labelledby="ts-truncate-unit-heading"
		>
			<h4
				id="ts-truncate-unit-heading"
				class={css({
					marginTop: '0',
					marginBottom: '3',
					fontSize: 'xs',
					fontWeight: 'semibold',
					color: 'fg.muted',
					textTransform: 'uppercase',
					letterSpacing: 'wide3'
				})}
			>
				{config.operation_type === 'truncate' ? 'Truncate' : 'Round'} Unit
			</h4>
			<label for="ts-select-truncate-unit" class={label({ variant: 'hidden' })}
				>Select unit for {config.operation_type}</label
			>
			<select
				id="ts-select-truncate-unit"
				data-testid="ts-truncate-unit-select"
				class={input()}
				bind:value={config.unit}
			>
				{#each timeUnits as unit (unit)}
					<option value={unit}>{unit}</option>
				{/each}
			</select>
			<p class={css({ fontSize: 'sm', marginTop: '2', marginBottom: '0', color: 'fg.muted' })}>
				{config.operation_type === 'truncate'
					? 'Truncate datetime to the start of the selected time unit.'
					: 'Round datetime to the nearest selected time unit boundary.'}
			</p>
		</div>
	{/if}

	<div
		class={css({
			marginBottom: '0',
			paddingBottom: '5',
			backgroundColor: 'transparent',

			border: 'none',
			borderTopWidth: '1',
			paddingTop: '5'
		})}
		role="group"
		aria-labelledby="ts-new-column-heading"
	>
		<h4
			id="ts-new-column-heading"
			class={css({
				marginTop: '0',
				marginBottom: '3',
				fontSize: 'xs',
				fontWeight: 'semibold',
				color: 'fg.muted',
				textTransform: 'uppercase',
				letterSpacing: 'wide3'
			})}
		>
			New Column Name
		</h4>
		<label for="ts-input-new-column" class={label({ variant: 'hidden' })}>New column name</label>
		<input
			id="ts-new-column"
			type="text"
			class={input()}
			bind:value={config.new_column}
			placeholder="e.g., year, future_date"
		/>
	</div>
</div>
