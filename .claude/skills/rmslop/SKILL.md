---
name: rmslop
description: Remove AI-generated code slop from diffs by stripping unnecessary comments, defensive checks, any-casts, inconsistent styles, and emoji. Use when asked to clean up AI-y changes, tidy diffs, or make code match existing conventions.
---

# Rmslop

## Workflow

1. **Compare against base** — review the diff against the base branch (usually `dev`).
2. **Identify slop patterns** — look for the categories in the checklist below.
3. **Trim aggressively** — remove slop while keeping behavior intact.
4. **Align style** — match existing file conventions and patterns.
5. **Report concisely** — 1-3 sentences on what was changed.

## Slop checklist

- Comments a human would not add or that mismatch the file’s tone
- Defensive checks or try/catch blocks that are abnormal for the area
- `any` casts or type escapes to bypass type issues
- Styling inconsistent with the rest of the file
- Unnecessary emoji usage

## Output format (strict)

Return only a short report at the end:

1. **Summary** — 1-3 sentences describing what was removed or simplified

Do not include extra analysis sections.

## Example output

Summary: Removed redundant null checks and a defensive try/catch in the service layer, and deleted two inline comments that restated the code. Kept the same logic while aligning with existing style.
