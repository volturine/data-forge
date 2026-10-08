# Engineering and problem-solving guidance

Use these principles when choosing an implementation and investigating a failure.

## Principles

- Remove obsolete runtime/API paths and avoid permissive fallback parsing. When a schema change affects persisted user configuration, use an explicit data migration rather than fallback parsing.
- For deployment-facing identifiers such as environment variable names and image tags, a deprecated alias may remain for one release; emit a deprecation log where the alias is read at runtime, and remove it after that release.
- Choose the simplest implementation that fully meets the current requirements. Avoid speculative abstractions, configuration, and indirection.
- Grow the system in layers. Start from the smallest version that works end to end, and add each new capability on top of a product that already works. Never trade a working product for unfinished complexity.
- Keep components modular and concerns clearly separated.
- Prefer established, well-maintained libraries when they reduce overall complexity or improve reliability. Do not reimplement common functionality without a clear reason.
- Lean on the dependencies already in the project before writing your own implementation or adding packages. Do not assume a library lacks a capability without checking its documentation and types.
- Make architectural decisions for the long term. Do not accept a stopgap that only works for now and is meant to be replaced later.

## Problem solving

- Start from the intended outcome, then trace the behavior across every relevant layer before changing code.
- Form a causal explanation and actively look for evidence that disproves it.
- Fix the cause where the responsibility belongs. Prefer clear ownership and isolation boundaries over patches at the point where symptoms appear.
- When one fix reveals another failure, investigate it independently instead of forcing it into the previous explanation.
- Before finishing, be able to explain the root cause, why the symptoms were misleading, what now prevents recurrence, and what evidence proves the fix.
