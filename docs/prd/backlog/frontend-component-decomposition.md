# PRD: Frontend Component Decomposition

> **Status (2026-10-15): Backlog — not started.** The four original audit hotspots (`ChatPanel`, the analysis editor page, `ScheduleManager`, `DatasourceConfigPanel`) have since been split or shrunk below 1,000 lines; the table below lists today's largest components.
> **Portfolio:** [PRD index](../README.md)

## Summary

Several frontend surfaces have grown into multi-thousand-line monoliths that concentrate unrelated responsibilities, slow review, and raise regression risk on every change. This PRD tracks their decomposition into focused components and modules.

## Problem

Largest components (2026-10-15):

| File | Lines |
|------|-------|
| `lib/components/pipeline/OutputNode.svelte` | 1,813 |
| `lib/components/operations/PlotConfig.svelte` | 1,614 |
| `lib/components/common/HealthChecksManager.svelte` | 1,529 |
| `lib/components/common/BuildsManager.svelte` | 1,462 |
| `lib/components/common/BuildPreview.svelte` | 1,221 |
| `lib/components/common/DataTable.svelte` | 1,157 |
| `lib/components/datasources/BuildComparisonPanel.svelte` | 1,142 |

Eleven `.svelte` components exceed 800 lines.

Additional audit findings folded in here:

- Keyboard-inaccessible clickable table rows across the manager screens (a11y).
- Small uncleared `setTimeout`/timer leaks.
- Hand-maintained frontend enum-token tables that can drift from generated protocol enums.

## Scope

- [ ] Decompose each hotspot into single-responsibility components/modules; no behavior changes in the same PR as a decomposition step.
- [ ] Replace clickable-row patterns with accessible buttons or row-level interactive semantics.
- [ ] Centralize timer lifecycle (one utility, effect-scoped cleanup).
- [ ] Generate enum token tables from the protocol toolchain instead of hand maintenance.
  - Current gap is frozen by `protocol-enum-tokens.test.ts`: every generated enum must either have a table or appear on the explicit exemption list (22 exempted enums as of 2026-10-15). New protos fail the suite until tabled or exempted.

## Non-goals

- Rewriting state management or swapping libraries.
- Visual redesign of the affected screens.

## Success criteria

- No `.svelte` component exceeds ~800 lines; each has one reason to change.
- `just check`, unit tests, and e2e stay green throughout; decomposition lands as a series of small PRs.
