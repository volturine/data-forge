---
name: Prefer dicts over lists of tuples
description: User prefers dict or dataclass over list[tuple] for named mappings
type: feedback
---

Use dicts (or dataclasses) instead of lists of tuples for named key-value mappings.

**Why:** User finds lists of tuples less readable and less semantically clear than dicts.

**How to apply:** When refactoring repeated patterns into a data-driven loop, use a dict (or dataclass if richer structure needed), not a list of tuples.
