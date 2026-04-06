import { describe, test, expect, beforeEach, vi } from 'vitest';
import { DragState } from './drag.svelte';
import type { DropTarget, TargetResolver } from './drag.svelte';

describe('DragState', () => {
	let state: DragState;

	beforeEach(() => {
		state = new DragState();
	});

	describe('initial state', () => {
		test('all fields are null/default', () => {
			expect(state.type).toBeNull();
			expect(state.stepId).toBeNull();
			expect(state.source).toBeNull();
			expect(state.target).toBeNull();
			expect(state.valid).toBe(true);
			expect(state.pointerId).toBeNull();
			expect(state.pointerX).toBeNull();
			expect(state.pointerY).toBeNull();
			expect(state.capturedElement).toBeNull();
		});

		test('active is false', () => {
			expect(state.active).toBe(false);
		});

		test('isReorder is false', () => {
			expect(state.isReorder).toBe(false);
		});

		test('isInsert is false', () => {
			expect(state.isInsert).toBe(false);
		});
	});

	describe('start', () => {
		test('sets type, source, pointerId, and pointer coords', () => {
			state.start('filter', 'library', 1, 100, 200);

			expect(state.type).toBe('filter');
			expect(state.source).toBe('library');
			expect(state.pointerId).toBe(1);
			expect(state.pointerX).toBe(100);
			expect(state.pointerY).toBe(200);
		});

		test('clears stepId', () => {
			state.start('filter', 'library', 1, 0, 0);
			expect(state.stepId).toBeNull();
		});

		test('sets active to true', () => {
			state.start('filter', 'library', 1, 0, 0);
			expect(state.active).toBe(true);
		});

		test('sets isInsert for library source', () => {
			state.start('filter', 'library', 1, 0, 0);
			expect(state.isInsert).toBe(true);
			expect(state.isReorder).toBe(false);
		});

		test('resets target and valid', () => {
			state.target = { index: 5, parentId: 'p', nextId: 'n' };
			state.valid = false;
			state.start('filter', 'library', 1, 0, 0);
			expect(state.target).toBeNull();
			expect(state.valid).toBe(true);
		});

		test('prevents concurrent drags', () => {
			state.start('filter', 'library', 1, 10, 20);
			state.start('select', 'canvas', 2, 30, 40);
			expect(state.type).toBe('filter');
			expect(state.source).toBe('library');
			expect(state.pointerId).toBe(1);
		});
	});

	describe('startMove', () => {
		test('sets stepId, type, source as canvas', () => {
			state.startMove('step-1', 'filter', 1, 50, 60);

			expect(state.stepId).toBe('step-1');
			expect(state.type).toBe('filter');
			expect(state.source).toBe('canvas');
			expect(state.pointerId).toBe(1);
			expect(state.pointerX).toBe(50);
			expect(state.pointerY).toBe(60);
		});

		test('sets active to true', () => {
			state.startMove('step-1', 'filter', 1, 0, 0);
			expect(state.active).toBe(true);
		});

		test('sets isReorder for canvas move', () => {
			state.startMove('step-1', 'filter', 1, 0, 0);
			expect(state.isReorder).toBe(true);
			expect(state.isInsert).toBe(false);
		});

		test('resets target and valid', () => {
			state.target = { index: 2, parentId: 'x', nextId: 'y' };
			state.valid = false;
			state.startMove('step-1', 'filter', 1, 0, 0);
			expect(state.target).toBeNull();
			expect(state.valid).toBe(true);
		});

		test('prevents concurrent drags', () => {
			state.startMove('step-1', 'filter', 1, 0, 0);
			state.startMove('step-2', 'select', 2, 10, 10);
			expect(state.stepId).toBe('step-1');
		});
	});

	describe('setTarget', () => {
		test('sets target and defaults valid to true', () => {
			const target: DropTarget = { index: 1, parentId: 'a', nextId: 'b' };
			state.setTarget(target);
			expect(state.target).toStrictEqual(target);
			expect(state.valid).toBe(true);
		});

		test('allows setting valid to false', () => {
			const target: DropTarget = { index: 2, parentId: null, nextId: null };
			state.setTarget(target, false);
			expect(state.target).toStrictEqual(target);
			expect(state.valid).toBe(false);
		});
	});

	describe('clearTarget', () => {
		test('nulls target and resets valid to true', () => {
			state.setTarget({ index: 3, parentId: 'p', nextId: 'n' }, false);
			state.clearTarget();
			expect(state.target).toBeNull();
			expect(state.valid).toBe(true);
		});
	});

	describe('setPointer', () => {
		test('updates pointer coordinates', () => {
			state.setPointer(300, 400);
			expect(state.pointerX).toBe(300);
			expect(state.pointerY).toBe(400);
		});
	});

	describe('end', () => {
		test('resets all state to initial values', () => {
			state.start('filter', 'library', 1, 100, 200);
			state.setTarget({ index: 0, parentId: null, nextId: 'x' });
			state.end();

			expect(state.type).toBeNull();
			expect(state.stepId).toBeNull();
			expect(state.source).toBeNull();
			expect(state.target).toBeNull();
			expect(state.valid).toBe(true);
			expect(state.pointerId).toBeNull();
			expect(state.pointerX).toBeNull();
			expect(state.pointerY).toBeNull();
			expect(state.active).toBe(false);
		});

		test('resets after startMove', () => {
			state.startMove('step-1', 'filter', 2, 50, 60);
			state.end();
			expect(state.active).toBe(false);
			expect(state.stepId).toBeNull();
			expect(state.isReorder).toBe(false);
		});
	});

	describe('cancel', () => {
		test('delegates to end and resets all state', () => {
			state.start('sort', 'library', 5, 10, 20);
			state.cancel();

			expect(state.active).toBe(false);
			expect(state.type).toBeNull();
			expect(state.source).toBeNull();
		});

		test('does not invoke dropHandler', () => {
			const handler = vi.fn();
			state.startMove('step-1', 'filter', 1, 10, 20, handler);
			state.setTarget({ index: 0, parentId: null, nextId: 'x' });
			state.cancel();
			expect(handler).not.toHaveBeenCalled();
			expect(state.active).toBe(false);
		});
	});

	describe('startMove with onDrop', () => {
		test('stores dropHandler from onDrop argument', () => {
			const handler = vi.fn();
			state.startMove('step-1', 'filter', 1, 0, 0, handler);
			state.setTarget({ index: 2, parentId: 'a', nextId: 'b' });
			state.commit();
			expect(handler).toHaveBeenCalledOnce();
			expect(handler).toHaveBeenCalledWith('step-1', { index: 2, parentId: 'a', nextId: 'b' });
		});

		test('works without onDrop argument', () => {
			state.startMove('step-1', 'filter', 1, 0, 0);
			state.setTarget({ index: 0, parentId: null, nextId: null });
			state.commit();
			expect(state.active).toBe(false);
		});
	});

	describe('commit', () => {
		test('invokes dropHandler when target, stepId, and valid', () => {
			const handler = vi.fn();
			state.startMove('step-1', 'filter', 1, 100, 200, handler);
			state.setTarget({ index: 1, parentId: 'a', nextId: 'b' });
			state.commit();
			expect(handler).toHaveBeenCalledOnce();
			expect(handler).toHaveBeenCalledWith('step-1', { index: 1, parentId: 'a', nextId: 'b' });
			expect(state.active).toBe(false);
		});

		test('does not invoke handler when valid is false', () => {
			const handler = vi.fn();
			state.startMove('step-1', 'filter', 1, 100, 200, handler);
			state.setTarget({ index: 1, parentId: 'a', nextId: 'b' }, false);
			state.commit();
			expect(handler).not.toHaveBeenCalled();
			expect(state.active).toBe(false);
		});

		test('does not invoke handler when target is null and no resolver', () => {
			const handler = vi.fn();
			state.startMove('step-1', 'filter', 1, 100, 200, handler);
			state.commit();
			expect(handler).not.toHaveBeenCalled();
			expect(state.active).toBe(false);
		});

		test('uses targetResolver when target is null but pointer coords exist', () => {
			const handler = vi.fn();
			const resolved: DropTarget = { index: 3, parentId: 'p', nextId: 'n' };
			const resolver: TargetResolver = vi.fn().mockReturnValue({ target: resolved, valid: true });
			state.startMove('step-1', 'filter', 1, 50, 60, handler);
			state.setTargetResolver(resolver);
			state.commit();
			expect(resolver).toHaveBeenCalledWith(50, 60);
			expect(handler).toHaveBeenCalledWith('step-1', resolved);
			expect(state.active).toBe(false);
		});

		test('does not use resolver when target already set', () => {
			const handler = vi.fn();
			const resolver: TargetResolver = vi.fn();
			const existing: DropTarget = { index: 1, parentId: null, nextId: null };
			state.startMove('step-1', 'filter', 1, 50, 60, handler);
			state.setTarget(existing);
			state.setTargetResolver(resolver);
			state.commit();
			expect(resolver).not.toHaveBeenCalled();
			expect(handler).toHaveBeenCalledWith('step-1', existing);
		});

		test('does not invoke handler when resolver returns null', () => {
			const handler = vi.fn();
			const resolver: TargetResolver = vi.fn().mockReturnValue(null);
			state.startMove('step-1', 'filter', 1, 50, 60, handler);
			state.setTargetResolver(resolver);
			state.commit();
			expect(handler).not.toHaveBeenCalled();
			expect(state.active).toBe(false);
		});

		test('does not invoke handler when resolver returns invalid target', () => {
			const handler = vi.fn();
			const resolved: DropTarget = { index: 2, parentId: null, nextId: null };
			const resolver: TargetResolver = vi.fn().mockReturnValue({ target: resolved, valid: false });
			state.startMove('step-1', 'filter', 1, 50, 60, handler);
			state.setTargetResolver(resolver);
			state.commit();
			expect(handler).not.toHaveBeenCalled();
		});

		test('ends even for library insert drags (no dropHandler)', () => {
			state.start('filter', 'library', 1, 100, 200);
			state.setTarget({ index: 0, parentId: null, nextId: 'x' });
			state.commit();
			expect(state.active).toBe(false);
		});

		test('double commit is safe', () => {
			const handler = vi.fn();
			state.startMove('step-1', 'filter', 1, 100, 200, handler);
			state.setTarget({ index: 1, parentId: null, nextId: null });
			state.commit();
			state.commit();
			expect(handler).toHaveBeenCalledOnce();
			expect(state.active).toBe(false);
		});
	});

	describe('setTargetResolver', () => {
		test('sets and clears resolver', () => {
			const resolver: TargetResolver = vi.fn().mockReturnValue(null);
			state.setTargetResolver(resolver);
			state.startMove('step-1', 'filter', 1, 50, 60);
			state.commit();
			expect(resolver).toHaveBeenCalled();

			state.setTargetResolver(null);
			state.startMove('step-2', 'sort', 2, 70, 80);
			state.commit();
			expect(resolver).toHaveBeenCalledOnce();
		});
	});

	describe('derived flags after state transitions', () => {
		test('active becomes false after end', () => {
			state.start('filter', 'library', 1, 0, 0);
			expect(state.active).toBe(true);
			state.end();
			expect(state.active).toBe(false);
		});

		test('isInsert becomes false after end', () => {
			state.start('filter', 'library', 1, 0, 0);
			expect(state.isInsert).toBe(true);
			state.end();
			expect(state.isInsert).toBe(false);
		});

		test('isReorder becomes false after end', () => {
			state.startMove('step-1', 'filter', 1, 0, 0);
			expect(state.isReorder).toBe(true);
			state.end();
			expect(state.isReorder).toBe(false);
		});

		test('start after end works normally', () => {
			state.start('filter', 'library', 1, 0, 0);
			state.end();
			state.start('select', 'canvas', 2, 5, 5);
			expect(state.active).toBe(true);
			expect(state.type).toBe('select');
		});
	});
});
