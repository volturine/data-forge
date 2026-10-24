import ElkConstructor from 'elkjs/lib/elk-api.js';
import elkWorkerUrl from 'elkjs/lib/elk-worker.min.js?url';
import { MarkerType } from '@xyflow/svelte';
import type { EdgeType, LineageResponse, NodeKind } from '#lib/api/lineage.js';

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

const EDGE_STYLES: Record<EdgeType, { color: string; dash: string }> = {
	uses: { color: 'var(--colors-canvas-lineage-edge)', dash: '' },
	produces: { color: 'var(--colors-fg-success)', dash: '' },
	chains: { color: 'var(--colors-fg-faint)', dash: '6 4' },
	consumes_internal: { color: 'var(--colors-fg-faint)', dash: '6 4' }
};

export const LINEAGE_KIND_LABELS: Record<NodeKind, string> = {
	source: 'Source',
	output: 'Output',
	internal: 'Internal',
	analysis: 'Analysis'
};

type ElkInstance = InstanceType<typeof ElkConstructor>;

interface ElkWorkerSession {
	elk: ElkInstance | null;
	worker: Worker | null;
	abortController: AbortController;
	error: Error | null;
	terminated: boolean;
	onWorkerFailure: (event: Event) => void;
}

function getAbortError(signal: AbortSignal): Error {
	return signal.reason instanceof Error ? signal.reason : new Error('ELK layout was interrupted.');
}

function raceWithAbort<T>(operation: Promise<T>, signal: AbortSignal): Promise<T> {
	if (signal.aborted) return Promise.reject(getAbortError(signal));

	let onAbort: (() => void) | undefined;
	const aborted = new Promise<T>((_resolve, reject) => {
		onAbort = () => reject(getAbortError(signal));
		signal.addEventListener('abort', onAbort, { once: true });
	});

	return Promise.race([operation, aborted]).finally(() => {
		if (onAbort) signal.removeEventListener('abort', onAbort);
	});
}

function makeWorkerError(event: Event): Error {
	const detail =
		'message' in event && typeof event.message === 'string' ? event.message.trim() : '';
	const cause = 'error' in event ? event.error : undefined;
	const message = detail ? `ELK worker ${event.type}: ${detail}` : `ELK worker ${event.type}.`;
	return new Error(message, { cause });
}

function terminateWorkerSession(session: ElkWorkerSession) {
	if (session.terminated) return;
	session.terminated = true;
	const worker = session.worker;
	session.worker = null;
	if (!worker) return;
	worker.removeEventListener('error', session.onWorkerFailure);
	worker.removeEventListener('messageerror', session.onWorkerFailure);
	worker.onmessage = null;
	worker.terminate();
}

/**
 * Creates a per-graph layout engine. ELK starts only for layered layouts and
 * runs in its own worker so graph layout does not block the UI thread.
 */
export function createLineageLayoutEngine() {
	let workerSession: ElkWorkerSession | null = null;
	let disposed = false;

	function getWorkerSession(): ElkWorkerSession {
		if (disposed) throw new Error('Cannot use a disposed lineage layout engine.');
		if (workerSession) return workerSession;

		const session: ElkWorkerSession = {
			elk: null,
			worker: null,
			abortController: new AbortController(),
			error: null,
			terminated: false,
			onWorkerFailure: () => {}
		};
		session.onWorkerFailure = (event) => {
			event.preventDefault();
			if (session.error || session.terminated) return;
			session.error = makeWorkerError(event);
			if (workerSession === session) workerSession = null;
			session.abortController.abort(session.error);
			terminateWorkerSession(session);
		};

		try {
			session.elk = new ElkConstructor({
				workerFactory: () => {
					const worker = new Worker(elkWorkerUrl);
					session.worker = worker;
					worker.addEventListener('error', session.onWorkerFailure);
					worker.addEventListener('messageerror', session.onWorkerFailure);
					return worker;
				}
			});
			if (!session.worker) throw new Error('ELK did not create its layout worker.');
			if (session.abortController.signal.aborted)
				throw getAbortError(session.abortController.signal);
			workerSession = session;
			return session;
		} catch (error) {
			terminateWorkerSession(session);
			throw error;
		}
	}

	async function compute(
		response: LineageResponse,
		mode: LineageLayoutMode
	): Promise<Map<string, { x: number; y: number }>> {
		if (response.nodes.length === 0) return new Map();
		if (mode === 'grid') return gridLayout(response.nodes);

		const session = getWorkerSession();
		const workerEngine = session.elk;
		if (!workerEngine) throw new Error('ELK layout worker is unavailable.');
		const layout = await raceWithAbort(
			workerEngine.layout(
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
			),
			session.abortController.signal
		);

		const positions = new Map<string, { x: number; y: number }>();
		for (const child of layout.children ?? []) {
			if (child.x === undefined || child.y === undefined) continue;
			positions.set(child.id, { x: child.x, y: child.y });
		}
		return positions;
	}

	function dispose() {
		disposed = true;
		const session = workerSession;
		workerSession = null;
		if (!session || session.terminated) return;
		session.error ??= new Error('Lineage layout engine was disposed.');
		session.abortController.abort(session.error);
		terminateWorkerSession(session);
	}

	return { compute, dispose };
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
		const stroke = EDGE_STYLES[edge.type];
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
