---
description: Review code for quality, bugs, and best practices
agent: second-opinion
subtask: true
---

Review the following code or changes for:

1. **Correctness**: Logic errors, edge cases, potential bugs
2. **Best practices**: Following project conventions (see AGENTS.md)
3. **Security**: Potential vulnerabilities
4. **Performance**: Obvious inefficiencies
5. **Maintainability**: Readability, complexity

## Project-Specific Checks

### Frontend (Svelte)

- Using Svelte 5 runes (`$state`, `$derived`, `$props`, `$effect`)
- No legacy syntax (`export let`, `$:`, `onMount`)
- Proper TypeScript types

### Backend (Python)

- Async/await for database operations
- RORO pattern (Pydantic in/out)
- Type hints everywhere

## Response Format

Provide specific, actionable feedback:

### Assessment

Agree / Partially Agree / Disagree with the approach

### Strengths

What's good about the code

### Issues Found

- Severity (High/Medium/Low)
- Location (file:line)
- Description
- Suggested fix

### Recommendations

Improvements or alternatives

---

Code to review:
$ARGUMENTS
