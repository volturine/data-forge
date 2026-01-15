# Claude Code Configuration

This directory contains Claude Code configuration and specialized instruction sets.

## Files

### settings.local.json
Main configuration file with:
- **Permissions**: Pre-approved commands for development workflow
- **Model**: Default model preference (sonnet)

All Read, Edit, Write, Glob, and Grep operations are pre-approved.
Common development commands are allowed: npm, uv, git, just, pytest, ruff, mypy, etc.

### Instruction Files

These files provide specialized guidance for different types of work:

#### code-reviewer-instructions.md
Use when: Reviewing code, checking quality, providing feedback
- Enforces Svelte 5 runes (no legacy syntax)
- Checks RORO pattern in backend
- Validates type safety and best practices
- Provides constructive, specific feedback

#### prd-writer-instructions.md
Use when: Creating Product Requirements Documents
- Comprehensive PRD structure
- Technical approach with frontend/backend details
- User stories with acceptance criteria
- Testing strategy and edge cases

#### task-planner-instructions.md
Use when: Breaking down work into implementation tasks
- Specific, testable tasks with file paths
- Properly ordered (DB → Backend → Frontend → Tests)
- Includes verification steps
- Follows project conventions

#### docs-writer-instructions.md
Use when: Writing documentation
- Relaxed, friendly tone
- Short paragraphs (max 2 sentences)
- Imperative mood for sections
- Code examples without trailing semicolons
- Commits prefixed with `docs:`

## How to Use

### Automatic
Claude Code automatically reads `.clinerules` in the project root.

### Manual Reference
When you need specialized guidance, you can ask Claude to reference these files:
- "Review this code following the code-reviewer-instructions"
- "Create a PRD using the prd-writer-instructions"
- "Break this down into tasks following task-planner-instructions"
- "Write documentation using the docs-writer-instructions"

### Direct @mention
You can @mention these files directly in your prompts:
```
@.claude/code-reviewer-instructions.md Review this component
```

## Project Context

Key project files Claude should reference:
- `AGENTS.md` - Development guidelines
- `STYLE_GUIDE.md` - Code style preferences
- `docs/PRD.md` - Complete product requirements
- `tasks/` - Implementation task breakdowns

## Permissions

Pre-approved operations:
✅ All file operations (Read, Edit, Write, Glob, Grep)
✅ npm commands (install, run, build, test, etc.)
✅ uv commands (sync, add, run, etc.)
✅ git commands (status, add, commit, push, etc.)
✅ just commands (task runner)
✅ Python tools (pytest, ruff, mypy)
✅ Common shell commands (ls, cat, mkdir, cp, mv, etc.)

## Customization

Edit `settings.local.json` to:
- Add more pre-approved commands
- Change default model
- Add hooks for specific events
- Configure additional permissions

See the [Claude Code settings schema](https://json.schemastore.org/claude-code-settings.json) for all options.
