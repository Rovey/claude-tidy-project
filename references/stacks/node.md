# Node projects

## Detect

`package.json` in the root, not part of a Laravel project.

## Layout

- Framework conventions win: Next.js `app/` or `pages/`, Vite `src/`, Electron `main`/`renderer`.
- Otherwise `src/`, `tests/`, `scripts/`, `docs/`, `assets/`.
- Moving files: update `package.json` (`main`, `exports`, `bin`, `files`, script paths),
  `tsconfig.json` (`include`, `paths`), and bundler entry points in the same commit.

## Contracts (in addition to rules.md)

`package.json` `name`, `bin` command names, `main`/`exports`, `scripts` names (people type
`npm run <name>`), HTTP routes, CLI flags, environment variable names.

## Tests

- `npm test` when the `test` script exists and is not npm's placeholder
  (`echo "Error: no test specified" && exit 1`).
- Otherwise Node's built-in runner: `node --test`, test files `tests/<name>.test.js` (`.test.mjs`
  when `package.json` has `"type": "module"`).
- TypeScript without a runner: add `vitest` as a devDependency (`npm install -D vitest`) and run
  `npx vitest run`.
- `node_modules/` missing and a lock file exists → `npm ci`. Never `npm update` or `npm audit fix`.
- Mock `fetch` with `mock.method(globalThis, "fetch", async () => new Response("{}"))` from
  `node:test`, or the runner's equivalent.

## Formatter

Only when already configured: Prettier config plus `prettier` in devDependencies →
`npx prettier --write .`; `biome.json` plus `@biomejs/biome` → `npx biome format --write .`.
Otherwise none.

## Smoke checks

- `npm run build` when a `build` script exists and passed at baseline
- `npx tsc --noEmit` for TypeScript projects
- `node --check <file>` for plain JavaScript entry files
