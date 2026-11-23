# Phase 0A: Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A public `GridWork-dev/m3-tool` repo with:
- The section 6 toolchain, and one green `pnpm check`.
- CI with gitleaks.
- A placeholder site live on Cloudflare Workers, with PR previews and both R2 buckets.
- The data contract: Zod schemas plus data-quality checks.
- The 3D asset contract: a GLB validator.
- `AGENTS.md`, the standards docs and the ADRs.

When this is done, Phase 0B (photo tooling) and both Phase 1 lanes build against stable contracts.

**Architecture:**
- **Site:** Astro 7 builds a fully static site, which Workers static assets serves. The site has no server code, so the Cloudflare adapter waits until Phase 2's share-image route (my call; recorded in ADR 0001).
- **Data:** YAML under `data/`. The same Zod schemas validate it in Astro content collections and in a standalone `tools/check-data.ts`.
- **3D validator:** in TypeScript on glTF-Transform, which decodes meshopt and reads KTX2 natively.
- **Pipeline:** a Python `uv` project under `pipeline/`, with a stage registry. Its `validate` stage calls the TS validator.

**Tech Stack:** Astro 7.4.13, React 19.3.1, Tailwind 4.3.5, TypeScript 7.0.2, Vitest 5.1.1, Playwright 1.65.1, Biome 2.6.8, pnpm 12.23.0, Node 26.13.1, glTF-Transform 4.5.1, Wrangler 4.167.0, Python 3.14 + uv 0.13.9 + Typer 0.29.2, gitleaks 8.30.1.

**Spec:** `docs/superpowers/specs/2026-11-23-m3-tool-design.md` (Task 1 moves it there from the maintainer's notes folder).

## Global Constraints

**Versions**
- **Pin these versions exactly** (`--save-exact`). They were checked on 2026-11-23:
  - Framework and UI: astro 7.4.13, @astrojs/react 7.1.9, @astrojs/check 0.9.12, react and react-dom 19.3.1, tailwindcss and @tailwindcss/vite 4.3.5.
  - Language and tests: typescript 7.0.2, vitest 5.1.1, @playwright/test 1.65.1.
  - Lint, deploy and search: @biomejs/biome 2.6.8, wrangler 4.167.0, pagefind 1.6.0.
  - Data and 3D: yaml 2.9.1, @gltf-transform/core, @gltf-transform/extensions and @gltf-transform/functions 4.5.1, meshoptimizer 1.3.0, gltf-validator 2.0.0-dev.3.10, ktx-parse 2.0.0 (dev only).
  - Vite comes in through Astro. Don't add it directly.
- **mise.toml:** node 26.13.1, pnpm 12.23.0, python 3.14, uv 0.13.9, gitleaks 8.30.1.
  - Python is 3.14, not 3.15, for wheel coverage: onnxruntime and similar packages land later.
- **Python deps:** typer 0.29.2 and pyyaml 6.0.4. Dev: ruff 0.17.6, pyright 1.1.414, pytest 9.2.0.
- **Not in 0A:** three, @react-three/*, zustand and @base-ui/react. The first task that uses each one installs it.

**TypeScript and module rules**
- `tools/*.ts` run directly with `node` (Node 26 type stripping). So:
  - Relative imports use explicit `.ts` extensions.
  - tsconfig sets `allowImportingTsExtensions`, `erasableSyntaxOnly`, `verbatimModuleSyntax` and `noEmit`.
  - No TS enums and no namespaces.
- Schemas import `z` from `astro/zod`.

**Product rules**
- No affiliate, ad or store links of any kind. A price observation's `url` is never rendered as a link.
- No BMW logos or badges anywhere: UI, models or textures, including the steering-wheel roundel.
- **Footer and `/about` notice**, exact copy:
  `Independent fan project. Not affiliated with, endorsed by, or sponsored by BMW AG. BMW and M3 are trademarks of BMW AG, used here only to describe the cars.`
- The site is `noindex` until the public beta. Pages emit `<meta name="robots" content="noindex">` unless `PUBLIC_INDEXABLE=true` at build time.
- IDs are kebab-case (`^[a-z0-9]+(-[a-z0-9]+)*$`). They're stable and never reused. Each data file's stem equals its `id`.

**Licenses and secrets**
- Licenses: code MIT (`LICENSE`), data CC BY-SA 4.0 (`DATA_LICENSE`).
- Secrets go only in `~/.config/secrets.env` and GitHub Actions secrets, with the `M3_` prefix. Never use `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`. Before appending a name, grep for the exact name.

**Public repo hygiene**
- Commits and PR bodies never carry a `Claude-Session` trailer or a session URL.
- A `Co-Authored-By:` trailer is fine. PR bodies may end with the "Generated with Claude Code" line, but no session link.
- Commit messages use Conventional Commits.

**Landing procedure** (Tasks 4–8; `main` is protected from Task 3 on)
1. Work on branch `phase0a/<task#>-<slug>` in its own worktree.
2. Push and open a PR whose body says `Closes #<issue>`.
3. Wait for CI to go green (`check`, `e2e`, `gitleaks`).
4. Review: Opus, plus a Codex second opinion via the codex-review skill.
5. Fix what the review finds, then squash-merge.

**Execution order**
- Tasks 1 → 2 → 3 run in order.
- Tasks 4, 5 and 6 can then run in parallel worktrees. Merge them one at a time and rebase onto `main` between merges, because all three touch `package.json` scripts.
- Task 7 runs after 5 and 6, since it documents their commands.
- Task 8 can run any time after Task 3.
- Phase 0B can start in its own worktree once Task 3 has merged.

## Review Focus

1. **A GLB exported in centimeters, or Z-up**, which is the most common exporter mistake. It must fail with `units` or `orientation`, not pass. Tested in Task 6.
2. **A meshopt-compressed GLB with KTX2 textures**, which is exactly what the export stage will produce. The validator must decode it and measure the textures, not crash or skip them. Tested in Task 6.
3. **An external link to a store**, such as a price `url` rendered as a link by mistake, or a protocol-relative `//shop…` link. `check:links` must fail the build. Tested in Task 1.
4. **A `verified: true` entry backed by two Tier 2 sources from the same publisher** (with differences in case or whitespace). That isn't "two independent" sources and must be rejected. Tested in Task 5.
5. **The same YAML date parsed two ways.** Astro's loader turns `checked: 2026-11-23` into a `Date`, while `yaml` 1.2 keeps it a string. Both must validate to the same instant. Tested in Task 5.

---

## File structure

```
m3-tool/
  mise.toml  package.json  pnpm-workspace.yaml  biome.json  tsconfig.json  astro.config.ts
  vitest.config.ts  playwright.config.ts  wrangler.jsonc  renovate.json  .mcp.json
  .gitignore  .githooks/pre-push  LICENSE  DATA_LICENSE  README.md  AGENTS.md  CLAUDE.md -> AGENTS.md
  CONTRIBUTING.md  .github/{workflows/ci.yml, pull_request_template.md}
  src/layouts/Base.astro  src/components/SiteFooter.astro  src/styles/global.css
  src/pages/{index,about,404}.astro
  src/lib/link-policy.ts          allowed link hosts + href checks          (Task 1)
  src/data/schemas.ts             Zod schemas for every collection          (Task 5)
  src/data/sources.ts             verification tier rule                    (Task 5)
  src/data/quality.ts             cross-file checks over a DataSet          (Task 5)
  src/data/load.ts                YAML -> DataSet for tools and tests       (Task 5)
  src/content.config.ts           Astro collections using schemas.ts        (Task 5)
  src/lib/asset-contract.ts       contract values per asset kind            (Task 6)
  src/lib/asset-validate.ts       validateDocument / validateGlb            (Task 6)
  src/lib/asset-manifest.ts       manifest.json schema                      (Task 6)
  src/assets/manifest.json                                                  (Task 6)
  tools/{check-links,check-data,validate-asset}.ts
  data/generations/e46.yaml  data/{variants,parts,maintenance,issues}/e46/.gitkeep
  tests/unit/**  tests/e2e/**  tests/fixtures/data/valid/**
  pipeline/pyproject.toml  pipeline/assets.toml  pipeline/src/m3_pipeline/**  pipeline/tests/**
  infra/{README.md, r2-models-cors.json}
  docs/{standards/*.md, decisions/*.md, superpowers/specs/, superpowers/plans/, spend-ledger.md}
```

---

### Task 1: Local scaffold, site skeleton and `pnpm check`

**Files:**
- Create: `mise.toml`, `package.json`, `pnpm-workspace.yaml`, `biome.json`, `tsconfig.json`, `astro.config.ts`, `vitest.config.ts`, `playwright.config.ts`, `.gitignore`, `LICENSE`, `DATA_LICENSE`, `README.md`
- Create: `src/layouts/Base.astro`, `src/components/SiteFooter.astro`, `src/styles/global.css`, `src/pages/index.astro`, `src/pages/about.astro`, `src/pages/404.astro`
- Create: `src/lib/link-policy.ts`, `tools/check-links.ts`
- Test: `tests/unit/link-policy.test.ts`, `tests/e2e/smoke.spec.ts`
- Move: the spec into `docs/superpowers/specs/2026-11-23-m3-tool-design.md`, and both Phase 0 plans into `docs/superpowers/plans/`

**Interfaces:**
- Produces, in `src/lib/link-policy.ts`:
  - `ALLOWED_LINK_HOSTS: readonly ['github.com', 'creativecommons.org', 'opensource.org', 'commons.wikimedia.org']`
  - `isAllowedHref(href: string): boolean`
  - `findHrefs(html: string): string[]`
- Produces, in `tools/check-links.ts`:
  - `checkLinks(distDir: string): Promise<LinkViolation[]>`, where `LinkViolation = { file: string; href: string }`.
  - The CLI is `node tools/check-links.ts <distDir>`. It exits 1 when there are violations.
- Produces these `package.json` scripts: `lint`, `typecheck`, `test`, `build`, `check:links`, `check:site`, `check`, `e2e`, `preview`.

- [ ] **Step 1: Create the repo and toolchain**

```bash
mkdir -p m3-tool && cd m3-tool && git init -b main
```
Write `mise.toml` with `[tools]` set to the Global Constraints versions, then run `mise install`.
Run: `node -v && pnpm -v && uv --version && gitleaks version`
Expected: `v26.13.1`, `12.23.0`, `uv 0.13.9`, `8.30.1`.

- [ ] **Step 2: Install pinned dependencies**

1. Write `package.json` with `"name": "m3-tool"`, `"private": true`, `"type": "module"`, `"packageManager": "pnpm@12.23.0"` and `"engines": { "node": ">=26" }`.
2. Install:
   - Runtime deps: astro, @astrojs/react, react, react-dom, tailwindcss, @tailwindcss/vite.
   - Dev deps: everything else in Global Constraints except the @gltf-transform packages, meshoptimizer, gltf-validator and ktx-parse, which Task 6 adds.
3. Use `--save-exact` for all of them.
4. If pnpm reports ignored build scripts, run `pnpm approve-builds` and allow only the packages it lists from `workerd`, `sharp` and `esbuild`. Commit the resulting `pnpm-workspace.yaml`.

Run: `pnpm install --frozen-lockfile`
Expected: exits 0.

- [ ] **Step 3: Write the configs**

- **tsconfig.json:** extends `astro/tsconfigs/strictest`. Add the Global Constraints flags. Include `src`, `tools`, `tests` and `*.config.ts`.
- **astro.config.ts:**
  - `site` comes from `process.env.SITE_URL ?? 'http://localhost:4321'`.
  - `integrations: [react()]` and `vite: { plugins: [tailwindcss()] }`.
  - No adapter. The output is static.
- **biome.json:** start from `pnpm biome init`. Set indent to 2 spaces and lineWidth to 100. Ignore `dist`, `.astro`, `.wrangler`, `pipeline`, `playwright-report` and `test-results`.
- **vitest.config.ts:** `test.include: ['tests/unit/**/*.test.ts']`.
- **playwright.config.ts:**
  - `testDir: 'tests/e2e'`.
  - `webServer: { command: 'pnpm preview --port 4321', url: 'http://localhost:4321', reuseExistingServer: !process.env.CI }`.
  - Chromium project only.
- **.gitignore:** `node_modules`, `dist`, `.astro`, `.wrangler`, `.dev.vars`, `.env`, `.env.*`, `playwright-report`, `test-results`, `pipeline/.venv`, `__pycache__`, `.pytest_cache`, `.ruff_cache`, `*.blend1`, `.m3-work/`.

- [ ] **Step 4: Write the failing link-policy tests**

```ts
// tests/unit/link-policy.test.ts
test('relative, root and fragment links are allowed', () => {
  for (const h of ['/about', 'about', '#top', '/e46/mods/']) expect(isAllowedHref(h)).toBe(true)
})
test('https links to allowlisted hosts are allowed', () => {
  expect(isAllowedHref('https://github.com/GridWork-dev/m3-tool')).toBe(true)
  expect(isAllowedHref('https://creativecommons.org/licenses/by-sa/4.0/')).toBe(true)
})
test('flags an absolute link to a store host', () => {
  expect(isAllowedHref('https://www.example-store.com/p/123')).toBe(false)
})
test('flags protocol-relative links', () => {
  expect(isAllowedHref('//shop.example.com/wheels')).toBe(false)
})
test('matches hosts exactly, not by suffix', () => {
  expect(isAllowedHref('https://evilgithub.com/x')).toBe(false)
  expect(isAllowedHref('https://gist.github.com/x')).toBe(false)
})
test('flags other schemes', () => {
  for (const h of ['mailto:a@b.c', 'http://github.com/x', 'javascript:void(0)']) expect(isAllowedHref(h)).toBe(false)
})
test('findHrefs returns every anchor href in order', () => {
  expect(findHrefs('<a href="/a">x</a><a class=y href=\'https://github.com\'>z</a>')).toEqual(['/a', 'https://github.com'])
})
```

- [ ] **Step 5: Run the tests and confirm they fail**

Run: `pnpm vitest run tests/unit/link-policy.test.ts`
Expected: FAIL, because `link-policy.ts` doesn't exist yet.

- [ ] **Step 6: Implement `src/lib/link-policy.ts` and `tools/check-links.ts`**

- `findHrefs` uses an attribute regex over `<a …>` tags.
- `checkLinks` walks `distDir` recursively, reads every `.html` file, and returns one violation per disallowed href.
- The CLI prints each violation as `<file>: <href>`.

- [ ] **Step 7: Run the tests and confirm they pass**

Run: `pnpm vitest run tests/unit/link-policy.test.ts`
Expected: PASS (7 tests).

- [ ] **Step 8: Build the layout and pages**

- **`Base.astro`:**
  - Props: `{ title: string; description?: string }`.
  - Renders the robots meta according to the noindex rule.
  - Imports `global.css` (`@import "tailwindcss";`).
  - Renders `<SiteFooter />` inside `<footer>`.
- **`SiteFooter`:**
  - The exact notice copy.
  - Then `Code MIT · Data CC BY-SA 4.0 · Source on GitHub`, linking to `https://opensource.org/license/mit`, `https://creativecommons.org/licenses/by-sa/4.0/` and `https://github.com/GridWork-dev/m3-tool`.
- **`index.astro`:**
  - `<h1>M3 tool</h1>`.
  - One paragraph: `Work in progress: a free reference for BMW M3 owners and shoppers, covering factory spec, real aftermarket parts with dated prices, build costs and maintenance. Nothing is for sale and there are no store links.`
- **`about.astro`:**
  - The notice.
  - A licenses section (MIT code, CC BY-SA 4.0 data, 3D model license to be confirmed).
  - `Credits for reference photos appear here once 3D models are published.`
- **`404.astro`:** `<h1>Page not found</h1>` and a link to `/`.

- [ ] **Step 9: Write the e2e smoke tests**

```ts
// tests/e2e/smoke.spec.ts
const NOTICE = 'Not affiliated with, endorsed by, or sponsored by BMW AG'
test('home page shows the not-affiliated notice', async ({ page }) => {
  await page.goto('/'); await expect(page.getByRole('contentinfo')).toContainText(NOTICE)
})
test('about page states the notice and licenses', async ({ page }) => {
  await page.goto('/about')
  for (const t of [NOTICE, 'MIT', 'CC BY-SA 4.0']) await expect(page.locator('main')).toContainText(t)
})
test('unknown paths return the 404 page', async ({ page }) => {
  const res = await page.goto('/no-such-page'); expect(res?.status()).toBe(404)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Page not found')
})
test('every page is noindex before the beta', async ({ page }) => {
  for (const p of ['/', '/about']) {
    await page.goto(p); await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', 'noindex')
  }
})
```

- [ ] **Step 10: Wire up the scripts**

```json
"lint": "biome check .",
"typecheck": "tsc --noEmit && astro check",
"test": "vitest run",
"build": "astro build && pagefind --site dist",
"preview": "astro preview",
"check:links": "node tools/check-links.ts dist",
"check:site": "pnpm lint && pnpm typecheck && pnpm test && pnpm build && pnpm check:links",
"check": "pnpm check:site",
"e2e": "playwright test"
```
If `astro check` fails to load TypeScript 7, scope TypeScript 6 to the checker only:
1. Add `overrides: { "@astrojs/check>typescript": "^6", "@astrojs/language-server>typescript": "^6" }` to `pnpm-workspace.yaml`.
2. Reinstall.
3. Note this in ADR 0001 (Task 8).

- [ ] **Step 11: Add licenses and README, and move the docs**

- `LICENSE`: MIT, `Copyright (c) 2026 GridWork-dev`.
- `DATA_LICENSE`: the official CC BY-SA 4.0 legal code text from `https://creativecommons.org/licenses/by-sa/4.0/legalcode.txt`, preceded by one line saying it covers `data/`.
- `README.md`: what it is, the status (work in progress), the licenses, and links to `AGENTS.md` and `CONTRIBUTING.md` (both written in Task 7).
- Move the docs:
  1. `git mv` isn't possible across repos, so move the spec and both plan files with `mv`.
  2. Leave a `README.md` in the maintainer's notes folder that points to the repo paths.

- [ ] **Step 12: Run everything**

Run: `pnpm exec playwright install chromium && pnpm check && pnpm e2e`
Expected: Biome, tsc and astro check report 0 errors. Vitest passes 7 tests. The build writes `dist/` with `index.html`, `about/index.html` and `404.html`. check:links prints nothing and exits 0. Playwright passes 4 tests.

- [ ] **Step 13: Commit**

```bash
git add -A && git commit -m "chore: scaffold astro site, toolchain and checks"
```

---

### Task 2: Python pipeline scaffold

**Files:**
- Create: `pipeline/pyproject.toml`, `pipeline/assets.toml`
- Create: `pipeline/src/m3_pipeline/__init__.py`, `cli.py`, `config.py`, `assets.py`, `stages/__init__.py`
- Test: `pipeline/tests/test_config.py`, `test_assets.py`, `test_cli.py`
- Modify: `package.json` (add `check:pipeline`, and extend `check`)

**Interfaces** (Plan 0B consumes these verbatim):
- `config.py`:
  - `@dataclass(frozen=True) class Settings: repo_root: Path; work_dir: Path`
  - `def load_settings(env: Mapping[str, str] | None = None) -> Settings`
  - `work_dir` comes from `M3_WORK_DIR`, default `~/.cache/m3-tool`.
  - `repo_root` comes from `M3_REPO_ROOT`, defaulting to the directory three levels above `src/m3_pipeline/`.
- `assets.py`:
  - `AssetKind = Literal["base-car", "interior", "product"]`
  - `@dataclass(frozen=True) class AssetSpec: id: str; kind: AssetKind; generation: str; subject: str`
  - `class AssetConfigError(ValueError)`
  - `def load_assets(path: Path) -> dict[str, AssetSpec]`
- `stages/__init__.py`:
  - `@dataclass class StageResult: ok: bool; messages: list[str]; outputs: list[Path]`
  - `Stage = Callable[[AssetSpec, Settings], StageResult]`
  - `REGISTRY: dict[str, Stage]`
  - `def register(name: str) -> Callable[[Stage], Stage]`
  - `class UnknownStageError(KeyError)`
  - `def run_stage(name: str, asset: AssetSpec, settings: Settings) -> StageResult`
- `cli.py`:
  - `app = typer.Typer()`
  - `pipeline run <asset_id> --stage <name>`: exit 0 when ok, 1 when not ok, 2 for an unknown asset or stage.
  - `pipeline stages` and `pipeline assets` list what's registered.
  - Sub-apps attach with `app.add_typer(...)`.
- Script: `check:pipeline` = `cd pipeline && uv run ruff check && uv run ruff format --check && uv run pyright && uv run pytest`.

- [ ] **Step 1: Create the project**

1. Run `cd pipeline && uv init --package --build-backend uv --name m3-pipeline --python 3.14`.
2. In `pyproject.toml`, set `requires-python = ">=3.14,<3.15"`, the pinned deps, `[project.scripts] pipeline = "m3_pipeline.cli:app"` and `[dependency-groups] dev = [...]`.
3. Settings:
   - `[tool.ruff]`: `line-length = 100`, `lint.select = ["E","F","I","UP","B","SIM"]`.
   - `[tool.pyright]`: `typeCheckingMode = "strict"`.
   - `[tool.pytest.ini_options]`: `testpaths = ["tests"]`.

Write `pipeline/assets.toml`:
```toml
[e46-coupe-body]
kind = "base-car"
generation = "e46"
subject = "e46-coupe"

[e46-coupe-interior]
kind = "interior"
generation = "e46"
subject = "e46-coupe-interior"
```

- [ ] **Step 2: Write the failing tests**

```python
def test_default_work_dir_is_outside_repo():
    s = load_settings({})
    assert s.work_dir == Path("~/.cache/m3-tool").expanduser()
    assert not s.work_dir.is_relative_to(s.repo_root)

def test_env_overrides_work_dir(tmp_path):
    assert load_settings({"M3_WORK_DIR": str(tmp_path)}).work_dir == tmp_path

def test_repo_root_contains_package_json():
    assert (load_settings({}).repo_root / "package.json").exists()

def test_load_assets_parses_repo_file():
    assets = load_assets(load_settings({}).repo_root / "pipeline/assets.toml")
    assert assets["e46-coupe-body"] == AssetSpec("e46-coupe-body", "base-car", "e46", "e46-coupe")

def test_load_assets_rejects_unknown_kind(tmp_path):
    p = tmp_path / "a.toml"; p.write_text('[x]\nkind="car"\ngeneration="e46"\nsubject="s"\n')
    with pytest.raises(AssetConfigError, match="kind"): load_assets(p)

def test_cli_unknown_stage_exits_2():
    r = CliRunner().invoke(app, ["run", "e46-coupe-body", "--stage", "nope"])
    assert r.exit_code == 2 and "unknown stage 'nope'" in r.output

def test_cli_unknown_asset_exits_2():
    r = CliRunner().invoke(app, ["run", "nope", "--stage", "validate"])
    assert r.exit_code == 2 and "unknown asset 'nope'" in r.output

def test_cli_runs_registered_stage(monkeypatch):
    monkeypatch.setitem(REGISTRY, "fake", lambda a, s: StageResult(False, ["boom"], []))
    r = CliRunner().invoke(app, ["run", "e46-coupe-body", "--stage", "fake"])
    assert r.exit_code == 1 and "boom" in r.output
```

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `cd pipeline && uv run pytest -q`
Expected: FAIL with import errors.

- [ ] **Step 4: Implement `config.py`, `assets.py`, `stages/__init__.py` and `cli.py`**

- `assets.py` reads TOML with `tomllib`.
- `run` resolves the asset before the stage. In Task 2 no stage is registered yet, and `test_cli_unknown_asset_exits_2` depends on that order.
- The CLI's unknown-name errors list the known names: `unknown stage 'nope'; known: …`.

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `cd pipeline && uv run pytest -q`
Expected: `8 passed`.

- [ ] **Step 6: Wire into the root check**

Add `check:pipeline` and set `"check": "pnpm check:site && pnpm check:pipeline"`.
Run: `pnpm check`
Expected: exits 0, with ruff, pyright (0 errors) and pytest (8 passed) all green.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "chore(pipeline): add uv project, stage registry and cli"
```

---

### Task 3: GitHub repo, CI and secret scanning

This task does outward-facing things. Creating a public repo was approved in the spec.

**Files:**
- Create: `.github/workflows/ci.yml`, `.githooks/pre-push`, `renovate.json`, `infra/github-ruleset.json`
- Modify: `package.json` (add `"prepare": "git config core.hooksPath .githooks"`)

**Interfaces:**
- Produces:
  - Remote `https://github.com/GridWork-dev/m3-tool`.
  - Required status checks named `check`, `e2e` and `gitleaks`.
  - Labels `data`, `3d`, `app`, `pipeline`, `safety`, `infra`, `docs`, `spike`, `contract`.
  - Milestones `Phase 0: foundations` through `Phase 4: more generations`.
  - One issue per Phase 0 roadmap step (spec section 15).

- [ ] **Step 1: Write the CI workflow**

`ci.yml` runs on `pull_request` and on `push` to `main`, with three jobs on `ubuntu-latest`:
- **`check`:**
  1. checkout.
  2. `jdx/mise-action`, which installs `mise.toml`.
  3. `pnpm install --frozen-lockfile`.
  4. `uv sync --locked --project pipeline`.
  5. `pnpm check`.
- **`e2e`:**
  1. The same setup.
  2. `pnpm exec playwright install --with-deps chromium`.
  3. `pnpm build`.
  4. `pnpm e2e`.
  5. Upload `playwright-report` on failure.
- **`gitleaks`:**
  1. checkout with `fetch-depth: 0`.
  2. mise.
  3. `gitleaks git --redact --verbose`.
  - Use the CLI, not `gitleaks-action`, which needs a paid license for org repos.

For action versions, use the latest major of each (`gh api repos/{owner}/{repo}/releases/latest --jq .tag_name`). Renovate keeps them current after that.

- [ ] **Step 2: Write the pre-push hook and prove it blocks a leak**

`.githooks/pre-push`:
```sh
#!/bin/sh
exec gitleaks git --redact --log-opts="--all --not --remotes"
```
Then `chmod +x` it and run `pnpm install`, which runs `prepare`.

Run the negative test in a throwaway repo under the scratchpad:
1. Init a repo.
2. Commit a file containing `ghp_` followed by 36 `a` characters.
3. Run `sh <repo>/.githooks/pre-push`.

Expected: exit 1, with `leaks found: 1`.
Then run: `sh .githooks/pre-push` in m3-tool.
Expected: exit 0, `no leaks found`.

- [ ] **Step 3: Configure Renovate**

`renovate.json`:
- Extends `config:recommended`, `schedule:weekly` and `group:allNonMajor`.
- `packageRules`: automerge `minor` and `patch` once checks pass.
- `lockFileMaintenance` enabled.

- [ ] **Step 4: Check the history for leaks, then create the repo**

Run: `gitleaks git --redact && git log --format=%B | grep -c 'Claude-Session' || true`
Expected: `no leaks found`, then `0`.
```bash
git add -A && git commit -m "ci: add checks, e2e, gitleaks, pre-push hook and renovate"
gh repo create GridWork-dev/m3-tool --public --source . --push \
  --description "Free BMW M3 reference: 3D configurator, real-part build sheets, maintenance. Nothing for sale."
```

- [ ] **Step 5: Repo settings, secret scanning and branch ruleset**

1. Settings: `gh repo edit GridWork-dev/m3-tool --enable-squash-merge --enable-merge-commit=false --enable-rebase-merge=false --delete-branch-on-merge --enable-wiki=false`.
2. Secret scanning: enable `secret_scanning` and `secret_scanning_push_protection` with `gh api -X PATCH repos/GridWork-dev/m3-tool --input -`, passing a JSON `security_and_analysis` body.
3. Ruleset: write `infra/github-ruleset.json`:
   - target `branch`, include `~DEFAULT_BRANCH`.
   - Rules:
     - `deletion`.
     - `non_fast_forward`.
     - `pull_request` with `required_approving_review_count: 0`.
     - `required_status_checks` for `check`, `e2e` and `gitleaks`.
   - Then POST it to `repos/GridWork-dev/m3-tool/rulesets`.
   - Zero approvals is my call. The only maintainer can't approve their own PRs. The review gate is the Opus and Codex review recorded on each PR, as written in `AGENTS.md` and ADR 0007.

Run: `gh api repos/GridWork-dev/m3-tool/rules/branches/main --jq '.[].type'`
Expected: lists `deletion`, `non_fast_forward`, `pull_request` and `required_status_checks`.

- [ ] **Step 6: Labels, milestones and Phase 0 issues**

1. Create the 9 labels with `gh label create`.
2. Create the 5 milestones with `gh api repos/GridWork-dev/m3-tool/milestones -f title=…`.
3. Open one issue per spec section 15 Phase 0 step (7 issues), each with its labels and the Phase 0 milestone. Issues 1–4 link this plan, issue 5 links the 0B plan, and issue 6 says "plan 0C is written after photos are collected".

Run: `gh issue list --milestone "Phase 0: foundations" --json number --jq length`
Expected: `7`.

- [ ] **Step 7: Verify CI on `main`**

Run: `gh run watch --exit-status $(gh run list --branch main --limit 1 --json databaseId --jq '.[0].databaseId')`
Expected: `check`, `e2e` and `gitleaks` all succeed.

Renovate needs its GitHub app on the GridWork-dev org. If `gh api repos/GridWork-dev/m3-tool/installation` doesn't show it, list "install the Renovate app on GridWork-dev, scoped to m3-tool" as a user step in the task report.

---

### Task 4: Cloudflare deploy, PR previews and R2

> Amended 2026-11-23 (ledger R8/R9). The user chose GitHub Actions over Workers Builds. Cloudflare tokens are minted by the **controller** through the API with the account's key-management token. Nothing is done in the dashboard. Implementers use the bootstrap token already in `~/.config/secrets.env` (`M3_CF_API_TOKEN`, `M3_CF_ACCOUNT_ID`), but never mint tokens and never print token values.

**Files:**
- Create: `wrangler.jsonc`, `.github/workflows/deploy.yml`, `infra/README.md`, `infra/r2-models-cors.json`
- Modify: `package.json` (add `deploy`), `astro.config.ts` (default `site` becomes the workers.dev URL)

**Interfaces:**
- Produces:
  - Worker `m3-tool` on the GridWork account, at `https://m3-tool.<subdomain>.workers.dev`.
  - PR preview URLs `https://pr-<n>-m3-tool.<subdomain>.workers.dev`, posted as a PR comment.
  - R2 bucket `m3-tool-models`: public through its r2.dev URL, CORS GET/HEAD for any origin.
  - R2 bucket `m3-tool-refs`: private.
  - GitHub Actions secrets (set by the controller): `M3_CF_DEPLOY_TOKEN`, `M3_CF_ACCOUNT_ID`.
  - Laptop env for Plan 0B (set by the controller): `M3_R2_ACCOUNT_ID`, `M3_R2_ACCESS_KEY_ID`, `M3_R2_SECRET_ACCESS_KEY`.

- [ ] **Step 1: Write `wrangler.jsonc`**

```jsonc
{
  "$schema": "node_modules/wrangler/config-schema.json",
  "name": "m3-tool",
  "compatibility_date": "2026-11-23",
  "assets": { "directory": "./dist", "not_found_handling": "404-page" },
  "workers_dev": true,
  "preview_urls": true
}
```
Add the script `"deploy": "wrangler deploy"`.

- [ ] **Step 2: First deploy from the laptop, with the bootstrap token**

Run: `pnpm build && CLOUDFLARE_API_TOKEN="$M3_CF_API_TOKEN" CLOUDFLARE_ACCOUNT_ID="$M3_CF_ACCOUNT_ID" pnpm deploy`
Expected: `Deployed m3-tool` with a `https://m3-tool.<subdomain>.workers.dev` URL.
Then set that URL as the `site` default in `astro.config.ts`.
Run: `curl -s https://m3-tool.<subdomain>.workers.dev/ | grep -c 'Not affiliated with, endorsed by'`
Expected: `1`.
Run: `curl -s -o /dev/null -w '%{http_code}' https://m3-tool.<subdomain>.workers.dev/nope`
Expected: `404`.

- [ ] **Step 3: Controller mints the deploy token and sets the repo secrets**

This step is done by the controller, not the implementer.
- Mint `m3-tool-deploy (GitHub Actions deploy.yml)`: "Individual Workers Editor" scoped to the `m3-tool` Worker, plus Account Settings Read. Copy the resource format from an existing per-Worker token on the account.
- Pipe the value straight into `gh secret set M3_CF_DEPLOY_TOKEN`.
- Set `M3_CF_ACCOUNT_ID` the same way.

Run: `gh secret list -R GridWork-dev/m3-tool`
Expected: both names listed.

- [ ] **Step 4: Write the deploy workflow**

`.github/workflows/deploy.yml`:
- Triggers: `push` to `main`, and `pull_request`. Skip the PR job when the head repo isn't `GridWork-dev/m3-tool`, because forks get no secrets.
- `concurrency: deploy-${{ github.ref }}`, with `cancel-in-progress` on PRs only.
- Permissions: `contents: read`, `pull-requests: write`.
- Steps:
  1. checkout.
  2. `jdx/mise-action`.
  3. `pnpm install --frozen-lockfile`.
  4. `pnpm build`.
  5. Then either:
     - `main`: `pnpm wrangler deploy`.
     - PR: `pnpm wrangler versions upload --preview-alias pr-${{ github.event.number }}`. Pull the preview URL out of its output, then create or update a single PR comment that starts with `<!-- m3-tool-preview -->` and contains the URL.
- Env for wrangler: `CLOUDFLARE_API_TOKEN: ${{ secrets.M3_CF_DEPLOY_TOKEN }}` and `CLOUDFLARE_ACCOUNT_ID: ${{ secrets.M3_CF_ACCOUNT_ID }}`.
- The deploy job is not a required status check. It needs secrets, and `check`/`e2e`/`gitleaks` stay the merge gate.

- [ ] **Step 5: Verify PR previews**

Push this task's branch and open its PR.
Expected: the deploy job passes, the PR has the `<!-- m3-tool-preview -->` comment, and `curl -s <preview-url> | grep -c 'Not affiliated'` prints `1`.

- [ ] **Step 6: Create the R2 buckets, with the bootstrap token**

```bash
export CLOUDFLARE_API_TOKEN="$M3_CF_API_TOKEN" CLOUDFLARE_ACCOUNT_ID="$M3_CF_ACCOUNT_ID"
pnpm wrangler r2 bucket create m3-tool-models
pnpm wrangler r2 bucket create m3-tool-refs
pnpm wrangler r2 bucket dev-url enable m3-tool-models
pnpm wrangler r2 bucket cors set m3-tool-models --file infra/r2-models-cors.json
```
`r2-models-cors.json` allows `GET` and `HEAD` from origin `*`, with `MaxAgeSeconds: 86400`. The models are public, CC BY-SA content. R2 is already enabled on the account.

Run: `pnpm wrangler r2 bucket list | grep -c m3-tool- && pnpm wrangler r2 bucket dev-url get m3-tool-refs`
Expected: `2`, and the refs bucket reports public access disabled.

- [ ] **Step 7: Controller mints the R2 token and derives the S3 keys**

This step is done by the controller.
1. Mint `m3-tool-r2 (laptop pipeline)`: "Workers R2 Storage Bucket Item Write", scoped to the two m3-tool buckets.
2. Derive the S3 keys: access key ID = token id, secret = SHA-256 hex of the token value.
3. Append `M3_R2_ACCOUNT_ID`, `M3_R2_ACCESS_KEY_ID` and `M3_R2_SECRET_ACCESS_KEY` to `~/.config/secrets.env`, grepping each name first. Never print the values.

Verify: `uv run --with boto3==1.44.9` lists `m3-tool-refs` through `https://$M3_R2_ACCOUNT_ID.r2.cloudflarestorage.com`.
Expected: an empty listing and no error.

- [ ] **Step 8: Document the infrastructure and land it**

`infra/README.md` lists, for each resource:
- What it is.
- Whether it's public.
- The command that recreates it.
- Which token or secret names exist and what each is scoped to. Names only.

It also notes:
- Tokens are minted through the API with the key-management token.
- The bootstrap token expires on 2026-12-07.
- Cloudflare Web Analytics waits for the beta domain (Phase 1).

Then follow the landing procedure (`Closes` the Phase 0 step 1–2 issues).

---

### Task 5: Data contract (schemas, checks, first real entry)

**Files:**
- Create: `src/data/schemas.ts`, `src/data/sources.ts`, `src/data/quality.ts`, `src/data/load.ts`, `src/content.config.ts`, `tools/check-data.ts`
- Create: `data/generations/e46.yaml`, `data/{variants,parts,maintenance,issues}/e46/.gitkeep`
- Create: `tests/fixtures/data/valid/**`, `docs/standards/data.md`
- Test: `tests/unit/data/schemas.test.ts`, `sources.test.ts`, `quality.test.ts`
- Modify: `package.json` (add `check:data` to `check:site`, after `test`)

**Interfaces:**
- Produces, in `schemas.ts`, Zod schemas named `Generation`, `Variant`, `Part`, `MaintenanceItem`, `KnownIssue`, `Source` and `PriceObservation`, plus inferred types of the same names.
- Produces, in `sources.ts`: `meetsVerificationRule(sources: Source[]): boolean`.
- Produces, in `quality.ts`:
  - `type QualityCode = 'schema' | 'duplicate-id' | 'id-filename-mismatch' | 'unknown-generation' | 'directory-generation-mismatch' | 'unknown-ref' | 'self-ref' | 'requires-conflicts-overlap' | 'verified-without-tier' | 'multiple-generic-in-category'`
  - `interface QualityIssue { file: string; code: QualityCode; message: string }`
  - `interface Entry<T> { file: string; data: T }`
  - `interface DataSet { generations: Entry<Generation>[]; variants: Entry<Variant>[]; parts: Entry<Part>[]; maintenance: Entry<MaintenanceItem>[]; issues: Entry<KnownIssue>[] }`
  - `checkDataSet(set: DataSet): QualityIssue[]`
- Produces, in `load.ts`: `loadDataSet(dataDir: string): Promise<{ set: DataSet; issues: QualityIssue[] }>`. Schema failures come back as `code: 'schema'`, with the Zod path in the message.
- Produces, in `tools/check-data.ts`: `runCheckData(dataDir: string): Promise<{ exitCode: 0 | 1; lines: string[] }>`. The CLI is `node tools/check-data.ts <dir>` and prints `<file>: <code>: <message>`.
- Layout `loadDataSet` reads: `generations/*.yaml` plus `{variants,parts,maintenance,issues}/<gen>/*.yaml`.

**Schema shapes.** These are decisions. Write them as Zod.

```ts
Id = /^[a-z0-9]+(-[a-z0-9]+)*$/;  Year = int 1985..2035;  Range = [min, max], 0 <= min <= max
DateLike = z.coerce.date()   // accepts YAML strings and Date objects; Invalid Date rejected
Body = 'coupe' | 'convertible' | 'sedan';  Transmission = '6mt' | 'smg' | 'dct' | 'auto' | '7mt'
Source = { title: string; publisher: string; url?: https URL; tier: 1 | 2 | 3; accessed: DateLike; note?: string }
WheelSize = { diameterIn: number; widthIn: number; offsetMm: number; tire: /^\d{3}\/\d{2}Z?R\d{2}$/ }
AxleFitment = { boltPattern: /^\d+x\d+(\.\d+)?$/; centerBoreMm: number; stock: WheelSize;
  envelopes: { rideDropMm: number; maxInnerMm: number; maxOuterMm: number; maxOuterWithFenderWorkMm: number }[] }
  // envelopes may be empty: Phase 1 rules then report "fitment unknown"
  // inner = widthIn*25.4/2 + offsetMm, outer = widthIn*25.4/2 - offsetMm (mm from hub face)
Dimensions = { lengthMm, widthMm, heightMm, wheelbaseMm, trackFrontMm, trackRearMm: positive numbers; sources: Source[] (min 1) }
Generation = { id: Id; name: string; chassis: string; years: [Year, Year] /* production */;
  engines: { code: string; displacementCc: number; cylinders: number }[] (min 1); bodies: Body[] (min 1);
  dimensions: Partial<Record<Body, Dimensions>> (at least one key, keys ⊆ bodies);
  driverEyePoint: { xMm: number; yMm: number; zMm: number; basis: 'measured' | 'estimated'; note: string; sources: Source[] };
    // asset-contract frame in mm: origin on ground under mid-wheelbase, +Y up, nose toward -Z, LHD driver at -X
    // refine: basis 'measured' requires sources (min 1)
  fitment: { front: AxleFitment; rear: AxleFitment; sources: Source[] (min 1) } }
Variant = { id: Id; generation: Id; name: string; market: 'us' | 'euro'; body: Body; transmissions: Transmission[] (min 1);
  years: [Year, Year]; packages: { id: Id; name: string; summary: string }[];
  paints: { code: string; name: string; finish: 'solid' | 'metallic' | 'pearl'; baseColor: /^#[0-9a-f]{6}$/ }[];
  factoryWheels: { id: Id; name: string; front: WheelSize; rear: WheelSize; asset?: Id }[];
  interiors: { id: Id; name: string; color: string; material: 'leather' | 'cloth' | 'alcantara' | 'mixed' }[];
  render: { baseAsset: Id; interiorAsset: Id; note?: string }; sources: Source[] (min 1) }
PartCategory = 'wheels' | 'tires' | 'brakes' | 'suspension' | 'exhaust' | 'intake' | 'aero' | 'lighting' | 'interior'
  | 'seats' | 'steering' | 'drivetrain' | 'engine' | 'tuning' | 'cooling' | 'protection' | 'tint'
PartAttributes = discriminated on kind:
  { kind: 'wheel'; diameterIn; widthIn; offsetMm; boltPattern; centerBoreMm; axle: 'front' | 'rear' | 'both' }
  | { kind: 'tire'; size: same regex as WheelSize.tire; approvedRimWidthIn: Range; axle: 'front' | 'rear' | 'both' }
  | { kind: 'brake-kit'; axle: 'front' | 'rear'; minWheelDiameterIn: number }
  | { kind: 'hub-ring'; outerMm: number; innerMm: number }
  | { kind: 'suspension'; rideDropMm: Range }
  // kind -> required category: wheel|hub-ring -> wheels, tire -> tires, brake-kit -> brakes, suspension -> suspension
PriceObservation = { amount: number > 0; currency: 'USD' | 'EUR'; seller: string (non-empty); checked: DateLike; url?: https URL }
Part = { id: Id; name: string; brand?: string; category: PartCategory; visible: boolean;
  fits: { generation: Id; years?: [Year, Year]; bodies?: Body[]; transmissions?: Transmission[] };
  attributes?: PartAttributes; options?: { id: Id; label: string; attributes?: PartAttributes; prices?: PriceObservation[] }[];
  requires?: Id[]; conflicts?: Id[]; labor: { hours: Range; diy: 'easy' | 'intermediate' | 'pro' };
  prices?: PriceObservation[]; model?: { asset: Id; params?: Record<string, number | string | boolean> }
    | { standIn: Id; params?: Record<string, number | string | boolean> };
  claims?: string[]; sources: Source[]; verified: boolean }
  // refines: no brand => no prices anywhere (generic tier is computed);
  //          visible => model required, !visible => model absent;
  //          options => no part-level attributes/prices, option ids unique; attributes.kind matches category
MaintenanceItem = { id; generation: Id; engine?: string; title: string; interval: { miles?: int; months?: int } (at least one);
  parts: string[]; fluids: string[]; cost: { currency: 'USD'; diy: Range; shop: Range };
  inspectWhenBuying: boolean; howToCheck?: string; sources: Source[] (min 1); verified: boolean; notes?: string }
KnownIssue = { id; generation: Id; engine?: string; title: string; symptoms: string[] (min 1); cause: string; fix: string;
  prevention?: string; cost: { currency: 'USD'; diy?: Range; shop: Range }; frequency: 'rare' | 'common' | 'very-common';
  inspectWhenBuying: boolean; howToCheck?: string; sources: Source[] (min 1); verified: boolean }
  // refine (both): inspectWhenBuying => howToCheck non-empty
```

The spec spells the frequency value `very common`. In YAML it's `very-common`, so values stay kebab-case like IDs (my call). The UI renders it with a space.

Spec section 15 asks for "2–3 sample E46 entries per collection". In this plan those samples are test fixtures under `tests/fixtures/data/valid/`, not files under `data/` (my call). Anything in `data/` gets published, and samples written before the data lane's sourcing and verification would put unverified prices and maintenance claims on a public site. The only real entry in Phase 0 is `data/generations/e46.yaml`, sourced in Step 8.

- [ ] **Step 1: Write the fixture set**

Create `tests/fixtures/data/valid/` with one valid file per shape:
- `generations/e46.yaml`
- `variants/e46/e46-us-coupe.yaml`
- `parts/e46/fixture-wheel.yaml` (brand `Fixture Co`, two size `options` with prices, `model.standIn`)
- `parts/e46/fixture-generic-wheels.yaml` (no brand, no prices)
- `parts/e46/fixture-coilovers.yaml` (suspension attributes, `requires: [fixture-wheel]`)
- `maintenance/e46/fixture-oil-service.yaml` (verified, with one Tier 1 source)
- `issues/e46/fixture-rod-bearings.yaml` (unverified, Tier 3 only)

Every name starts with `fixture-`, and every brand is `Fixture Co`, so none of it can be mistaken for real data.

- [ ] **Step 2: Write the failing schema and source tests**

```ts
// schemas.test.ts
test('the valid fixture set loads with no issues', async () => {
  expect((await loadDataSet('tests/fixtures/data/valid')).issues).toEqual([])
})
test('YAML date strings and Date objects parse to the same instant', () => {
  const base = { amount: 1, currency: 'USD', seller: 'S' } as const
  expect(PriceObservation.parse({ ...base, checked: '2026-11-23' }).checked.getTime())
    .toBe(PriceObservation.parse({ ...base, checked: new Date('2026-11-23') }).checked.getTime())
})
test('rejects a price without a seller or with an unparseable date', ...)   // seller '' and checked 'soon' each fail
test('rejects prices on a generic (brandless) part, including option prices', ...)
test('requires model when visible and forbids it when not', ...)
test('rejects part-level attributes or prices when options exist', ...)
test('rejects wheel attributes on a part outside the wheels category', ...)
test('rejects inspectWhenBuying without howToCheck', ...)                     // maintenance and issue
test('rejects a maintenance interval with neither miles nor months', ...)
test('rejects non-kebab ids', ...)                                            // 'E46_Coupe'
test('rejects a measured eye point without sources', ...)
test('rejects dimensions keyed by a body the generation lacks', ...)

// sources.test.ts
const s = (tier: 1 | 2 | 3, publisher: string) => ({ title: 't', publisher, tier, accessed: new Date() })
test('one tier-1 source verifies', () => expect(meetsVerificationRule([s(1, 'BMW')])).toBe(true))
test('two tier-2 sources from different publishers verify', () =>
  expect(meetsVerificationRule([s(2, 'Shop A'), s(2, 'Mag B')])).toBe(true))
test('two tier-2 sources from the same publisher do not verify', () =>
  expect(meetsVerificationRule([s(2, 'Shop A'), s(2, ' shop a ')])).toBe(false))
test('tier-3 sources never verify', () =>
  expect(meetsVerificationRule([s(3, 'F1'), s(3, 'F2'), s(3, 'F3')])).toBe(false))
```
Each `...` test asserts that `safeParse(...).success` is `false` for the named mutation of a valid fixture object, and `true` for the unmutated object.

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `pnpm vitest run tests/unit/data`
Expected: FAIL, because the modules don't exist yet.

- [ ] **Step 4: Implement `schemas.ts` and `sources.ts`**

- Refinements use `superRefine` with explicit messages.
- Publisher normalization is `trim().toLowerCase()`.

- [ ] **Step 5: Write the failing quality tests**

```ts
// quality.test.ts: each builds a DataSet from the valid fixtures, applies one change, and checks the codes
test('duplicate ids across files', ...)                → ['duplicate-id']
test('file stem differs from id', ...)                 → ['id-filename-mismatch']
test('part fits an unknown generation', ...)           → ['unknown-generation']
test('part file under parts/e46 fits another generation', ...) → ['directory-generation-mismatch']
test('requires or conflicts names a missing part', ...) → ['unknown-ref'], message includes the missing id
test('part requires itself', ...)                      → ['self-ref']
test('same id in requires and conflicts', ...)         → ['requires-conflicts-overlap']
test('verified maintenance or issue fails the tier rule', ...) → ['verified-without-tier'] for each
test('two generic parts in one category for one generation', ...) → ['multiple-generic-in-category']
test('check-data exits 1 and prints file: code: message', async () => {
  // copy valid fixtures to a tmp dir, rename one part file, run runCheckData(tmp)
  // expect exitCode 1 and a line matching /fixture-.*: id-filename-mismatch: /
})
```

- [ ] **Step 6: Implement `quality.ts`, `load.ts` and `tools/check-data.ts`, and run all data tests**

`load.ts` parses with `yaml`'s `parse`, which follows YAML 1.2, so dates stay strings and are coerced by the schema.
Run: `pnpm vitest run tests/unit/data`
Expected: PASS.

- [ ] **Step 7: Astro collections**

`src/content.config.ts` defines `generations`, `variants`, `parts`, `maintenance` and `issues`. Each uses `glob({ pattern: '**/*.yaml', base: './data/<name>' })` and the matching schema from `schemas.ts`.
Run: `pnpm build`
Expected: the build succeeds. An empty collection only warns.

- [ ] **Step 8: Write the first real entry, `data/generations/e46.yaml`**

These values are starting points. Each one must be confirmed against a cited source. If a source disagrees, use the source's value and say so in the PR.

| Field | Value | Source needed |
|---|---|---|
| `name`, `chassis`, `years` | `M3 (E46)`, `E46`, `[2000, 2006]` | Tier 1 or 2 |
| `engines` | `S54B32`, 3246 cc, 6 cylinders | Tier 1 |
| `bodies` | `[coupe, convertible]` | Tier 1 |
| `dimensions.coupe` (mm) | length 4492, width 1780, height 1372, wheelbase 2731, front track 1508, rear track 1525 | Tier 1 (BMW technical data or press kit) |
| `fitment` front | `5x120`, center bore 72.6, stock 18×8 ET47, `225/45ZR18`, `envelopes: []` | Tier 1 or 2 |
| `fitment` rear | `5x120`, center bore 72.6, stock 18×9 ET26, `255/40ZR18`, `envelopes: []` | Tier 1 or 2 |
| `driverEyePoint` | x −370, y 1100, z 0; `basis: estimated` | None |

The eye point's `note` reads: `Placeholder estimate. The 3D lane replaces it with a value measured from the interior asset.`

Run: `node tools/check-data.ts data`
Expected: exit 0, no output.

- [ ] **Step 9: Write `docs/standards/data.md`**

Cover:
- The file layout and ID rules.
- The schema summary, linking to `src/data/schemas.ts`.
- The source tiers and verification rule from spec section 7.6, verbatim.
- Price rules:
  - Seller and date are required.
  - `url` is never rendered.
  - The UI shows the 90-day range and marks it stale after 60 days.
- The generic tier is computed and never hand-priced.
- PRs touching maintenance or issues get the `safety` label.
- The rules for collecting starting prices.
- How to run `check-data`.

- [ ] **Step 10: Wire up and land**

Add `"check:data": "node tools/check-data.ts data"` into `check:site`, after `test`.
Run: `pnpm check`
Expected: green.
Follow the landing procedure with the `contract` and `data` labels, and `Closes` the Phase 0 step 4 issue jointly with Task 6.

---

### Task 6: 3D asset contract, validator, manifest, and the pipeline `validate` stage

**Files:**
- Create: `src/lib/asset-contract.ts`, `src/lib/asset-validate.ts`, `src/lib/asset-manifest.ts`, `src/assets/manifest.json`, `tools/validate-asset.ts`, `docs/standards/3d-assets.md`
- Create: `tests/unit/assets/fixtures.ts`, `tests/unit/assets/validate.test.ts`, `tests/unit/assets/manifest.test.ts`
- Create: `pipeline/src/m3_pipeline/stages/validate.py`, `pipeline/tests/test_validate_stage.py`
- Modify: `package.json` (add deps; add `"validate-asset": "node tools/validate-asset.ts"`), `tools/check-data.ts` (also parse the manifest)

**Interfaces:**
- Consumes `REGISTRY`, `register`, `StageResult`, `AssetSpec` and `Settings` (Task 2).
- Produces:
```ts
type AssetKind = 'base-car' | 'interior' | 'product'
interface AssetContract { kind: AssetKind; requiredNodes: readonly string[]; requiredAnchors: readonly string[];
  requiredMaterials: readonly string[]; triangles: { min: number; max: number }; maxBytes: number;
  maxTextureSize: number; detailTexture?: { materials: readonly string[]; maxSize: number } }
const CONTRACTS: Record<AssetKind, AssetContract>
type IssueCode = 'khronos' | 'missing-node' | 'missing-anchor' | 'missing-material' | 'triangles' | 'bytes'
  | 'texture-size' | 'units' | 'orientation' | 'origin' | 'root-count'
interface ContractIssue { code: IssueCode; severity: 'error' | 'warning'; message: string }
function validateDocument(doc: Document, opts: { kind: AssetKind; bytes: number }): ContractIssue[]
function validateGlb(bytes: Uint8Array, kind: AssetKind): Promise<{ ok: boolean; issues: ContractIssue[] }>
const AssetManifest: ZodType  // { version: 1; assets: Record<Id, { kind; url: https; sha256: /^[a-f0-9]{64}$/;
                              //   bytes: int > 0; triangles: int >= 0; license: string; sources: string[]; publishedAt: DateLike }> }
```
- The CLI is `node tools/validate-asset.ts <file.glb> --kind <kind> [--json]`.
  - Exits 0 when the asset passes, 1 on any `error` issue, and 2 on a usage error.
  - JSON output is `{ ok, issues }`.
- Python stage `validate`:
  - Reads `<work_dir>/assets/<id>/export/<id>.glb`.
  - Runs `node <repo>/tools/validate-asset.ts <glb> --kind <kind> --json` through the module-level `_run: Callable[[list[str]], subprocess.CompletedProcess[str]]`, which tests monkeypatch.

**Contract values** (spec section 9.6; "MB" means 1,000,000 bytes):

| Kind | Required nodes | Required anchors | Required materials | Triangles | Max bytes | Max texture size |
|---|---|---|---|---|---|---|
| `base-car` | `body` | `wheel_FL`, `wheel_FR`, `wheel_RL`, `wheel_RR`, `mount_front_lip`, `mount_trunk`, `mount_wing`, `mount_exhaust_L`, `mount_exhaust_R`, `mount_interior` | `paint`, `glass`, `trim`, `lights_front`, `lights_rear` | 100,000–200,000 | 8,000,000 | 2048, or 4096 for textures used only by `paint` |
| `interior` | `interior`, `cabin_shell`, `dash`, `console`, `door_L`, `door_R`, `seat_driver`, `seat_passenger`, `steering_wheel` | `mount_seat_L`, `mount_seat_R`, `mount_steering`, `camera_driver_eye` | none | 0–150,000 | 6,000,000 | 4096 |
| `product` | none | none | none | 0–30,000 | 1,000,000 | 2048 |

Products must also have exactly one root node in the scene.

**How each check works:**
- **Names:** matched exactly, case-sensitive, anywhere in the scene graph. Anchors are nodes without a mesh.
- **Triangles:**
  - Counted per instance: for TRIANGLES primitives, the index count ÷ 3, or the position count ÷ 3 when there are no indices.
  - Strips and fans count as n − 2.
  - Points and lines are skipped with a `triangles` warning.
- **Texture size:** read with glTF-Transform's `ImageUtils.getSize` (PNG, JPEG, WebP, and KTX2 once `KHR_texture_basisu` is registered through `ALL_EXTENSIONS`).
- **Units:**
  - Base car: the world bounding box must be 3.0–6.0 m along Z and 0.9–2.0 m along Y.
  - Interior and product: the largest dimension must be between 0.05 and 4.0 m.
- **Orientation** (base car): world positions must satisfy all of these:
  - `FL.x<0, FL.z<0`.
  - `FR.x>0, FR.z<0`.
  - `RL.x<0, RL.z>0`.
  - `RR.x>0, RR.z>0`.
  - Every wheel anchor has `y>0`.
- **Origin** (base car):
  - The mean z of the 4 wheel anchors must be within 2% of the wheelbase, where wheelbase = mean rear z − mean front z.
  - The bounding box's min y must be within 0.03 m of zero.
- **Khronos:** `validateBytes` from `gltf-validator`. Any `numErrors > 0` becomes one `khronos` error that quotes the first 5 messages.
- **Reading GLBs:** `NodeIO` with `ALL_EXTENSIONS`, and the `meshopt.decoder` dependency from `meshoptimizer`.

- [ ] **Step 1: Add the dependencies**

Install the @gltf-transform packages, meshoptimizer and gltf-validator as dev deps, and ktx-parse as a dev dep. All `--save-exact`.

- [ ] **Step 2: Write the fixture builders (`tests/unit/assets/fixtures.ts`)**

```ts
function makeBaseCar(o?: { scale?: number; zUp?: boolean; originAtFrontAxle?: boolean; omitAnchor?: string;
  omitMaterial?: string; triangles?: number /* default 120_000 */; texture?: { size: number; material: string } }): Document
function makeInterior(o?: { omitAnchor?: string; omitNode?: string }): Document
function makeProduct(o?: { roots?: number; triangles?: number }): Document
function toGlb(doc: Document, o?: { meshopt?: boolean; ktx2Size?: number }): Promise<Uint8Array>
```
- Base car geometry: a non-degenerate subdivided box of 4.49 × 1.37 × 1.78 m, because Khronos flags degenerate triangles.
- Wheel anchors sit at x ±0.75, y 0.32, z ±1.3655.
- PNG textures come from a minimal writer using `zlib.deflateSync` and `zlib.crc32`.
- KTX2 textures: `ktx-parse` `write()`, with `pixelWidth` and `pixelHeight` set.
- Meshopt: `reorder` + `quantize`, then `EXTMeshoptCompression` with the encoder.

- [ ] **Step 3: Write the failing validator and manifest tests**

```ts
const errs = (i: ContractIssue[]) => i.filter((x) => x.severity === 'error').map((x) => x.code)
test('a well-formed base car passes', () => expect(errs(validateDocument(makeBaseCar(), { kind: 'base-car', bytes: 1e6 }))).toEqual([]))
test('names each missing anchor', () => {
  const i = validateDocument(makeBaseCar({ omitAnchor: 'wheel_RR' }), { kind: 'base-car', bytes: 1e6 })
  expect(i).toContainEqual(expect.objectContaining({ code: 'missing-anchor', message: expect.stringContaining('wheel_RR') }))
})
test('reports a missing paint material', ...)                     → contains 'missing-material'
test('flags a base car exported in centimeters', ...)             → makeBaseCar({ scale: 100 }) contains 'units'
test('flags a Z-up base car', ...)                                → makeBaseCar({ zUp: true }) contains 'orientation'
test('flags a car whose origin is at the front axle', ...)        → contains 'origin'
test('enforces the triangle budget both ways', ...)               → 210_000 and 90_000 each contain 'triangles'
test('allows 4K textures only on paint', ...)                     → 4096 on paint ok; 4096 on trim contains 'texture-size'
test('decodes meshopt GLBs and measures KTX2 textures', async () => {
  const ok = await validateGlb(await toGlb(makeBaseCar(), { meshopt: true, ktx2Size: 2048 }), 'base-car')
  expect(errs(ok.issues).filter((c) => c !== 'khronos')).toEqual([])
  const big = await validateGlb(await toGlb(makeBaseCar(), { meshopt: true, ktx2Size: 8192 }), 'base-car')
  expect(errs(big.issues)).toContain('texture-size')
})
test('interior requires camera_driver_eye', ...)                  → contains 'missing-anchor'
test('product must have exactly one root', ...)                   → makeProduct({ roots: 2 }) contains 'root-count'
test('file size over budget', ...)                                → bytes 8_000_001 contains 'bytes'
// manifest.test.ts
test('the committed manifest parses', ...)                         → AssetManifest.parse(json of src/assets/manifest.json)
test('rejects a bad sha256 and a non-https url', ...)
```

- [ ] **Step 4: Run the tests and confirm they fail**

Run: `pnpm vitest run tests/unit/assets`
Expected: FAIL, because the modules don't exist yet.

- [ ] **Step 5: Implement the contract, validator, manifest schema and CLI**

- Implement `asset-contract.ts`, `asset-validate.ts`, `asset-manifest.ts` and `tools/validate-asset.ts`.
- Write `src/assets/manifest.json` as `{ "version": 1, "assets": {} }`.
- Make `check-data` parse the manifest too.

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `pnpm vitest run tests/unit/assets`
Expected: PASS.

- [ ] **Step 7: Python `validate` stage, test first**

```python
def test_missing_export_fails_with_hint(tmp_path):
    r = validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path))
    assert not r.ok and "run --stage export first" in r.messages[0]

def test_passes_kind_and_maps_issues(tmp_path, monkeypatch):
    glb = tmp_path / "assets/e46-coupe-body/export/e46-coupe-body.glb"; glb.parent.mkdir(parents=True); glb.write_bytes(b"x")
    calls = []
    def fake(cmd):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, json.dumps({"ok": False, "issues": [
            {"code": "units", "severity": "error", "message": "Z length 449 m"}]}), "")
    monkeypatch.setattr(validate_mod, "_run", fake)
    r = validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path))
    assert not r.ok and r.messages == ["ERROR units: Z length 449 m"]
    assert calls[0][-3:] == ["--kind", "base-car", "--json"]

def test_validate_is_registered():
    assert "validate" in REGISTRY
```
Run: `cd pipeline && uv run pytest tests/test_validate_stage.py -q`. It fails first. Implement the stage, then run it again.
Expected: `3 passed`.

- [ ] **Step 8: Write `docs/standards/3d-assets.md`**

Cover:
- Spec section 9.6, verbatim: units and axes, names, budgets.
- How each check is measured (the list above).
- "Every change is a script in `pipeline/`. No unscripted Blender edits."
- No logos, badges or roundels, in meshes or in textures.
- Manifest fields and license metadata.
- How to run `pnpm validate-asset` and `pipeline run <asset> --stage validate`.

- [ ] **Step 9: Land**

Run: `pnpm check`
Expected: green.
Follow the landing procedure with the `contract` and `3d` labels, and `Closes` the Phase 0 step 4 issue.

---

### Task 7: `AGENTS.md`, standards, contributing, PR template and spend ledger

**Files:**
- Create: `AGENTS.md`, `CLAUDE.md` (symlink), `CONTRIBUTING.md`, `.github/pull_request_template.md`, `.mcp.json`
- Create: `docs/standards/{code,testing,legal}.md`, `docs/spend-ledger.md`, `docs/README.md`
- Test: `tests/unit/repo-hygiene.test.ts`

**Interfaces:**
- Consumes every script and path from Tasks 1–6.
- Produces the agent entry point. Plan 0B and Phase 1 agents read `AGENTS.md` first.

- [ ] **Step 1: Write the failing hygiene tests**

```ts
const tracked = execSync('git ls-files', { encoding: 'utf8' }).split('\n').filter(Boolean)
test('CLAUDE.md is a symlink to AGENTS.md', () => expect(readlinkSync('CLAUDE.md')).toBe('AGENTS.md'))
test('no images or GLBs are tracked outside allowed folders', () => {
  const media = tracked.filter((f) => /\.(jpe?g|png|webp|avif|heic|glb|gltf|blend)$/i.test(f))
  expect(media.filter((f) => !/^(public\/|tests\/fixtures\/)/.test(f))).toEqual([])
})
test('no env files are tracked', () => expect(tracked.filter((f) => /(^|\/)\.env/.test(f))).toEqual([]))
test('no forbidden secret names appear in tracked config', () => {
  for (const f of tracked.filter((f) => /\.(json|jsonc|toml|ya?ml|sh)$/.test(f)))
    expect(readFileSync(f, 'utf8')).not.toMatch(/\b(ANTHROPIC|OPENAI)_API_KEY\b/)
})
```
Run: `pnpm vitest run tests/unit/repo-hygiene.test.ts`
Expected: FAIL on the symlink test.

- [ ] **Step 2: Write `AGENTS.md` (150 lines at most) and create the symlink**

Sections, in this order:
1. **What this is:** 2 lines, plus a link to the spec.
2. **Commands:** a table covering `pnpm check`, `pnpm test`, `pnpm e2e`, `pnpm build`, `pnpm validate-asset`, `node tools/check-data.ts data`, `pipeline run <asset> --stage <name>` and `pipeline stages`. Also the background dev server and JSON-log flags exactly as `pnpm astro dev --help` lists them.
3. **Layout:** spec section 14, updated to match the real tree.
4. **Hard rules:**
   - Every product rule and hygiene rule from Global Constraints.
   - Contracts (`src/data/schemas.ts`, `src/lib/asset-contract.ts`, `docs/standards/3d-assets.md`) change only in a dedicated `contract`-labeled PR that both lanes rebase onto.
   - Paid API calls need a session-approved cap and a ledger row before the call.
   - Reference photos never enter the repo.
5. **Workflow:**
   - Branch and PR. Each PR carries the CI checks and screenshots for UI or 3D changes.
   - Review: Opus, plus Codex via codex-review.
   - Data PRs also get the data verifier. `safety` PRs wait for the user's spot-check.
   - Zero required approvals, and why (solo maintainer).
6. **Model routing:** the spec section 12.1 table, verbatim.
7. **Where docs live.**

Then run `ln -s AGENTS.md CLAUDE.md`.

- [ ] **Step 3: Write the standards and supporting files**

- `code.md`: TS rules (strictest, erasable syntax only, explicit `.ts` imports); pure logic in `src/lib` with unit tests; islands use `client:only="react"`; small focused files; Python rules (ruff, strict pyright, Typer, side effects behind injectable module functions).
- `testing.md`: spec section 10, the one-command-per-question table, fixture conventions (`fixture-` IDs, programmatic GLBs), and that visual baselines arrive in Phase 1.
- `legal.md`:
  - Trademark use.
  - The list of forbidden marks: roundel, M logo, badges, wheel center-cap logos.
  - The exact notice copy.
  - The reference-photo policy.
  - Generator license gates: Hunyuan 2.x is experiment-only (its license excludes the EU, UK and South Korea), and Rodin's terms must be checked before publishing.
  - The licenses, and the credits requirement.
- `CONTRIBUTING.md`: setup (`mise install`, `pnpm install`, `uv sync --project pipeline`), then the same rules in short form.
- PR template:
  - Sections: Summary, Lane, Checks, Screenshots, Data sources (tiers), Spend (ledger row).
  - Checkboxes: "No store links, logos or secrets" and "Opus + Codex review done".
- `.mcp.json`:
  - `astro-docs`: http `https://mcp.docs.astro.build/mcp`.
  - `cloudflare-docs`: http `https://docs.mcp.cloudflare.com/mcp`.
  - `playwright`: `pnpm dlx @playwright/mcp@<exact version from npm view @playwright/mcp version>`.
- `docs/spend-ledger.md`:
  - Columns: Date | Session cap | Service | Purpose | Units | Cost (USD) | Running total / cap.
  - First row: `2026-11-23 | $50 (Phase 0 spike, 3D generation) | — | cap approved by the user | — | 0.00 | 0.00 / 50.00`.
- `docs/README.md`: an index of the docs.

- [ ] **Step 4: Run the hygiene tests and the full check**

Run: `pnpm vitest run tests/unit/repo-hygiene.test.ts && pnpm check`
Expected: PASS and green.

- [ ] **Step 5: Land**

Follow the landing procedure with the `docs` label, and `Closes` the Phase 0 step 3 issue jointly with Task 8.

---

### Task 8: ADRs

**Files:**
- Create: `docs/decisions/README.md` (the index) and `docs/decisions/0001` … `0008` below.

**Interfaces:** none.

Each ADR is 60 lines at most, with this structure:
- `# NNNN. Title`
- `- **Status:** Accepted 2026-11-23`
- `- **Date:** 2026-11-23`
- `## Context`
- `## Decision`
- `## Alternatives considered`, taken from spec section 5 where it covers them.
- `## Consequences`

| ADR | Decision |
|---|---|
| 0001 | Astro static site on Workers static assets. No adapter until Phase 2's dynamic route. Deploys and PR previews from GitHub Actions (ledger R8), with Cloudflare tokens minted through the API, one per purpose (R9). TypeScript split: root `typescript` 6.0.3 so `astro check` runs, and 7.0.2 as the alias `typescript-7` for `tsc` (R10). |
| 0002 | three.js WebGPURenderer with WebGL2 fallback and TSL. R3F 9 now, v10 once it's beta. Path-traced photo mode in its own canvas. |
| 0003 | YAML data validated by Zod, shared by Astro and `check-data`. The source tiers and verification rule. CC BY-SA 4.0 for data. |
| 0004 | Bodies AI-generated from curated online photos, gated by the Phase 0 spike. Buying licensed models is a fallback offered to the user, never switched to automatically. |
| 0005 | The asset contract: frame (meters, Y up, nose toward −Z, origin on the ground at mid-wheelbase), names and budgets. |
| 0006 | Pipeline in Python with uv (bpy and image tools). The asset validator in TS (glTF-Transform). |
| 0007 | Agent roles and model routing, the review gates, and zero required approvals for a solo maintainer. |
| 0008 | No commerce, no store links, no logos. Enforced by `check:links` and the standards. |

- [ ] **Step 1: Write the 8 ADRs and the index**

- [ ] **Step 2: Verify the structure**

Run: `ls docs/decisions/0*.md | wc -l && grep -L '^- \*\*Status:\*\* Accepted' docs/decisions/0*.md`
Expected: `8`, and no files listed.

- [ ] **Step 3: Land**

Follow the landing procedure with the `docs` label, and `Closes` the Phase 0 step 3 issue.

---

## After this plan

- **Plan 0B** (photo tooling) runs in its own worktree from Task 3 on.
- **Plan 0C** (spike and bake-off) gets written once the user has collected photos with 0B's tooling, because the collected view sets decide how the spike runs.
- Phase 0 step 7 (the Phase 1 spend cap) is asked after the spike report.
