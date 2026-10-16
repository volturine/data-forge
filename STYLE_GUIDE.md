# Style Guide

**MANDATORY READ FOR AI ASSISTANTS** — every AI coding assistant working in this repository must follow this guidance; `AGENTS.md` is the assistant entry point.

Code style standards for this repository. See `AGENTS.md` for project-specific patterns.

## Core Principles

- **Prefer `const`** over `let` — avoid reassigning variables
- **Avoid `else`** — use early returns
- **Cohesive category names** — prefer a concise single word for a category containing multiple related components; use intention-revealing names within it
- **Cohesive behavior** — keep behavior together when it shares an invariant and lifecycle; extract reusable operations, side-effect boundaries, and independently testable policies
- **No unnecessary destructuring** — use `obj.a` instead of `const { a } = obj`
- **Avoid `try/catch`** — handle errors at boundaries
- **No `any`** type — use proper types or infer from function signatures

## TypeScript

- Avoid `as any` — infer types from function signatures instead
- Avoid `as SomeType` casts unless absolutely necessary; prefer type guards
- Use `satisfies` for object literals that should conform to a type
- Prioritize type inference — let TypeScript figure it out from context
- All function parameters and return types should be explicitly typed at module boundaries

## Examples

### Prefer const

```ts
// Good
const foo = condition ? 1 : 2;

// Bad
let foo;
if (condition) foo = 1;
else foo = 2;
```

### Avoid else

```ts
// Good
function foo() {
	if (condition) return 1;
	return 2;
}

// Bad
function foo() {
	if (condition) return 1;
	else return 2;
}
```

### Cohesive category naming

```ts
// Good — `runtime` is a cohesive category; members retain domain meaning
const runtime = {
	claimLease,
	renewLease,
	finalizeBuild,
};

// Bad — short names hide ownership and intent
const run = {
	do: claimLease,
	next: renewLease,
};
```

Do not shorten an identifier at the cost of ownership, domain meaning, or searchability. Keep a function or component unified when its behavior shares one invariant and lifecycle. Extract it when the result is a reusable operation, an isolated side-effect boundary, or an independently testable policy with a clear owner.

### No any

```ts
// Good — infer from function
const result = await fetchData();
// result type is inferred

// Bad
const result = await fetchData() as any;
```

## File Naming

- Python: `snake_case.py`
- TypeScript: `kebab-case.ts`
- Svelte components: `PascalCase.svelte`
- Stores: `*.svelte.ts`

## Svelte Components

- All components must have `lang="ts"` on the `<script>` tag
- Use Svelte 5 runes — `$state`, `$derived`, `$effect`, `$props`
- `$derived` for computed values — never `$effect` for deriving state
- `$effect` only for side effects (DOM, subscriptions, timers, network)
- If `$effect` is used, include a one-line comment explaining why `$derived` is insufficient

```svelte
<script lang="ts">
	// Good — runes, typed props, derived state
	interface Props {
		items: string[];
	}

	let { items }: Props = $props();
	const count = $derived(items.length);
</script>
```

## Styling (Panda CSS)

- Use Panda CSS recipes and semantic tokens — never raw hex/rgb values
- Avoid inline `style=""` attributes — use `css()` or recipe classes
- Never transition `all` — always specify the properties:

```ts
// Good
css({ transitionProperty: 'color, background-color', transitionDuration: 'normal' });

// Bad
css({ transitionProperty: 'all', transitionDuration: 'normal' });
```

## Patterns

**Config Defaults:** Centralize in `packages/frontend/src/lib/utils/step-config-defaults.ts`

```typescript
export function getDefaultConfig(stepType: string): StepConfig {
	const normalizedType = normalizePipelineStepType(stepType);
	const defaults = defaultConfigs[normalizedType];
	return defaults ? cloneJson(defaults) : {};
}
```

**Icons:** Use Lucide (`@lucide/svelte`). Store as component references, render as `<Icon />`.

**Dynamic Styles:** Use Svelte actions (e.g., `use:setWidth`) not inline styles.

**$effect Rules (Strict):**

- **Allowed only for side effects** that cannot be expressed via `$derived` or pure functions
- **Allowed examples:** DOM access, event listeners, subscriptions, timers, network calls, localStorage/sessionStorage
- **Explicitly forbidden:** data initialization, validation, derived state, mapping, filtering, sorting, or transforming props/state
- **Requirement:** if `$effect` is used, include a one-line comment explaining why `$derived` is not sufficient
