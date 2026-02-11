# Style Guide

**MANDATORY READ FOR AI ASSISTANTS** - OpenCode, Copilot, Claude Code must follow this guidance when working on this repository.

Code style standards for this repository. See `AGENTS.md` for project-specific patterns.

## Core Principles

- **Prefer `const`** over `let` - avoid reassigning variables
- **Avoid `else`** - use early returns
- **Single word names** - keep identifiers short
- **Unified functions** - don't split unless composable
- **No unnecessary destructuring** - use `obj.a` instead of `const { a } = obj`
- **Avoid `try/catch`** - handle errors at boundaries
- **No `any`** type - use proper types

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

## File Naming

- Python: `snake_case.py`
- TypeScript: `kebab-case.ts`
- Svelte components: `PascalCase.svelte`
- Stores: `*.svelte.ts`

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

- **Allowed only for side effects** that cannot be expressed via `$derived` or pure functions.
- **Allowed examples:** DOM access, event listeners, subscriptions, timers, network calls, localStorage/sessionStorage.
- **Explicitly forbidden:** data initialization, validation, derived state, mapping, filtering, sorting, or transforming props/state.
- **Requirement:** if `$effect` is used, include a one-line comment explaining why `$derived` is not sufficient.
