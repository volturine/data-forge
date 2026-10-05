// Each step form bind:s a different config type. Svelte bind is invariant, so
// one shared draft object cannot be a Record and still type-check against
// every form. `any` is the type that stays the same object Apply reads.
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- heterogeneous step bind
export type StepDraft = any;
