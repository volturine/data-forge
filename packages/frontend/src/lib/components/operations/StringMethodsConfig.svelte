<script lang="ts">
	import type { Schema } from '#lib/types/schema.js';
	import type { StringMethodsConfigData } from '#lib/types/operation-config.js';
	import ColumnDropdown from '#lib/components/common/ColumnDropdown.svelte';
	import { getColumnTypeConfig } from '#lib/utils/column-types.js';
	import { css, label, stepConfig, input } from '#lib/styles/panda.js';

	interface Props {
		schema: Schema;
		config: StringMethodsConfigData;
	}

	let { schema, config = $bindable() }: Props = $props();

	const methods = [
		{ value: 'uppercase', label: 'Uppercase' },
		{ value: 'lowercase', label: 'Lowercase' },
		{ value: 'title', label: 'Title Case' },
		{ value: 'strip', label: 'Strip (Trim)' },
		{ value: 'lstrip', label: 'Left Strip' },
		{ value: 'rstrip', label: 'Right Strip' },
		{ value: 'length', label: 'String Length' },
		{ value: 'slice', label: 'Substring (Slice)' },
		{ value: 'replace', label: 'Replace Text' },
		{ value: 'extract', label: 'Extract (Regex)' },
		{ value: 'split', label: 'Split to List' },
		{ value: 'split_take', label: 'Split & Take' }
	];

	// `.str` operations apply to String columns only (not Struct or Categorical).
	const isStringColumn = (col: { dtype: string }) =>
		getColumnTypeConfig(col.dtype).canonicalName === 'String';
	const stringColumns = $derived(schema.columns.filter(isStringColumn));
</script>

<div class={stepConfig()} role="region" aria-label="String methods configuration">
	<div
		class={css({
			marginBottom: '0',
			paddingBottom: '5',
			backgroundColor: 'transparent',

			border: 'none'
		})}
		role="group"
		aria-labelledby="str-column-heading"
	>
		<h4
			id="str-column-heading"
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
			placeholder="Select string column..."
			filter={isStringColumn}
		/>
		{#if stringColumns.length === 0}
			<p
				id="str-no-columns-warning"
				class={css({
					paddingX: '3',
					paddingY: '2.5',
					border: 'none',
					borderLeftWidth: '2',

					marginTop: '3',
					marginBottom: '0',
					fontSize: 'xs',
					lineHeight: '1.5',
					backgroundColor: 'transparent',
					borderLeftColor: 'border.warning',
					color: 'fg.tertiary'
				})}
				role="alert"
			>
				No string columns detected in schema
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
		aria-labelledby="str-method-heading"
	>
		<h4
			id="str-method-heading"
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
			String Method
		</h4>
		<label for="str-select-method" class={label({ variant: 'hidden' })}>Select string method</label>
		<select
			id="str-select-method"
			data-testid="str-method-select"
			class={input()}
			bind:value={config.method}
		>
			{#each methods as method (method.value)}
				<option value={method.value}>{method.label}</option>
			{/each}
		</select>
	</div>

	{#if config.method === 'slice'}
		<div
			class={css({
				marginBottom: '0',
				paddingBottom: '5',
				backgroundColor: 'transparent',

				border: 'none'
			})}
			role="group"
			aria-labelledby="slice-params-heading"
		>
			<h4
				id="slice-params-heading"
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
				Slice Parameters
			</h4>
			<div class={css({ display: 'flex', gap: '4' })}>
				<div class={css({ flex: '1' })}>
					<label
						for="str-input-start"
						class={css({
							display: 'block',
							fontSize: 'sm',
							fontWeight: 'medium',
							color: 'fg.secondary',
							textTransform: 'none',
							letterSpacing: 'normal',
							marginBottom: '1'
						})}>Start Index:</label
					>
					<input
						id="str-input-start"
						data-testid="str-start-input"
						type="number"
						class={input()}
						bind:value={config.start}
						aria-describedby="str-start-help"
					/>
					<span
						id="str-start-help"
						class={css({
							position: 'absolute',
							width: 'px',
							height: 'px',
							padding: '0',
							margin: '-1px',
							overflow: 'hidden',
							clip: 'rect(0, 0, 0, 0)',
							whiteSpace: 'nowrap',
							border: '0'
						})}>Starting index for substring</span
					>
				</div>
				<div class={css({ flex: '1' })}>
					<label
						for="str-input-end"
						class={css({
							display: 'block',
							fontSize: 'sm',
							fontWeight: 'medium',
							color: 'fg.secondary',
							textTransform: 'none',
							letterSpacing: 'normal',
							marginBottom: '1'
						})}>End Index (optional):</label
					>
					<input
						id="str-input-end"
						data-testid="str-end-input"
						type="number"
						class={input()}
						bind:value={config.end}
						placeholder="Leave empty for end"
						aria-describedby="str-end-help"
					/>
					<span
						id="str-end-help"
						class={css({
							position: 'absolute',
							width: 'px',
							height: 'px',
							padding: '0',
							margin: '-1px',
							overflow: 'hidden',
							clip: 'rect(0, 0, 0, 0)',
							whiteSpace: 'nowrap',
							border: '0'
						})}>Ending index for substring (leave empty for end of string)</span
					>
				</div>
			</div>
		</div>
	{/if}

	{#if config.method === 'replace'}
		<div
			class={css({
				marginBottom: '0',
				paddingBottom: '5',
				backgroundColor: 'transparent',

				border: 'none'
			})}
			role="group"
			aria-labelledby="replace-params-heading"
		>
			<h4
				id="replace-params-heading"
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
				Replace Parameters
			</h4>
			<div>
				<label
					for="str-input-pattern"
					class={css({
						display: 'block',
						fontSize: 'sm',
						fontWeight: 'medium',
						color: 'fg.secondary',
						textTransform: 'none',
						letterSpacing: 'normal',
						marginBottom: '1'
					})}>Pattern to find:</label
				>
				<input
					id="str-input-pattern"
					data-testid="str-pattern-input"
					type="text"
					class={input()}
					bind:value={config.pattern}
					placeholder="Text or regex pattern"
					aria-describedby="str-pattern-help"
				/>
				<span
					id="str-pattern-help"
					class={css({
						position: 'absolute',
						width: 'px',
						height: 'px',
						padding: '0',
						margin: '-1px',
						overflow: 'hidden',
						clip: 'rect(0, 0, 0, 0)',
						whiteSpace: 'nowrap',
						border: '0'
					})}>Text or regular expression pattern to find and replace</span
				>
			</div>
			<div>
				<label
					for="str-input-replacement"
					class={css({
						display: 'block',
						fontSize: 'sm',
						fontWeight: 'medium',
						color: 'fg.secondary',
						textTransform: 'none',
						letterSpacing: 'normal',
						marginBottom: '1'
					})}>Replacement:</label
				>
				<input
					id="str-input-replacement"
					data-testid="str-replacement-input"
					type="text"
					class={input()}
					bind:value={config.replacement}
					placeholder="Replacement text"
					aria-describedby="str-replacement-help"
				/>
				<span
					id="str-replacement-help"
					class={css({
						position: 'absolute',
						width: 'px',
						height: 'px',
						padding: '0',
						margin: '-1px',
						overflow: 'hidden',
						clip: 'rect(0, 0, 0, 0)',
						whiteSpace: 'nowrap',
						border: '0'
					})}>Text to replace the matched pattern with</span
				>
			</div>
		</div>
	{/if}

	{#if config.method === 'extract'}
		<div
			class={css({
				marginBottom: '0',
				paddingBottom: '5',
				backgroundColor: 'transparent',

				border: 'none'
			})}
			role="group"
			aria-labelledby="extract-params-heading"
		>
			<h4
				id="extract-params-heading"
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
				Extract Parameters
			</h4>
			<div>
				<label
					for="str-input-extract-pattern"
					class={css({
						display: 'block',
						fontSize: 'sm',
						fontWeight: 'medium',
						color: 'fg.secondary',
						textTransform: 'none',
						letterSpacing: 'normal',
						marginBottom: '1'
					})}>Regex Pattern:</label
				>
				<input
					id="str-input-extract-pattern"
					data-testid="str-extract-pattern-input"
					type="text"
					class={input()}
					bind:value={config.pattern}
					placeholder="e.g., @(.+)$ to extract domain"
					aria-describedby="str-extract-pattern-help"
				/>
				<span
					id="str-extract-pattern-help"
					class={css({
						position: 'absolute',
						width: 'px',
						height: 'px',
						padding: '0',
						margin: '-1px',
						overflow: 'hidden',
						clip: 'rect(0, 0, 0, 0)',
						whiteSpace: 'nowrap',
						border: '0'
					})}>Regular expression with capture group to extract</span
				>
			</div>
			<div>
				<label
					for="str-input-group-index"
					class={css({
						display: 'block',
						fontSize: 'sm',
						fontWeight: 'medium',
						color: 'fg.secondary',
						textTransform: 'none',
						letterSpacing: 'normal',
						marginBottom: '1'
					})}>Group Index:</label
				>
				<input
					id="str-input-group-index"
					data-testid="str-group-index-input"
					type="number"
					class={input()}
					bind:value={config.group_index}
					min="0"
					aria-describedby="str-group-index-help"
				/>
				<span
					id="str-group-index-help"
					class={css({
						position: 'absolute',
						width: 'px',
						height: 'px',
						padding: '0',
						margin: '-1px',
						overflow: 'hidden',
						clip: 'rect(0, 0, 0, 0)',
						whiteSpace: 'nowrap',
						border: '0'
					})}>Index of the capture group to extract (0-based)</span
				>
			</div>
		</div>
	{/if}

	{#if config.method === 'split'}
		<div
			class={css({
				marginBottom: '0',
				paddingBottom: '5',
				backgroundColor: 'transparent',

				border: 'none'
			})}
			role="group"
			aria-labelledby="split-delimiter-heading"
		>
			<h4
				id="split-delimiter-heading"
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
				Split Delimiter
			</h4>
			<div>
				<label
					for="str-input-delimiter-only"
					class={css({
						display: 'block',
						fontSize: 'sm',
						fontWeight: 'medium',
						color: 'fg.secondary',
						textTransform: 'none',
						letterSpacing: 'normal',
						marginBottom: '1'
					})}>Delimiter:</label
				>
				<input
					id="str-input-delimiter-only"
					data-testid="str-delimiter-only-input"
					type="text"
					class={input()}
					bind:value={config.delimiter}
					placeholder="e.g., , or |"
					aria-describedby="str-delimiter-only-help"
				/>
				<span
					id="str-delimiter-only-help"
					class={css({
						position: 'absolute',
						width: 'px',
						height: 'px',
						padding: '0',
						margin: '-1px',
						overflow: 'hidden',
						clip: 'rect(0, 0, 0, 0)',
						whiteSpace: 'nowrap',
						border: '0'
					})}>Delimiter to split the string into a list</span
				>
			</div>
		</div>
	{/if}

	{#if config.method === 'split_take'}
		<div
			class={css({
				marginBottom: '0',
				paddingBottom: '5',
				backgroundColor: 'transparent',

				border: 'none'
			})}
			role="group"
			aria-labelledby="split-params-heading"
		>
			<h4
				id="split-params-heading"
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
				Split & Take Parameters
			</h4>
			<div>
				<label
					for="str-input-delimiter"
					class={css({
						display: 'block',
						fontSize: 'sm',
						fontWeight: 'medium',
						color: 'fg.secondary',
						textTransform: 'none',
						letterSpacing: 'normal',
						marginBottom: '1'
					})}>Delimiter:</label
				>
				<input
					id="str-input-delimiter"
					data-testid="str-delimiter-input"
					type="text"
					class={input()}
					bind:value={config.delimiter}
					placeholder="e.g., , or |"
					aria-describedby="str-delimiter-help"
				/>
				<span
					id="str-delimiter-help"
					class={css({
						position: 'absolute',
						width: 'px',
						height: 'px',
						padding: '0',
						margin: '-1px',
						overflow: 'hidden',
						clip: 'rect(0, 0, 0, 0)',
						whiteSpace: 'nowrap',
						border: '0'
					})}>Delimiter character or string to split on</span
				>
			</div>
			<div>
				<label
					for="str-input-part-index"
					class={css({
						display: 'block',
						fontSize: 'sm',
						fontWeight: 'medium',
						color: 'fg.secondary',
						textTransform: 'none',
						letterSpacing: 'normal',
						marginBottom: '1'
					})}>Part Index:</label
				>
				<input
					id="str-input-part-index"
					data-testid="str-part-index-input"
					type="number"
					class={input()}
					bind:value={config.index}
					min="0"
					aria-describedby="str-part-index-help"
				/>
				<span
					id="str-part-index-help"
					class={css({
						position: 'absolute',
						width: 'px',
						height: 'px',
						padding: '0',
						margin: '-1px',
						overflow: 'hidden',
						clip: 'rect(0, 0, 0, 0)',
						whiteSpace: 'nowrap',
						border: '0'
					})}>Index of the part to take after splitting (0-based)</span
				>
			</div>
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
		aria-labelledby="new-column-heading"
	>
		<h4
			id="new-column-heading"
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
		<label for="str-input-new-column" class={label({ variant: 'hidden' })}>New column name</label>
		<input
			id="str-input-new-column"
			data-testid="str-new-column-input"
			type="text"
			class={input()}
			bind:value={config.new_column}
			placeholder="e.g., name_upper, domain, first_name"
			aria-describedby="str-new-column-help"
		/>
		<span
			id="str-new-column-help"
			class={css({
				position: 'absolute',
				width: 'px',
				height: 'px',
				padding: '0',
				margin: '-1px',
				overflow: 'hidden',
				clip: 'rect(0, 0, 0, 0)',
				whiteSpace: 'nowrap',
				border: '0'
			})}>Name for the new column that will contain the result</span
		>
	</div>
</div>
