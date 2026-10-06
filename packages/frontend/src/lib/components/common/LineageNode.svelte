<script lang="ts">
	import { Handle, Position, type NodeProps } from '@xyflow/svelte';
	import type { Node } from '@xyflow/svelte';
	import type { LineageNodeData } from './lineage-flow';
	import { css } from '$lib/styles/panda';

	type LineageNodeProps = NodeProps<Node<LineageNodeData, 'lineage'>>;

	let { data }: LineageNodeProps = $props();

	const kindLabel: Record<LineageNodeData['kind'], string> = {
		source: 'Source',
		output: 'Output',
		internal: 'Internal',
		analysis: 'Analysis'
	};

	const kindBorderColor: Record<LineageNodeData['kind'], string> = {
		source: 'var(--colors-accent-primary)',
		output: 'var(--colors-fg-success)',
		internal: 'var(--colors-fg-faint)',
		analysis: 'var(--colors-fg-warning)'
	};
</script>

<Handle id="left" type="target" position={Position.Left} style="opacity: 0" isConnectable={false} />
<Handle id="top" type="target" position={Position.Top} style="opacity: 0" isConnectable={false} />
<Handle
	id="right"
	type="source"
	position={Position.Right}
	style="opacity: 0"
	isConnectable={false}
/>
<Handle
	id="bottom"
	type="source"
	position={Position.Bottom}
	style="opacity: 0"
	isConnectable={false}
/>

<div
	class={[
		'lineage-node',
		css({
			display: 'flex',
			flexDirection: 'column',
			gap: '1',
			width: '100%',
			height: '100%',
			boxSizing: 'border-box',
			overflow: 'hidden',
			borderWidth: '1',
			borderLeftWidth: data.kind === 'internal' ? '1' : '3',
			paddingX: '4',
			paddingY: '3',
			background: 'canvas.lineageNode',
			boxShadow: 'sm'
		})
	]}
	style:border-left-color={kindBorderColor[data.kind]}
	style:border-style={data.kind === 'internal' ? 'dashed' : 'solid'}
	role="button"
	tabindex="0"
	aria-label={`${data.kind} ${data.label}`}
	onkeydown={(event) => {
		if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			event.currentTarget.click();
		}
	}}
>
	<div
		class={css({
			fontSize: 'xs',
			textTransform: 'uppercase',
			letterSpacing: 'wide',
			color: data.kind === 'internal' ? 'fg.faint' : 'fg.muted'
		})}
	>
		{kindLabel[data.kind]}
	</div>
	<div
		class={css({
			overflow: 'hidden',
			textOverflow: 'ellipsis',
			whiteSpace: 'nowrap',
			fontSize: 'sm',
			fontWeight: 'semibold',
			color: data.kind === 'internal' ? 'fg.tertiary' : 'fg.primary'
		})}
	>
		{data.label}
	</div>
	{#if data.meta}
		<div
			class={css({ fontSize: 'xs', color: data.kind === 'internal' ? 'fg.faint' : 'fg.tertiary' })}
		>
			{data.meta}
		</div>
	{/if}
</div>
