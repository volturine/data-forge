<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';
	import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
	import { css, label, stepConfig, cx, input } from '$lib/styles/panda';

	interface ExpressionConfigData {
		expression: string;
		column_name: string;
	}

	interface Props {
		schema: Schema;
		config?: ExpressionConfigData;
	}

	let { schema, config = $bindable({ expression: '', column_name: '' }) }: Props = $props();

	function insertColumn(columnName: string) {
		if (!columnName) return;
		const colRef = `pl.col("${columnName}")`;
		config.expression = config.expression ? `${config.expression} ${colRef}` : colRef;
	}
</script>

<div class={stepConfig()} role="region" aria-label="Expression configuration">
	<div
		class={css({
			marginBottom: '0',
			paddingBottom: '5',
			backgroundColor: 'transparent',

			border: 'none'
		})}
		role="group"
		aria-labelledby="expr-expression-heading"
	>
		<span id="expr-expression-heading"><SectionHeader>Expression</SectionHeader></span>
		<label for="expr-textarea-expression" class={label({ variant: 'hidden' })}
			>Polars expression</label
		>
		<textarea
			id="expr-textarea-expression"
			data-testid="expr-expression-textarea"
			class={cx(input(), css({ resize: 'vertical', marginBottom: '2' }))}
			bind:value={config.expression}
			placeholder="e.g., pl.col(&quot;price&quot;) * 1.2"
			rows="4"
			aria-describedby="expr-expression-help"
		></textarea>
		<span
			id="expr-expression-help"
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
			})}>Enter a Polars expression using pl.col() to reference columns</span
		>

		<div
			id="expr-syntax-help"
			class={css({
				color: 'fg.tertiary',
				backgroundColor: 'transparent',
				borderTopWidth: '0',
				borderRightWidth: '0',
				borderBottomWidth: '0',
				borderLeftWidth: '2',
				fontSize: 'xs',
				paddingX: '3',
				paddingY: '2',
				lineHeight: 'relaxed',
				marginTop: '3'
			})}
			aria-label="Syntax help"
		>
			<strong>Polars Expression Syntax:</strong><br />
			Use
			<code
				class={css({
					backgroundColor: 'bg.tertiary',
					paddingX: '2',
					paddingY: '1',
					fontFamily: 'mono',
					fontSize: 'xs',
					color: 'accent.primary'
				})}>pl.col("column")</code
			>
			to reference columns.<br />
			Examples:<br />
			-
			<code
				class={css({
					backgroundColor: 'bg.tertiary',
					paddingX: '2',
					paddingY: '1',
					fontFamily: 'mono',
					fontSize: 'xs',
					color: 'accent.primary'
				})}>pl.col("price") * 1.2</code
			>
			- Multiply<br />
			-
			<code
				class={css({
					backgroundColor: 'bg.tertiary',
					paddingX: '2',
					paddingY: '1',
					fontFamily: 'mono',
					fontSize: 'xs',
					color: 'accent.primary'
				})}>pl.col("value").cast(pl.Float64)</code
			>
			- Cast type<br />
			-
			<code
				class={css({
					backgroundColor: 'bg.tertiary',
					paddingX: '2',
					paddingY: '1',
					fontFamily: 'mono',
					fontSize: 'xs',
					color: 'accent.primary'
				})}>pl.col("name").str.to_uppercase()</code
			>
			- String method<br />
			-
			<code
				class={css({
					backgroundColor: 'bg.tertiary',
					paddingX: '2',
					paddingY: '1',
					fontFamily: 'mono',
					fontSize: 'xs',
					color: 'accent.primary'
				})}>pl.col("date").dt.year()</code
			> - Date component
		</div>
	</div>

	<div
		class={css({
			borderTopWidth: '1',
			marginBottom: '0',
			paddingBottom: '5',
			paddingTop: '5',
			backgroundColor: 'transparent'
		})}
		role="group"
		aria-labelledby="expr-new-column-heading"
	>
		<span id="expr-new-column-heading"><SectionHeader>New Column Name</SectionHeader></span>
		<label for="expr-input-column" class={label({ variant: 'hidden' })}>New column name</label>
		<input
			id="expr-input-column"
			data-testid="expr-column-input"
			type="text"
			class={input()}
			bind:value={config.column_name}
			placeholder="e.g., price_with_tax, full_name"
		/>
	</div>

	<div
		class={css({
			borderTopWidth: '1',
			marginBottom: '0',
			paddingBottom: '5',
			paddingTop: '5',
			backgroundColor: 'transparent'
		})}
		role="group"
		aria-labelledby="expr-columns-heading"
	>
		<span id="expr-columns-heading"><SectionHeader>Insert Column</SectionHeader></span>
		<ColumnDropdown
			{schema}
			value=""
			onChange={(val) => insertColumn(val)}
			placeholder="Select column to insert..."
		/>
		<span class={css({ marginTop: '1', display: 'block', fontSize: 'xs', color: 'fg.muted' })}>
			Select a column to insert it into the expression above.
		</span>
	</div>
</div>
