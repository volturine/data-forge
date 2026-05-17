# PRD: Schedule Descriptions

## Overview

Add a first-class schedule description field so users and AI agents can store why a schedule exists, what it is intended to accomplish, and any operational caveats that are not captured by trigger mechanics alone.

## Problem Statement

Schedules currently expose trigger mechanics such as cron expressions, dependency links, or datasource triggers, but they do not persist a human-authored description.

That means the product can answer **how** a schedule runs, but not **why** it exists.

Teams need to store answers to questions like:

- Why does this schedule exist?
- What business outcome depends on this run?
- Is this schedule for production reporting, ad hoc refresh, QA validation, or experimentation?
- What caution should an AI agent consider before editing or disabling it?

Without a first-class description field:

1. Monitoring views show trigger summaries but not operational intent.
2. AI can infer schedule mechanics, but not schedule purpose.
3. Users cannot document exceptions, run windows, or stakeholder expectations inside the schedule itself.
4. Trigger summary strings risk being misused as pseudo-descriptions even though they are computed UI text.

## Goals

| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Persist an optional description on every schedule | Schedule model stores nullable `description` |
| G-2 | Separate trigger summary from human-authored context | UI shows both trigger mechanics and description distinctly |
| G-3 | Make descriptions editable during create and update | Schedule create/edit flows support plain-text description |
| G-4 | Make descriptions readable and writable by AI | Standard schedule contracts expose the field directly |
| G-5 | Improve monitoring clarity | Users can understand a schedule's intent from the monitoring UI |

## Non-Goals

- Rich operational runbooks or attachments in v1
- Schedule ownership/paging policy redesign
- Automated schedule description generation in v1
- Historical audit timeline for every description edit in v1

## User Stories

### US-1: Add Description While Creating a Schedule

> As a user, I want to describe a schedule when I create it so others understand why it exists.

**Acceptance Criteria:**

1. Schedule create UI includes an optional `Description` field.
2. The field accepts multi-line plain text.
3. Saving a new schedule persists the description.
4. Leaving the field empty is valid.

### US-2: Edit Description on Existing Schedule

> As a user, I want to update the description of an existing schedule as business context changes.

**Acceptance Criteria:**

1. Existing schedules expose an edit path for description.
2. Users can update or clear the description without recreating the schedule.
3. Save failures surface explicit errors.

### US-3: Read Description in Monitoring and Detail Views

> As a user, I want monitoring surfaces to show the schedule's purpose, not just its trigger mechanics.

**Acceptance Criteria:**

1. Monitoring/details views display the stored description.
2. Trigger summary remains visible as a separate computed field.
3. Empty descriptions show a clear empty state.

### US-4: AI Can Use Schedule Descriptions

> As an AI agent, I need schedule descriptions in read and write contracts so I can reason about schedule intent before suggesting edits.

**Acceptance Criteria:**

1. Schedule list and detail responses include `description`.
2. Schedule create and update contracts accept `description`.
3. AI-facing tool surfaces expose the same field directly.
4. Description is plain text, not derived from trigger summary strings.

## Technical Design

### Backend

Add a nullable `description` field directly to the schedule model.

#### Proposed Model Change

```python
class Schedule(SQLModel, table=True):
    id: str
    datasource_id: str
    description: str | None = None
    cron_expression: str
    enabled: bool = True
    ...
```

#### API Contract Changes

```python
class ScheduleCreate(BaseModel):
    datasource_id: str
    description: str | None = None
    cron_expression: str
    ...

class ScheduleUpdate(BaseModel):
    description: str | None = None
    enabled: bool | None = None
    ...

class ScheduleResponse(BaseModel):
    id: str
    datasource_id: str
    description: str | None
    cron_expression: str
    ...
```

#### Rules

- Empty string is normalized to `null`.
- Maximum length: 2,000 characters.
- `description` is included in list, create, update, and detail contracts.
- Computed trigger labels remain derived UI text and must not replace `description`.

### Frontend

#### Create/Edit UX

Add `Description` to the shared schedule manager form.

Display order:

1. Target dataset
2. Description
3. Trigger type
4. Trigger-specific configuration

#### Monitoring UI

1. Show description in expanded schedule details.
2. Optionally show a short description preview in the table when space allows.
3. Keep `Trigger` and `Description` as separate concepts.

### AI Surfaces

- Any MCP/tool wrapper for schedules must return `description` directly.
- AI write paths must support updating only `description` without requiring trigger changes.

## Migration

- Add nullable `description` column to schedules.
- Existing schedules backfill to `null`.
- No special legacy behavior beyond nullable reads is required.

## Rollout Plan

| Phase | Scope |
|-------|-------|
| 1 | Add schedule migration and backend schema updates |
| 2 | Thread description through scheduler service and routes |
| 3 | Add create/edit/display support in schedule manager and monitoring UI |
| 4 | Expose description in AI-facing tool contracts |
| 5 | Add tests for create, update, and monitoring display |

## Acceptance Criteria

- [ ] Schedule model supports nullable `description`
- [ ] Schedule create and update APIs accept `description`
- [ ] Schedule list/detail APIs return `description`
- [ ] Schedule creation and edit flows include a description field
- [ ] Monitoring/detail views display stored description separately from trigger summary
- [ ] AI-facing read/write contracts expose the same field directly
- [ ] `just verify` passes
