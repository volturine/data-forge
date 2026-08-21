# PRD: Frontend Component Decomposition

> **Status:** Backlog — identified by the 2026-08 codebase audit.
> **Portfolio:** [PRD index](../README.md)

## Summary

Several frontend surfaces have grown into multi-thousand-line monoliths that concentrate unrelated responsibilities, slow review, and raise regression risk on every change. This PRD tracks their decomposition into focused components and modules.

## Problem

Audit-measured hotspots:

| File | Lines | Responsibilities mixed |
|------|-------|------------------------|
| `lib/components/chat/ChatPanel.svelte` | ~2,640 | message list, markdown pipeline, composer, tool-call rendering, virtualization |
| `routes/analysis/[id]/...` editor page | ~2,611 | tab state, step editing, preview orchestration, build triggers |
| `lib/components/datasources/ScheduleManager.svelte` | ~2,043 | schedule CRUD, cron editing, run history |
| `lib/components/datasources/DatasourceConfigPanel.svelte` | ~1,906 | config tabs, ingest settings, runs, stats |

Additional audit findings folded in here:

- Keyboard-inaccessible clickable table rows across the manager screens (a11y).
- Small uncleared `setTimeout`/timer leaks.
- Hand-maintained frontend enum-token tables that can drift from generated protocol enums.

## Scope

- [ ] Decompose each hotspot into single-responsibility components/modules; no behavior changes in the same PR as a decomposition step.
- [ ] Replace clickable-row patterns with accessible buttons or row-level interactive semantics.
- [ ] Centralize timer lifecycle (one utility, effect-scoped cleanup).
- [ ] Generate enum token tables from the protocol toolchain instead of hand maintenance.

## Non-goals

- Rewriting state management or swapping libraries.
- Visual redesign of the affected screens.

## Success criteria

- No `.svelte` component exceeds ~800 lines; each has one reason to change.
- `just check`, unit tests, and e2e stay green throughout; decomposition lands as a series of small PRs.
