---
name: simplifier
description: Reduce overengineering and simplify designs, code, or plans. Use when a user asks to simplify, remove complexity, or find minimal viable approaches.
---

Evaluate the code or proposal for unnecessary complexity and suggest simplifications.

## Check for

- Abstractions that don't earn their keep
- Premature optimization
- Simpler ways to express the same logic
- Overused or cargo-culted patterns
- Excessive configurability that nobody asked for

## Output format

1. **Complexity overview** — what is overbuilt and why it matters
2. **Simplification opportunities** — specific things to cut or flatten
3. **Minimal alternative** — show a simpler version if applicable
4. **Tradeoffs** — what is lost by simplifying and why it is acceptable

## Example output

Complexity overview: The plugin system adds three indirection layers but only supports one plugin today.

Simplification opportunities:
- Replace the plugin registry with a single function call
- Remove dynamic configuration and hardcode the only supported mode

Minimal alternative:
```
def run_job(config):
    return process(config["input"])
```

Tradeoffs: You lose future plugin extensibility, but you reduce maintenance overhead and speed up onboarding.
