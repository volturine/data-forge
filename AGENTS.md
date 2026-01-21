# AGENTS.md

This file provides guidance to AI coding assistants (OpenCode, Copilot, Claude Code) when working with code in this repository.

## Model Configuration

Default Model: minimax m2.1 free

## General Guidelines

As an autonomous agent you will:

1. Call vibe_check after planning and before major actions.
2. Provide the full user request and your current plan.
3. Optionally, record resolved issues with vibe_learn.

### Backend (Python/FastAPI)

- Use async/await for all database operations
- Follow RORO pattern: service functions receive Pydantic input, return Pydantic output
- Use type hints everywhere
- Use Pydantic V2 with `model_config = ConfigDict(from_attributes=True)`
- Use SQLAlchemy `Mapped` type hints for models
- Keep routes thin - business logic goes in services

### Frontend (Svelte/TypeScript)

ALWAYS use Svelte 5 runes - never legacy syntax:

```svelte
<script lang="ts">
  let count = $state(0);
  let doubled = $derived(count * 2);
  $effect(() => {
    console.log(`Count: ${count}`);
  });
  interface Props {
    name: string;
  }
  let { name }: Props = $props();
  let value = $bindable(0);
</script>
```

NEVER use legacy syntax:

- `let x = 0` for reactive state (use `$state()`)
- `$: x = ...` for derived values (use `$derived()`)
- `export let` for props (use `$props()`)
- `onMount` lifecycle (use `$effect()`)

### Data Fetching

Use TanStack Query for server state:

```svelte
<script lang="ts">
  import { createQuery } from '@tanstack/svelte-query';
  const query = createQuery({
    queryKey: ['items'],
    queryFn: fetchItems
  });
</script>
```

### Styling

Use scoped CSS in Svelte components with the `<style>` tag.

### File Naming

- Backend: `snake_case.py`
- Frontend components: `PascalCase.svelte`
- Frontend utilities: `kebab-case.ts`
- Stores: `*.svelte.ts` (enables runes outside components)

### Import Patterns

```typescript
// Frontend - use $lib alias
import { apiRequest } from "$lib/api/client";
import { authStore } from "$lib/stores/auth.svelte";
```

```python
# Backend - use relative imports within modules
from core.config import settings
from modules.auth.schemas import UserResponse
```

### Runed Utilities

This project uses [Runed](https://runed.dev/docs) for Svelte 5 utilities:

```typescript
import {
  PersistedState,
  Debounced,
  FiniteStateMachine,
  onClickOutside,
  Previous,
} from "runed";

// Debounced state for search inputs
const searchQuery = $state("");
const debouncedSearch = new Debounced(() => searchQuery, 200);

// Finite state machine for complex state transitions
type SaveStates = "saved" | "unsaved" | "saving";
type SaveEvents = "markUnsaved" | "startSave" | "saveComplete" | "saveError";
const saveStatus = new FiniteStateMachine<SaveStates, SaveEvents>("saved", {
  saved: { markUnsaved: "unsaved" },
  unsaved: { startSave: "saving" },
  saving: { saveComplete: "saved", saveError: "unsaved" },
});

// Persist state to localStorage
const settings = new PersistedState("user-settings", { theme: "dark" });

// Click outside detection for modals/dropdowns
let modalRef = $state<HTMLElement>();
onClickOutside(
  () => modalRef,
  () => closeModal(),
);

// Track previous values
const prevValue = new Previous(() => someValue);
if (prevValue.hasChanged()) {
  /* react to change */
}
```

## Project Overview

Full-stack template: SvelteKit 2 frontend + FastAPI backend + SQLite database.

## Common Commands

### Backend (from `backend/` directory)

```bash
uv sync --extra dev                        # Install dependencies
uv run main.py                             # Start dev server (port 8000)
uv run pytest                              # Run tests
uv run pytest -k "test_name"               # Run tests matching pattern
uv run pytest path/to/test_file.py         # Run specific test file
uv run ruff format . && uv run ruff check --fix .  # Format and lint
uv run mypy .                              # Type check
```

### Frontend (from `frontend/` directory)

```bash
npm install                 # Install dependencies
npm run dev                 # Start dev server (port 5173)
npm run build               # Production build
npm run test                # Run all tests
npm run test -- src/lib/foo # Run tests in specific directory
npm run test -- --ui        # Run tests with UI
npm run check               # TypeScript check
npm run lint && npm run format  # Lint and format
```

## Available Agents

### PRD Generator

Creates detailed Product Requirements Documents from feature requests.

Usage: Run the "PRD Generator" agent when you need to document a new feature.

### Task List Generator

Creates implementation task lists from PRDs or feature requirements.

Usage: Run the "Task List Generator" agent after creating a PRD or when you have clear requirements.

### Code Reviewer

Automated code review following project conventions.

Usage: Automatic via OpenCode integration. Reviews Python and Svelte/TypeScript files.

## Environment Setup

Copy `.env.example` to `.env` in both `backend/` and `frontend/` directories.

## Git Restrictions

- NEVER push to remote repositories
- Only local commits are allowed
- To share changes, create a pull request or ask a maintainer to push

## Testing

### Playwright E2E Testing Strategy

This project uses Playwright MCP for end-to-end testing with a subagent-based approach to keep the main processing agent uncluttered.

#### Philosophy

- Use subagents for testing to avoid cluttering main processing agents
- Test every functionality by creating a new analysis for each test session
- Test compute pipeline nodes (operations) thoroughly
- Subagents run Playwright tests in parallel while the main agent coordinates

#### Testing Workflow

1. **Per-Feature Testing**: Each new feature gets its own analysis to avoid state pollution
2. **Node Testing**: Test compute nodes (operations) by adding them to pipelines and verifying:
   - Config panel opens correctly
   - Step appears in pipeline
   - Save succeeds
   - Preview/data loads correctly

3. **Subagent Pattern**:
   ```typescript
   // Main agent coordinates
   await task((subagent_type = "general"), (command = "/test-feature-x"));
   // Subagent runs Playwright, reports results back
   ```

#### Quick Test Script

```bash
# Start services
cd /home/kripso/workspace/polars-fastapi-svelte
uv run main.py &    # Backend on port 8000
cd frontend
npm run dev -- --port 5173 --host &  # Frontend on port 5173

# Run tests via Playwright MCP
```

#### Available as OpenCode Skill

Create a skill `e2e-testing` that provides:

- Prompt template for testing new features
- Checklist for complete E2E coverage
- Reporting format for test results

#### Test Coverage Requirements

- ✅ New analysis creation flow
- ✅ Data source selection
- ✅ All operation config panels
- ✅ Pipeline step management (add, edit, delete, reorder)
- ✅ Save/load state persistence
- ✅ Engine lifecycle (creation, monitor, shutdown)
- ✅ Export functionality
- ✅ Error handling

### E2E Testing Lessons Learned

During comprehensive E2E testing of this project, the following patterns and lessons were documented:

#### 1. Subagent Pattern for Testing

**Why**: Avoids cluttering main processing agent with Playwright interactions.

**How**:

```typescript
// Main agent coordinates testing
await task((subagent_type = "general"), (command = "/test-phase-5-operations"));
// Subagent runs Playwright, reports results back
```

**Benefits**:

- Parallel test execution possible
- Clean separation of concerns
- Each test gets fresh analysis (no state pollution)
- Standardized reporting format

#### 2. File Upload Monitoring

**Check uploads directory**:

```bash
ls -la /home/kripso/workspace/polars-fastapi-svelte/data/uploads/
```

Files are renamed to UUIDs when uploaded (e.g., `6ce4c9e9-b4de-4dde-a143-80f772390972.csv`).

#### 3. Test Organization

**Use Phases Structure**:

- Phase 1: Home Page
- Phase 2: Create Analysis Wizard
- Phase 3: Data Sources Management
- Phase 4: Analysis Editor
- Phase 5: Operations Pipeline
- Phase 6: Engine Lifecycle
- Phase 7: Export Functionality
- Phase 8: Error Handling

**Analysis Naming**: Use descriptive names like `E2E Test - Phase 5 Operations` to avoid confusion.

#### 4. Status Tracking

**Use todo list** to track progress across sessions:

```typescript
todowrite({
  todos: [
    { id: "1", content: "Test Phase 5 operations", status: "in_progress" },
    { id: "2", content: "Update E2E_TEST_RESULTS.md", status: "pending" },
  ],
});
```

#### 5. Documentation

**E2E_TEST_RESULTS.md is source of truth**:

- Track completed/blocked tests per phase
- Document bugs found and fixes applied
- Note Docker MCP limitations
- Update after each testing session

**Sections to include**:

- Test execution log
- Phase-by-phase results
- Key findings (what works, what needs testing)
- Known issues
- Session notes

#### 6. Playwright MCP Limitations

| Feature                 | Status                 | Workaround                       |
| ----------------------- | ---------------------- | -------------------------------- |
| Host file access        | ❌ Blocked             | check the ./data local directory |
| Slow network simulation | ❌ Blocked             | Manual test                      |
| Drag-drop operations    | ⚠️ Partial             | Manual verification              |
| WebSocket connections   | ⚠️ Errors non-critical | Ignore HMR errors                |

#### 7. Frontend URLs for Testing

- **Development**: http://192.168.1.140:5173 (network-accessible)
- **Local**: http://localhost:5173
- **Backend**: http://localhost:8000

**Start services**:

```bash
cd /home/kripso/workspace/polars-fastapi-svelte
uv run main.py &    # Backend on port 8000
cd frontend
npm run dev -- --port 5173 --host &  # Frontend on port 5173
```

#### 8. Testing Checklist Template

When testing new features, verify:

- [ ] Config panel opens correctly
- [ ] Step appears in pipeline
- [ ] Save succeeds
- [ ] Preview/data loads correctly
- [ ] Error handling works
- [ ] Update E2E_TEST_RESULTS.md

### Frontend Responsiveness During Testing

**CRITICAL**: During E2E testing with Playwright, if any operation times out or the UI becomes unresponsive:

1. **IMMEDIATELY investigate** - An unresponsive frontend usually indicates:
   - Infinite loop in JavaScript/TypeScript code
   - Uncaught exception in event handlers
   - Excessive re-rendering cycles
   - Memory leak causing browser to freeze

2. **Check for these common causes**:
   - Missing dependency in `$derived` or `$effect` causing infinite recursion
   - `$state` updates that trigger effects that update the same state
   - Incorrect use of `$effect` without cleanup functions
   - Too many concurrent reactive updates

3. **If UI is unresponsive**:
   - Open browser DevTools console for errors
   - Check `page.snapshot()` for infinite loops in rendering
   - Review recent code changes for potential issues
   - Run `npm run check` for TypeScript errors that might cause runtime issues

4. **Never ignore timeouts** - A timeout during testing is a signal that something is wrong, not just a slow operation. An infinite loop will cause the browser to become completely unresponsive, requiring a full restart.
