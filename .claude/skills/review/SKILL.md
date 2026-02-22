---
name: review
description: Review code or diffs for correctness, security, performance, maintainability, and project conventions. Use when asked to review code, changes, or provide QA feedback.
---

Review the provided code or changes for:

1. **Correctness**: Logic errors, edge cases, potential bugs
2. **Best practices**: Following project conventions (see AGENTS.md)
3. **Security**: Potential vulnerabilities
4. **Performance**: Obvious inefficiencies
5. **Maintainability**: Readability, complexity

## Project-Specific Checks

- Read relevant `AGENTS.md` files before reviewing
- Apply language- and framework-specific conventions from the repo
- If no project-specific conventions are found, review against general best practices

## Response Format

Provide specific, actionable feedback:

### Assessment

Agree / Partially Agree / Disagree with the approach, with 1-2 sentences of rationale

### Strengths

1-3 bullets, each naming a concrete positive

### Issues Found

Use this exact bullet format for each issue:

- Severity: High|Medium|Low; Location: file:line; Issue: <description>; Fix: <suggested fix>

### Recommendations

Numbered list, highest impact first

---

Code to review:
$ARGUMENTS

## Example output

### Assessment
Partially Agree — the approach is sound, but there are unsafe edge cases around null handling.

### Strengths
- Clear separation between parsing and validation steps
- Query is parameterized to avoid injection risks

### Issues Found
- Severity: High; Location: src/app.ts:42; Issue: Accesses `user.id` without null check; Fix: Guard with `if (!user) return` before access.
- Severity: Medium; Location: src/db.py:118; Issue: Missing transaction rollback on failure; Fix: Wrap in `try/except` and call `rollback()`.

### Recommendations
1. Add unit tests for null user paths to prevent regressions.
2. Consider extracting validation into a reusable helper.
