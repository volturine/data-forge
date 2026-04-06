<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';
	import { css, cx, label, stepConfig, divider, input } from '$lib/styles/panda';

	interface StringMethodsConfigData {
		column: string;
		method: string;
		new_column: string;
		start?: number;
		end?: number | null;
		pattern?: string;
		replacement?: string;
		group_index?: number;
		delimiter?: string;
		index?: number;
	}

	interface Props {
		schema: Schema;
		config?: StringMethodsConfigData;
	}

	let {
		schema,
		config = $bindable({
			column: '',
			method: 'uppercase',
			new_column: '',
			start: 0,
			end: null,
			pattern: '',
			replacement: '',
			group_index: 0,
			delimiter: ' ',
			index: 0
		})
	}: Props = $props();

	const methods = [
		{ value: 'uppercase', label: 'Uppercase', params: [] },
		{ value: 'lowercase', label: 'Lowercase', params: [] },
		{ value: 'title', label: 'Title Case', params: [] },
		{ value: 'strip', label: 'Strip (Trim)', params: [] },
		{ value: 'lstrip', label: 'Left Strip', params: [] },
		{ value: 'rstrip', label: 'Right Strip', params: [] },
		{ value: 'length', label: 'String Length', params: [] },
		{ value: 'slice', label: 'Substring (Slice)', params: ['start', 'end'] },
		{ value: 'replace', label: 'Replace Text', params: ['pattern', 'replacement'] },
		{ value: 'extract', label: 'Extract (Regex)', params: ['pattern', 'group_index'] },
		{ value: 'split', label: 'Split to List', params: ['delimiter'] },
		{ value: 'split_take', label: 'Split & Take', params: ['delimiter', 'index'] }
	];

	const stringColumns = $derived(
		schema.columns.filter(
			(col) =>
				col.dtype.toLowerCase().includes('str') ||
				col.dtype.toLowerCase().includes('string') ||
				col.dtype.toLowerCase() === 'utf8'
		)
	);

	const currentMethod = $derived(methods.find((m) => m.value === config.method));

	function needsParam(param: string): boolean {
		return currentMethod?.params.includes(param) || false;
	}
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
			filter={(col) =>
				col.dtype.toLowerCase().includes('str') ||
				col.dtype.toLowerCase().includes('string') ||
				col.dtype.toLowerCase() === 'utf8'}
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
		class={cx(
			css({
				marginBottom: '0',
				paddingBottom: '5',
				backgroundColor: 'transparent',

				border: 'none'
			}),
			cx(
				divider,
				css({
					paddingTop: '5'
				})
			)
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

	{#if needsParam('start') || needsParam('end')}
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
						class={cx(label({ variant: 'field' }), css({ marginBottom: '1' }))}>Start Index:</label
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
						class={cx(label({ variant: 'field' }), css({ marginBottom: '1' }))}
						>End Index (optional):</label
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

	{#if needsParam('pattern') && needsParam('replacement')}
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
					class={cx(label({ variant: 'field' }), css({ marginBottom: '1' }))}
					>Pattern to find:</label
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
					class={cx(label({ variant: 'field' }), css({ marginBottom: '1' }))}>Replacement:</label
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

	{#if needsParam('pattern') && needsParam('group_index')}
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
					class={cx(label({ variant: 'field' }), css({ marginBottom: '1' }))}>Regex Pattern:</label
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
					class={cx(label({ variant: 'field' }), css({ marginBottom: '1' }))}>Group Index:</label
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

	{#if needsParam('delimiter') && !needsParam('index')}
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
					class={cx(label({ variant: 'field' }), css({ marginBottom: '1' }))}>Delimiter:</label
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

	{#if needsParam('delimiter') && needsParam('index')}
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
					class={cx(label({ variant: 'field' }), css({ marginBottom: '1' }))}>Delimiter:</label
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
					class={cx(label({ variant: 'field' }), css({ marginBottom: '1' }))}>Part Index:</label
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
		class={cx(
			css({
				marginBottom: '0',
				paddingBottom: '5',
				backgroundColor: 'transparent',

				border: 'none'
			}),
			cx(
				divider,
				css({
					paddingTop: '5'
				})
			)
		)}
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
