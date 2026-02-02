---
description: Does end-to-end testing of the application using Playwright.
model: github-copilot/grok-code-fast-1
mode: subagent
temperature: 0.7
tools:
  write: true
  edit: true
---

# E2E Testing Skill

Use this skill for comprehensive end-to-end testing of the application using Playwright.

## Prompt Template for Testing New Features

When testing a new feature, use this prompt:

```
I need to test the [FEATURE NAME] functionality.

Start services:
1. Start backend on port 8000
2. Start frontend on port 5173

Test flow:
1. [Step 1 - e.g., "Create new analysis"]
2. [Step 2 - e.g., "Add data source"]
3. [Step 3 - e.g., "Configure operation"]
4. [Step 4 - e.g., "Verify output"]

Verify:
- [Specific assertion 1]
- [Specific assertion 2]
- [Specific assertion 3]

Report results in table format with status, feature, and notes.
```

## How to Start Services

```bash
# Terminal 1 - Backend
cd /home/kripso/workspace/polars-fastapi-svelte/backend
uv run main.py

# Terminal 2 - Frontend
cd /home/kripso/workspace/polars-fastapi-svelte/frontend
npm run dev -- --port 5173 --host
```

## How to Create Test Analysis

1. Navigate to http://localhost:5173
2. Click "New Analysis" button
3. Enter analysis name
4. Select data source from available options
5. Add operations from the pipeline builder
6. Configure each operation's settings
7. Save analysis
8. Run engine and verify results

## Testing Pipeline Operations

For each operation type (filter, group_by, aggregate, etc.):

1. Click "Add Step" in pipeline
2. Select operation from dropdown
3. Open config panel - verify it opens correctly
4. Configure operation parameters
5. Click "Apply" to save configuration
6. Verify step appears in pipeline with correct config
7. Run engine and verify output data

## Checklist for Complete E2E Coverage

### Analysis Creation

- [ ] Create new analysis from dashboard
- [ ] Enter valid analysis name
- [ ] Cancel creation flow
- [ ] Create multiple analyses

### Data Source Selection

- [ ] Upload new data source
- [ ] Select from existing data sources
- [ ] Remove data source
- [ ] Verify data preview loads

### Operation Config Panels

- [ ] Filter operation config
- [ ] Group by operation config
- [ ] Aggregate operation config
- [ ] Select columns operation config
- [ ] Sort operation config
- [ ] Rename operation config
- [ ] Derived column operation config

### Pipeline Step Management

- [ ] Add step to pipeline
- [ ] Edit step configuration
- [ ] Delete step from pipeline
- [ ] Reorder steps (drag and drop)
- [ ] Duplicate step
- [ ] Toggle step enabled/disabled

### Save/Load Persistence

- [ ] Save new analysis
- [ ] Update existing analysis
- [ ] Load analysis from dashboard
- [ ] Verify unsaved changes warning
- [ ] Clear pipeline and start over

### Engine Lifecycle

- [ ] Create new engine
- [ ] Start engine execution
- [ ] Monitor engine progress
- [ ] Cancel running engine
- [ ] View engine results
- [ ] Delete engine
- [ ] Handle engine errors gracefully

### Export Functionality

- [ ] Export to CSV
- [ ] Export to Parquet
- [ ] Export to JSON
- [ ] Verify exported file contents

### Error Handling

- [ ] Invalid configuration validation
- [ ] Missing required fields
- [ ] Connection errors
- [ ] Invalid data format
- [ ] Operation failures
- [ ] Error messages are user-friendly

## Reporting Format for Test Results

### Test Results Table

| Status | Feature               | Notes                   |
| ------ | --------------------- | ----------------------- |
| ✅     | Analysis creation     | Works correctly         |
| ✅     | Data source selection | Preview loads fast      |
| ❌     | Filter config panel   | Missing column dropdown |
| ⚠️     | Export CSV            | Large files timeout     |

### Summary Section

**Total Tests:** 24
**Passed:** 22
**Failed:** 1
**Warnings:** 1
**Pass Rate:** 91.7%

### Known Issues

- Filter operation config panel doesn't load column dropdown when opened for first time
- Export timeout for files larger than 100MB

### Backend Status

| Service  | Status       | Port   |
| -------- | ------------ | ------ |
| Backend  | ✅ Running   | 8000   |
| Frontend | ✅ Running   | 5173   |
| Database | ✅ Connected | SQLite |

### Recommendations

1. Fix filter operation column dropdown issue
2. Add streaming for large file exports
3. Consider adding progress indicator for data preview

## Testing Node (Operation) Patterns

Each operation should be tested with:

1. **Happy path**: Valid configuration → success
2. **Edge cases**: Empty values, invalid types, boundary values
3. **Error cases**: Missing required fields, invalid combinations
4. **UI feedback**: Loading states, error messages, success confirmation

Example test sequence for "Filter" operation:

1. Add Filter step to pipeline
2. Open config panel
3. Select column from dropdown
4. Select operator (equals, contains, etc.)
5. Enter filter value
6. Click Apply
7. Verify step appears in pipeline
8. Run engine
9. Verify filtered results in output
