const PANEL_HEIGHT_KEY = 'chat_panel_height';
const PANEL_WIDTH_KEY = 'chat_panel_width';
const EXPANDED_HEIGHT_KEY = 'chat_expanded_height';

export class ChatPanelLayout {
	maximized = $state(false);
	panelHeight = $state(500);
	panelWidth = $state(420);
	expandedHeight = $state(
		typeof window !== 'undefined' ? Math.round(window.innerHeight * 0.95) : 800
	);
	isResizing = $state(false);

	get activeHeight(): number {
		return this.maximized ? this.expandedHeight : this.panelHeight;
	}

	restore(): void {
		const height = localStorage.getItem(PANEL_HEIGHT_KEY);
		if (height) this.panelHeight = Math.max(300, Number(height));
		const width = localStorage.getItem(PANEL_WIDTH_KEY);
		if (width) this.panelWidth = Math.max(320, Number(width));
		const expanded = localStorage.getItem(EXPANDED_HEIGHT_KEY);
		if (expanded) this.expandedHeight = Math.max(400, Number(expanded));
	}

	startHeightResize(event: PointerEvent): void {
		event.preventDefault();
		this.isResizing = true;
		const startY = event.clientY;
		const startHeight = this.activeHeight;
		const minimum = this.maximized ? 400 : 300;
		this.trackPointer(
			(move) => {
				const height = Math.max(
					minimum,
					Math.min(window.innerHeight * 0.95, startHeight + (startY - move.clientY))
				);
				if (this.maximized) this.expandedHeight = height;
				else this.panelHeight = height;
			},
			() => this.persist()
		);
	}

	startWidthResize(event: PointerEvent): void {
		event.preventDefault();
		this.isResizing = true;
		const startX = event.clientX;
		const startWidth = this.panelWidth;
		this.trackPointer(
			(move) => {
				this.panelWidth = Math.max(
					320,
					Math.min(window.innerWidth * 0.9, startWidth + (startX - move.clientX))
				);
			},
			() => this.persist()
		);
	}

	startCornerResize(event: PointerEvent): void {
		event.preventDefault();
		this.isResizing = true;
		const startX = event.clientX;
		const startY = event.clientY;
		const startWidth = this.panelWidth;
		const startHeight = this.activeHeight;
		const minimum = this.maximized ? 400 : 300;
		this.trackPointer(
			(move) => {
				this.panelWidth = Math.max(
					320,
					Math.min(window.innerWidth * 0.9, startWidth + (startX - move.clientX))
				);
				const height = Math.max(
					minimum,
					Math.min(window.innerHeight * 0.95, startHeight + (startY - move.clientY))
				);
				if (this.maximized) this.expandedHeight = height;
				else this.panelHeight = height;
			},
			() => this.persist()
		);
	}

	private trackPointer(move: (event: PointerEvent) => void, done: () => void): void {
		const finish = () => {
			this.isResizing = false;
			window.removeEventListener('pointermove', move);
			window.removeEventListener('pointerup', finish);
			done();
		};
		window.addEventListener('pointermove', move);
		window.addEventListener('pointerup', finish);
	}

	private persist(): void {
		localStorage.setItem(
			this.maximized ? EXPANDED_HEIGHT_KEY : PANEL_HEIGHT_KEY,
			String(this.activeHeight)
		);
		localStorage.setItem(PANEL_WIDTH_KEY, String(this.panelWidth));
	}
}
