# Styling

Documentation for the design system and CSS architecture.

## Overview

The application uses scoped CSS within Svelte components with CSS custom properties (variables) for theming.

## CSS Variables

### Colors

```css
:root {
  /* Background */
  --bg-primary: #ffffff;
  --bg-secondary: #f8f9fa;
  --bg-tertiary: #f1f3f5;
  --bg-hover: #e9ecef;

  /* Foreground */
  --fg-primary: #212529;
  --fg-secondary: #495057;
  --fg-tertiary: #868e96;
  --fg-muted: #adb5bd;

  /* Accent */
  --accent-primary: #228be6;
  --accent-secondary: #1c7ed6;
  --accent-bg: rgba(34, 139, 230, 0.1);

  /* Borders */
  --border-primary: #dee2e6;
  --border-secondary: #ced4da;
  --border-focus: #228be6;

  /* Status Colors */
  --success-fg: #2f9e44;
  --success-bg: #d3f9d8;
  --success-border: #8ce99a;

  --warning-fg: #e67700;
  --warning-bg: #fff3bf;
  --warning-border: #ffd43b;

  --error-fg: #e03131;
  --error-bg: #ffe3e3;
  --error-border: #ffa8a8;

  --info-fg: #1971c2;
  --info-bg: #d0ebff;
  --info-border: #74c0fc;
}
```

### Spacing

```css
:root {
  --space-1: 0.25rem; /* 4px */
  --space-2: 0.5rem; /* 8px */
  --space-3: 0.75rem; /* 12px */
  --space-4: 1rem; /* 16px */
  --space-5: 1.25rem; /* 20px */
  --space-6: 1.5rem; /* 24px */
  --space-8: 2rem; /* 32px */
  --space-10: 2.5rem; /* 40px */
  --space-12: 3rem; /* 48px */
}
```

### Typography

```css
:root {
  /* Font Families */
  --font-sans: system-ui, -apple-system, sans-serif;
  --font-mono: "SF Mono", "Fira Code", monospace;

  /* Font Sizes */
  --text-xs: 0.75rem; /* 12px */
  --text-sm: 0.875rem; /* 14px */
  --text-base: 1rem; /* 16px */
  --text-lg: 1.125rem; /* 18px */
  --text-xl: 1.25rem; /* 20px */
  --text-2xl: 1.5rem; /* 24px */
  --text-3xl: 1.875rem; /* 30px */

  /* Line Heights */
  --leading-tight: 1.25;
  --leading-normal: 1.5;
  --leading-relaxed: 1.75;
}
```

### Effects

```css
:root {
  /* Border Radius */
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 8px;
  --radius-full: 9999px;

  /* Shadows */
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
  --shadow-md: 0 4px 6px rgba(0, 0, 0, 0.1);
  --shadow-lg: 0 10px 15px rgba(0, 0, 0, 0.1);
  --card-shadow: 0 1px 3px rgba(0, 0, 0, 0.12);

  /* Transitions */
  --transition: 150ms ease;
  --transition-normal: 200ms ease;
  --transition: 300ms ease;
}
```

### Form Inputs

```css
:root {
  --input-bg: #ffffff;
  --input-border: #ced4da;
  --input-focus-border: #228be6;
  --input-focus-ring: rgba(34, 139, 230, 0.25);
}
```

## Scoped Styles

Styles are scoped to components by default:

```svelte
<style>
    /* Only affects this component */
    .button {
        padding: var(--space-2) var(--space-4);
        background: var(--accent-primary);
        color: white;
        border: none;
        border-radius: var(--radius-sm);
        cursor: pointer;
    }

    .button:hover {
        opacity: 0.9;
    }
</style>
```

## Global Styles

Global styles are defined in the root layout:

```svelte
<!-- routes/+layout.svelte -->
<style>
    :global(body) {
        margin: 0;
        font-family: var(--font-sans);
        background: var(--bg-secondary);
        color: var(--fg-primary);
    }

    :global(*) {
        box-sizing: border-box;
    }

    :global(a) {
        color: var(--accent-primary);
        text-decoration: none;
    }
</style>
```

## Common Patterns

### Cards

```svelte
<style>
    .card {
        background: var(--bg-primary);
        border: 1px solid var(--border-primary);
        border-radius: var(--radius-md);
        padding: var(--space-4);
        box-shadow: var(--card-shadow);
    }
</style>
```

### Buttons

```svelte
<style>
    .btn {
        display: inline-flex;
        align-items: center;
        gap: var(--space-2);
        padding: var(--space-2) var(--space-4);
        font-family: var(--font-mono);
        font-size: var(--text-sm);
        font-weight: 500;
        border-radius: var(--radius-sm);
        cursor: pointer;
        transition: all var(--transition);
    }

    .btn-primary {
        background: var(--accent-primary);
        color: white;
        border: 1px solid var(--accent-primary);
    }

    .btn-secondary {
        background: transparent;
        color: var(--fg-primary);
        border: 1px solid var(--border-secondary);
    }

    .btn-ghost {
        background: transparent;
        color: var(--fg-tertiary);
        border: 1px solid transparent;
    }

    .btn-danger {
        background: var(--error-bg);
        color: var(--error-fg);
        border: 1px solid var(--error-border);
    }

    .btn:hover:not(:disabled) {
        opacity: 0.85;
    }

    .btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
</style>
```

### Form Inputs

```svelte
<style>
    input[type='text'],
    input[type='url'],
    select,
    textarea {
        padding: var(--space-2) var(--space-3);
        border: 1px solid var(--input-border);
        border-radius: var(--radius-sm);
        font-size: var(--text-sm);
        background: var(--input-bg);
        color: var(--fg-primary);
        transition: border-color var(--transition);
    }

    input:focus,
    select:focus,
    textarea:focus {
        outline: none;
        border-color: var(--input-focus-border);
        box-shadow: 0 0 0 3px var(--input-focus-ring);
    }

    input:disabled,
    select:disabled,
    textarea:disabled {
        background: var(--bg-tertiary);
        cursor: not-allowed;
    }
</style>
```

### Status Badges

```svelte
<style>
    .badge {
        display: inline-block;
        padding: var(--space-1) var(--space-2);
        font-size: var(--text-xs);
        font-weight: 500;
        border-radius: var(--radius-sm);
        border: 1px solid;
    }

    .badge-success {
        color: var(--success-fg);
        background: var(--success-bg);
        border-color: var(--success-border);
    }

    .badge-warning {
        color: var(--warning-fg);
        background: var(--warning-bg);
        border-color: var(--warning-border);
    }

    .badge-error {
        color: var(--error-fg);
        background: var(--error-bg);
        border-color: var(--error-border);
    }

    .badge-info {
        color: var(--info-fg);
        background: var(--info-bg);
        border-color: var(--info-border);
    }
</style>
```

### Tables

```svelte
<style>
    .table-container {
        background: var(--bg-primary);
        border: 1px solid var(--border-primary);
        border-radius: var(--radius-sm);
        overflow: hidden;
    }

    table {
        width: 100%;
        border-collapse: collapse;
    }

    th {
        text-align: left;
        padding: var(--space-3) var(--space-4);
        font-size: var(--text-xs);
        font-weight: 600;
        color: var(--fg-tertiary);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        background: var(--bg-tertiary);
        border-bottom: 1px solid var(--border-primary);
    }

    td {
        padding: var(--space-3) var(--space-4);
        font-size: var(--text-sm);
        border-bottom: 1px solid var(--border-primary);
    }

    tr:last-child td {
        border-bottom: none;
    }

    tr:hover td {
        background: var(--bg-hover);
    }
</style>
```

## Responsive Design

Use media queries for responsive layouts:

```svelte
<style>
    .grid {
        display: grid;
        gap: var(--space-4);
        grid-template-columns: 1fr;
    }

    @media (min-width: 768px) {
        .grid {
            grid-template-columns: repeat(2, 1fr);
        }
    }

    @media (min-width: 1024px) {
        .grid {
            grid-template-columns: repeat(3, 1fr);
        }
    }
</style>
```

## Dark Mode (Future)

Variables are structured for easy dark mode support:

```css
/* Future dark mode implementation */
@media (prefers-color-scheme: dark) {
  :root {
    --bg-primary: #1a1a1a;
    --bg-secondary: #2d2d2d;
    --fg-primary: #ffffff;
    --fg-secondary: #e0e0e0;
    /* ... */
  }
}
```

## See Also

- [Components](./components/README.md) - Component library
- [SvelteKit Structure](./sveltekit-structure.md) - Application structure
