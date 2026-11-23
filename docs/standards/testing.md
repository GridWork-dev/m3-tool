# Testing standard

This page is spec section 10, applied to the repo as it is. Each question has one command. If you can't tell which command answers your question, the command is missing: say so in the PR.

## One command per question

| Question | Command |
|---|---|
| Is everything green? | `pnpm check` |
| Do the unit tests pass? | `pnpm test` |
| Does the built site work in a browser? | `pnpm build && pnpm e2e` |
| Do the types hold? | `pnpm typecheck` |
| Is the code formatted and lint-free? | `pnpm lint` |
| Is the data valid? | `pnpm check:data` |
| Does the built site have a forbidden link? | `pnpm build && pnpm check:links` |
| Does a GLB meet the 3D contract? | `pnpm validate-asset <file.glb> --kind <kind>` |
| Do the pipeline checks pass? | `pnpm check:pipeline` |
| Does one pipeline stage work? | `uv run --project pipeline pipeline run <asset> --stage <name>` |

`pnpm check` runs the lint, typecheck, unit tests, data checks, build and link check, then the pipeline's ruff, pyright and pytest. `pnpm e2e` is separate: CI runs it as its own job (`e2e`) after a build.

## What each layer covers

- **Unit tests (Vitest, `tests/unit/`).** Pure logic in `src/lib` and `src/data`: schemas, the cross-file data rules, the link policy and the asset validator. Test the failure cases as well as the pass: a rule that has only a passing test isn't tested.
- **Data tests.** `pnpm check:data` fails on any schema error and on the cross-file rules (ids, references, `verified` against the tier rules). The data standard lists every code.
- **Pipeline tests (pytest, `pipeline/tests/`).** Pure functions, plus stages with their side effects replaced. A stage test never starts node, Blender or the network.
- **End-to-end tests (Playwright, `tests/e2e/`).** They run against the built site served by `pnpm preview`, in Chromium. Run `pnpm build` first, because the tests serve `dist/`. On a fresh machine, install the browser once with `pnpm exec playwright install chromium`.
- **Visual regression** arrives in Phase 1, with the configurator. Fixed views of each car and preset are compared with approved baselines. CI renders with software WebGL, and a Mac script renders with the real GPU for review. No baselines exist yet, so don't add screenshot assertions before then.

## Fixtures

- **Sample data lives under `tests/fixtures/data/`, never under `data/`.** `data/` is published, so it holds real, sourced values only.
- **Fixture entries can't be mistaken for real ones.** Parts, issues and maintenance items use ids that start with `fixture-`, and the brand is `Fixture Co`. The fixture generation and variant keep the real `e46` ids that the other entries point at.
- **Build every GLB in code.** `tests/unit/assets/fixtures.ts` builds each test model programmatically, so no binary is committed. A test that needs a bad model starts from the good builder and breaks one thing, which also documents the failure.
- **No reference photos in fixtures.** Reference photos never enter the repo (see [legal](legal.md)). A test image is generated in code.
- **Dates in fixtures are calendar dates** (`YYYY-MM-DD`), like all data.

## A bug fix starts with a failing test

Write the test that reproduces the bug, watch it fail for the right reason, then fix it. A fix without a test comes back.
