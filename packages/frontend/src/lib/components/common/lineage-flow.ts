import ElkConstructor from 'elkjs/lib/elk.bundled.js';
import { MarkerType } from '@xyflow/svelte';
import type { EdgeType, LineageResponse, NodeKind } from '$lib/api/lineage';

export const LINEAGE_NODE_WIDTH = 240;
export const LINEAGE_NODE_HEIGHT = 72;

export type LineageLayoutMode = 'horizontal' | 'vertical' | 'grid';

export interface LineageNodeData extends Record<string, unknown> {
	kind: NodeKind;
	name: string;
	meta: string | null;
}

export interface LineageFlowNode {
	id: string;
	type: 'lineage';
	position: { x: number; y: number };
	width: number;
	height: number;
	data: LineageNodeData;
}

export interface LineageFlowEdge {
	id: string;
	source: string;
	target: string;
	type: 'default';
	sourceHandle: string;
	targetHandle: string;
	markerEnd: { type: MarkerType; color: string };
	style: string;
}

// ELK is constructed lazily: instantiating at module scope runs during SSR
// prerender, where no Worker implementation exists.
let elk: InstanceType<typeof ElkConstructor> | null = null;

function getElk(): InstanceType<typeof ElkConstructor> {
	elk ??= new ElkConstructor();
	return elk;
}

const EDGE_STYLES: Record<EdgeType, { color: string; dash: string }> = {
	uses: { color: 'var(--colors-canvas-lineage-edge)', dash: '' },
	produces: { color: 'var(--colors-fg-success)', dash: '' },
	chains: { color: 'var(--colors-fg-faint)', dash: '6 4' },
	consumes_internal: { color: 'var(--colors-fg-faint)', dash: '6 4' }
};

/**
 * Lays out the lineage graph. Horizontal/vertical use ELK's layered
 * algorithm; grid keeps the deterministic column-major placement.
 */
export async function computeLineageLayout(
	response: LineageResponse,
	mode: LineageLayoutMode
): Promise<Map<string, { x: number; y: number }>> {
	if (response.nodes.length === 0) return new Map();
	if (mode === 'grid') return gridLayout(response.nodes);

	const layout = await getElk().layout(
		{
			id: 'root',
			children: response.nodes.map((node) => ({
				id: node.id,
				width: LINEAGE_NODE_WIDTH,
				height: LINEAGE_NODE_HEIGHT
			})),
			edges: response.edges.map((edge) => ({
				id: `${edge.from}->${edge.to}:${edge.type}`,
				sources: [edge.from],
				targets: [edge.to]
			}))
		},
		{
			layoutOptions: {
				'elk.algorithm': 'layered',
				'elk.direction': mode === 'vertical' ? 'DOWN' : 'RIGHT',
				'elk.layered.spacing.nodeNode': '48',
				'elk.layered.spacing.nodeNodeBetweenLayers': '40'
			}
		}
	);

	const positions = new Map<string, { x: number; y: number }>();
	for (const child of layout.children ?? []) {
		if (child.x === undefined || child.y === undefined) continue;
		positions.set(child.id, { x: child.x, y: child.y });
	}
	return positions;
}

function gridLayout(nodes: LineageResponse['nodes']): Map<string, { x: number; y: number }> {
	const cols = Math.max(1, Math.ceil(Math.sqrt(nodes.length)));
	const gap = 280;
	const rowGap = 120;
	const positions = new Map<string, { x: number; y: number }>();
	for (const [index, node] of nodes.entries()) {
		positions.set(node.id, {
			x: 80 + (index % cols) * gap,
			y: 80 + Math.floor(index / cols) * (rowGap + LINEAGE_NODE_HEIGHT)
		});
	}
	return positions;
}

/**
 * Maps the lineage API response onto Svelte Flow node/edge objects with the
 * given positions. Vertical layouts anchor edges top/bottom, everything else
 * left/right (grid has no flow direction and reuses horizontal anchors).
 */
export function buildFlowGraph(
	response: LineageResponse,
	positions: Map<string, { x: number; y: number }>,
	mode: LineageLayoutMode
): { nodes: LineageFlowNode[]; edges: LineageFlowEdge[] } {
	const vertical = mode === 'vertical';
	const handles = vertical
		? { source: 'bottom', target: 'top' }
		: { source: 'right', target: 'left' };

	const nodes: LineageFlowNode[] = [];
	for (const node of response.nodes) {
		const position = positions.get(node.id);
		if (!position) continue;
		const meta =
			node.type === 'datasource'
				? node.branch
					? `${node.source_type ?? ''} • ${node.branch}`
					: (node.source_type ?? null)
				: (node.status ?? null);
		nodes.push({
			id: node.id,
			type: 'lineage',
			position,
			width: LINEAGE_NODE_WIDTH,
			height: LINEAGE_NODE_HEIGHT,
			data: { kind: node.node_kind, name: node.name, meta }
		});
	}

	const seen = new Set<string>();
	const edges: LineageFlowEdge[] = [];
	for (const edge of response.edges) {
		const id = `${edge.from}->${edge.to}:${edge.type}`;
		if (seen.has(id)) continue;
		if (!positions.has(edge.from) || !positions.has(edge.to)) continue;
		seen.add(id);
		const stroke = EDGE_STYLES[edge.type] ?? EDGE_STYLES.uses;
		edges.push({
			id,
			source: edge.from,
			target: edge.to,
			type: 'default',
			sourceHandle: handles.source,
			targetHandle: handles.target,
			markerEnd: { type: MarkerType.ArrowClosed, color: stroke.color },
			style: `stroke: ${stroke.color}; stroke-width: 1.5;`.concat(
				stroke.dash ? ` stroke-dasharray: ${stroke.dash};` : ''
			)
		});
	}
	return { nodes, edges };
}
