/**
 * Centralized drag state management for pipeline editor.
 * Single source of truth for all drag-and-drop operations.
 */

export type DragSource = 'library' | 'canvas';

export interface DropTarget {
	index: number;
	parentId: string | null;
	nextId: string | null;
}

export type DropHandler = (stepId: string, target: DropTarget) => void;
export type TargetResolver = (
	x: number,
	y: number
) => { target: DropTarget; valid: boolean } | null;

export class DragState {
	/** The operation type being dragged (e.g., "filter", "select") - only for library drags */
	public type: string | null = $state<string | null>(null);

	/** The step ID being moved - only for canvas reordering */
	public stepId: string | null = $state<string | null>(null);

	/** Where the drag originated from */
	public source: DragSource | null = $state<DragSource | null>(null);

	/** Current drop target being hovered */
	public target: DropTarget | null = $state<DropTarget | null>(null);

	/** Whether the current target is a valid drop location */
	public valid: boolean = $state(true);

	/** Whether a drag operation is in progress */
	public active: boolean = $derived(this.type !== null || this.stepId !== null);

	/** Pointer id for active drag */
	public pointerId: number | null = $state<number | null>(null);

	/** Pointer coordinates during drag - always tracked for all input types */
	public pointerX: number | null = $state<number | null>(null);
	public pointerY: number | null = $state<number | null>(null);

	/** Element with pointer capture (for cleanup on cancel/end) */
	public capturedElement: HTMLElement | null = $state<HTMLElement | null>(null);

	/** Whether this is a reorder operation (moving existing step) */
	public isReorder: boolean = $derived(this.source === 'canvas' && this.stepId !== null);

	/** Whether this is an insert operation (adding new step from library) */
	public isInsert: boolean = $derived(this.source === 'library' && this.type !== null);

	/** Callback invoked on successful drop for reorder operations */
	private dropHandler: DropHandler | null = null;

	/** Synchronous target resolver set by PipelineCanvas */
	private targetResolver: TargetResolver | null = null;

	/** Start a drag operation for a new step from library */
	start(type: string, source: DragSource, pointerId: number, pointerX: number, pointerY: number) {
		if (this.active) return;
		this.type = type;
		this.stepId = null;
		this.source = source;
		this.target = null;
		this.valid = true;
		this.pointerId = pointerId;
		this.pointerX = pointerX;
		this.pointerY = pointerY;
		this.dropHandler = null;
	}

	/** Start a reorder operation for an existing step */
	public startMove(
		stepId: string,
		type: string,
		pointerId: number,
		pointerX: number,
		pointerY: number,
		onDrop?: DropHandler
	) {
		if (this.active) return;
		this.stepId = stepId;
		this.type = type;
		this.source = 'canvas';
		this.target = null;
		this.valid = true;
		this.pointerId = pointerId;
		this.pointerX = pointerX;
		this.pointerY = pointerY;
		this.dropHandler = onDrop ?? null;
	}

	/** Update the current drop target */
	setTarget(target: DropTarget, valid = true) {
		this.target = target;
		this.valid = valid;
	}

	/** Clear the current drop target (mouse left drop zone) */
	clearTarget() {
		this.target = null;
		this.valid = true;
	}

	/** Update pointer position during drag */
	public setPointer(x: number, y: number) {
		this.pointerX = x;
		this.pointerY = y;
	}

	/** Set the element that has pointer capture for proper cleanup */
	public setCapturedElement(el: HTMLElement, pointerId: number) {
		this.capturedElement = el;
		this.pointerId = pointerId;
	}

	/** Register a synchronous target resolver (set by PipelineCanvas) */
	public setTargetResolver(resolver: TargetResolver | null) {
		this.targetResolver = resolver;
	}

	/** Release pointer capture if held */
	private releaseCapture() {
		if (this.capturedElement && this.pointerId !== null) {
			try {
				this.capturedElement.releasePointerCapture(this.pointerId);
			} catch (err) {
				void err;
			}
		}
		this.capturedElement = null;
	}

	/** Cancel the drag operation (e.g., via Escape key) */
	cancel() {
		this.dropHandler = null;
		this.end();
	}

	/** Commit the current drop: invoke the handler then reset */
	commit() {
		if (!this.target && this.pointerX !== null && this.pointerY !== null && this.targetResolver) {
			const resolved = this.targetResolver(this.pointerX, this.pointerY);
			if (resolved) {
				this.target = resolved.target;
				this.valid = resolved.valid;
			}
		}
		if (this.target && this.stepId && this.valid && this.dropHandler) {
			this.dropHandler(this.stepId, this.target);
		}
		this.dropHandler = null;
		this.end();
	}

	/** End the drag operation and reset all state */
	end() {
		this.releaseCapture();
		this.dropHandler = null;
		this.type = null;
		this.stepId = null;
		this.source = null;
		this.target = null;
		this.valid = true;
		this.pointerId = null;
		this.pointerX = null;
		this.pointerY = null;
	}
}

export const drag = new DragState();

// Module-level effects for global drag behavior
$effect.root(() => {
	// Escape key listener to cancel active drags
	$effect(() => {
		if (!drag.active) return;
		const handleKeydown = (e: KeyboardEvent) => {
			if (e.key === 'Escape') {
				e.preventDefault();
				drag.cancel();
			}
		};
		window.addEventListener('keydown', handleKeydown);
		return () => window.removeEventListener('keydown', handleKeydown);
	});

	// DOM: global pointerup/mouseup to commit or clean up drags when the
	// captured element misses the event (e.g., pointer released outside).
	$effect(() => {
		if (!drag.active) return;
		const finish = (e: PointerEvent) => {
			if (!drag.active) return;
			drag.setPointer(e.clientX, e.clientY);
			drag.commit();
		};
		window.addEventListener('pointerup', finish);
		window.addEventListener('pointercancel', finish);
		return () => {
			window.removeEventListener('pointerup', finish);
			window.removeEventListener('pointercancel', finish);
		};
	});

	// Body class management for touch-dragging
	$effect(() => {
		if (!drag.active) return;
		document.body.classList.add('touch-dragging');
		return () => document.body.classList.remove('touch-dragging');
	});
});
