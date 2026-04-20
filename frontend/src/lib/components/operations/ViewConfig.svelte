<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import { css, input, stepConfig } from '$lib/styles/panda';

	interface ViewConfigData {
		rowLimit: number;
	}

	interface Props {
		schema: Schema;
		config?: ViewConfigData;
	}

	let { schema: _schema, config = $bindable({ rowLimit: 100 }) }: Props = $props();
</script>

<div class={stepConfig()}>
	<div
		class={css({
			marginBottom: '0',
			paddingBottom: '5',
			backgroundColor: 'transparent',

			border: 'none'
		})}
	>
		<label
			for="row-limit"
			class={css({
				display: 'flex',
				flexDirection: 'column',
				gap: '3',
				fontSize: 'xs2',
				fontWeight: 'semibold',
				color: 'fg.muted',
				marginBottom: '0',
				textTransform: 'none',
				letterSpacing: 'normal'
			})}
		>
			Preview Rows
			<input
				id="row-limit"
				type="number"
				class={input()}
				bind:value={config.rowLimit}
				min="10"
				max="1000"
				step="10"
			/>
		</label>
		<p
			class={css({
				marginTop: '2',
				marginBottom: '0',
				fontSize: 'sm',
				fontWeight: 'normal',
				color: 'fg.tertiary'
			})}
		>
			Number of rows to display (10-1000)
		</p>
	</div>
</div>
