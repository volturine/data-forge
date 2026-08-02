# PRD: Application Shell and Shared Panels

> **Status (audited 2026-08-02): Backlog — navigation redesign has not started.**
> **Portfolio:** [PRD index](../README.md) · [Feature-overhaul portfolio](data-forge-2.md)

## Purpose

Create a coherent application shell whose navigation and route-level panels remain consistent as the product grows. This is a UI architecture PRD; it does not own authentication policy or lineage semantics.

## Decisions required before implementation

- [ ] Choose a full sidebar, collapsible icon rail, or hybrid primary navigation model.
- [ ] Define which routes use a shared panel framework in the initial pass.
- [ ] Define compact/mobile behavior and keyboard-navigation expectations.

## Scope

### Navigation foundation

- [ ] Build an accessible primary-navigation component with active state, responsive behavior, and persistent user preferences where appropriate.
- [ ] Make authentication/account state visible without coupling route layout to auth implementation details.
- [ ] Preserve route ownership: pages compose the shell; feature modules own feature state.

### Shared panels

- [ ] Create a reusable panel contract for headings, actions, loading/error states, and responsive layout.
- [ ] Adopt it deliberately in Analyses, Datasources, and Lineage rather than forcing every existing view into it.
- [ ] Remove duplicate fixed-aside and one-off panel implementations as each route migrates.

## Verification

- [ ] Test active navigation, collapse/expand, focus management, and narrow-viewport behavior.
- [ ] Test route transitions and panel interactions across analyses, datasources, and lineage.
- [ ] Confirm the shell does not trigger unnecessary feature fetches or remount work.
