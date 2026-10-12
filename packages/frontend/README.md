# Data-Forge frontend

SvelteKit 3, Svelte 5 runes, Panda CSS 2, and Bun. Run the shared services through `just dev` from the repository root.

```sh
bun install --frozen-lockfile
bun run check
bun run build
```

Configuration lives in `vite.config.ts`. Project imports use the `#lib` subpath declared in `package.json`; `tsconfig.json` mirrors that path so the native checker resolves generated Svelte component declarations.

Type checking uses stable TypeScript 7 through `svelte-check --tsgo`. The `@typescript/native` npm alias supplies TS7, while `typescript` remains on TS6 to provide the compiler API used by Svelte tooling and ESLint. Check scripts clear only the generated `.svelte-kit/.svelte-check` directory before starting, so removed components cannot leave stale diagnostics.

Panda's base and theme presets are explicit in `panda.config.ts`. After changing Panda versions, regenerate once with `bunx panda build --clean` to remove obsolete generated modules.

Use the public isolated test recipes from the repository root:

```sh
just verify
just test-frontend
just test-e2e
```

Never run Playwright directly on the host. For Mac-hosted development services, use `rolands-mac-mini.bee-justice.ts.net` with the service port.
