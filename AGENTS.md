# AGENTS.md

## What this is

m3-tool is a free reference site for BMW M3 owners and shoppers: factory spec, real aftermarket parts with dated prices, build costs and maintenance. It sells nothing and links to no stores.

Read the [design spec](docs/superpowers/specs/2026-11-23-m3-tool-design.md) before you plan work. This file is derived from it, plus later decisions recorded in PRs and ADRs. Where the spec and this file disagree, this file wins. Spec amendments are marked `(amended YYYY-MM-DD)`.

## Commands

Set up once per machine: `mise install`. Set up in every worktree, each new one included: `pnpm install` and `uv sync --project pipeline`. Then run `pnpm exec playwright install chromium` once, for `pnpm e2e`. Run everything from the repo root.

| Command | What it answers |
|---|---|
| `pnpm check` | Is everything green? Biome, typecheck, unit tests, data checks, build, link check, then ruff, pyright and pytest for `pipeline/`. Run it before every push. |
| `pnpm test` | Do the unit tests pass? (Vitest, `tests/unit/`) |
| `pnpm e2e` | Does the built site work in a browser? Run `pnpm build` first: it serves `dist/`. |
| `pnpm build` | Does the site build? (`astro build`, then Pagefind) |
| `pnpm typecheck` | Do the types hold? Always use this, never a bare `tsc`. |
| `pnpm validate-asset <file.glb> --kind <base-car\|interior\|product\|body-module> [--json]` | Does a GLB meet the 3D contract? |
| `node tools/check-data.ts data` | Is the data valid? Same as `pnpm check:data`. |
| `pipeline run <asset> --stage <name>` | Run one pipeline stage for one asset. |
| `pipeline stages` | Which stages exist? |

`pipeline` is the Typer CLI in `pipeline/`. Run it as `uv run --project pipeline pipeline <command>`. It also has `pipeline assets`, which lists `pipeline/assets.toml`.

**Why `pnpm typecheck`:** it runs `astro sync && node node_modules/typescript-7/bin/tsc --noEmit && astro check`. A bare `tsc` skips `astro sync`, so a fresh tree can't resolve `astro:content`, and it skips `astro check`, so `.astro` files go unchecked. It also runs whichever TypeScript pnpm links into `node_modules/.bin`, and that version depends on how pnpm resolves the two `tsc` bins. The root `typescript` is 6.0.3 because `astro check` needs it, and TypeScript 7.0.2 is installed as the alias `typescript-7`.

**Dev server:** start it in the background so you can keep working.
- `pnpm astro dev --background` starts it. Add `--port <n>` to change the port (default 4321).
- `pnpm astro dev status`, `pnpm astro dev logs [--follow]` and `pnpm astro dev stop` manage it.
- `--json` turns on JSON logging. It's a global flag, listed under `pnpm astro --help`, not `astro dev --help`.
- `--ignore-lock` starts a second server on the same project.

## Layout

```
AGENTS.md  CLAUDE.md -> AGENTS.md  CONTRIBUTING.md  README.md  LICENSE (MIT)  DATA_LICENSE (CC BY-SA 4.0)
data/{generations,variants,parts,maintenance,issues}/   YAML, one entry per file (see docs/standards/data.md)
src/content.config.ts   Astro collections, built from the schemas
src/data/               schemas.ts (the data contract), loader, cross-file checks, source tiers
src/lib/                pure logic with unit tests: asset contract, validator, manifest, link policy
src/assets/manifest.json  published GLBs (the publish stage writes it)
src/{pages,layouts,components,styles}/   the site
pipeline/               Python (uv): assets.toml, src/m3_pipeline/{cli,config,assets,stages/}, tests/
tools/                  check-data.ts, check-links.ts, validate-asset.ts (run with node)
tests/{unit,e2e,fixtures}/   fixtures hold the sample data; visual tests arrive in Phase 1
docs/{standards,decisions,superpowers/specs,superpowers/plans}/  docs/spend-ledger.md  (index: docs/README.md)
infra/                  Cloudflare resources, the main ruleset, R2 CORS (see infra/README.md)
.github/workflows/ (ci, deploy)  .githooks/pre-push  renovate.json  biome.json  mise.toml  wrangler.jsonc
```

Phase 1 adds `src/configurator/`, `tests/visual/` and `pipeline/blender/`.

## Hard rules

**Product**
- No affiliate, ad or store links of any kind. A price observation's `url` is never rendered as a link. A source's `url` is a link only when `isCitationLinkable` says so (a short list of non-commercial hosts). `check:links` fails the build on an external link outside its allowlist.
- No BMW logos or badges anywhere: UI, models or textures, including the steering-wheel roundel.
- The footer and `/about` carry this notice, word for word: `Independent fan project. Not affiliated with, endorsed by, or sponsored by BMW AG. BMW and M3 are trademarks of BMW AG, used here only to describe the cars.`
- The site is `noindex` until the public beta. Pages emit `<meta name="robots" content="noindex">` unless `PUBLIC_INDEXABLE=true` at build time.
- IDs are kebab-case (`^[a-z0-9]+(-[a-z0-9]+)*$`), stable and never reused. A data file's stem equals its `id`.
- Every price has a seller and a checked date. Safety advice (maintenance intervals, fixes) never rests on a forum post alone: it needs a Tier 1 or Tier 2 source, and `check:data` enforces it.

**Code**
- `tools/*.ts` run directly under `node` (type stripping), so imports use explicit `.ts` extensions, and you use no enums and no namespaces.
- Schemas import `z` from `astro/zod`.
- Pin dependency versions exactly (`--save-exact`). Vite comes in through Astro: don't add it.
- Follow the standards: [code](docs/standards/code.md), [testing](docs/standards/testing.md), [data](docs/standards/data.md), [3D assets](docs/standards/3d-assets.md), [legal](docs/standards/legal.md).

**Contracts**
- `src/data/schemas.ts`, `src/lib/asset-contract.ts` and `docs/standards/3d-assets.md` change only in a dedicated PR labeled `contract`, which both lanes rebase onto. Two lanes build against them, so a quiet edit breaks the other lane.

**Money and secrets**
- Paid API calls need a session-approved cap and a row in `docs/spend-ledger.md` before the call. The user approves a cap each session, so a past approval covers nothing.
- Secrets live only in `~/.config/secrets.env` and GitHub Actions secrets, with the `M3_` prefix. Never use `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`: they flip tools to API billing. Grep for the exact name before you add one.
- Write secret names in docs, never values or account IDs. Only the maintainer's session mints Cloudflare tokens, one per purpose, through the API. Contributors and subagents never do.

**Photos and legal**
- Reference photos never enter the repo. They live in the private `m3-tool-refs` bucket and a local cache. See [legal](docs/standards/legal.md).
- Licenses: code MIT (`LICENSE`), data CC BY-SA 4.0 (`DATA_LICENSE`).

**Public repo hygiene**
- No `Claude-Session` trailer and no session URL in commits or PR bodies. A `Co-Authored-By:` trailer is fine, and so is the "Generated with Claude Code" line.
- Commits use Conventional Commits. Stage files by path: never `git add -A`.
- `gitleaks` runs in CI and in the pre-push hook, which needs gitleaks on PATH (`mise install`). Never bypass the hook.
- Don't track images, GLBs or `.env` files. Only `public/` and `tests/fixtures/` may hold media. `tests/unit/repo-hygiene.test.ts` enforces this.

## Workflow

1. Work on a branch in its own worktree: `git worktree add ../m3-tool.worktrees/<slug> -b <branch> origin/main`, then set it up as above. `main` is protected, so a PR is the only way in.
2. Run `pnpm check` and `pnpm e2e` green, push, and open a PR from the [template](.github/pull_request_template.md). Say `Closes #<issue>`. UI and 3D changes carry before-and-after screenshots.
3. Wait for CI. The required checks are `check`, `e2e` and `gitleaks`. `deploy` runs too, but it isn't required, because it needs secrets that fork PRs don't get.
4. Get a task review, plus a Codex second opinion through the `codex-review` skill. Data PRs also get the data verifier. `safety` PRs (maintenance and issues) wait for the user's spot-check.
5. Fix what review finds, then squash-merge.

Zero approvals are required, because the repo has one maintainer who can't approve their own PR. The review happens before the merge instead. See `infra/github-ruleset.json`.

**Deploys** run from GitHub Actions (`deploy.yml`), not Workers Builds ([ADR 0001](docs/decisions/0001-static-site-on-workers.md)). A push to `main` runs `wrangler deploy`, and each same-repo PR gets a preview at `pr-<n>-m3-tool.broken-wood-97a9.workers.dev`, posted as a PR comment that starts with `<!-- m3-tool-preview -->`. Run the deploy script as `pnpm run deploy`, because `pnpm deploy` is a pnpm built-in. Details are in [infra/README.md](infra/README.md).

## Model routing

Pass a model on every subagent. Never run a child on the orchestrator's tier.

| Role | Claude | Codex |
|---|---|---|
| Orchestrator: owns specs, plans and merges, together with the user | Main session (Fable or Opus) | — |
| Architecture and code review | Opus 5.5 (when the orchestrator isn't Opus) | gpt-6-astra (high), via codex-review |
| Data verifier (every data PR) | Opus 5.5 | — |
| 3D vision critic | Opus 5.5 | — |
| Implementation, tests, bounded edits | Sonnet 5.5 | gpt-6.1-sol |
| Research, bulk data gathering, recon | Haiku 5.5 | gpt-6-luna (low) |

Opus reviews only when the orchestrator isn't Opus. With an Opus orchestrator, the reviewers are Sonnet plus Codex.

## Where docs live

- [docs/README.md](docs/README.md): the index.
- [docs/standards/](docs/standards): code, testing, data, 3D assets, legal.
- [docs/decisions/](docs/decisions): the ADRs. Read one before you reopen a decision.
- [docs/superpowers/specs/](docs/superpowers/specs) and [docs/superpowers/plans/](docs/superpowers/plans): the design and the implementation plans.
- [docs/spend-ledger.md](docs/spend-ledger.md): every paid call.
- [infra/README.md](infra/README.md): Cloudflare resources and tokens, by name.
- [CONTRIBUTING.md](CONTRIBUTING.md): setup and the rules in short form.
