<script lang="ts">
	interface DownloadConfigData {
		format: string;
		filename: string;
	}

	interface Props {
		config?: DownloadConfigData;
	}

	import { css, stepConfig, input } from '$lib/styles/panda';

	let { config = $bindable({ format: 'csv', filename: 'download' }) }: Props = $props();

	const formats = [
		{ value: 'csv', label: 'CSV' },
		{ value: 'json', label: 'JSON' },
		{ value: 'ndjson', label: 'NDJSON' },
		{ value: 'parquet', label: 'Parquet' },
		{ value: 'excel', label: 'Excel' },
		{ value: 'duckdb', label: 'DuckDB' }
	];
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
			for="download-filename"
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
			Filename
			<input
				id="download-filename"
				type="text"
				class={input()}
				bind:value={config.filename}
				placeholder="download"
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
			Name of the downloaded file (without extension)
		</p>
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
	>
		<label
			for="download-format"
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
			Format
			<select id="download-format" class={input()} bind:value={config.format}>
				{#each formats as fmt (fmt.value)}
					<option value={fmt.value}>{fmt.label}</option>
				{/each}
			</select>
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
			File format for download
		</p>
	</div>
</div>
