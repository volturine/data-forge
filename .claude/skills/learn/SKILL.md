---
name: learn
description: Extract non-obvious learnings from a session into AGENTS.md files. Use after finishing meaningful work, debugging, or repeatable discoveries that should be captured for future sessions.
---

Analyze the current session and distill non-obvious learnings into AGENTS.md files so future sessions avoid repeating mistakes.

## How AGENTS.md works

AGENTS.md files can exist at any directory level. When an agent reads a file, any AGENTS.md in parent directories is automatically loaded into context. Placement matters — put learnings as close to the relevant code as possible.

| Scope | Location |
|-------|----------|
| Project-wide | `AGENTS.md` (root) |
| Package or module | `transforms-python/AGENTS.md` |
| Feature-specific | `src/myproject/datasets/AGENTS.md` |

## What to capture

Only record **non-obvious** discoveries — things a developer would not know from reading the README or standard docs, or issues that were encountered and resolved during the session. Focus on insights that save time, prevent bugs, or clarify confusing aspects of the codebase.

## Process

1. **Scan the session** — look for discoveries, multi-attempt debugging, surprises, and unexpected connections
2. **Classify by scope** — determine which directory level each learning belongs to
3. **Read existing AGENTS.md files** at the relevant levels to avoid duplicates
4. **Create or update** AGENTS.md at the appropriate level
5. **Keep each entry to 1-3 lines** — concise and focused on the insight
6. **Group related entries** under a heading if there are multiple learnings for the same area
7. **Avoid hindsight noise** — do not include obvious steps or command output

## After updating

Provide a summary:

- Which AGENTS.md files were created or updated
- How many learnings were added to each
- A one-line preview of the most impactful learning

If there are no non-obvious learnings, state that clearly and do not edit files.

## Output format (strict)

1. **Files updated** — list of `AGENTS.md` paths
2. **Learnings added** — count per file
3. **Most impactful** — one-line preview

## Example output

Files updated: `AGENTS.md`, `transforms-python/AGENTS.md`
Learnings added: `AGENTS.md` (2), `transforms-python/AGENTS.md` (1)
Most impactful: Spark transforms must use `output.write_dataframe`, not `write_table`.

## Example entries

- Spark transforms must use `output.write_dataframe` or writes will fail at runtime.
- Ruff config lives in `transforms-python/src/ruff.toml`, not the repo root.

$ARGUMENTS
