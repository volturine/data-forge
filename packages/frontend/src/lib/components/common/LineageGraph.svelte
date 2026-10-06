<script lang="ts">
	import { SvelteFlow, MiniMap, type Node, type Edge, type OnMove } from '@xyflow/svelte';
	import type { LineageNode, LineageResponse } from '$lib/api/lineage';
	import LineageNodeView from './LineageNode.svelte';
	import LineageFlowController, { type LineageFlowApi } from './LineageFlowController.svelte';
	import {
		buildFlowGraph,
		computeLineageLayout,
		type LineageFlowNode,
		type LineageLayoutMode
	} from './lineage-flow';
	import { css } from '$lib/styles/panda';
	import '@xyflow/svelte/dist/style.css';
	import '$lib/styles/xyflow-theme.css';

	interface Props {
		lineage: LineageResponse;
		onnodeclick?: (node: LineageNode) => void;
		layoutMode?: LineageLayoutMode;
		zoomPercent?: number;
	}

	let {
		lineage,
		onnodeclick,
		layoutMode = $bindable<LineageLayoutMode>('horizontal'),
		// The zoom label lives in the page toolbar; the value is written back
		// through the binding and never read inside this component.
		// eslint-disable-next-line no-useless-assignment
		zoomPercent = $bindable(100)
	}: Props = $props();

	const nodeTypes = { lineage: LineageNodeView };

	let flowNodes = $state.raw<LineageFlowNode[]>([]);
	let flowEdges = $state.raw<Edge[]>([]);
	let flowApi: LineageFlowApi | null = $state(null);
	let layoutSeq = 0;

	function syncZoom() {
		const zoom = flowApi?.getZoom();
		if (zoom !== undefined) zoomPercent = Math.round(zoom * 100);
	}

	const handleMove: OnMove = (_event, viewport) => {
		zoomPercent = Math.round(viewport.zoom * 100);
	};

	function handleNodeClick(node: Node) {
		const lineageNode = lineage.nodes.find((candidate) => candidate.id === node.id);
		if (lineageNode && onnodeclick) onnodeclick(lineageNode);
	}

	async function runLayout() {
		const seq = ++layoutSeq;
		const response = lineage;
		const mode = layoutMode;
		if (response.nodes.length === 0) {
			flowNodes = [];
			flowEdges = [];
			return;
		}
		const positions = await computeLineageLayout(response, mode);
		if (seq !== layoutSeq) return;
		const graph = buildFlowGraph(response, positions, mode);
		flowNodes = graph.nodes;
		flowEdges = graph.edges;
		flowApi?.fitView();
		syncZoom();
	}

	$effect(() => {
		void lineage;
		void layoutMode;
		void runLayout();
	});

	export function resetLineageView() {
		void flowApi?.fitView();
		syncZoom();
	}

	export async function zoomInView() {
		await flowApi?.zoomIn();
		syncZoom();
	}

	export async function zoomOutView() {
		await flowApi?.zoomOut();
		syncZoom();
	}
</script>

<div
	class={css({
		height: '100%',
		isolation: 'isolate',
		position: 'relative',
		overflow: 'hidden',
		backgroundColor: 'bg.secondary'
	})}
	data-testid="lineage-canvas"
>
	{#if lineage.nodes.length > 0}
		<SvelteFlow
			bind:nodes={flowNodes}
			bind:edges={flowEdges}
			{nodeTypes}
			fitView
			minZoom={0.2}
			maxZoom={3}
			nodesConnectable={false}
			onlyRenderVisibleElements
			onnodeclick={({ node }) => handleNodeClick(node)}
			onmove={handleMove}
		>
			<LineageFlowController
				onready={(api) => {
					flowApi = api;
					syncZoom();
				}}
			/>
			<MiniMap
				position="bottom-left"
				pannable
				zoomable
				nodeColor={(node) => {
					const kind = (node.data as { kind?: string } | undefined)?.kind;
					return kind === 'output'
						? 'var(--colors-fg-success)'
						: kind === 'analysis'
							? 'var(--colors-fg-warning)'
							: kind === 'source'
								? 'var(--colors-accent-primary)'
								: 'var(--colors-fg-faint)';
				}}
			/>
		</SvelteFlow>
	{:else}
		<div
			class={css({
				display: 'flex',
				height: '100%',
				alignItems: 'center',
				justifyContent: 'center'
			})}
		>
			<p class={css({ fontSize: 'sm', color: 'fg.tertiary' })}>No lineage data available.</p>
		</div>
	{/if}
</div>
