<script lang="ts" module>
	export type CsvConfig = {
		delimiter: string;
		quote_char: string;
		has_header: boolean;
		skip_rows: number;
		encoding: string;
	};
</script>

<script lang="ts">
	import { Loader, Save } from '@lucide/svelte';
	import { css, input } from '$lib/styles/panda';

	interface Props {
		datasourceId: string;
		config?: CsvConfig;
		pending: boolean;
		hasChanges: boolean;
		onDirty: () => void;
		onSave: () => Promise<void> | void;
	}

	let {
		datasourceId,
		config = $bindable({
			delimiter: ',',
			quote_char: '"',
			has_header: true,
			skip_rows: 0,
			encoding: 'utf8'
		}),
		pending,
		hasChanges,
		onDirty,
		onSave
	}: Props = $props();

	function handleCsvConfigChange<K extends keyof CsvConfig>(key: K, value: CsvConfig[K]) {
		config = { ...config, [key]: value };
		onDirty();
	}
</script>

<div class={css({ display: 'flex', flexDirection: 'column', gap: '4' })}>
	<h3 class={css({ margin: '0', fontSize: 'sm', fontWeight: 'semibold' })}>CSV Options</h3>

	<div
		class={css({
			display: 'grid',
			gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
			gap: '3'
		})}
	>
		<div class={css({ display: 'flex', flexDirection: 'column', gap: '1.5' })}>
			<label
				for="csv-delimiter-{datasourceId}"
				class={css({
					display: 'block',
					fontSize: 'xs',
					fontWeight: 'medium',
					color: 'fg.secondary',
					textTransform: 'none',
					letterSpacing: 'normal',
					marginBottom: '1.5'
				})}>Delimiter</label
			>
			<select
				id="csv-delimiter-{datasourceId}"
				value={config.delimiter}
				onchange={(e) => handleCsvConfigChange('delimiter', e.currentTarget.value)}
				class={input()}
			>
				<option value=",">Comma (,)</option>
				<option value=";">Semicolon (;)</option>
				<option value="&#9;">Tab</option>
				<option value="|">Pipe (|)</option>
				<option value=" ">Space</option>
			</select>
		</div>

		<div class={css({ display: 'flex', flexDirection: 'column', gap: '1.5' })}>
			<label
				for="csv-quote-{datasourceId}"
				class={css({
					display: 'block',
					fontSize: 'xs',
					fontWeight: 'medium',
					color: 'fg.secondary',
					textTransform: 'none',
					letterSpacing: 'normal',
					marginBottom: '1.5'
				})}>Quote</label
			>
			<select
				id="csv-quote-{datasourceId}"
				value={config.quote_char}
				onchange={(e) => handleCsvConfigChange('quote_char', e.currentTarget.value)}
				class={input()}
			>
				<option value="&quot;">Double Quote (")</option>
				<option value="'">Single Quote (')</option>
				<option value="">None</option>
			</select>
		</div>

		<div class={css({ display: 'flex', flexDirection: 'column', gap: '1.5' })}>
			<label
				for="csv-encoding-{datasourceId}"
				class={css({
					display: 'block',
					fontSize: 'xs',
					fontWeight: 'medium',
					color: 'fg.secondary',
					textTransform: 'none',
					letterSpacing: 'normal',
					marginBottom: '1.5'
				})}>Encoding</label
			>
			<select
				id="csv-encoding-{datasourceId}"
				value={config.encoding}
				onchange={(e) => handleCsvConfigChange('encoding', e.currentTarget.value)}
				class={input()}
			>
				<option value="utf8">UTF-8</option>
				<option value="utf8-lossy">UTF-8 (lossy)</option>
				<option value="latin1">Latin-1</option>
				<option value="ascii">ASCII</option>
			</select>
		</div>

		<div class={css({ display: 'flex', flexDirection: 'column', gap: '1.5' })}>
			<label
				for="csv-skip-rows-{datasourceId}"
				class={css({
					display: 'block',
					fontSize: 'xs',
					fontWeight: 'medium',
					color: 'fg.secondary',
					textTransform: 'none',
					letterSpacing: 'normal',
					marginBottom: '1.5'
				})}>Skip Rows</label
			>
			<input
				id="csv-skip-rows-{datasourceId}"
				type="number"
				min="0"
				value={config.skip_rows}
				oninput={(e) => handleCsvConfigChange('skip_rows', parseInt(e.currentTarget.value) || 0)}
				class={input()}
			/>
		</div>
	</div>

	<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
		<input
			id="csv-header-{datasourceId}"
			type="checkbox"
			checked={config.has_header}
			onchange={(e) => handleCsvConfigChange('has_header', e.currentTarget.checked)}
			class={css({ height: 'iconSm', width: 'iconSm', cursor: 'pointer' })}
		/>
		<label
			for="csv-header-{datasourceId}"
			class={css({
				display: 'block',
				fontSize: 'sm',
				fontWeight: 'medium',
				color: 'fg.secondary',
				textTransform: 'none',
				letterSpacing: 'normal',
				margin: '0'
			})}>First row is header</label
		>
	</div>

	{#if hasChanges}
		<button
			class={css({
				borderWidth: '1',
				backgroundColor: 'accent.primary',
				color: 'fg.inverse',
				'&:hover:not(:disabled)': { opacity: '0.9' },
				display: 'flex',
				alignItems: 'center',
				width: '100%',
				justifyContent: 'center',
				gap: '2'
			})}
			onclick={onSave}
			disabled={pending}
		>
			{#if pending}
				<Loader size={16} class={css({ animation: 'spin 1s linear infinite' })} />
				Saving...
			{:else}
				<Save size={16} />
				Save Changes
			{/if}
		</button>
	{/if}
</div>
