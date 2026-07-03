export class ReconnectionManager {
	private timer: ReturnType<typeof setTimeout> | null = null;

	constructor(private readonly delayMs: number) {}

	get scheduled(): boolean {
		return this.timer !== null;
	}

	schedule(callback: () => void): boolean {
		if (this.timer !== null) return false;
		this.timer = setTimeout(() => {
			this.timer = null;
			callback();
		}, this.delayMs);
		return true;
	}

	clear(): void {
		if (this.timer === null) return;
		clearTimeout(this.timer);
		this.timer = null;
	}
}
