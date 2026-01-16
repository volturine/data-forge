# UI/UX Redesign - Flexoki Theme System

**Overall Completion: 0%**

This task file tracks a comprehensive UI redesign implementing the Flexoki color palette with modern, cohesive styling across the entire application. Focus on warm, earthy tones with excellent readability.

---

## Design System Foundation (0% Complete)

### 1. Create Flexoki CSS Variables (0% Complete)

**Purpose:** Define Flexoki color palette as CSS custom properties

**File:** `frontend/src/app.css`

**Tasks:**
- [ ] Define light theme Flexoki colors
- [ ] Define dark theme Flexoki colors
- [ ] Add semantic color mappings (primary, success, danger, etc.)
- [ ] Add spacing scale (4px base)
- [ ] Add typography scale
- [ ] Add border radius tokens
- [ ] Add shadow tokens
- [ ] Add transition/animation tokens

**Flexoki Light Palette:**
```css
:root {
  /* Base colors */
  --fx-black: #100F0F;
  --fx-paper: #FFFCF0;
  --fx-bg: #CECDC3;
  --fx-bg-2: #E6E4D9;
  
  /* Text colors */
  --fx-tx-3: #282726;
  --fx-tx-2: #403E3C;
  --fx-tx: #575653;
  --fx-tx-dim: #6F6E69;
  
  /* UI colors */
  --fx-ui-3: #878580;
  --fx-ui-2: #B7B5AC;
  --fx-ui: #CECDC3;
  
  /* Accent colors */
  --fx-red: #AF3029;
  --fx-red-dim: #D14D41;
  --fx-orange: #BC5215;
  --fx-orange-dim: #DA702C;
  --fx-yellow: #AD8301;
  --fx-yellow-dim: #D0A215;
  --fx-green: #66800B;
  --fx-green-dim: #879A39;
  --fx-cyan: #24837B;
  --fx-cyan-dim: #3AA99F;
  --fx-blue: #205EA6;
  --fx-blue-dim: #4385BE;
  --fx-purple: #5E409D;
  --fx-purple-dim: #8B7EC8;
  --fx-magenta: #A02F6F;
  --fx-magenta-dim: #CE5D97;
  
  /* Semantic mappings */
  --color-bg-primary: var(--fx-paper);
  --color-bg-secondary: var(--fx-bg-2);
  --color-bg-tertiary: var(--fx-bg);
  --color-text-primary: var(--fx-tx-3);
  --color-text-secondary: var(--fx-tx);
  --color-text-tertiary: var(--fx-tx-dim);
  --color-border: var(--fx-ui-2);
  --color-border-focus: var(--fx-blue);
  
  --color-primary: var(--fx-blue);
  --color-primary-hover: var(--fx-blue-dim);
  --color-success: var(--fx-green);
  --color-success-hover: var(--fx-green-dim);
  --color-danger: var(--fx-red);
  --color-danger-hover: var(--fx-red-dim);
  --color-warning: var(--fx-yellow);
  --color-warning-hover: var(--fx-yellow-dim);
  --color-info: var(--fx-cyan);
  --color-info-hover: var(--fx-cyan-dim);
  
  /* Spacing scale (4px base) */
  --space-1: 0.25rem;  /* 4px */
  --space-2: 0.5rem;   /* 8px */
  --space-3: 0.75rem;  /* 12px */
  --space-4: 1rem;     /* 16px */
  --space-5: 1.25rem;  /* 20px */
  --space-6: 1.5rem;   /* 24px */
  --space-8: 2rem;     /* 32px */
  --space-10: 2.5rem;  /* 40px */
  --space-12: 3rem;    /* 48px */
  --space-16: 4rem;    /* 64px */
  
  /* Typography */
  --font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --font-mono: 'SF Mono', Monaco, 'Cascadia Code', monospace;
  
  --text-xs: 0.75rem;    /* 12px */
  --text-sm: 0.875rem;   /* 14px */
  --text-base: 1rem;     /* 16px */
  --text-lg: 1.125rem;   /* 18px */
  --text-xl: 1.25rem;    /* 20px */
  --text-2xl: 1.5rem;    /* 24px */
  --text-3xl: 1.875rem;  /* 30px */
  --text-4xl: 2.25rem;   /* 36px */
  
  /* Border radius */
  --radius-sm: 0.25rem;  /* 4px */
  --radius-md: 0.5rem;   /* 8px */
  --radius-lg: 0.75rem;  /* 12px */
  --radius-xl: 1rem;     /* 16px */
  --radius-full: 9999px;
  
  /* Shadows */
  --shadow-sm: 0 1px 2px 0 rgba(16, 15, 15, 0.05);
  --shadow-md: 0 4px 6px -1px rgba(16, 15, 15, 0.1);
  --shadow-lg: 0 10px 15px -3px rgba(16, 15, 15, 0.1);
  --shadow-xl: 0 20px 25px -5px rgba(16, 15, 15, 0.1);
  
  /* Transitions */
  --transition-fast: 150ms cubic-bezier(0.4, 0, 0.2, 1);
  --transition-base: 200ms cubic-bezier(0.4, 0, 0.2, 1);
  --transition-slow: 300ms cubic-bezier(0.4, 0, 0.2, 1);
}

@media (prefers-color-scheme: dark) {
  :root {
    --fx-black: #FFFCF0;
    --fx-paper: #100F0F;
    --fx-bg: #1C1B1A;
    --fx-bg-2: #282726;
    /* ... dark mode variants */
  }
}
```

---

### 2. Create Base Component Styles (0% Complete)

**Purpose:** Reusable CSS classes for common patterns

**File:** `frontend/src/lib/styles/components.css`

**Tasks:**
- [ ] Button styles (primary, secondary, danger, ghost)
- [ ] Input/select/textarea styles
- [ ] Card/panel styles
- [ ] Badge/chip styles
- [ ] Alert/banner styles
- [ ] Modal/dialog styles
- [ ] Table styles
- [ ] Loading spinner styles

**Example Button Styles:**
```css
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  font-weight: 500;
  border-radius: var(--radius-md);
  border: none;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.btn-primary {
  background-color: var(--color-primary);
  color: var(--fx-paper);
}

.btn-primary:hover {
  background-color: var(--color-primary-hover);
  transform: translateY(-1px);
  box-shadow: var(--shadow-md);
}

.btn-secondary {
  background-color: var(--color-bg-secondary);
  color: var(--color-text-primary);
  border: 1px solid var(--color-border);
}

.btn-ghost {
  background-color: transparent;
  color: var(--color-text-secondary);
}

.btn-ghost:hover {
  background-color: var(--color-bg-secondary);
}
```

---

### 3. Create Utility Classes (0% Complete)

**Purpose:** Atomic CSS utilities for rapid development

**File:** `frontend/src/lib/styles/utilities.css`

**Tasks:**
- [ ] Spacing utilities (margin, padding)
- [ ] Typography utilities (size, weight, align)
- [ ] Color utilities (text, background, border)
- [ ] Layout utilities (flex, grid)
- [ ] Display utilities (show, hide, responsive)
- [ ] Interactive utilities (hover, focus, active)

**Example Utilities:**
```css
/* Spacing */
.m-1 { margin: var(--space-1); }
.mt-4 { margin-top: var(--space-4); }
.p-4 { padding: var(--space-4); }
.gap-4 { gap: var(--space-4); }

/* Typography */
.text-sm { font-size: var(--text-sm); }
.font-medium { font-weight: 500; }
.text-center { text-align: center; }

/* Colors */
.text-primary { color: var(--color-text-primary); }
.bg-secondary { background-color: var(--color-bg-secondary); }
.border-focus { border-color: var(--color-border-focus); }

/* Layout */
.flex { display: flex; }
.flex-col { flex-direction: column; }
.items-center { align-items: center; }
.justify-between { justify-content: space-between; }
```

---

## Component Redesign (0% Complete)

### 4. Redesign Gallery Components (0% Complete)

**Files:**
- `frontend/src/lib/components/gallery/AnalysisCard.svelte`
- `frontend/src/lib/components/gallery/GalleryGrid.svelte`
- `frontend/src/routes/+page.svelte`

**Tasks:**
- [ ] Update AnalysisCard with Flexoki colors
- [ ] Add subtle hover animations
- [ ] Improve card shadows and borders
- [ ] Use design system spacing
- [ ] Add status badges with Flexoki accent colors
- [ ] Improve typography hierarchy
- [ ] Add card actions on hover
- [ ] Update thumbnail styling

**Design Goals:**
- Warm, approachable card design
- Clear visual hierarchy
- Subtle depth with shadows
- Smooth transitions

---

### 5. Redesign Pipeline Builder (0% Complete)

**Files:**
- `frontend/src/lib/components/pipeline/StepNode.svelte`
- `frontend/src/lib/components/pipeline/StepLibrary.svelte`
- `frontend/src/lib/components/pipeline/PipelineCanvas.svelte`
- `frontend/src/lib/components/pipeline/ConnectionLine.svelte`

**Tasks:**
- [ ] Update StepNode card styling
- [ ] Use Flexoki accent colors for operation types
- [ ] Improve connection line styling
- [ ] Add visual indicators for step status
- [ ] Redesign StepLibrary drawer
- [ ] Add drag-and-drop visual feedback
- [ ] Improve spacing and layout
- [ ] Add operation icons

**Color Coding for Operations:**
- Data Source: `--fx-blue`
- Filter/Select: `--fx-purple`
- Transform: `--fx-orange`
- Aggregate: `--fx-green`
- Time Series: `--fx-cyan`
- String: `--fx-yellow`
- Clean: `--fx-magenta`

---

### 6. Redesign Operation Config Panels (0% Complete)

**Files:** All `*Config.svelte` components in `operations/`

**Tasks:**
- [ ] Standardize section styling
- [ ] Update form input styles
- [ ] Improve checkbox/radio styling
- [ ] Add better focus states
- [ ] Use consistent spacing
- [ ] Improve help text styling
- [ ] Add validation feedback colors
- [ ] Standardize button placement

**Common Pattern:**
```svelte
<div class="config-panel">
  <h3 class="config-title">Operation Name</h3>
  
  <div class="config-section">
    <h4 class="section-title">Section Title</h4>
    <p class="section-help">Help text</p>
    <!-- Inputs -->
  </div>
  
  <div class="config-actions">
    <button class="btn btn-primary">Save</button>
    <button class="btn btn-secondary">Cancel</button>
  </div>
</div>
```

---

### 7. Redesign Data Viewers (0% Complete)

**Files:**
- `frontend/src/lib/components/viewers/DataTable.svelte`
- `frontend/src/lib/components/viewers/SchemaViewer.svelte`
- `frontend/src/lib/components/viewers/StatsPanel.svelte`

**Tasks:**
- [ ] Update table header styling
- [ ] Improve row hover states
- [ ] Add zebra striping with subtle Flexoki tones
- [ ] Update schema viewer cards
- [ ] Improve type badge styling
- [ ] Add better data type icons
- [ ] Update stats panel layout
- [ ] Add mini charts/sparklines

---

### 8. Redesign Navigation & Layout (0% Complete)

**Files:**
- `frontend/src/routes/+layout.svelte`

**Tasks:**
- [ ] Create app header/nav bar
- [ ] Add sidebar navigation (optional)
- [ ] Improve page layouts
- [ ] Add breadcrumb navigation
- [ ] Create consistent page headers
- [ ] Add loading states
- [ ] Improve error pages (404, 500)

**Header Design:**
```
┌──────────────────────────────────────────┐
│ 📊 Polars Analyzer    Gallery  Datasets │
│                              [User Menu] │
└──────────────────────────────────────────┘
```

---

### 9. Redesign Forms & Inputs (0% Complete)

**Purpose:** Consistent form styling across all pages

**Tasks:**
- [ ] Create styled input component
- [ ] Create styled select component
- [ ] Create styled checkbox component
- [ ] Create styled radio component
- [ ] Create styled textarea component
- [ ] Add floating labels (optional)
- [ ] Add input icons
- [ ] Add validation states (error, success)

**Input Styles:**
```css
.input {
  width: 100%;
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-base);
  color: var(--color-text-primary);
  background-color: var(--fx-paper);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  transition: all var(--transition-fast);
}

.input:focus {
  outline: none;
  border-color: var(--color-border-focus);
  box-shadow: 0 0 0 3px rgba(32, 94, 166, 0.1);
}

.input.error {
  border-color: var(--color-danger);
}
```

---

### 10. Add Loading & Empty States (0% Complete)

**Purpose:** Polish with delightful loading and empty states

**Tasks:**
- [ ] Create loading spinner component (Flexoki colors)
- [ ] Create skeleton loaders for cards
- [ ] Create empty state illustrations
- [ ] Add loading overlays
- [ ] Add progress indicators
- [ ] Create toast notifications

**Loading Spinner:**
```svelte
<div class="spinner">
  <div class="spinner-ring" style="--color: var(--fx-blue)"></div>
</div>
```

---

## Page-Specific Redesigns (0% Complete)

### 11. Gallery Page Redesign (0% Complete)

**File:** `frontend/src/routes/+page.svelte`

**Tasks:**
- [ ] Add page header with title and actions
- [ ] Improve filters/search bar styling
- [ ] Update grid layout
- [ ] Add view switcher (grid/list)
- [ ] Add sort dropdown
- [ ] Improve responsive layout

---

### 12. Analysis Editor Redesign (0% Complete)

**File:** `frontend/src/routes/analysis/[id]/+page.svelte`

**Tasks:**
- [ ] Improve top toolbar styling
- [ ] Better panel separation
- [ ] Update "Run Analysis" button styling
- [ ] Add progress visualization
- [ ] Improve result tabs
- [ ] Add fullscreen mode toggle

---

### 13. Datasource Pages Redesign (0% Complete)

**Files:**
- `frontend/src/routes/datasources/+page.svelte`
- `frontend/src/routes/datasources/new/+page.svelte`

**Tasks:**
- [ ] Update upload area styling
- [ ] Improve drag-and-drop visuals
- [ ] Add file type icons
- [ ] Update datasource list cards
- [ ] Improve file info display

---

### 14. New Analysis Wizard Redesign (0% Complete)

**File:** `frontend/src/routes/analysis/new/+page.svelte`

**Tasks:**
- [ ] Update step indicators
- [ ] Improve step transitions
- [ ] Better datasource selection cards
- [ ] Update wizard navigation buttons
- [ ] Add step validation feedback

---

## Advanced UI Enhancements (0% Complete)

### 15. Add Micro-interactions (0% Complete)

**Tasks:**
- [ ] Button hover lift effect
- [ ] Card hover shadow
- [ ] Smooth page transitions
- [ ] Input focus animations
- [ ] Success checkmark animations
- [ ] Error shake animations
- [ ] Loading state transitions

---

### 16. Responsive Design Improvements (0% Complete)

**Tasks:**
- [ ] Mobile-first component designs
- [ ] Tablet breakpoint optimizations
- [ ] Touch-friendly button sizes
- [ ] Mobile navigation menu
- [ ] Responsive grid layouts
- [ ] Responsive typography scale

**Breakpoints:**
```css
@media (min-width: 640px) { /* sm */ }
@media (min-width: 768px) { /* md */ }
@media (min-width: 1024px) { /* lg */ }
@media (min-width: 1280px) { /* xl */ }
```

---

### 17. Accessibility Improvements (0% Complete)

**Tasks:**
- [ ] Add focus visible states
- [ ] Improve color contrast (WCAG AA)
- [ ] Add ARIA labels
- [ ] Keyboard navigation support
- [ ] Screen reader announcements
- [ ] Reduce motion support

```css
@media (prefers-reduced-motion: reduce) {
  * {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

### 18. Dark Mode Support (0% Complete)

**Tasks:**
- [ ] Define dark mode Flexoki palette
- [ ] Add theme toggle button
- [ ] Persist theme preference
- [ ] Test all components in dark mode
- [ ] Add smooth theme transition
- [ ] Respect system preference

**Dark Mode Colors:**
```css
@media (prefers-color-scheme: dark) {
  :root {
    --fx-paper: #100F0F;
    --fx-bg-2: #1C1B1A;
    --fx-bg: #282726;
    --fx-tx-3: #CECDC3;
    --fx-tx-2: #B7B5AC;
    --fx-tx: #878580;
    /* ... */
  }
}
```

---

## Documentation (0% Complete)

### 19. Design System Documentation (0% Complete)

**File:** `frontend/src/lib/styles/README.md`

**Tasks:**
- [ ] Document color palette
- [ ] Document spacing scale
- [ ] Document typography
- [ ] Show component examples
- [ ] Add usage guidelines
- [ ] Create component library page (Storybook-style)

---

### 20. Migration Guide (0% Complete)

**Purpose:** Help migrate existing components to new design system

**Tasks:**
- [ ] Create before/after examples
- [ ] Document CSS class mappings
- [ ] Add migration checklist
- [ ] Provide code snippets

---

## Testing (0% Complete)

### 21. Visual Regression Testing (0% Complete)

**Tasks:**
- [ ] Set up Playwright visual testing
- [ ] Capture screenshots of key pages
- [ ] Test light and dark modes
- [ ] Test responsive breakpoints
- [ ] Create baseline images

---

### 22. Accessibility Testing (0% Complete)

**Tasks:**
- [ ] Run axe accessibility checker
- [ ] Test keyboard navigation
- [ ] Test with screen readers
- [ ] Check color contrast ratios
- [ ] Validate ARIA attributes

---

## Implementation Strategy

### Phase 1 - Foundation (Week 1)
1. Create CSS variables and design tokens
2. Create base component styles
3. Create utility classes

### Phase 2 - Core Components (Week 2)
1. Redesign gallery components
2. Redesign pipeline builder
3. Update operation configs

### Phase 3 - Pages (Week 3)
1. Redesign all main pages
2. Add loading/empty states
3. Improve navigation

### Phase 4 - Polish (Week 4)
1. Add micro-interactions
2. Implement dark mode
3. Accessibility improvements
4. Testing and refinement

---

## Success Criteria

- [ ] All components use Flexoki color palette
- [ ] Consistent spacing throughout app
- [ ] Smooth transitions and animations
- [ ] WCAG AA accessibility compliance
- [ ] Dark mode fully functional
- [ ] Mobile responsive on all pages
- [ ] Visual regression tests passing
- [ ] Design system documented

---

## Reference Resources

- **Flexoki Palette:** https://stephango.com/flexoki
- **Design Inspiration:** Linear, Notion, Figma
- **Component Patterns:** Shadcn UI, Radix UI
- **Accessibility:** WCAG 2.1 Guidelines

---

## Notes

- **Flexoki Philosophy:** Warm, earthy tones inspired by analog materials
- **Design Principle:** Less is more - avoid visual clutter
- **Consistency:** Use design tokens everywhere, no magic values
- **Performance:** CSS-only animations where possible
- **Maintainability:** Document patterns, create reusable components

---

## Related Files

**New Files:**
- `frontend/src/lib/styles/variables.css` - Design tokens
- `frontend/src/lib/styles/components.css` - Base components
- `frontend/src/lib/styles/utilities.css` - Utility classes
- `frontend/src/lib/styles/README.md` - Documentation

**Updated Files:**
- `frontend/src/app.css` - Import new stylesheets
- All `.svelte` components - Apply new styles

---

**Last Updated:** 2026-01-16
**Status:** Not started - all tasks pending
**Priority:** High - significantly improves user experience and brand
