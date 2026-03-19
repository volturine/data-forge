<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';
	import { css, label, stepConfig, input } from '$lib/styles/panda';

	interface Props {
		schema: Schema;
		config?: { index?: string[]; on?: string[]; variable_name?: string; value_name?: string };
	}

	let { schema, config = $bindable({}) }: Props = $props();

	// Helper to get config value with default
	const get = <T,>(key: keyof typeof config, defaultValue: T): T =>
		(config[key] as T) ?? defaultValue;
</script>

<div class={stepConfig()} role="region" aria-label="Unpivot configuration">
	<p
		class={css({
			marginTop: '0',
			marginBottom: '3',
			color: 'fg.tertiary',
			fontSize: 'xs',
			lineHeight: '1.6'
		})}
	>
		Transform wide data to long format (melt operation).
	</p>

	<div class={css({ marginBottom: '5' })}>
		<div
			class={css({
				display: 'block',
				fontSize: 'xs',
				fontWeight: '600',
				color: 'fg.muted',
				marginBottom: '1.5',
				textTransform: 'uppercase',
				letterSpacing: 'wider'
			})}
		>
			Index columns (identifiers)
		</div>
		<MultiSelectColumnDropdown
			{schema}
			value={config.index ?? []}
			onChange={(val) => (config.index = val)}
			placeholder="Select index columns..."
		/>
		<span class={css({ marginTop: '1', display: 'block', fontSize: 'xs', color: 'fg.tertiary' })}
			>Columns to use as identifiers</span
		>
	</div>

	<div class={css({ marginBottom: '5' })}>
		<div
			class={css({
				display: 'block',
				fontSize: 'xs',
				fontWeight: '600',
				color: 'fg.muted',
				marginBottom: '1.5',
				textTransform: 'uppercase',
				letterSpacing: 'wider'
			})}
		>
			Columns to unpivot
		</div>
		<MultiSelectColumnDropdown
			{schema}
			value={config.on ?? []}
			onChange={(val) => (config.on = val)}
			placeholder="Select columns to unpivot..."
		/>
		<span class={css({ marginTop: '1', display: 'block', fontSize: 'xs', color: 'fg.tertiary' })}
			>Columns that will be transformed to rows</span
		>
	</div>

	<div class={css({ marginBottom: '5' })}>
		<label class={label()} for="unpivot-input-variable">Variable column name</label>
		<input
			id="unpivot-input-variable"
			data-testid="unpivot-variable-input"
			type="text"
			class={input()}
			value={get('variable_name', 'variable')}
			oninput={(e) => (config.variable_name = e.currentTarget.value)}
			placeholder="variable"
		/>
	</div>

	<div class={css({ marginBottom: '0' })}>
		<label class={label()} for="unpivot-input-value">Value column name</label>
		<input
			id="unpivot-input-value"
			data-testid="unpivot-value-input"
			type="text"
			class={input()}
			value={get('value_name', 'value')}
			oninput={(e) => (config.value_name = e.currentTarget.value)}
			placeholder="value"
		/>
	</div>
</div>
