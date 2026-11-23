# Code standard

How code is written in this repo. The rules are short on purpose: each one is something a tool enforces or a reviewer would otherwise repeat on every PR. Run `pnpm check` before you push, and it catches most of them.

## TypeScript

- **Strictest settings.** `tsconfig.json` extends `astro/tsconfigs/strictest`. Don't loosen a flag to make an error go away: fix the code.
- **Erasable syntax only.** `erasableSyntaxOnly` is on, so no enums, no namespaces and no constructor parameter properties. The scripts in `tools/` run directly under `node`, which strips types and can't compile those.
- **Explicit `.ts` imports.** Write `import { x } from './x.ts'`, never `'./x'`. Node doesn't guess extensions, and `allowImportingTsExtensions` lets the type checker agree with it.
- **`import type` for types.** `verbatimModuleSyntax` is on, so a type-only import must say so.
- **Schemas import `z` from `astro/zod`.** One Zod, the one Astro uses.
- **Typecheck with `pnpm typecheck`, never a bare `tsc`.** The root `typescript` is 6.0.3 because `astro check` needs it, and TypeScript 7.0.2 is the alias `typescript-7`. `pnpm typecheck` runs `astro sync`, then TypeScript 7 by path, then `astro check`.
- **Format with Biome.** Single quotes, no semicolons, two spaces, 100 columns. `pnpm lint` checks. `pnpm exec biome check --write <path>` fixes.
- **Pin dependencies exactly** (`pnpm add --save-exact`). Add a dependency in the task that first uses it. Vite comes in through Astro, so don't add it.

## Structure

- **Pure logic goes in `src/lib` and has unit tests.** Rules, cost, codec, the asset validator and the link policy are functions of their inputs, so a test needs no browser and no build. Write the test first where it fits.
- **Components stay thin.** An Astro or React component calls into `src/lib` and renders the result. It doesn't hold a rule.
- **Islands use `client:only="react"`.** The configurator and anything that needs the browser (WebGL, the URL hash, `localStorage`) renders only on the client. The page around it works without it, and a server render of 3D code would fail anyway.
- **Small, focused files.** One file does one job and has a name that says which. If you need "and" to describe a file, split it. A file you can't hold in your head is one an agent edits wrongly.
- **Comments say why.** The code says what. Spell out a constraint or a surprise, such as why a function checks a case that looks impossible.
- **Fail loudly.** Return a typed error or throw with a message that names the file and field. Don't catch an error to hide it.

## Python (`pipeline/`)

- **Python 3.14 and uv.** Dependencies are pinned in `pipeline/pyproject.toml` and locked in `uv.lock`. Run `uv sync --project pipeline` after you pull.
- **ruff** lints and formats, at 100 columns, with the rule sets `E`, `F`, `I`, `UP`, `B` and `SIM`.
- **Strict pyright.** Every function has types. Parse untyped data (JSON, TOML) into a typed shape at the edge, as `stages/validate.py` does.
- **Typer for the CLI.** Each command is a function in `cli.py` with `Annotated` arguments. Exit codes mean something: 0 ok, 1 not ok, 2 a bad name.
- **A stage is one function.** It takes an `AssetSpec` and `Settings`, returns a `StageResult`, and registers itself with `@register("<name>")`. Import the module at the bottom of `stages/__init__.py`.
- **Side effects sit behind injectable module functions.** A subprocess call, a network call or a write outside the work directory goes in a small module-level function that the stage calls through a variable, like `_run` in `stages/validate.py`. Tests replace it with `monkeypatch`, so no test starts Blender or node, or touches the network.
- **One source of truth for a contract.** The 3D asset contract lives in TypeScript. The Python `validate` stage runs `tools/validate-asset.ts` instead of reimplementing it.
- **Every change to a model is a script.** No hand edits in Blender that a script doesn't capture. See [3D assets](3d-assets.md).

Run the Python checks with `pnpm check:pipeline`.
