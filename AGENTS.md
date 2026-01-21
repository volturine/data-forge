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
