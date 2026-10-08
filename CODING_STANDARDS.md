# Coding Standards

These are review-time judgment rules, not an implementation checklist. Keep mechanical requirements in lint or CI so they can be checked consistently.

## Scope and product decisions

- Keep one concern per pull request; split unrelated changes.
- When a change removes user-visible behavior or changes the access model, explain the product or security reason in the pull request description.

## Visual semantics

- Use status tokens such as `fg.error`, `fg.warning`, and `fg.success` only to communicate status. Use dedicated semantic tokens for other palettes, such as `syntax.*` for syntax highlighting.
- Never communicate a state or category through color alone. Pair color with text or an icon.

## Pull request risk

- `Merge Danger` must describe the concrete user or data impact and, for one-way changes, the migration or upgrade path.
- For stacked pull requests, name the base pull request in the description. Once the base merges, retarget to `master` and confirm the full required suite ran. A base-branch edit alone does not start `pull_request` checks; push a commit or close and reopen the pull request. Do not add `edited` solely to trigger tests, because skipped jobs can appear successful as required checks.
