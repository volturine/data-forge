type ClockListener = (now: number) => void;

interface Clock {
	listeners: Set<ClockListener>;
	timer: ReturnType<typeof setInterval> | undefined;
	updateVisibility: () => void;
}

const clocks = new Map<number, Clock>();

/** Share display-only timers, and stop waking background browser tabs. */
export function subscribeVisibleClock(refreshMs: number, listener: ClockListener): () => void {
	const interval = Number.isFinite(refreshMs) && refreshMs > 0 ? refreshMs : 60_000;
	let clock = clocks.get(interval);
	if (!clock) {
		const listeners = new Set<ClockListener>();
		const tick = (): void => {
			const now = Date.now();
			for (const notify of listeners) notify(now);
		};
		const created: Clock = {
			listeners,
			timer: undefined,
			updateVisibility: () => {
				clearInterval(created.timer);
				created.timer = undefined;
				if (document.hidden) return;
				tick();
				created.timer = setInterval(tick, interval);
			}
		};
		clock = created;
		clocks.set(interval, clock);
		document.addEventListener('visibilitychange', clock.updateVisibility);
		clock.updateVisibility();
	}
	clock.listeners.add(listener);
	listener(Date.now());

	return () => {
		clock.listeners.delete(listener);
		if (clock.listeners.size > 0) return;
		clearInterval(clock.timer);
		document.removeEventListener('visibilitychange', clock.updateVisibility);
		clocks.delete(interval);
	};
}
