# CLAUDE.md

**Claude Code instructions for this repository.** Read `AGENTS.md` first — this file extends it with Claude-specific guidance.

## Quick Reference

```bash
just verify          # REQUIRED before declaring any task done
just format          # ruff format + prettier
just check           # ruff + mypy + svelte-check + eslint
just test            # backend pytest
just dev             # start both servers
```

## Claude Code Behaviour

- **No confirmation prompts** on implementation details — decide, implement, verify
- **Stop and ask** only on genuine requirement ambiguity or conflicts with AGENTS.md rules
- **Always run `just verify`** before declaring a task complete — never skip this
- **One task at a time** in the todo list; mark complete immediately when done

## Agentic Workflow

Sequential with parallelism only where independent:

1. **Explore** → gather context before anything else (prerequisite for all other steps)
2. **Plan** → orchestrator creates a structured plan from exploration results (depends on step 1)
3. **Implement** → delegate to backend/frontend; parallelize only independent implementation tasks (depends on step 2)
4. **Verify + Review** — `just verify` must pass and reviewer checks the diff (depends on step 3)
5. **Reflect** — update `AGENTS.md` with any new learnings

**Critical:** Do NOT parallelize Explore, Plan, and Implement. Each step depends on the previous one's results. Only parallelize when two implementation tasks are truly independent (e.g., backend and frontend changes).

## Tool Usage

- **Grep/Glob** for targeted searches; **Explore agent** for broad codebase exploration
- **Read before Edit** — always read a file before modifying it
- **Write** only for new files; **Edit** for modifications
- Prefer **parallel tool calls** for independent reads/searches

## Code Standards

Defer to `STYLE_GUIDE.md` for all style decisions. Key reminders:

- All Svelte components need `lang="ts"`
- No `any` — infer types or use proper generics
- `$derived` over `$effect` for computed state
- `const` over `let`; early returns over `else`
- Panda CSS for all styling — no inline styles
