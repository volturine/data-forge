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

	/** Whether this is a reorder operation (moving existing step) */
	public isReorder: boolean = $derived(this.source === 'canvas' && this.stepId !== null);

	/** Whether this is an insert operation (adding new step from library) */
	public isInsert: boolean = $derived(this.source === 'library' && this.type !== null);

	/** Start a drag operation for a new step from library */
	start(type: string, source: DragSource, pointerId: number, pointerX: number, pointerY: number) {
		this.type = type;
		this.stepId = null;
		this.source = source;
		this.target = null;
		this.valid = true;
		this.pointerId = pointerId;
		this.pointerX = pointerX;
		this.pointerY = pointerY;
	}

	/** Start a reorder operation for an existing step */
	public startMove(stepId: string, type: string, pointerId: number, pointerX: number, pointerY: number) {
		this.stepId = stepId;
		this.type = type;
		this.source = 'canvas';
		this.target = null;
		this.valid = true;
		this.pointerId = pointerId;
		this.pointerX = pointerX;
		this.pointerY = pointerY;
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

	/** End the drag operation and reset all state */
	end() {
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
