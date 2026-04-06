# Style Guide

**MANDATORY READ FOR AI ASSISTANTS** — OpenCode, Copilot, Claude Code must follow this guidance when working on this repository.

Code style standards for this repository. See `AGENTS.md` for project-specific patterns.

## Core Principles

- **Prefer `const`** over `let` — avoid reassigning variables
- **Avoid `else`** — use early returns
- **Single word names** — keep identifiers short
- **Unified functions** — don't split unless composable
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

### Single word naming

```ts
// Good
const foo = 1;
const bar = 2;

// Bad
const fooBar = 1;
const barBaz = 2;
```

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
	const { items } = $props<{ items: string[] }>();
	const count = $derived(items.length);
</script>
```

## Styling (Panda CSS)

- Use Panda CSS recipes and semantic tokens — never raw hex/rgb values
- Avoid inline `style=""` attributes — use `css()` or recipe classes
- Never use `transition-all` — always specify the properties:

```ts
// Good
'transition-colors duration-150'
'transition-opacity duration-200'
'transition-[color,background-color,border-color,opacity] duration-150'

// Bad
'transition-all duration-150'
```

## Patterns

**Config Defaults:** Centralize in `step-config-defaults.ts`

```typescript
export function getDefaultConfig(stepType: string) {
	const defaults = { select: { columns: [] }, filter: { conditions: [] } };
	return JSON.parse(JSON.stringify(defaults[stepType] ?? {}));
}
```

**Icons:** Use Lucide. Store as component references, render as `<Icon />`.

**Dynamic Styles:** Use Svelte actions (e.g., `use:setWidth`) not inline styles.

**$effect Rules (Strict):**

- **Allowed only for side effects** that cannot be expressed via `$derived` or pure functions
- **Allowed examples:** DOM access, event listeners, subscriptions, timers, network calls, localStorage/sessionStorage
- **Explicitly forbidden:** data initialization, validation, derived state, mapping, filtering, sorting, or transforming props/state
- **Requirement:** if `$effect` is used, include a one-line comment explaining why `$derived` is not sufficient
