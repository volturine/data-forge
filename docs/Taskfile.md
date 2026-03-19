# Panda CSS Migration Taskfile

## Scope
- Migrate Tailwind utility usage to Panda CSS
- Replace Tailwind tokens/utilities with Panda tokens, recipes, and css helpers
- Remove Tailwind/PostCSS dependencies and configuration

## Commands
```bash
cd frontend
npm install
npm run panda:codegen
```

## Tasks
1. Audit Tailwind classes in Svelte components
2. Map CSS variables to Panda tokens in `panda.config.ts`
3. Create shared recipes/helpers for repeated patterns
4. Replace Tailwind classes with Panda `css`/`cx`/`recipes` usage
5. Remove Tailwind/PostCSS config and dependencies
6. Verify no Tailwind class strings remain
