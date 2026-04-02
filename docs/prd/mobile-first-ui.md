# PRD: Mobile-First UI

## Overview

Implement a mobile-first interface for Data-Forge based on the `mobile-design-concept.html` mockup. The mobile UI is AI-first, designed for phone-sized screens (320–428px), and provides a streamlined workflow: pick/create analysis → chat with AI → review pipeline → inspect data → fine-tune manually.

## Problem Statement

Data-Forge is currently desktop-only. The editor canvas (`PipelineCanvas`), step configuration panels, lineage graph, and datasource management are all designed for wide screens with mouse-based interaction. Mobile users cannot effectively use the application — the UI is not responsive, panels overflow, and touch interactions (tap, swipe) are not supported.

## Design Reference

All screens and interactions are defined in `/mobile-design-concept.html`. This PRD is derived directly from that mockup.

## Goals

| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Fully functional on 320px–428px screens | All flows completable on iPhone SE (375px) and iPhone 15 Pro (393px) |
| G-2 | AI-first interaction model | Primary workflow is chat → action card → confirm, not manual config |
| G-3 | Touch-optimized controls | All interactive elements ≥ 44px tap target, no hover-only interactions |
| G-4 | Consistent design language | Uses exact design tokens from existing desktop theme (no new colors) |
| G-5 | Progressive enhancement | Desktop experience unchanged; mobile layout loaded via media query or route |

## Non-Goals

- Tablet-optimized layout (focus on phone only; tablet uses desktop layout)
- Offline support / PWA
- Native mobile app (this is responsive web)
- Replacing desktop UI (mobile is an additional layout, not a replacement)

## Design Tokens (from Mockup)

All tokens match the existing `panda.config.ts` dark theme:

| Token | Value | Usage |
|-------|-------|-------|
| `bg.primary` | `#0e0e0e` | Page background |
| `bg.secondary` | `#111111` | Card backgrounds |
| `bg.tertiary` | `#171717` | Input backgrounds, nav bar |
| `bg.elevated` | `#1f1f1f` | Elevated panels, sheets |
| `bg.hover` | `#262626` | Hover/active states |
| `fg.primary` | `#fafafa` | Primary text |
| `fg.secondary` | `#d4d4d4` | Secondary text |
| `fg.muted` | `#a3a3a3` | Muted text, placeholders |
| `fg.subtle` | `#737373` | Subtle text, disabled |
| `border.primary` | `#262626` | Borders, separators |
| `success` | `#86efac` | Live status, success |
| `warning` | `#fde047` | Paused, pending |
| `error` | `#fca5a5` | Error, failed |
| Font | JetBrains Mono | Monospace throughout |
| Border radius | 0px | Zero radius everywhere |

## Design Principles (from Mockup)

1. **AI-first with manual escape hatches** — Chat is the primary interface; manual config is the fallback.
2. **Monospace font throughout** — JetBrains Mono at all sizes.
3. **Zero border-radius** — Consistent with desktop, no rounded corners.
4. **Semantic colors only for status** — Green = live, yellow = paused/pending, red = error.
5. **Step origin bars** — 3px left border encoding origin: white = AI-generated, amber = user-edited, green = chart step.
6. **No drag handles** — Panels anchored with 2px top border.
7. **Dense layouts** — Optimized for small screens, no wasted space.
8. **Bottom navigation** — 4 main areas always accessible.

## Screens

### Screen 01: Analyses Gallery

Entry point showing recent and all analyses.

**Layout:**

```
┌─────────────────────────────┐
│ ≡  data forge    + ⚙       │  ← Header: hamburger, title, new + settings
├─────────────────────────────┤
│ 🔍 search analyses...      │  ← Search input
├─────────────────────────────┤
│ recent                      │  ← Section label
│ ┌───────────────────────────┤
│ │ ● Sales Q1       12 steps │  ← Analysis row
│ │   150k rows  ■ live       │     status pill, metadata
│ │   ████████████████░░  85% │     progress bar
│ ├───────────────────────────┤
│ │ ● Churn Model    8 steps  │
│ │   42k rows   ■ paused     │
│ │   ██████████░░░░░░░░  52% │
│ ├───────────────────────────┤
│ │ ● Revenue ETL    15 steps │
│ │   1.2M rows  ■ live       │
│ │   ████████████████████ 100│
│ └───────────────────────────┤
│                             │
│                         [+] │  ← FAB: create new analysis
├─────────────────────────────┤
│ 🏠 Home  💬 Chat  ⚡ Pipe  📊 Data │ ← Bottom nav
└─────────────────────────────┘
```

**Components:**

- `MobileAnalysisGallery.svelte` — Gallery list with search and FAB.
- `MobileAnalysisRow.svelte` — Individual analysis row with metadata, status, progress.
- `MobileBottomNav.svelte` — Fixed bottom navigation bar.
- `MobileHeader.svelte` — Top header with hamburger menu, title, actions.

**Behavior:**

- Tap analysis row → navigate to Chat screen (Screen 02) in context of that analysis.
- Tap FAB → new analysis creation flow.
- Search is instant-filter on client side (no API call for < 100 analyses).

### Screen 02: AI Chat

Primary interaction screen. AI-first pipeline building.

**Layout:**

```
┌─────────────────────────────┐
│ ← Sales Q1    ⓘ model ▾    │  ← Header: back, analysis name, model selector
├─────────────────────────────┤
│ ┌src──┐┌filt──┐┌grp──┐     │  ← Pipeline strip (horizontal scroll)
│ └─────┘└──────┘└─────┘     │     compact step badges
├─────────────────────────────┤
│ 💬 messages                 │
│                             │
│ ┌─ system ─────────────────┐│
│ │ Pipeline loaded: Sales Q1 ││
│ │ 3 steps · 150k rows      ││
│ └──────────────────────────┘│
│                             │
│ ┌─ user ───────────────────┐│
│ │ filter to only active    ││
│ │ customers and sort by    ││
│ │ revenue descending       ││
│ └──────────────────────────┘│
│                             │
│ ┌─ assistant ──────────────┐│
│ │ I'll add two steps:      ││
│ │                          ││
│ │ ┌─ action card ─────────┐││
│ │ │ + filter              │││
│ │ │ status = 'active'     │││
│ │ │         [apply] [edit]│││
│ │ └───────────────────────┘││
│ │ ┌─ action card ─────────┐││
│ │ │ + sort                │││
│ │ │ revenue desc          │││
│ │ │         [apply] [edit]│││
│ │ └───────────────────────┘││
│ └──────────────────────────┘│
│                             │
│ [+ Chart] [Stats] [Export]  │  ← Quick chips
├─────────────────────────────┤
│ 💬 type a message...    🎤  │  ← Chat input with mic
├─────────────────────────────┤
│ 🏠  💬  ⚡  📊               │  ← Bottom nav
└─────────────────────────────┘
```

**Components:**

- `MobileChatView.svelte` — Chat interface with messages and action cards.
- `MobilePipelineStrip.svelte` — Horizontal scrollable step badges.
- `MobileActionCard.svelte` — AI-generated step configuration card with apply/edit actions.
- `MobileQuickChips.svelte` — Quick action buttons for common operations.
- `MobileChatInput.svelte` — Text input with microphone button.

**Behavior:**

- Chat messages are streaming (SSE or WebSocket).
- Action cards show exact step config that AI suggests.
- "Apply" adds the step to the pipeline immediately.
- "Edit" opens Manual Tuning screen (Screen 05) with suggested config pre-filled.
- Quick chips send predefined prompts to the AI.
- Pipeline strip updates when steps are added/modified.

### Screen 03: Pipeline View

Step inspection — see all steps in the pipeline.

**Layout:**

```
┌─────────────────────────────┐
│ ← Sales Q1    pipeline      │
├─────────────────────────────┤
│ ┌ source ──────────────────┐│
│ │ 📦 customers.csv         ││
│ │   150k rows · 12 cols    ││
│ └──────────────────────────┘│
│           │                 │
│           ▼                 │
│ ┌──────────────────────────┐│
│ │▌filter · status='active' ││  ← 3px left border (white=AI)
│ │ 142k rows  ⓘ            ││
│ ├──────────────────────────┤│
│ │▌sort · revenue desc      ││  ← 3px left border (amber=user-edited)
│ │ 142k rows  ⓘ            ││
│ ├──────────────────────────┤│
│ │▌group by · region        ││  ← 3px left border (white=AI)
│ │ 8 rows     ⓘ            ││
│ ├──────────────────────────┤│
│ │▌bar chart · revenue      ││  ← 3px left border (green=chart)
│ │ visualization  ⓘ        ││
│ └──────────────────────────┘│
│                             │
│ ┌──────────────────────────┐│
│ │  + add step              ││  ← Add step CTA
│ └──────────────────────────┘│
├─────────────────────────────┤
│ 🏠  💬  ⚡  📊               │
└─────────────────────────────┘
```

**Components:**

- `MobilePipelineView.svelte` — Full pipeline step list.
- `MobileStepRow.svelte` — Individual step row with origin bar, description, row count, info icon.
- `MobileSourceBlock.svelte` — Input datasource block.
- `MobileConnectorLine.svelte` — Visual connector between source and steps.

**Behavior:**

- Tap step row → opens Data Preview (Screen 04) for that step's output.
- Tap ⓘ → opens Manual Tuning (Screen 05) for that step's config.
- Tap "Add step" → opens step type picker or returns to Chat.
- Step origin encoding: 3px left border color indicates AI vs. user vs. chart.

### Screen 04: Data Preview

Per-step data output inspection.

**Layout:**

```
┌─────────────────────────────┐
│ ← Sales Q1    preview       │
├─────────────────────────────┤
│ [src] [filter] [sort] [grp] │  ← Step tabs (horizontal scroll)
├─────────────────────────────┤
│ 142k rows · 12 cols         │
│ 0 nulls · 2.3 MB            │  ← Data stats
├─────────────────────────────┤
│ id    │ name   │ revenue    │  ← Table header
│ Int64 │ Utf8   │ Float64    │     column types
├───────┼────────┼────────────┤
│ 1001  │ Acme   │ 45,230.50  │
│ 1002  │ Beta   │ 38,100.00  │
│ 1003  │ null   │ 29,750.25  │  ← null in muted color
│ 1004  │ Delta  │ null       │
│ ...   │ ...    │ ...        │
├─────────────────────────────┤
│              [📥 CSV]        │  ← Download button
├─────────────────────────────┤
│ 🏠  💬  ⚡  📊               │
└─────────────────────────────┘
```

**Components:**

- `MobileDataPreview.svelte` — Data preview with stats and table.
- `MobileStepTabs.svelte` — Horizontal scrollable step tab bar.
- `MobileDataStats.svelte` — Row count, column count, null count, size.
- `MobileDataTable.svelte` — Horizontally scrollable data table with fixed header.

**Behavior:**

- Tap step tab → switches preview to that step's output (triggers API call).
- Table is horizontally scrollable (no column truncation).
- Column types shown below column names.
- Null values rendered in `fg.subtle` color.
- Download button exports current preview as CSV.

### Screen 05: Manual Tuning

Fine-tune step configuration via bottom sheet.

**Layout:**

```
┌─────────────────────────────┐
│ pipeline / step 2 / sort    │  ← Breadcrumb titlebar
│                      config │
├─────────────────────────────┤
│ ┌ ai suggestion ───────────┐│
│ │ 💡 sort revenue desc     ││  ← AI suggestion with apply link
│ │                  [apply]  ││
│ └──────────────────────────┘│
├─────────────────────────────┤
│ column      │ revenue    ▾  │  ← Property: dropdown
│ direction   │ [asc][DESC]   │  ← Property: segment toggle
│ nulls       │ [first][LAST] │  ← Property: segment toggle
│ limit       │ [- 100 +]     │  ← Property: number stepper
├─────────────────────────────┤
│       [discard]  [apply]    │  ← Action footer
└─────────────────────────────┘
```

**Components:**

- `MobileTuningSheet.svelte` — Bottom sheet container with breadcrumb and actions.
- `MobilePropertyGrid.svelte` — Key-value property editor.
- `MobileDropdown.svelte` — Touch-friendly dropdown selector.
- `MobileSegmentToggle.svelte` — Segment button control (binary/ternary choices).
- `MobileNumberStepper.svelte` — Increment/decrement control.
- `MobileAISuggestion.svelte` — AI suggestion row with apply action.

**Behavior:**

- Sheet slides up from bottom, anchored with 2px top border.
- Breadcrumb shows navigation path: pipeline / step / operation / config.
- AI suggestion (if available) shown at top as a single dense row.
- Property grid adapts controls per config type:
  - Text fields → text input.
  - Enums → dropdown or segment toggle.
  - Numbers → stepper.
  - Booleans → toggle switch.
  - Column references → column picker dropdown.
- "Discard" reverts changes; "Apply" saves and returns to previous screen.

## Technical Design

### Frontend Architecture

#### Routing Strategy

Mobile layout detected via media query or dedicated route prefix:

**Option A (recommended): Responsive components with breakpoint detection**

```svelte
<!-- +layout.svelte -->
<script lang="ts">
    import { isMobile } from '$lib/stores/viewport';
</script>

{#if $isMobile}
    <MobileLayout><slot /></MobileLayout>
{:else}
    <DesktopLayout><slot /></DesktopLayout>
{/if}
```

**Option B: Separate route tree**

```
routes/
├── (desktop)/          # Desktop routes
│   ├── analysis/
│   └── ...
└── (mobile)/           # Mobile routes
    ├── m/analysis/
    └── ...
```

Option A is preferred because it avoids route duplication and shares data loading.

#### Component Structure

```
components/mobile/
├── layout/
│   ├── MobileLayout.svelte         # Root mobile layout (header + content + bottom nav)
│   ├── MobileHeader.svelte         # Top header bar
│   ├── MobileBottomNav.svelte      # Fixed bottom navigation
│   └── MobileBottomSheet.svelte    # Reusable bottom sheet container
├── gallery/
│   ├── MobileAnalysisGallery.svelte
│   └── MobileAnalysisRow.svelte
├── chat/
│   ├── MobileChatView.svelte
│   ├── MobileChatInput.svelte
│   ├── MobileActionCard.svelte
│   ├── MobilePipelineStrip.svelte
│   └── MobileQuickChips.svelte
├── pipeline/
│   ├── MobilePipelineView.svelte
│   ├── MobileStepRow.svelte
│   └── MobileSourceBlock.svelte
├── data/
│   ├── MobileDataPreview.svelte
│   ├── MobileDataTable.svelte
│   ├── MobileDataStats.svelte
│   └── MobileStepTabs.svelte
└── tuning/
    ├── MobileTuningSheet.svelte
    ├── MobilePropertyGrid.svelte
    ├── MobileDropdown.svelte
    ├── MobileSegmentToggle.svelte
    ├── MobileNumberStepper.svelte
    └── MobileAISuggestion.svelte
```

#### Viewport Detection

```typescript
// frontend/src/lib/stores/viewport.ts

import { readable } from 'svelte/store';

export const MOBILE_BREAKPOINT = 768;

export const isMobile = readable(false, (set) => {
    if (typeof window === 'undefined') return;
    const mq = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT}px)`);
    set(mq.matches);
    const handler = (e: MediaQueryListEvent) => set(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
});
```

#### Bottom Sheet Pattern

```svelte
<!-- MobileBottomSheet.svelte -->
<script lang="ts">
    let { title, onClose, children } = $props<{
        title: string;
        onClose: () => void;
        children: Snippet;
    }>();

    let sheetHeight = $state(60); // percentage of viewport
</script>

<div
    class={css({
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        height: `${sheetHeight}vh`,
        backgroundColor: 'bg.elevated',
        borderTopWidth: '2px',
        borderColor: 'border.primary',
        zIndex: 50,
        display: 'flex',
        flexDirection: 'column',
    })}
>
    <header class={css({ padding: '3', borderBottomWidth: '1', borderColor: 'border.primary' })}>
        <span>{title}</span>
        <button onclick={onClose}>✕</button>
    </header>
    <div class={css({ flex: 1, overflowY: 'auto', padding: '3' })}>
        {@render children()}
    </div>
</div>
```

### Backend

No backend changes required for mobile UI — it consumes the same API endpoints as desktop. The following APIs are already available and sufficient:

- `GET /api/v1/analysis` — list analyses
- `POST /api/v1/analysis` — create analysis
- `POST /api/v1/compute/preview` — data preview
- `POST /api/v1/chat/messages` — AI chat
- `GET /api/v1/analysis/step-types` — operation catalog

### Dependencies

No new dependencies. Mobile layout uses existing Panda CSS with responsive utilities.

### Security Considerations

- Same authentication and authorization as desktop.
- Touch-optimized inputs must still validate on the server side.
- Bottom sheet z-index management to prevent click-jacking on overlapping elements.

## Migration

- No database migration.
- No API changes.
- Frontend-only addition: new component tree + viewport detection.
- Desktop UI unchanged — mobile components loaded only at mobile breakpoints.

## Rollout Plan

| Phase | Scope | Duration |
|-------|-------|----------|
| 1 | Foundation: MobileLayout, Header, BottomNav, viewport store | 2 days |
| 2 | Screen 01: Analysis Gallery | 2 days |
| 3 | Screen 02: AI Chat with action cards and pipeline strip | 4 days |
| 4 | Screen 03: Pipeline View with step rows | 2 days |
| 5 | Screen 04: Data Preview with table and stats | 2 days |
| 6 | Screen 05: Manual Tuning bottom sheet | 3 days |
| 7 | Polish: animations, transitions, touch gestures, keyboard handling | 2 days |
| 8 | Testing: device testing (iOS Safari, Android Chrome), accessibility | 3 days |

## Open Questions

1. Should mobile be opt-in (toggle in settings) or automatic (media query detection)?
2. Should the mobile chat support voice input (speech-to-text via Web Speech API)?
3. How do we handle multi-tab analyses on mobile — show all tabs in pipeline strip, or one tab at a time?
4. Should the bottom navigation persist during chat input (keyboard open), or hide to give more screen space?
