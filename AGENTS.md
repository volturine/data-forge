# AGENTS.md

This file provides guidance to AI coding assistants (OpenCode, Copilot, Claude Code) when working with code in this repository.

## Model Configuration

Default Model: minimax m2.1 free

## General Guidelines

As an autonomous agent you will:

1. Follow the **Explore → Plan → Code → Commit** workflow for complex tasks
2. Use `vibe_check` after planning and before major actions
3. Use `vibe_distill` when plans become overly complex
4. Record resolved issues with `vibe_learn` to improve future sessions
5. Use the **Second Opinion** agent before completing any significant task

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

### Config Defaults Pattern

When creating steps with configs, always provide proper defaults at creation time:

```typescript
// In step-config-defaults.ts - centralize all default configs
export function getDefaultConfig(stepType: string): StepConfig {
  const defaults: Record<string, StepConfig> = {
    select: { columns: [] },
    filter: { conditions: [{ column: '', operator: '=', value: '' }], logic: 'AND' },
    join: { how: 'inner', right_source: '', join_columns: [], right_columns: [], suffix: '_right' },
    // ... one entry per operation type
  };
  return JSON.parse(JSON.stringify(defaults[stepType] ?? {}));
}

// Use when building steps
import { getDefaultConfig } from '$lib/utils/step-config-defaults';

function buildStep(type: string): PipelineStep {
  return { 
    id: makeId(), 
    type, 
    config: getDefaultConfig(type) as Record<string, unknown>, 
    depends_on: [] 
  };
}
```

### Svelte 5 $effect Patterns

**DO NOT use `$effect` for data validation or initialization** - these are code smells indicating data should be fixed at the source:

```svelte
<!-- BAD: Defensive $effect in config component -->
<script>
  let { config = $bindable({}) }: Props = $props();
  
  $effect(() => {
    if (!config || typeof config !== 'object') {
      config = { columns: [] };
    }
  });
</script>

<!-- GOOD: Centralize defaults at step creation -->
<!-- In step-config-defaults.ts -->
export function getDefaultConfig(stepType: string) {
  const defaults = {
    select: { columns: [] },
    filter: { conditions: [], logic: 'AND' },
    // ...
  };
  return defaults[stepType] ?? {};
}

<!-- In +page.svelte -->
function buildStep(type: string) {
  return { 
    id: makeId(), 
    type, 
    config: getDefaultConfig(type),  // Proper defaults
    depends_on: [] 
  };
}
```

**Legitimate `$effect` uses:**
- DOM manipulation (theme changes, focus management)
- External side effects (API calls, localStorage)
- Event listener setup/cleanup
- Syncing internal UI state (SvelteSet) when external config changes

**Prefer `$derived` for computed values:**
```svelte
<!-- GOOD -->
let selectedColumns = $derived(new SvelteSet(config.columns ?? []));
```

**Config Normalization for Backward Compatibility:**
When loading saved data that might have malformed configs, normalize once in the store:
```typescript
// In analysis.svelte.ts
private normalizeSteps(steps: PipelineStep[]) {
  return steps.map(step => ({
    ...step,
    config: normalizeConfig(step.type, step.config)
  }));
}
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

### Subagents

| Agent | Description | When to Use |
|-------|-------------|-------------|
| **Second Opinion** | Validates implementations, provides independent code review | Before completing ANY task |
| **E2E Testing** | Playwright-based end-to-end testing with structured reporting | Automated UI testing |
| **Docks** | Technical documentation writer with concise, friendly tone | Always use when writing docs |
| **Learn** | Extracts non-obvious learnings to AGENTS.md files | After sessions to record discoveries |
| **Researcher** | Web research using Perplexity for docs and best practices | When current information is needed |
| **Debugger** | Systematic investigation and root cause analysis | When debugging complex issues |

### Slash Commands

| Command | Description |
|---------|-------------|
| `/prd-generator` | Creates detailed PRDs from feature requests |
| `/tasklist-generator` | Creates implementation task lists from PRDs |
| `/plan` | Create implementation plan before coding |
| `/review` | Quick code review using Second Opinion agent |
| `/clarify` | Ask clarifying questions before starting work |
| `/rmslop` | Removes AI-generated code slop (extra comments, defensive checks) |
| `/spellcheck` | Checks spelling/grammar in markdown file changes |

## MCP Servers

| Server | Description |
|--------|-------------|
| **Svelte** | Svelte documentation, autofixer, and playground links (remote) |
| **Perplexity** | AI search, research, and reasoning capabilities |
| **Playwright** | Remote browser automation for E2E testing (remote) |
| **Vibe Check** | Metacognitive oversight to prevent tunnel vision and over-engineering |
| **Filesystem** | File system operations (read, write, list, search within project directory) |
| **Memory** | Knowledge graph for storing and retrieving entities, relations, and observations |
| **Fetch** | HTTP requests to fetch URLs from the internet |
| **Sequential Thinking** | Dynamic reflective problem-solving with adaptive chain-of-thought |

### Vibe Check Tools

- `vibe_check` - Pattern interrupt that challenges assumptions during planning/implementation/review
- `vibe_distill` - Simplifies complex plans back to minimal viable approach
- `vibe_learn` - Records mistakes and solutions for future pattern recognition

### Sequential Thinking

Use `sequential-thinking` for:
- Complex multi-step problem solving
- Planning and design with room for revision
- Breaking down complex problems
- Analysis that might need course correction
- Hypothesis generation and verification

## Recommended Workflows

### Explore → Plan → Code → Commit

For most features and bug fixes:

1. **Explore**: Read relevant files, understand the codebase context
2. **Plan**: Create a plan (use `/plan`), get approval before coding
3. **Code**: Implement the solution
4. **Review**: Use Second Opinion agent to validate
5. **Commit**: Create a well-formed commit

### Test-Driven Development

For algorithmic or well-defined work:

1. Write tests based on expected input/output
2. Run tests, confirm they fail
3. Implement code to pass tests
4. Refactor if needed
5. Commit tests and implementation together

## Environment Setup

Copy `.env.example` to `.env` in both `backend/` and `frontend/` directories.

## Git Restrictions

- NEVER push to remote repositories
- Only local commits are allowed
- To share changes, create a pull request or ask a maintainer to push

## Testing

### Playwright E2E Testing Strategy

This project uses Playwright MCP for end-to-end testing with a subagent-based approach to keep the main processing agent uncluttered.

#### Quick Start

```bash
# Start services
cd backend && uv run main.py &
cd frontend && npm run dev -- --port 5173 --host &
```

#### Testing Workflow

1. Create a new analysis for each test session (avoid state pollution)
2. Use descriptive names like `E2E Test - Phase 5 Operations`
3. Report results in table format with status, feature, and notes
4. Update `E2E_TEST_RESULTS.md` after each session

#### Testing Checklist

When testing new features, verify:

- [ ] Config panel opens correctly
- [ ] Step appears in pipeline
- [ ] Save succeeds
- [ ] Preview/data loads correctly
- [ ] Error handling works
- [ ] Update E2E_TEST_RESULTS.md

#### Playwright MCP Limitations

| Feature | Status | Workaround |
|---------|--------|------------|
| Host file access | Blocked | Check `./data` local directory |
| Drag-drop operations | Partial | Manual verification |
| WebSocket connections | Errors non-critical | Ignore HMR errors |

### Frontend Responsiveness During Testing

**CRITICAL**: If any operation times out or UI becomes unresponsive during testing:

1. **Investigate immediately** - likely indicates infinite loop or uncaught exception
2. Check for: missing dependencies in `$derived`/`$effect`, `$state` update loops
3. Open DevTools console, run `npm run check` for TypeScript errors
4. **Never ignore timeouts** - they signal something is wrong
