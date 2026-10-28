export function createDeleteConfirm(remove: (id: string) => void) {
	let pendingId = $state<string | null>(null);

	return {
		get pendingId() {
			return pendingId;
		},
		request: (id: string) => {
			pendingId = id;
		},
		confirm: () => {
			if (!pendingId) return;
			remove(pendingId);
			pendingId = null;
		},
		cancel: () => {
			pendingId = null;
		}
	};
}
