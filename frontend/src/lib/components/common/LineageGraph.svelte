<script lang="ts">
	import type { LineageResponse } from '$lib/api/lineage';

	interface Props {
		lineage: LineageResponse;
	}

	let { lineage }: Props = $props();

	const nodes = $derived(lineage.nodes);
	const edges = $derived(lineage.edges);
	const nodeWidth = 240;
	const nodeHeight = 72;
	const baseSpacing = 220;
	const chargeStrength = 3400;
	const linkStrength = 0.05;
	const damping = 0.85;
	const maxVelocity = 8;
	const maxIterations = 240;
	const minVelocity = 0.08;

	// Plain Map for physics — NOT reactive. Mutations during simulation do not trigger Svelte updates.
	// eslint-disable-next-line svelte/prefer-svelte-reactivity -- intentionally non-reactive for physics simulation
	const physicsMap = new Map<string, { x: number; y: number; vx: number; vy: number }>();

	// Reactive snapshot — only updated when simulation settles or drag ends.
	let positionSnapshot = $state<Record<string, { x: number; y: number }>>({});

	let dragId = $state<string | null>(null);
	let dragOffset: { x: number; y: number } | null = null;
	let viewSize = $state({ width: 1200, height: 720 });

	// Non-reactive simulation state — no need for Svelte tracking on raf/iteration/running.
	let rafId: number | null = null;
	let running = false;
	let iteration = 0;

	const layoutNodes = $derived.by(() => {
		const next = [] as Array<{ id: string; label: string; meta: string | null; type: string }>;
		for (const node of nodes) {
			next.push({
				id: node.id,
				label: node.name,
				meta: node.type === 'datasource' ? (node.source_type ?? null) : (node.status ?? null),
				type: node.type
			});
		}
		return next;
	});

	function seedPositions() {
		const ids = new Set(layoutNodes.map((node) => node.id));
		for (const id of Array.from(physicsMap.keys())) {
			if (!ids.has(id)) physicsMap.delete(id);
		}
		let idx = 0;
		for (const node of layoutNodes) {
			const existing = physicsMap.get(node.id);
			if (existing) {
				idx += 1;
				continue;
			}
			const col = idx % 3;
			const row = Math.floor(idx / 3);
			physicsMap.set(node.id, {
				x: 120 + col * baseSpacing,
				y: 120 + row * baseSpacing * 0.6,
				vx: 0,
				vy: 0
			});
			idx += 1;
		}
	}

	function clamp(value: number, min: number, max: number) {
		return Math.max(min, Math.min(max, value));
	}

	function applyForces() {
		if (!layoutNodes.length) return;
		seedPositions();
		const positions = layoutNodes
			.map((node) => {
				const pos = physicsMap.get(node.id);
				if (!pos) return null;
				return { id: node.id, ...pos };
			})
			.filter((pos): pos is { id: string; x: number; y: number; vx: number; vy: number } => !!pos);

		const edgesList = edges.map((edge) => ({ from: edge.from, to: edge.to }));
		for (const pos of positions) {
			if (dragId === pos.id) continue;
			pos.vx *= damping;
			pos.vy *= damping;
		}

		for (let i = 0; i < positions.length; i += 1) {
			const a = positions[i];
			for (let j = i + 1; j < positions.length; j += 1) {
				const b = positions[j];
				const dx = a.x - b.x;
				const dy = a.y - b.y;
				const dist = Math.sqrt(dx * dx + dy * dy) + 0.01;
				const force = chargeStrength / (dist * dist);
				const fx = (dx / dist) * force;
				const fy = (dy / dist) * force;
				if (dragId !== a.id) {
					a.vx += fx;
					a.vy += fy;
				}
				if (dragId !== b.id) {
					b.vx -= fx;
					b.vy -= fy;
				}
			}
		}

		for (const link of edgesList) {
			const source = physicsMap.get(link.from);
			const target = physicsMap.get(link.to);
			if (!source || !target) continue;
			const dx = target.x - source.x;
			const dy = target.y - source.y;
			const dist = Math.sqrt(dx * dx + dy * dy) + 0.01;
			const desired = 220;
			const delta = dist - desired;
			const fx = (dx / dist) * delta * linkStrength;
			const fy = (dy / dist) * delta * linkStrength;
			if (dragId !== link.from) {
				source.vx += fx;
				source.vy += fy;
			}
			if (dragId !== link.to) {
				target.vx -= fx;
				target.vy -= fy;
			}
		}

		for (const pos of positions) {
			if (dragId === pos.id) continue;
			pos.vx = clamp(pos.vx, -maxVelocity, maxVelocity);
			pos.vy = clamp(pos.vy, -maxVelocity, maxVelocity);
			pos.x += pos.vx;
			pos.y += pos.vy;
			physicsMap.set(pos.id, pos);
		}
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

	function tick() {
		applyForces();
		iteration += 1;

		// Sync to reactive state periodically (every 4 frames) during simulation for visual updates
		if (iteration % 4 === 0) {
			syncSnapshot();
		}

		const velocities = layoutNodes.map((node) => {
			const pos = physicsMap.get(node.id);
			if (!pos) return 0;
			return Math.abs(pos.vx) + Math.abs(pos.vy);
		});
		const maxVelocityNow = velocities.length ? Math.max(...velocities) : 0;
		if (iteration < maxIterations && maxVelocityNow > minVelocity) {
			rafId = requestAnimationFrame(tick);
			return;
		}
		running = false;
		if (rafId !== null) cancelAnimationFrame(rafId);
		rafId = null;
		// Final sync when simulation settles
		syncSnapshot();
	}

	function startSimulation() {
		if (running) return;
		running = true;
		iteration = 0;
		seedPositions();
		if (rafId !== null) cancelAnimationFrame(rafId);
		rafId = requestAnimationFrame(tick);
	}

	function stopSimulation() {
		if (rafId !== null) cancelAnimationFrame(rafId);
		rafId = null;
		running = false;
	}

	// $effect needed: must start/stop RAF-based force simulation when graph data changes — not expressible via $derived
	$effect(() => {
		void layoutNodes;
		startSimulation();
		return () => {
			stopSimulation();
		};
	});

	const viewBox = $derived.by(() => {
		const coords = Object.values(positionSnapshot);
		if (!coords.length) return { width: viewSize.width, height: viewSize.height };
		const xs = coords.map((c) => c.x);
		const ys = coords.map((c) => c.y);
		const minX = Math.min(...xs);
		const maxX = Math.max(...xs);
		const minY = Math.min(...ys);
		const maxY = Math.max(...ys);
		return {
			width: Math.max(viewSize.width, maxX - minX + nodeWidth * 2),
			height: Math.max(viewSize.height, maxY - minY + nodeHeight * 2)
		};
	});

	function startDrag(event: PointerEvent, id: string) {
		const pos = physicsMap.get(id);
		if (!pos) return;
		dragId = id;
		dragOffset = { x: event.clientX - pos.x, y: event.clientY - pos.y };
		(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
		startSimulation();
	}

	function moveDrag(event: PointerEvent) {
		if (!dragId || !dragOffset) return;
		const next = {
			x: event.clientX - dragOffset.x,
			y: event.clientY - dragOffset.y,
			vx: 0,
			vy: 0
		};
		physicsMap.set(dragId, next);
		// Sync immediately during drag for responsive feedback
		syncSnapshot();
	}

	function endDrag() {
		dragId = null;
		dragOffset = null;
	}

	function stopDrag(event: PointerEvent) {
		if (!dragId) return;
		(event.currentTarget as HTMLElement).releasePointerCapture(event.pointerId);
		endDrag();
		startSimulation();
	}

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

	function setSize(node: HTMLElement, size: { width: number; height: number }) {
		node.style.width = `${size.width}px`;
		node.style.height = `${size.height}px`;
		return {
			update(next: { width: number; height: number }) {
				node.style.width = `${next.width}px`;
				node.style.height = `${next.height}px`;
			}
		};
	}
</script>

<div class="rounded-sm border border-tertiary bg-bg-primary p-4">
	{#if nodes.length === 0}
		<p class="text-sm text-fg-tertiary">No lineage data available.</p>
	{:else}
		<div
			class="relative overflow-auto border border-tertiary bg-bg-secondary lineage-canvas"
			bind:clientWidth={viewSize.width}
			bind:clientHeight={viewSize.height}
		>
			<svg
				class="absolute inset-0"
				viewBox={`0 0 ${viewBox.width} ${viewBox.height}`}
				preserveAspectRatio="xMinYMin meet"
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
						<path d="M0,0 L10,5 L0,10 Z" fill="var(--lineage-edge)" />
					</marker>
				</defs>
				{#each edges as edge (edge.from + edge.to)}
					{@const from = positionSnapshot[edge.from]}
					{@const to = positionSnapshot[edge.to]}
					{#if from && to}
						<path
							d={`M ${from.x + nodeWidth / 2} ${from.y + nodeHeight / 2} C ${from.x + nodeWidth} ${from.y + nodeHeight / 2} ${to.x - nodeWidth / 2} ${to.y + nodeHeight / 2} ${to.x} ${to.y + nodeHeight / 2}`}
							fill="none"
							stroke="var(--lineage-edge)"
							stroke-width="2"
							marker-end="url(#lineage-arrow)"
						/>
					{/if}
				{/each}
			</svg>
			<div class="relative min-h-100" use:setSize={viewBox}>
				{#each layoutNodes as node (node.id)}
					{@const pos = positionSnapshot[node.id]}
					{#if pos}
						<div
							class="absolute flex flex-col gap-1 rounded-sm border px-4 py-3 shadow-sm lineage-node"
							use:setPosition={pos}
							onpointerdown={(event) => startDrag(event, node.id)}
							onpointermove={moveDrag}
							onpointerup={stopDrag}
							onpointercancel={stopDrag}
							role="button"
							tabindex="0"
							aria-label={`Drag ${node.type} ${node.label}`}
						>
							<div class="text-xs uppercase tracking-wide text-fg-muted">
								{node.type === 'datasource' ? 'Datasource' : 'Analysis'}
							</div>
							<div class="text-sm font-semibold text-fg-primary">
								{node.label}
							</div>
							{#if node.meta}
								<div class="text-xs text-fg-tertiary">{node.meta}</div>
							{/if}
						</div>
					{/if}
				{/each}
			</div>
		</div>
	{/if}
</div>
