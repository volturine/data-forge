---
name: Explicit over implicit code
description: User strongly prefers explicit, declarative code with proper types — no implicit patterns, stringly-typed code, or bare dicts
type: feedback
---

Write explicit, declarative code. Eliminate implicit patterns.

**Why:** User wants a codebase where implicit problems cannot occur. Stringly-typed code, bare dicts with untyped shapes, scattered magic constants, and duplicated type-checking logic are all anti-patterns.

**How to apply:**
- Use dataclasses/TypedDicts instead of bare dicts when a dict has a consistent shape
- Use Literal types or StrEnum instead of raw strings for status/type values
- Extract shared type-checking logic (like `isChartStep`) into named functions instead of inlining `startsWith('plot_')` in 8 files
- Use `satisfies` in TypeScript to validate config shapes at the type level
- Add return type annotations to all public functions
- Prefer generics and typed protocols over `dict` / `Any` / `Record<string, unknown>`
