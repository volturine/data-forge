<script lang="ts">
	import type { LineageNode, LineageResponse, NodeKind, EdgeType } from '$lib/api/lineage';
	import { ArrowRight, ArrowDown, LayoutGrid, RotateCcw, ZoomIn, ZoomOut } from 'lucide-svelte';
	import { css, button } from '$lib/styles/panda';

	type LayoutMode = 'horizontal' | 'vertical' | 'grid';

	interface Props {
		lineage: LineageResponse;
		onnodeclick?: (node: LineageNode) => void;
		panelOffset?: number;
		showToolbar?: boolean;
		layoutMode?: LayoutMode;
		zoomPercent?: number;
	}

	let {
		lineage,
		onnodeclick,
		panelOffset = 0,
		showToolbar = true,
		layoutMode = $bindable<LayoutMode>('horizontal'),
		zoomPercent = $bindable(100)
	}: Props = $props();

	const nodes = $derived(lineage.nodes);
	const edges = $derived(lineage.edges);
	const nodeWidth = 240;
	const nodeHeight = 72;

	/* ---------- non-reactive position map ---------- */
	// eslint-disable-next-line svelte/prefer-svelte-reactivity -- intentionally non-reactive for layout computation
	const physicsMap = new Map<string, { x: number; y: number; vx: number; vy: number }>();

	/* ---------- reactive state ---------- */
	let positionSnapshot = $state<Record<string, { x: number; y: number }>>({});
	let dragId = $state<string | null>(null);
	let dragOffset: { x: number; y: number } | null = null;
	let pointerStart: { x: number; y: number } | null = null;
	let wasDrag = false;
	let viewWidth = $state(1200);
	let viewHeight = $state(720);

	/* ---------- pan/zoom state ---------- */
	let pan = $state({ x: 0, y: 0 });
	let scale = $state(1);
	let panning = $state(false);
	let panStart: { x: number; y: number; px: number; py: number } | null = null;
	let panPointerId = $state<number | null>(null);

	const layoutNodes = $derived.by(() => {
		const next = [] as Array<{
			id: string;
			label: string;
			meta: string | null;
			type: string;
			kind: NodeKind;
		}>;
		for (const node of nodes) {
			const meta =
				node.type === 'datasource'
					? node.branch
						? `${node.source_type ?? ''} • ${node.branch}`
						: (node.source_type ?? null)
					: (node.status ?? null);
			next.push({
				id: node.id,
				label: node.name,
				meta,
				type: node.type,
				kind: node.node_kind
			});
		}
		return next;
	});

	/* ---------- node kind → border color ---------- */
	const kindBorderColor: Record<NodeKind, string> = {
		source: 'var(--colors-accent-primary)',
		output: 'var(--colors-fg-success)',
		internal: 'var(--colors-fg-faint)',
		analysis: 'var(--colors-fg-warning)'
	};

	/* ---------- edge type → stroke config ---------- */
	const edgeStroke: Record<EdgeType, { color: string; dash: string }> = {
		uses: { color: 'var(--colors-canvas-lineage-edge)', dash: '' },
		produces: { color: 'var(--colors-fg-success)', dash: '' },
		chains: { color: 'var(--colors-fg-faint)', dash: '6 4' },
		consumes_internal: { color: 'var(--colors-fg-faint)', dash: '6 4' }
	};

	/* ---------- topological sort for tree layouts ---------- */
	function topoSort(): string[][] {
		// eslint-disable-next-line svelte/prefer-svelte-reactivity -- local algorithm data structure, not reactive state
		const adj = new Map<string, string[]>();
		// eslint-disable-next-line svelte/prefer-svelte-reactivity -- local algorithm data structure, not reactive state
		const indegree = new Map<string, number>();
		for (const node of layoutNodes) {
			adj.set(node.id, []);
			indegree.set(node.id, 0);
		}
		for (const edge of edges) {
			adj.get(edge.from)?.push(edge.to);
			indegree.set(edge.to, (indegree.get(edge.to) ?? 0) + 1);
		}
		const layers: string[][] = [];
		let queue = layoutNodes.filter((n) => (indegree.get(n.id) ?? 0) === 0).map((n) => n.id);
		// eslint-disable-next-line svelte/prefer-svelte-reactivity -- local algorithm data structure, not reactive state
		const visited = new Set<string>();
		while (queue.length > 0) {
			layers.push([...queue]);
			const next: string[] = [];
			for (const id of queue) {
				visited.add(id);
				for (const child of adj.get(id) ?? []) {
					const deg = (indegree.get(child) ?? 1) - 1;
					indegree.set(child, deg);
					if (deg === 0 && !visited.has(child)) next.push(child);
				}
			}
			queue = next;
		}
		const remaining = layoutNodes.filter((n) => !visited.has(n.id)).map((n) => n.id);
		if (remaining.length > 0) layers.push(remaining);
		return layers;
	}

	function applyDeterministicLayout(mode: 'horizontal' | 'vertical' | 'grid') {
		const gap = 280;
		const rowGap = 120;

		if (mode === 'grid') {
			const cols = Math.max(1, Math.ceil(Math.sqrt(layoutNodes.length)));
			let idx = 0;
			for (const node of layoutNodes) {
				const col = idx % cols;
				const row = Math.floor(idx / cols);
				physicsMap.set(node.id, {
					x: 80 + col * gap,
					y: 80 + row * (rowGap + nodeHeight),
					vx: 0,
					vy: 0
				});
				idx += 1;
			}
			return;
		}
		const layers = topoSort();
		for (let li = 0; li < layers.length; li += 1) {
			const layer = layers[li];
			for (let ni = 0; ni < layer.length; ni += 1) {
				const id = layer[ni];
				physicsMap.set(id, {
					x: mode === 'horizontal' ? 80 + li * gap : 80 + ni * gap,
					y:
						mode === 'horizontal'
							? 80 + ni * (rowGap + nodeHeight)
							: 80 + li * (rowGap + nodeHeight),
					vx: 0,
					vy: 0
				});
			}
		}
		syncSnapshot();
	}

	function getBounds(): { minX: number; minY: number; maxX: number; maxY: number } | null {
		if (!layoutNodes.length) return null;
		let minX = Number.POSITIVE_INFINITY;
		let minY = Number.POSITIVE_INFINITY;
		let maxX = Number.NEGATIVE_INFINITY;
		let maxY = Number.NEGATIVE_INFINITY;
		for (const node of layoutNodes) {
			const pos = physicsMap.get(node.id);
			if (!pos) continue;
			minX = Math.min(minX, pos.x);
			minY = Math.min(minY, pos.y);
			maxX = Math.max(maxX, pos.x + nodeWidth);
			maxY = Math.max(maxY, pos.y + nodeHeight);
		}
		if (!Number.isFinite(minX)) return null;
		return { minX, minY, maxX, maxY };
	}

	function resetViewToBounds(): void {
		const bounds = getBounds();
		if (!bounds) {
			pan = { x: 0, y: 0 };
			scale = 1;
			return;
		}
		const padding = 80;
		const contentWidth = bounds.maxX - bounds.minX + padding * 2;
		const contentHeight = bounds.maxY - bounds.minY + padding * 2;
		const usableWidth = Math.max(1, viewWidth - panelOffset);
		const sx = usableWidth / contentWidth;
		const sy = viewHeight / contentHeight;
		const nextScale = clamp(Math.min(sx, sy, 1), 0.2, 3);
		const scaledWidth = contentWidth * nextScale;
		const scaledHeight = contentHeight * nextScale;
		scale = nextScale;
		pan = {
			x: panelOffset + (usableWidth - scaledWidth) / 2 - (bounds.minX - padding) * nextScale,
			y: (viewHeight - scaledHeight) / 2 - (bounds.minY - padding) * nextScale
		};
	}

	function clamp(value: number, min: number, max: number) {
		return Math.max(min, Math.min(max, value));
	}

	function syncSnapshot() {
		const next: Record<string, { x: number; y: number }> = {};
		for (const node of layoutNodes) {
			const pos = physicsMap.get(node.id);
			if (!pos) continue;
			next[node.id] = { x: pos.x, y: pos.y };
		}
		positionSnapshot = next;
	}

	// DOM: $derived can't apply layout/reset bounds.
	$effect(() => {
		void layoutNodes;
		applyDeterministicLayout(layoutMode);
		resetViewToBounds();
	});

	/* ---------- canvas size (fixed, no expansion) ---------- */
	const canvasWidth = $derived.by(() => {
		const bounds = getBounds();
		if (!bounds) return viewWidth;
		return Math.max(viewWidth, bounds.maxX - bounds.minX + 160);
	});
	const canvasHeight = $derived.by(() => {
		const bounds = getBounds();
		if (!bounds) return viewHeight;
		return Math.max(viewHeight, bounds.maxY - bounds.minY + 160);
	});

	/* ---------- node interaction ---------- */
	function startDrag(event: PointerEvent, id: string) {
		const pos = physicsMap.get(id);
		if (!pos) return;
		dragId = id;
		dragOffset = {
			x: event.clientX / scale - pan.x / scale - pos.x,
			y: event.clientY / scale - pan.y / scale - pos.y
		};
		pointerStart = { x: event.clientX, y: event.clientY };
		wasDrag = false;
		(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
	}

	function moveDrag(event: PointerEvent) {
		if (!dragId || !dragOffset) return;
		if (pointerStart) {
			const dx = event.clientX - pointerStart.x;
			const dy = event.clientY - pointerStart.y;
			if (Math.sqrt(dx * dx + dy * dy) > 5) wasDrag = true;
		}
		const next = {
			x: event.clientX / scale - pan.x / scale - dragOffset.x,
			y: event.clientY / scale - pan.y / scale - dragOffset.y,
			vx: 0,
			vy: 0
		};
		physicsMap.set(dragId, next);
		syncSnapshot();
	}

	function stopDrag(event: PointerEvent) {
		if (!dragId) return;
		const clickedId = dragId;
		(event.currentTarget as HTMLElement).releasePointerCapture(event.pointerId);
		dragId = null;
		dragOffset = null;

		if (!wasDrag) {
			const node = nodes.find((n) => n.id === clickedId);
			if (node && onnodeclick) onnodeclick(node);
		}
		pointerStart = null;
		wasDrag = false;
	}

	/* ---------- pan ---------- */
	function startPan(event: PointerEvent) {
		if (event.button === 0) {
			const target = event.target as HTMLElement;
			if (target.closest('.lineage-node')) return;
		} else if (event.button !== 1 && event.button !== 2) {
			return;
		}
		event.preventDefault();
		panning = true;
		panStart = { x: event.clientX, y: event.clientY, px: pan.x, py: pan.y };
		panPointerId = event.pointerId;
		(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
	}

	function movePan(event: PointerEvent) {
		if (!panning || !panStart) return;
		pan = {
			x: panStart.px + (event.clientX - panStart.x),
			y: panStart.py + (event.clientY - panStart.y)
		};
	}

	function stopPan(event?: PointerEvent) {
		if (panPointerId !== null && event?.currentTarget instanceof HTMLElement) {
			const canvas = event.currentTarget;
			if (canvas.hasPointerCapture(panPointerId)) {
				canvas.releasePointerCapture(panPointerId);
			}
		}
		panning = false;
		panStart = null;
		panPointerId = null;
	}

	function handleWheel(event: WheelEvent) {
		event.preventDefault();
		const delta = event.deltaY > 0 ? 0.9 : 1.1;
		const next = clamp(scale * delta, 0.2, 3);
		const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
		const mx = event.clientX - rect.left;
		const my = event.clientY - rect.top;
		pan = {
			x: mx - ((mx - pan.x) / scale) * next,
			y: my - ((my - pan.y) / scale) * next
		};
		scale = next;
	}

	function resetView() {
		resetViewToBounds();
	}

	export function resetLineageView() {
		resetView();
	}

	function zoomIn() {
		const next = clamp(scale * 1.2, 0.2, 3);
		const cx = viewWidth / 2;
		const cy = viewHeight / 2;
		pan = {
			x: cx - ((cx - pan.x) / scale) * next,
			y: cy - ((cy - pan.y) / scale) * next
		};
		scale = next;
	}

	export function zoomInView() {
		zoomIn();
	}

	function zoomOut() {
		const next = clamp(scale * 0.8, 0.2, 3);
		const cx = viewWidth / 2;
		const cy = viewHeight / 2;
		pan = {
			x: cx - ((cx - pan.x) / scale) * next,
			y: cy - ((cy - pan.y) / scale) * next
		};
		scale = next;
	}

	export function zoomOutView() {
		zoomOut();
	}

	function setLayout(mode: LayoutMode) {
		layoutMode = mode;
		resetView();
		applyDeterministicLayout(mode);
	}

	// Subscription: $derived can't sync zoom percent.
	$effect(() => {
		zoomPercent = Math.round(scale * 100);
	});

	const _transform = $derived(`translate(${pan.x}px, ${pan.y}px) scale(${scale})`);

	function setPosition(node: HTMLElement, coords: { x: number; y: number }) {
		node.style.left = `${coords.x}px`;
		node.style.top = `${coords.y}px`;
		return {
			update(next: { x: number; y: number }) {
				node.style.left = `${next.x}px`;
				node.style.top = `${next.y}px`;
			}
		};
	}

	const kindLabel: Record<NodeKind, string> = {
		source: 'Source',
		output: 'Output',
		internal: 'Internal',
		analysis: 'Analysis'
	};
</script>

{#if nodes.length === 0}
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
{:else}
	<div class={css({ display: 'flex', height: '100%', flexDirection: 'column' })}>
		{#if showToolbar}
			<!-- Toolbar -->
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					gap: '1',
					borderBottomWidth: '1',
					backgroundColor: 'bg.primary',
					paddingX: '3',
					paddingY: '1.5'
				})}
			>
				<span class={css({ marginRight: '2', fontSize: 'xs', color: 'fg.muted' })}> Layout </span>
				<button
					class={layoutMode === 'horizontal'
						? button({ variant: 'primary', size: 'sm' })
						: button({ variant: 'ghost', size: 'sm' })}
					onclick={() => setLayout('horizontal')}
					title="Horizontal tree layout"
				>
					<ArrowRight size={14} />
					<span class={css({ fontSize: 'xs' })}>Horizontal</span>
				</button>
				<button
					class={layoutMode === 'vertical'
						? button({ variant: 'primary', size: 'sm' })
						: button({ variant: 'ghost', size: 'sm' })}
					onclick={() => setLayout('vertical')}
					title="Vertical tree layout"
				>
					<ArrowDown size={14} />
					<span class={css({ fontSize: 'xs' })}>Vertical</span>
				</button>
				<button
					class={layoutMode === 'grid'
						? button({ variant: 'primary', size: 'sm' })
						: button({ variant: 'ghost', size: 'sm' })}
					onclick={() => setLayout('grid')}
					title="Grid layout"
				>
					<LayoutGrid size={14} />
					<span class={css({ fontSize: 'xs' })}>Grid</span>
				</button>

				<div
					class={css({
						marginX: '2',
						height: 'iconSm',
						width: 'px',
						backgroundColor: 'bg.muted'
					})}
				></div>

				<button class={button({ variant: 'ghost', size: 'sm' })} onclick={zoomIn} title="Zoom in">
					<ZoomIn size={14} />
				</button>
				<button class={button({ variant: 'ghost', size: 'sm' })} onclick={zoomOut} title="Zoom out">
					<ZoomOut size={14} />
				</button>
				<button
					class={button({ variant: 'ghost', size: 'sm' })}
					onclick={resetView}
					title="Reset view"
				>
					<RotateCcw size={14} />
				</button>

				<span class={css({ marginLeft: 'auto', fontSize: 'xs', color: 'fg.muted' })}>
					{zoomPercent}%
				</span>
			</div>
		{/if}

		<!-- Canvas -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			class={css({
				isolation: 'isolate',
				position: 'relative',
				flex: '1',
				overflow: 'hidden',
				backgroundColor: 'bg.secondary'
			})}
			data-testid="lineage-canvas"
			bind:clientWidth={viewWidth}
			bind:clientHeight={viewHeight}
			onpointerdown={startPan}
			onpointermove={movePan}
			onpointerup={(event) => stopPan(event)}
			onpointercancel={(event) => stopPan(event)}
			onwheel={handleWheel}
			oncontextmenu={(e) => e.preventDefault()}
		>
			<div
				class={css({
					position: 'absolute',
					inset: '0',
					transformOrigin: 'top left',
					willChange: 'transform'
				})}
				style:transform={_transform}
			>
				<!-- Transformed layer -->
				<svg
					class={css({ pointerEvents: 'none', position: 'absolute', inset: '0' })}
					width={canvasWidth}
					height={canvasHeight}
				>
					<defs>
						<marker
							id="lineage-arrow"
							markerWidth="10"
							markerHeight="10"
							refX="8"
							refY="5"
							orient="auto"
						>
							<path d="M0,0 L10,5 L0,10 Z" fill="var(--colors-fg-primary)" />
						</marker>
						<marker
							id="lineage-arrow-success"
							markerWidth="10"
							markerHeight="10"
							refX="8"
							refY="5"
							orient="auto"
						>
							<path d="M0,0 L10,5 L0,10 Z" fill="var(--colors-fg-success)" />
						</marker>
						<marker
							id="lineage-arrow-faint"
							markerWidth="10"
							markerHeight="10"
							refX="8"
							refY="5"
							orient="auto"
						>
							<path d="M0,0 L10,5 L0,10 Z" fill="var(--colors-fg-faint)" />
						</marker>
					</defs>
					{#each edges as edge (edge.from + edge.to)}
						{@const from = positionSnapshot[edge.from]}
						{@const to = positionSnapshot[edge.to]}
						{@const stroke = edgeStroke[edge.type] ?? edgeStroke.uses}
						{@const marker =
							edge.type === 'produces'
								? 'url(#lineage-arrow-success)'
								: edge.type === 'chains' || edge.type === 'consumes_internal'
									? 'url(#lineage-arrow-faint)'
									: 'url(#lineage-arrow)'}
						{#if from && to}
							<path
								d={`M ${from.x + nodeWidth} ${from.y + nodeHeight / 2} C ${from.x + nodeWidth + 60} ${from.y + nodeHeight / 2} ${to.x - 60} ${to.y + nodeHeight / 2} ${to.x} ${to.y + nodeHeight / 2}`}
								fill="none"
								stroke={stroke.color}
								stroke-width="1.5"
								stroke-dasharray={stroke.dash}
								marker-end={marker}
							/>
						{/if}
					{/each}
				</svg>

				{#each layoutNodes as node (node.id)}
					{@const pos = positionSnapshot[node.id]}
					{@const isInternal = node.kind === 'internal'}
					{#if pos}
						<div
							class={[
								'lineage-node',
								css({
									width: '240px',
									background: 'canvas.lineageNode',
									transition: 'box-shadow 160ms ease, transform 160ms ease',
									_active: {
										cursor: 'grabbing'
									},
									position: 'absolute',
									display: 'flex',
									flexDirection: 'column',
									gap: '1',
									borderWidth: '1',
									paddingX: '4',
									paddingY: '3',
									boxShadow: 'sm',
									borderLeftWidth: isInternal ? '1' : '3'
								})
							]}
							style:border-left-color={kindBorderColor[node.kind]}
							style:border-style={isInternal ? 'dashed' : 'solid'}
							use:setPosition={pos}
							onpointerdown={(event) => {
								if (event.button === 0) startDrag(event, node.id);
							}}
							onpointermove={moveDrag}
							onpointerup={stopDrag}
							onpointercancel={stopDrag}
							role="button"
							tabindex="0"
							aria-label={`${node.kind} ${node.label}`}
						>
							<div
								class={css({
									fontSize: 'xs',
									textTransform: 'uppercase',
									letterSpacing: 'wide',
									color: isInternal ? 'fg.faint' : 'fg.muted'
								})}
							>
								{kindLabel[node.kind]}
							</div>
							<div
								class={css({
									overflow: 'hidden',
									textOverflow: 'ellipsis',
									whiteSpace: 'nowrap',
									fontSize: 'sm',
									fontWeight: 'semibold',
									color: isInternal ? 'fg.tertiary' : 'fg.primary'
								})}
							>
								{node.label}
							</div>
							{#if node.meta}
								<div
									class={css({ fontSize: 'xs', color: isInternal ? 'fg.faint' : 'fg.tertiary' })}
								>
									{node.meta}
								</div>
							{/if}
						</div>
					{/if}
				{/each}
			</div>
		</div>
	</div>
{/if}
