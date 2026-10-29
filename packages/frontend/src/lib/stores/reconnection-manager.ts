export class ReconnectionManager {
	private timer: ReturnType<typeof setTimeout> | null = null;

	private nextDelayMs: number;

	constructor(
		private readonly delayMs: number,
		private readonly maxDelayMs = delayMs
	) {
		this.nextDelayMs = delayMs;
	}

	get scheduled(): boolean {
		return this.timer !== null;
	}

	schedule(callback: () => void): boolean {
		if (this.timer !== null) return false;
		const delay =
			this.maxDelayMs > this.delayMs
				? this.nextDelayMs * (0.5 + Math.random() * 0.5)
				: this.delayMs;
		this.nextDelayMs = Math.min(this.nextDelayMs * 2, this.maxDelayMs);
		this.timer = setTimeout(() => {
			this.timer = null;
			callback();
		}, delay);
		return true;
	}

	reset(): void {
		this.clear();
		this.nextDelayMs = this.delayMs;
	}

	clear(): void {
		if (this.timer === null) return;
		clearTimeout(this.timer);
		this.timer = null;
	}
}
