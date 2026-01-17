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

class DragState {
	/** The operation type being dragged (e.g., "filter", "select") - only for library drags */
	type = $state<string | null>(null);

	/** The step ID being moved - only for canvas reordering */
	stepId = $state<string | null>(null);

	/** Where the drag originated from */
	source = $state<DragSource | null>(null);

	/** Current drop target being hovered */
	target = $state<DropTarget | null>(null);

	/** Whether the current target is a valid drop location */
	valid = $state(true);

	/** Whether a drag operation is in progress */
	get active() {
		return this.type !== null || this.stepId !== null;
	}

	/** Whether this is a reorder operation (moving existing step) */
	get isReorder() {
		return this.source === 'canvas' && this.stepId !== null;
	}

	/** Whether this is an insert operation (adding new step from library) */
	get isInsert() {
		return this.source === 'library' && this.type !== null;
	}

	/** Start a drag operation for a new step from library */
	start(type: string, source: DragSource) {
		this.type = type;
		this.stepId = null;
		this.source = source;
		this.target = null;
		this.valid = true;
	}

	/** Start a reorder operation for an existing step */
	startMove(stepId: string, type: string) {
		this.stepId = stepId;
		this.type = type;
		this.source = 'canvas';
		this.target = null;
		this.valid = true;
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

	/** End the drag operation and reset all state */
	end() {
		this.type = null;
		this.stepId = null;
		this.source = null;
		this.target = null;
		this.valid = true;
	}
}

export const drag = new DragState();
