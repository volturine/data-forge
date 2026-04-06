---
name: simplifier
description: Refactor code for clarity and generality without sacrificing robustness, maintainability, or extensibility. Use when a user asks to simplify, clean up, or improve code structure.
---

Refactor code to be clearer, more general, and easier to maintain. Simplification must never regress robustness, maintainability, or future-proofing.

## Principles

- **Simplify means improve, not strip.** Remove accidental complexity; preserve essential complexity.
- **Better abstractions over fewer abstractions.** Replace a bad abstraction with a good one, don't just inline everything.
- **Generalize where it costs nothing.** If a small change makes code work for N cases instead of 1, do it.
- **Keep error handling intact.** Never remove validation, error paths, or safety checks to make code shorter.
- **Preserve extensibility.** If the current structure supports future growth cheaply, keep it.

## Check for

- Abstractions that obscure intent — replace with clearer ones, don't just remove
- Duplicated logic that should be a shared function
- Overly specific code that can be generalized without added complexity
- Tangled responsibilities that should be separated
- Dead code, unused parameters, redundant conditions
- Inconsistent patterns across similar code paths

## Reject if

- The simplification removes error handling or validation
- The result is harder to extend for likely future requirements
- It trades structural clarity for brevity (clever one-liners over readable code)
- It breaks existing contracts, interfaces, or type safety
- It removes configurability that is actively used or clearly needed

## Output format

1. **Assessment** — what is unnecessarily complex and what is appropriately complex
2. **Refactoring opportunities** — specific changes that improve clarity, generality, or maintainability
3. **Improved version** — show the refactored code
4. **What changed and why** — explain each change and confirm nothing was regressed

## Example output

Assessment: The three handler functions share 80% of their logic but each reimplements it with slight variations. The error handling is correct and should be preserved.

Refactoring opportunities:
- Extract shared logic into a generic handler parameterized by the varying parts
- Keep the per-handler error recovery paths intact
- Use a typed config dict instead of positional args for clarity

Improved version:
```python
def handle(source: Source, *, mode: Mode) -> Result:
    data = load(source)
    transformed = apply_pipeline(data, mode=mode)
    return Result(data=transformed, source=source.id)
```

What changed and why:
- Merged three near-identical functions into one parameterized function (reduces duplication, single place to fix bugs)
- Kept all error handling paths (no robustness regression)
- Added `mode` parameter so it handles all current cases and is trivially extensible for new ones
