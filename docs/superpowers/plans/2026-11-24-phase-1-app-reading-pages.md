# Phase 1 App Lane, Plan 1: Reading Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The read side of the site, on the B2 "pit garage" design: home, the generation page (specs, variants, hero drawing), known issues (list and detail), maintenance, the used-buyer checklist and `/about`. Issues, maintenance and the checklist filter and label by market and by model year.

**Architecture:**
- Static Astro pages over the content collections. Every rule that decides what a page shows (markets, model years, the filter, intervals, unverified marks, costs, citations, checklist order) is a pure function in `src/lib/`, unit-tested against fixtures. Components stay thin.
- The B2 tokens move into the Tailwind theme once, in `src/styles/`, and fonts are self-hosted through Astro's Fonts API.
- Two builds, two Playwright projects. The `real` project serves the site built from `data/`. The `fixture` project serves a second build from a purpose-built data set, `tests/fixtures/site-data/`, chosen through the `SITE_DATA_DIR` setting. The real build proves the pages survive whatever data exists (zero maintenance items today, nine with PR #41). The fixture build proves the rules the real data cannot exercise: filters, ordering, gap notices, cost order, the `inspection-i` label.
- Page e2e tests are data-driven. They read the data of the build they run against through `loadDataSet` and assert what each page shows for each entry.

**Tech Stack:** Astro 7.4.13 (static, content collections, Fonts API), Tailwind 4.3.5, TypeScript 7.0.2 via `pnpm typecheck`, Vitest 5.1.1, Playwright 1.65.1, Biome 2.6.8, plus one new dev dependency, `@axe-core/playwright` 4.14.0 (Task 2). No React in this plan: it has no island.

**Spec:** `docs/superpowers/specs/2026-11-23-m3-tool-design.md` (sections 1, 2, 7.2, 7.3, 7.6, 10, 15, 17). Also `AGENTS.md` (it wins over the spec), `docs/standards/{code,testing,data,legal}.md` and `docs/design/` (B2 tokens and the mock-up `b2-garage.html`).

## Roadmap: the app lane in five plans

The spec's Phase 1 app lane has five subsystems that share only components and `src/lib`. Each plan below produces working, testable software on its own. This file is Plan 1.

1. **Reading pages (this plan).** B2 tokens, self-hosted fonts, the site shell and its route-wide gates, the fixture build and CI screenshots; home, `/[gen]/` (specs, variants, hero drawing), known issues (list and detail), maintenance, buyer checklist, and `/about` with a derived data-sources list. Needs: the data on `main`, including the optional `modelYears` that the data lane's `contract` PR #45 added to `MaintenanceItem` and `KnownIssue` and merged on 2026-11-24 (this plan writes no schema change, and no task waits for anything else).
2. **Prices and mods.** `src/lib/price.ts` (90-day range, stale after 60 days, generic-tier price computed from the category's real products), then `/[gen]/mods/` and `/[gen]/mods/[part]` (seller and checked date as text, tier badge, "3D look approximate", labor marked "estimated", a part with no price shows "no price recorded"). Needs: Plan 1's components and fixture build (it adds parts and prices to `tests/fixtures/site-data/`), parts data from the data lane, prices from the scraping lane.
3. **Build logic.** `src/lib/rules.ts`, `cost.ts` and `codec.ts` with unit tests, including a fixture for every saved link version. Pure TypeScript, no UI. Needs: the schemas, and `price.ts` (Plan 2, Task 1). Runs in parallel with the rest of Plan 2.
4. **Build sheet and share links.** `/[gen]/build` as one `client:only="react"` island (zustand, the B2 work order, fitment reasons, rate, tax and DIY, empty and first-visit states), with the build in the URL hash through the codec. No 3D. Needs: Plans 2 and 3. Its page specs run under both projects.
5. **Search and beta readiness.** Pagefind UI and `data-pagefind-body`, sitemap and robots, Cloudflare Web Analytics, and the checklist for flipping `PUBLIC_INDEXABLE`. Needs: Plans 1 to 4, and the user's domain for the final flip.

**Why this order.** The spec's Phase 1 exit is a public beta of the whole text tool, so no plan can ship alone to the public. Reading pages go first because their data exists now, they need no prices and no parts, and they build the components, tokens, fixture build and gates Plans 2 to 4 reuse. Build logic is pure and could start first, but its only input that does not exist yet is price data, so it follows `price.ts` instead.

**Gated, in no plan here:** the hero outline swap waits for the 3D spike, and the Gearwell rename waits for the domain. Task 1 puts the site name in one constant (`SITE_NAME`) and Task 9 puts the hero outline in one file, so each is a one-place change later.

## Global Constraints

Every task's requirements include this section. Quoted lines are copied from `AGENTS.md`, the spec and `docs/standards/data.md` (for model years, from the contract PR #45's `data.md`, merged).

**Rulings applied (R87 answers to this plan's open questions, and R88)**
1. The buyer checklist has two ordered groups. Known problems come first, ordered by frequency, then by higher sourced shop cost, with no-cost last. Service history comes second (Tasks 15, 16).
2. Filters default to All markets and All model years. Without JavaScript everything shows, with market and model-year chips. An empty selection shows a "gap in the data" notice (Tasks 12, 14, 16).
3. `modelYears` is `[from, to]`, both required (R88): inclusive, inside the generation's `years` exactly, with no `last + 1`. There is no open-ended form and nothing is clamped. The year choices are the generation's `years`. An entry with no `modelYears` is labelled "All model years" and shows under every year choice.
4. Every route has a trailing slash: `trailingSlash: 'always'` (Tasks 1, 2).
5. A `zero-cost` check goes in a separate data-lane PR. This plan only guards the display (Task 5).
6. Fonts are self-hosted through Astro's Fonts API, and e2e fails any cross-origin request (Tasks 1, 2).
7. Screenshots are captured in CI as a run artifact (Task 4).
8. Variants render as `<details>` panels on `/[gen]/`, with a mark on each unverified value (Task 8).
9. The hero caption says the outline is generic, and its dimension lines come from the data (Task 9).
10. The contract PR (#45, which adds `modelYears`) is merged, so no task waits for it.

**Product rules (AGENTS.md, "Hard rules")**
- "No affiliate, ad or store links of any kind. A price observation's `url` is never rendered as a link. A source's `url` is a link only when `isCitationLinkable` says so (a short list of non-commercial hosts). `check:links` fails the build on an external link outside its allowlist."
- "No BMW logos or badges anywhere: UI, models or textures, including the steering-wheel roundel." The design adds: no M stripes, and no car photos in the UI.
- "The footer and `/about` carry this notice, word for word: `Independent fan project. Not affiliated with, endorsed by, or sponsored by BMW AG. BMW and M3 are trademarks of BMW AG, used here only to describe the cars.`"
- "The site is `noindex` until the public beta. Pages emit `<meta name="robots" content="noindex">` unless `PUBLIC_INDEXABLE=true` at build time."
- "Every price has a seller and a checked date. Safety advice (maintenance intervals, fixes) never rests on a forum post alone: it needs a Tier 1 or Tier 2 source, and `check:data` enforces it." This plan renders no price, so the first rule binds Plans 2 and 4. The second binds every page here that shows a service interval or a fix.
- "IDs are kebab-case (`^[a-z0-9]+(-[a-z0-9]+)*$`), stable and never reused. A data file's stem equals its `id`." Entry ids are in URLs, so never rewrite one.

**Data display rules (spec 7.3 and 7.6, `docs/standards/data.md`)**
- "With no sourced cost the site shows "no sourced cost", never zero."
- "Tier 3 alone is enough for symptoms and "how common". The entry stays `verified: false`, and the UI shows an "unverified" badge."
- "Pages that render these fields show a per-value "unverified" marker, taken from this field and not from the comments. A value is covered, and gets the marker, when its own path is listed, or the path of an object or element above it." (`unverified` on a generation or variant.) This plan's reading: every place a covered value is rendered carries its own mark, including repeats (a variant's summary row and its panel, the hero and the drawer, the home card).
- "A page that shows an item's triggers shows an `inspection-i` item as due at every inspection, not only at Inspection I."
- "`markets` names the markets a maintenance item's or a known issue's sources speak for: a non-empty list of `us` or `euro`, each at most once." Spec 7.3: "(`us`, `euro`, or every market when left out)". This plan's reading: `markets` decides which market an entry is shown for, and an entry with no `markets` is shown for both.
- "`modelYears` names the model years a maintenance item's or a known issue's sources speak for: `[from, to]`, both inclusive, such as `[2001, 2003]`. One year is `[2004, 2004]`. Both ends are always given, and there is no open-ended form: "from 2004 on" for a generation that ends in 2006 is `[2004, 2006]`." "The range lies inside the generation's `years`, with nothing past either end (ruling R88). The generation's `years` are also the year choices the site offers." `check-data` reports a range outside as `model-years-outside-generation`. "Leave `modelYears` out only when the sources cover every model year of the generation, meaning every year in its `years`." This plan's reading: `modelYears` decides which model years an entry is shown for. The E46 coolant (BMW changed it mid-run) is two items, `[2001, 2003]` and `[2004, 2006]`, each shown only for its own years.
- "A source renders as a citation: its publisher, title and accessed date, always as text. Its `url` is a link only when the host is on `CITATION_HOSTS` (`archive.org`, `web.archive.org`, `newsroom.bmwgroup.com`, `en.wikipedia.org`, `commons.wikimedia.org`), which `isCitationLinkable` tests. Any other URL is not linked, and a Tier 2 retailer never is."
- Dates are calendar dates, shown as `YYYY-MM-DD`. A frequency is `very-common` in YAML and "Very common" on the page, never the slug.

**Design (`docs/design/README.md`)**
- Direction B2: dark only, spec groups as tool-chest drawers, the key figures on a yellow pit board, a known issue as a tech card on a pegboard. Big Shoulders Display for headings, Geist for text, tabular numerals.
- WCAG AA contrast, a visible focus ring on every stop, 44 px tap targets on phone (390 px), and every state the mock-up settles (empty, stale, unverified).
- No colour literal outside `src/styles/tokens.css`: use tokens.
- Run each UI task through the `impeccable` skill before its commit (spec section 17). Its pass criterion is the gates below plus the CI screenshots: `a11y.spec.ts` and `mobile.spec.ts` are green for the new routes, and the orchestrator compares the artifact with the mock-up at review. No pixel assertion exists.

**Code (AGENTS.md, `docs/standards/code.md`)**
- `tsconfig` extends `astro/tsconfigs/strictest`, so `exactOptionalPropertyTypes` is on: write optional parameters and fields as `x?: T | undefined`. Imports use explicit `.ts` extensions, `import type` for types, no enums, no namespaces. Run `pnpm typecheck`, never a bare `tsc`.
- Pure logic goes in `src/lib` with a unit test, written first. Components call into `src/lib` and render the result.
- Biome formats: single quotes, no semicolons, 100 columns. Run `pnpm exec biome check --write <paths>` before a commit. Pin dependencies exactly (`--save-exact`) and add one in the task that first uses it.
- Astro scoped styles do not reach slot content, so a rule that targets content a page passes into a component uses `:global()`.
- Contract files (`src/data/schemas.ts`, `src/data/unverified.ts`, `src/lib/asset-contract.ts`, `docs/standards/3d-assets.md`) "change only in a dedicated PR labeled `contract`". This plan changes none. If a task finds it needs one, stop and raise a `contract` PR first. `astro.config.ts`, `src/content.config.ts`, `biome.json`, `playwright.config.ts` and `.github/workflows/ci.yml` are not contract files.
- Each task's tests add the facts they need to the fixture set (`tests/fixtures/site-data/`, Task 3) in Step 1. Fixture ids start with `fixture-`, except the generation `e46` and its variants, as in `tests/fixtures/data/valid`. Never use an `M3_` name for a setting that is not a secret: the prefix is for secrets (`SITE_DATA_DIR`, `SITE_OUT_DIR`, `SHOOT`).

**Out of scope:** the 3D lane, the hero outline swap, the Gearwell rename, scraping or price collection, and writing data entries to `data/`.

**Workflow (AGENTS.md)**
- "Run `pnpm check` and `pnpm e2e` green, push, and open a PR from the template. Say `Closes #<issue>`. UI and 3D changes carry before-and-after screenshots." The orchestrator opens one issue per landing group before dispatch, and each group's PR says `Closes #<that issue>`. Commits use Conventional Commits, staged by path, never `git add -A`. The only trailer is `Co-Authored-By:`, with no `Claude-Session` trailer and no session URL.
- Every subagent gets a pinned model. Implementers are Sonnet 5.5. Review is Sonnet plus a Codex second opinion through `codex-review` when the orchestrator is Opus.

**Landing procedure.** Tasks land in six groups, one PR each, in order. Work on branch `feat/p1-<group>` in its own worktree (`git worktree add ../m3-tool.worktrees/p1-<group> -b feat/p1-<group> origin/main`, then `pnpm install` and `uv sync --project pipeline`).

| Group | Tasks | PR title |
|---|---|---|
| A | 1 to 4 | `feat(site): B2 tokens, shell, fixture build and CI screenshots` |
| B | 5 to 7 | `feat(site): display libraries and the generation page` |
| C | 8 to 10 | `feat(site): variants, hero drawing and the home page` |
| D | 11 to 12 | `feat(site): known issues pages and the market and year filter` |
| E | 13 to 16 | `feat(site): maintenance schedule and buyer checklist` |
| F | 17 to 18 | `feat(site): about page data sources and docs` |

Before a PR opens: `pnpm check` exits 0, then `pnpm build && pnpm build:fixture && pnpm e2e` exits 0. Screenshots never enter the repo (`tests/unit/repo-hygiene.test.ts` forbids tracked images, and no hand upload exists). CI captures them (Task 4): the `e2e` job uploads one `screenshots` run artifact holding `before/` (production), `after/` (this PR's real build) and `after-fixture/` (this PR's fixture build). The PR body links that run artifact and the PR's preview URL. A route that does not exist in production has no before: the artifact says so by omission.

## Review Focus

Inputs and conditions the spec implies and no happy path covers, most likely first. Each line has a named test in its owning task.

1. **A selection with no sourced entries, by market or by model year.** Every maintenance item in PR #41 is `markets: [us]`, so the Euro view of the maintenance page and the checklist is empty, and a model year can be empty too. Expect a visible "gap in the data" notice for that selection, in each group, never a blank list that reads as "nothing is due". One empty group must not remove the controls its sibling group needs. Task 12 `filterStatus names the gap when a selection shows nothing`; Task 14 `a selection with no sourced items says so`; Task 16 `a selection with no sourced entries names the gap in each group`.
2. **A source URL on a retailer, CDN or forum host rendered as a link.** The data cites BMW bulletins copied to `cdn.shopify.com`, and publishers such as PistonHeads. Their URLs render as text. A `web.archive.org` snapshot of the same file is on `CITATION_HOSTS`, so it renders as a link, and a page must not unlink it. Task 6 `no source in data/ is linked unless isCitationLinkable allows it`; Task 7 `source anchors are exactly the linkable sources`.
3. **An `inspection-i` item shown as due at Inspection I only.** It is due at every inspection, because Inspection II repeats it. Task 13 `inspection-i reads as every inspection`; Task 14 `inspection-i rows say every inspection`; Task 16 `a service-history row for inspection-i says every inspection`.
4. **A flag, marker or value misread.** `verified: false` shown as verified (a maintenance row in the checklist included), an `unverified` path template that puts the front offset's mark on the rear value, a flagged element whose other fields are printed with no mark at all, a repeat that loses its mark, `very-common` leaking as a slug, an absent or `[0, 0]` cost shown as `$0`. Task 5 `describeCost never shows zero`; Task 7 and Task 8 `expectMarks`, checked against an inventory the test builds independently of the page: `every rendered value is marked exactly when its path is covered`, `each mark sits on the value its path names` and, in `marks-selftest.spec.ts`, `a value printed without a Mark fails the inventory`; Task 11 `the verified chip follows the flag` and `frequency never shows as a slug`.
5. **Model-year scoping read wrongly.** A range read as from-only, an end year dropped (off by one at `to`), the split coolant items both showing for one year, an entry with no `modelYears` hidden once a year is chosen. Task 5 `appliesToYear is inclusive at both ends`; Task 12 `isVisible: a year outside the entry's years hides it`; Task 14 `selecting a model year hides exactly the rows that do not apply`.

## File structure

```
src/styles/{tokens,theme,global}.css   B2 tokens verbatim; Tailwind aliases; base rules              (Task 1)
astro.config.ts, src/content.config.ts  fonts, trailingSlash, SITE_DATA_DIR, SITE_OUT_DIR, cacheDir    (Tasks 1, 3)
src/lib/{notice,site}.ts               NOTICE; SITE_NAME, pageTitle                                    (Task 1)
src/lib/route-list.ts                  routesFor(set), keyRoutes(set)                                  (Task 2)
src/layouts/Base.astro, src/components/{SiteNav,SiteFooter}.astro                                      (Task 2)
tests/e2e/test.ts                  `test` with `dataSet` and the cross-origin guard                (Task 2)
tests/e2e/shared/*.spec.ts             run on both builds                                              (Tasks 2, 7 to 17)
tests/e2e/fixture-only/*.spec.ts            run on the fixture build only                                   (Tasks 12, 14, 16)
tests/fixtures/site-data/              the e2e data set; dist-fixture/ is its build                    (Task 3)
tests/shots/shoot.spec.ts              CI screenshot capture (SHOOT=1)                                 (Task 4)
src/lib/{format,money,routes,markets,model-years}.ts                                                   (Task 5)
src/lib/{citations,unverified-marks}.ts, tests/support/value-at.ts                                     (Task 6)
src/data/site.ts                       typed loaders over the content collections                      (Tasks 7, 17)
src/components/{Drawer,Tier,Mark,SourceList,GenerationNav}.astro, tests/e2e/{marks,inventories}.ts,
  tests/e2e/shared/marks-selftest.spec.ts                                                              (Task 7)
src/pages/[gen]/index.astro            generation page                                                 (Tasks 7 to 9)
src/components/VariantPanel.astro                                                                      (Task 8)
src/lib/hero-layout.ts, src/components/hero/coupe-outline.ts, src/components/{HeroDrawing,PitBoard}.astro (Task 9)
src/pages/index.astro                  pick a generation                                               (Task 10)
src/components/{Chip,CostBox}.astro, src/pages/[gen]/issues/[issue].astro                              (Task 11)
src/lib/{issue-order,filters}.ts, src/components/FilterScope.astro, tests/e2e/filter.ts,
  src/pages/[gen]/issues/index.astro                                                                   (Task 12)
src/lib/intervals.ts                   describeInterval, compareSchedule, TRIGGER_LABELS               (Task 13)
src/pages/[gen]/maintenance/index.astro                                                                (Task 14)
src/lib/checklist.ts, src/pages/[gen]/buying/index.astro                                               (Tasks 15, 16)
src/lib/data-sources.ts, src/pages/about.astro                                                         (Task 17)
```

## Execution map

| Task | Needs | Parallel with |
|---|---|---|
| 1 Tokens, fonts, constants, config | none | none |
| 2 Shell and route-wide gates | 1 | 5, 6 |
| 3 Fixture data set and second build | 2 | 5, 6 |
| 4 CI screenshots | 3 | 5, 6 |
| 5 Display libs | 1 | 2, 3, 4 |
| 6 Citation, unverified and value libs | 5 | 2, 3, 4 |
| 7 Generation page: specs | 2, 3, 5, 6 | none |
| 8 Variants | 7 | 10 |
| 9 Hero and pit board | 7, 8 (both edit `[gen]/index.astro`) | 10 |
| 10 Home page | 5, 7 | 8, 9 |
| 11 Issue detail | 3, 5, 6, 7 | 13 |
| 12 Issues list and filter | 11 | 13 |
| 13 Interval lib | 5 | 11, 12 |
| 14 Maintenance page | 12, 13 | 15 |
| 15 Checklist lib | 5, 12, 13 | 14 |
| 16 Checklist page | 11, 12, 14, 15 | none |
| 17 About: data sources | 6, 7 | 13 to 16 |
| 18 Docs and final verification | all | none |

Tasks that run in parallel can both touch `src/lib/routes.ts`, `src/lib/route-list.ts` or the e2e files: merge one at a time and rebase between.

---

### Task 1: Design tokens, fonts, constants and config

**Files:**
- Create: `src/styles/tokens.css`, `src/styles/theme.css`, `src/lib/notice.ts`, `src/lib/site.ts`, `tests/unit/helpers/contrast.ts`
- Modify: `src/styles/global.css`, `astro.config.ts`, `biome.json`
- Test: `tests/unit/notice.test.ts`, `tests/unit/site.test.ts`, `tests/unit/tokens.test.ts`

**Interfaces:**
- Produces: `NOTICE: string` (`src/lib/notice.ts`); `SITE_NAME = 'm3-tool'` and `pageTitle(title?: string | undefined): string` (`src/lib/site.ts`); CSS custom properties from `tokens.css`; Tailwind utilities (`bg-floor`, `text-muted`, `border-line`) from `theme.css`; the font variables `--font-display` and `--font-sans`, provided by Astro's `<Font>` component (Task 2); `trailingSlash: 'always'`.
- Produces for tests: `contrastRatio(foreground: string, background: string): number` (WCAG 2.x, hex inputs).

- [ ] **Step 1: Write the failing tests**

```ts
// notice.test.ts: the notice is pinned to the rulebook, not just to itself
test('NOTICE is the exact text in AGENTS.md and the legal standard', () => {
  expect(NOTICE).toBe('Independent fan project. Not affiliated with, endorsed by, or sponsored by BMW AG. BMW and M3 are trademarks of BMW AG, used here only to describe the cars.')
  for (const file of ['AGENTS.md', 'docs/standards/legal.md']) expect(readFileSync(file, 'utf8')).toContain(NOTICE)
})
// site.test.ts
expect(pageTitle()).toBe('m3-tool'); expect(pageTitle('About')).toBe('About · m3-tool'); expect(pageTitle('   ')).toBe('m3-tool')
```

`tokens.test.ts` reads `src/styles/tokens.css` and checks:
- `contrastRatio('#000000', '#ffffff')` is 21.
- Text pairs, each at least 4.5: `--text`, `--muted`, `--dim` on `--floor`; `--muted` and `--dim` on `--steel-2`; `--board-ink` on `--board`; `--board` on `--floor`; `--canary-ink` on `--canary`; `--canary-muted` and `--stale` on `--canary` and on `--canary-2`; `--hot` on `--floor` and on `--steel-2`. Non-text: `--edge` on `--floor` is at least 3.
- `no raw colour literals outside tokens.css`: no match of `(?<!&)#[0-9a-fA-F]{3,8}\b` (the lookbehind keeps a decimal entity such as `&#8211;` out), `rgb(`, `rgba(`, `hsl(`, `hwb(`, `oklch(` in `src/{pages,components,layouts,styles}/**` except `tokens.css`.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test tests/unit/notice.test.ts tests/unit/site.test.ts tests/unit/tokens.test.ts`
Expected: FAIL, modules and `tokens.css` not found.

- [ ] **Step 3: Implement**
- `notice.ts` and `site.ts` as specified.
- `tokens.css`: one `:root { ... }` block copied from `docs/design/b2-garage.html` lines 17 to 98, minus `--font-display` and `--font-sans` (Astro generates those with fallbacks). Keep `color-scheme: dark`.
- `theme.css`: `@theme inline { --color-floor: var(--floor); ... }`, one alias per colour token, plus `--radius-*` and `--shadow-*`. Spacing and the type scale stay plain custom properties.
- `global.css`: `@import "tailwindcss"; @import "./tokens.css"; @import "./theme.css";`, then the mock-up's Base block (lines 100 to 118) inside `@layer base`, so Tailwind utilities win over the bare `a` colour, and the `prefers-reduced-motion` block (lines 602 to 607). Add no `[hidden]` rule: Tailwind's preflight already hides `[hidden]` elements with `!important`.
- `biome.json`: set `css.parser.tailwindDirectives` to `true`, so `@theme` parses.
- `astro.config.ts`: `trailingSlash: 'always'`, `fontProviders` in the `astro/config` import, and this `fonts` entry (checked on 2026-11-24: it builds and emits both families as `/_astro/fonts/*.woff2`):

```ts
fonts: [
  { provider: fontProviders.fontsource(), name: 'Big Shoulders Display', cssVariable: '--font-display',
    weights: ['600 900'], styles: ['normal'], fallbacks: ['Arial Narrow', 'sans-serif'] },
  { provider: fontProviders.fontsource(), name: 'Geist', cssVariable: '--font-sans',
    weights: ['400 700'], styles: ['normal'], fallbacks: ['system-ui', 'sans-serif'] },
],
```

The build now needs network at build time for the Fontsource files. If the CDN is down, `pnpm build` fails: rerun it, and never vendor a copy to work around it.

- [ ] **Step 4: Format and verify**

Run: `pnpm exec biome check --write src/styles biome.json && pnpm test tests/unit/notice.test.ts tests/unit/site.test.ts tests/unit/tokens.test.ts`
Expected: exit 0, PASS.

- [ ] **Step 5: One-off check that the lift is verbatim**

Run: `diff <(sed -n '17,98p' docs/design/b2-garage.html | grep -E '^\s+--' | sort) <(grep -E '^\s+--' src/styles/tokens.css | sort)`
Expected: the only differences are the two `--font-*` lines, present only on the left (custom properties stay one per line after formatting). A one-time check, not a test: the design README makes the theme the source after the lift.

- [ ] **Step 6: Typecheck, build and commit**

Run: `pnpm typecheck && pnpm lint && pnpm build`
Expected: exit 0.

```bash
git add src/styles src/lib/notice.ts src/lib/site.ts astro.config.ts biome.json tests/unit/notice.test.ts tests/unit/site.test.ts tests/unit/tokens.test.ts tests/unit/helpers/contrast.ts
git commit -m "feat(site): B2 tokens, self-hosted font config and shared constants"
```

---

### Task 2: Site shell and route-wide gates

**Files:**
- Create: `src/lib/route-list.ts`, `src/components/SiteNav.astro`, `tests/unit/route-list.test.ts`, `tests/e2e/test.ts`, `tests/e2e/shared/site.spec.ts`, `tests/e2e/shared/a11y.spec.ts`, `tests/e2e/shared/mobile.spec.ts`
- Modify: `src/layouts/Base.astro`, `src/components/SiteFooter.astro`, `src/pages/index.astro`, `src/pages/about.astro`, `src/pages/404.astro`, `playwright.config.ts`, `package.json` and `pnpm-lock.yaml`
- Delete: `tests/e2e/smoke.spec.ts` (its cases move into `site.spec.ts`)

**Interfaces:**
- Consumes: Task 1.
- Produces: `Base.astro` with props `{ title?: string | undefined; description?: string | undefined }` (it builds `<title>` with `pageTitle`), a skip link to `#main`, the sticky top bar, `<main id="main">`, the footer, and `<meta name="robots" content="noindex">` unless `PUBLIC_INDEXABLE === 'true'`.
- Produces (`route-list.ts`): `routesFor(set: DataSet): string[]`, every route of the site for a data set, each with a trailing slash. It starts as `['/', '/about/']`, and each page task adds its routes and extends `route-list.test.ts`. `keyRoutes(set)` is added in Task 4.
- Produces (`tests/e2e/test.ts`): `test` and `expect`, where `test` adds the fixture `dataSet: DataSet` (loaded from `testInfo.project.metadata.dataDir`, cached per directory) and replaces `page` with one that fails the test at teardown on any request to another origin (a `data:` URL is fine) and on any `requestfailed` except `net::ERR_ABORTED` (what a navigation that leaves a page before it finishes loading produces: specs wait for load before they leave a page). Every spec imports from this file, except `tests/shots/shoot.spec.ts` (Task 4), which imports `@playwright/test` directly: the `shots` project has no `baseURL`, and its "before" visit is to production.
- Playwright: for now one project, `real` (`metadata.dataDir: 'data'`), `testMatch` `shared/**`. Task 3 adds the second.
- Dependency: `@axe-core/playwright` 4.14.0 (4.14.1 is under three days old, and Renovate waits three days).

- [ ] **Step 1: Write the failing tests.** Each invariant is one test that loops `routesFor(dataSet)` inside `test.step(route, ...)`, so a later page is covered the moment it registers.
  - `site.spec.ts`:
    - `footer carries the notice word for word`: `getByRole('contentinfo')` `toContainText(NOTICE)`, and `/about/` `main` too.
    - `every route is noindex`; `no route renders an img`; `every route has exactly one h1`.
    - `unknown paths return the 404 page`, at `/no-such-page/` with the slash: under `trailingSlash: 'always'` preview answers `/no-such-page` with Astro's own message, not the site's 404 page.
    - `the skip link is the first focus stop and targets main`.
    - `the fonts are self-hosted`: at least one `/_astro/fonts/*.woff2` request.
    - `every internal link has a trailing slash and resolves`: every same-origin `a[href]` except fragments, `/_astro/` and file links ends in `/` and answers 200 through `request.get`. This is the only check that a dead internal link fails, because `check:links` never follows one.
    - `every external anchor passes isAllowedHref`.
  - `a11y.spec.ts`: for each route, `AxeBuilder` with tags `wcag2a`, `wcag2aa`, `wcag21aa` reports no violations.
  - `mobile.spec.ts` at 390 x 844: for each route, no sideways scroll (`scrollWidth <= clientWidth`); then open every disclosure (`document.querySelectorAll('details').forEach((d) => (d.open = true))`), and every visible `summary`, `nav a`, `[data-filter-scope] label` and `[data-filter-scope] select` is at least 44 px high, and there is still no sideways scroll.
  - `route-list.test.ts`: `routesFor` of the real data set contains `/` and `/about/`, and every entry starts and ends with `/`.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm build && pnpm test tests/unit/route-list.test.ts && pnpm e2e`
Expected: FAIL on the skip link, `main#main`, fonts, `/about/` and the missing `@axe-core/playwright` import.

- [ ] **Step 3: Implement**
  - Run `pnpm add -D --save-exact @axe-core/playwright@4.14.0` first.
  - `Base.astro`: `<Font cssVariable="--font-display" preload />` and `<Font cssVariable="--font-sans" preload />` from `astro:assets`, `<meta name="color-scheme" content="dark">`, the skip link (`.sr`, visible on focus), `SiteNav`, `<main id="main">`, `<footer>` with `SiteFooter`.
  - `SiteNav.astro`: the mock-up's `.top` bar: a `SITE_NAME` mark with the yellow square, and an "About" link to `/about/`. 44 px tap targets.
  - `SiteFooter.astro`: renders `NOTICE`, and keeps the license line (MIT, CC BY-SA 4.0, source on GitHub: all allowlisted hosts).
  - `index.astro`, `about.astro` and `404.astro`: the new props and B2 typography only. Their content is unchanged, except `about.astro` renders `NOTICE`. Tasks 10 and 17 rewrite them.

- [ ] **Step 4: Run to verify**

Run: `pnpm exec biome check --write src tests playwright.config.ts && pnpm build && pnpm e2e`
Expected: PASS. Under `trailingSlash: 'always'`, `astro preview` answers `/about/` and returns 404 for `/about`: that is expected, and the tests use the slash form.

- [ ] **Step 5: Commit** (`feat(site): B2 shell with skip link, self-hosted fonts and route-wide gates`). Stage by path.

---

### Task 3: Fixture data set and the second build

**Files:**
- Create: `tests/fixtures/site-data/**` (the base set below), `tests/unit/data/site-fixture.test.ts`
- Modify: `astro.config.ts`, `src/content.config.ts`, `playwright.config.ts`, `package.json`, `.gitignore`, `.github/workflows/ci.yml`

**Interfaces:**
- Produces, settings (not `M3_` names, which are for secrets): `SITE_DATA_DIR` (default `./data`) is the base of every collection in `content.config.ts`. `SITE_OUT_DIR` (default `./dist`) is Astro's `outDir`. When `SITE_DATA_DIR` is set, `cacheDir` is `./node_modules/.astro-site-data`, which keeps the two builds' content caches isolated. A first probe on 2026-11-24 (build `data/`, then `SITE_DATA_DIR=tests/fixtures/data/valid SITE_OUT_DIR=dist-fixture astro build` on the default cache) printed duplicate-slug warnings for `generations` and `variants`. A re-review that alternated the builds four times could not reproduce them, so treat the separate cache as cheap insurance, not a proven fix: it costs one extra font download per fixture build.
- Produces, scripts: `build:fixture` is `SITE_DATA_DIR=tests/fixtures/site-data SITE_OUT_DIR=dist-fixture astro build` (no Pagefind: the fixture build needs no search index). `check:links:fixture` is `node tools/check-links.ts dist-fixture`.
- Produces, Playwright: a second `webServer` on port 4322 (`pnpm preview --port 4322 --ignore-lock` with `SITE_OUT_DIR=dist-fixture` in its `env`) and a second project `fixture` (`baseURL` port 4322, `metadata.dataDir: 'tests/fixtures/site-data'`). `real` matches `shared/**`, and `fixture` matches `shared/**` and `fixture-only/**`.
- Produces, CI: the `e2e` job runs `pnpm build`, `pnpm build:fixture`, `pnpm check:links:fixture`, then `pnpm e2e`. The second build is a handful of pages, with no Pagefind and no lint, so it adds seconds, not minutes: record the measured seconds in the PR.

**The base fixture set** (valid under the merged schemas; Tasks 11, 14 and 16 add the facts their tests assert, in their own Step 1):

| File | Purpose |
|---|---|
| `generations/e46.yaml` | The real figures (length 4492, height 1372, wheelbase 2731) so the hero draws; run 2000 to 2006; two engines (`FIXTURE-ENGINE` and `FIXTURE-ENGINE-2`, with different displacements and cylinder counts, so the pit board's per-engine rows are exercised); front and rear stock wheels with different values (front 18 x 8 ET47, 225/45ZR18; rear 18 x 9 ET26, 255/40ZR18); a rear `envelopes` row, front empty; an estimated eye point; `unverified` listing `years.1`, `engines.FIXTURE-ENGINE-2.displacementCc`, `fitment.front.stock.widthIn`, `fitment.front.stock.offsetMm` and `fitment.rear.stock.offsetMm`. |
| `generations/fixture-gen2.yaml` | Run 2008 to 2013; dimensions that match no outline (no hero drawing); a measured eye point with one source; no `unverified`. |
| `variants/e46/e46-us-coupe.yaml` | A US coupe with packages, paints, interiors and distinct front and rear wheels; `unverified` with `years.1`, scalar paths, element paths (`paints.<code>`, `interiors.<id>`) and wheel values on both axles. |
| `variants/e46/fixture-euro-csl.yaml` | A Euro variant with no interiors ("None recorded") and its own `unverified`. |
| `variants/fixture-gen2/fixture-gen2-coupe.yaml` | One variant for the second generation. |
| `issues/e46/*.yaml` | Both markets; `very-common`, `common` and `rare`; costed and no-cost; a verified and an unverified issue; `inspectWhenBuying` true and false. |
| `issues/fixture-gen2/fixture-gen2-issue.yaml` | One `markets: [us]` issue, so Euro is an empty selection on that generation. |

The second generation has no maintenance items, which gives the "no items" state. Collection directories the base set leaves empty (`maintenance/e46`, `maintenance/fixture-gen2`, `parts/e46`) hold a `.gitkeep`, as `data/` does, so Astro's glob finds its base directory.

- [ ] **Step 1: Write the failing tests.**
  - `site-fixture.test.ts`: `loadDataSet('tests/fixtures/site-data')` reports no issues from the loader, and `checkDataSet` reports none. It also asserts the coverage the table promises (two generations; issues in both markets, in all three frequencies, with and without cost, verified and unverified). Later tasks extend this test with the facts they add.
  - The shared specs from Task 2 run under both projects: they prove the fixture build is served and passes the route-wide gates.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test tests/unit/data/site-fixture.test.ts`
Expected: FAIL, no fixture directory.

- [ ] **Step 3: Implement** the fixture files, the settings in `astro.config.ts` and `content.config.ts` (each collection's `base` is `process.env.SITE_DATA_DIR ?? './data'` followed by `/<collection>`), the scripts, the Playwright projects and servers, `.gitignore` entries for `dist-fixture/` and `node_modules/.astro-site-data`, and the CI steps. Leave `check:site` as it is: the fixture build runs in the `e2e` job.

- [ ] **Step 4: Run to verify**

Run: `pnpm check && pnpm build && pnpm build:fixture && pnpm check:links:fixture && pnpm e2e`
Expected: exit 0 for all. `pnpm build && pnpm build:fixture` alternating leaves no duplicate-slug warning.

- [ ] **Step 5: Commit** (`test(site): fixture data set, second build and fixture e2e project`).

---

### Task 4: CI screenshots

**Files:**
- Create: `tests/shots/shoot.spec.ts`
- Modify: `src/lib/route-list.ts`, `tests/unit/route-list.test.ts`, `playwright.config.ts`, `.github/workflows/ci.yml`, `.github/pull_request_template.md`, `.gitignore`

Do not touch `deploy.yml`: `tests/unit/workflows.test.ts` locks it.

**Interfaces:**
- Produces: `keyRoutes(set: DataSet): string[]`, the routes worth looking at. In this task it returns every route `routesFor` has registered (only `/` and `/about/` exist yet). Task 11 narrows it to the first issue page per generation once issue pages exist, with its own assertion, so this group tests only routes that are registered.
- Produces: a Playwright project `shots` (`testDir: 'tests/shots'`), defined only when `SHOOT === '1'`, so a plain `pnpm e2e` never runs it. `shoot.spec.ts` imports `@playwright/test` directly (Task 2 names this exception), loads the data sets with `loadDataSet` itself (the `dataSet` fixture is not available to it), and writes, for each key route and each viewport (390 x 844 and 1280 x 800, full page), `screenshots/after/<slug>-<width>.png` from the `real` server and `screenshots/after-fixture/...` from the fixture server. When `SHOOT_BEFORE_URL` is set it also writes `screenshots/before/...` from that URL, and skips a route that answers anything but 200 (a new route) or an unreachable production, logging the skip without failing. It asserts nothing about pixels: `testing.md` forbids screenshot assertions before the visual suite.
- CI: in the `e2e` job, after the e2e step, `pnpm exec playwright test --project=shots` with `if: always()`, `continue-on-error: true` (the capture is advisory, so a flake in it cannot turn the required `e2e` job red), and `env` `SHOOT: '1'` and `SHOOT_BEFORE_URL: https://m3-tool.broken-wood-97a9.workers.dev`, then the `actions/upload-artifact` step already pinned in this file (`cf430e030ddbb5b0abf93d22962f4752f3646cd9`, `# v7.0.2`) with `name: screenshots`, `path: screenshots/`, `if: always()`, `if-no-files-found: ignore`, `retention-days: 14`. Keep `${{ }}` expressions out of every `run:` and use `pnpm exec`, never `npx`: `workflows.test.ts` requires it. Any new checkout needs `persist-credentials: false` (this job adds none).

- [ ] **Step 1: Write the failing tests.** `route-list.test.ts`: `keyRoutes` of the real and the fixture data set contains `/` and `/about/`, and every entry is also in `routesFor` of the same set (no issue route is asserted here: none is registered until Task 11). `workflows.test.ts` must stay green with the new steps.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test tests/unit/route-list.test.ts tests/unit/workflows.test.ts`
Expected: FAIL on `keyRoutes`.

- [ ] **Step 3: Implement** `keyRoutes`, the `shots` project, the capture spec, the CI steps, the `.gitignore` entry for `screenshots/`, and the PR template's Screenshots comment ("CI attaches before and after as the `screenshots` run artifact: link it and the preview URL here").

- [ ] **Step 4: Run to verify**

Run: `pnpm build && pnpm build:fixture && SHOOT=1 pnpm exec playwright test --project=shots && git status --short`
Expected: PNGs under `screenshots/after/` and `screenshots/after-fixture/`, no `before/` (no URL set), and `git status` shows no untracked image. Push the branch, and confirm the CI run has a `screenshots` artifact with `before/`, `after/` and `after-fixture/`.

- [ ] **Step 5: Commit** (`ci(site): capture before and after screenshots as a run artifact`).

---

### Task 5: Display libraries: format, money, routes, markets, model years

**Files:**
- Create: `src/lib/format.ts`, `src/lib/money.ts`, `src/lib/routes.ts`, `src/lib/markets.ts`, `src/lib/model-years.ts`
- Test: `tests/unit/{format,money,routes,markets,model-years}.test.ts`

**Interfaces:**
- Produces (`format.ts`): `formatDate(date: Date): string` (UTC `YYYY-MM-DD`); `formatNumber(value: number): string` (`4492` to `4,492`, `3.5` to `3.5`, `-370` to `-370`; for millimetres and similar, never for years); `formatYears(years: readonly [number, number]): string` (`2000–2006` with an en dash, `2004` when equal); `frequencyLabel(f: KnownIssue['frequency']): string`; `transmissionLabel(t: Variant['transmissions'][number]): string` (`6mt` "6-speed manual", `smg` "SMG", `dct` "DCT", `auto` "Automatic", `7mt` "7-speed manual"); `bodyLabel(b: Variant['body']): string`; `wheelParts(w: { diameterIn: number; widthIn: number; offsetMm: number; tire: string }): { diameter: string; width: string; offset: string; tire: string }` (each value as its own string through `formatNumber`, so a page can put a mark around each one); `wheelLabel(w)` (the parts joined, `18 × 8 ET47`, for `aria-label` and `<title>` text only).
- Produces (`money.ts`): `NO_SOURCED_COST = 'no sourced cost'`; `formatUsdRange(range: readonly [number, number]): string`; `sourcedShopMax(cost: { shop: readonly [number, number] } | undefined): number | undefined`, the one place that decides a cost is sourced: `undefined` when `cost` is absent or `shop[1]` is 0; `describeCost(cost: { diy?: readonly [number, number] | undefined; shop: readonly [number, number] } | undefined): CostView`, with `CostView = { kind: 'sourced'; shop: string; diy?: string } | { kind: 'none'; label: typeof NO_SOURCED_COST }`, built on `sourcedShopMax`. Zero is decided per side: a `shop` range with a high end of 0 makes the whole cost `none` (a DIY figure with no shop figure is not published either), and a `diy` range with a high end of 0 is dropped on its own, so `{ diy: [0, 0], shop: [60, 100] }` shows the shop figure and no DIY tile. `compareIssues` (Task 12) and `buildChecklist` (Task 15) call `sourcedShopMax` too. A `zero-cost` check will reject `[0, 0]` in a separate data-lane PR (R87.5), and until it lands this guard is all that stands between a `[0, 0]` entry and a printed `$0`.
- Produces (`routes.ts`): `generationPath(gen: string)` (`/e46/`), `issuesPath(gen)`, `issuePath(gen, id)`, `maintenancePath(gen)`, `buyingPath(gen)`, all with a leading and trailing slash; `GenerationSection = { key: 'overview' | 'maintenance' | 'issues' | 'buying'; label: string; path: (gen: string) => string }`; `GENERATION_SECTIONS: readonly GenerationSection[]`. This task owns the `overview` entry. Each later task that adds a page inserts its entry at its spec-order position (overview, mods, maintenance, issues, buying, build) and updates the `keys` assertion.
- Produces (`markets.ts`): `type Market = Variant['market']`; `MARKETS: readonly ['us', 'euro']`; `marketsOf(entry: { markets?: readonly Market[] | undefined }): readonly Market[]` (no `markets` means both); `marketsLabel(entry): string` ("All markets", "US only", "Euro only", "US and Euro"); `marketLabel(m: Market): 'US' | 'Euro'`; `marketsAttr(entry): string` (`'us euro'`, for `data-markets`).
- Produces (`model-years.ts`): `type ModelYears = NonNullable<MaintenanceItem['modelYears']>` (derived from the merged schema, so it cannot drift: `[from, to]`, both required, R88); `appliesToYear(entry: { modelYears?: ModelYears | undefined }, year: number): boolean` (no `modelYears` means every year; both ends inclusive); `modelYearsLabel(entry): string` (`All model years`, `2001–2003`, or `2004 only` for `[2004, 2004]`); `yearsAttr(entry, run: readonly [number, number]): string` (the years from `from` to `to`, space-separated, for `data-years`; with no `modelYears`, every year of the run; nothing is clamped, because `check:data` already rejects a range outside the run as `model-years-outside-generation`).

- [ ] **Step 1: Write the failing tests.** Key assertions:

```ts
test('describeCost never shows zero (Review Focus 4)', () => {
  const none = { kind: 'none', label: 'no sourced cost' }
  expect(describeCost(undefined)).toEqual(none)
  expect(describeCost({ shop: [0, 0] })).toEqual(none)
  expect(describeCost({ diy: [0, 0], shop: [0, 0] })).toEqual(none)
  expect(describeCost({ diy: [20, 40], shop: [0, 0] })).toEqual(none)
  expect(describeCost({ diy: [0, 0], shop: [60, 100] })).toEqual({ kind: 'sourced', shop: '$60–100' }) // zero DIY dropped, no $0
  expect(describeCost({ diy: [20, 40], shop: [60, 100] })).toEqual({ kind: 'sourced', shop: '$60–100', diy: '$20–40' })
  expect(describeCost({ shop: [60, 100] })).toEqual({ kind: 'sourced', shop: '$60–100' }) // no diy key at all
  expect(sourcedShopMax({ shop: [0, 0] })).toBeUndefined(); expect(sourcedShopMax({ shop: [60, 100] })).toBe(100)
})
test('appliesToYear is inclusive at both ends (Review Focus 5)', () => {
  expect(appliesToYear({ modelYears: [2004, 2006] }, 2003)).toBe(false)
  for (const y of [2004, 2005, 2006]) expect(appliesToYear({ modelYears: [2004, 2006] }, y)).toBe(true)
  expect(appliesToYear({ modelYears: [2004, 2006] }, 2007)).toBe(false)
  expect(appliesToYear({ modelYears: [2004, 2004] }, 2005)).toBe(false)
  expect(appliesToYear({}, 1999)).toBe(true) // no range: every year
})
test('yearsAttr lists from to to, and every year of the run when there is no range', () => {
  expect(yearsAttr({ modelYears: [2001, 2003] }, [2000, 2006])).toBe('2001 2002 2003')
  expect(yearsAttr({}, [2000, 2002])).toBe('2000 2001 2002')
})
```

Also: `formatUsdRange([500, 900])` is `$500–900`, `[60, 60]` is `$60`, `[1200, 3400]` is `$1,200–3,400`; `modelYearsLabel({})` is `All model years`, `[2001, 2003]` is `2001–2003`, `[2004, 2004]` is `2004 only`; `formatDate(new Date('2026-11-23'))` is `2026-11-23`; `frequencyLabel('very-common')` is `Very common`; `wheelParts({ diameterIn: 18, widthIn: 9.5, offsetMm: 26, tire: '255/40ZR18' })` is `{ diameter: '18', width: '9.5', offset: '26', tire: '255/40ZR18' }` and `wheelLabel` of it is `18 × 9.5 ET26`; the label for `{ markets: ['us', 'euro'] }` is `US and Euro`, `marketsAttr({})` is `us euro`, `marketsAttr({ markets: ['us'] })` is `us`; every path builder starts and ends with `/`, and `GENERATION_SECTIONS.map((s) => s.key)` is `['overview']`.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test tests/unit/format.test.ts tests/unit/money.test.ts tests/unit/routes.test.ts tests/unit/markets.test.ts tests/unit/model-years.test.ts`
Expected: FAIL, modules not found.

- [ ] **Step 3: Implement the five modules** to the signatures above (`Intl.NumberFormat('en-US')` for numbers and money, an en dash in ranges; types from `../data/schemas.ts` with `import type`).

- [ ] **Step 4: Format and verify**

Run: `pnpm exec biome check --write src/lib tests/unit && pnpm test tests/unit/format.test.ts tests/unit/money.test.ts tests/unit/routes.test.ts tests/unit/markets.test.ts tests/unit/model-years.test.ts && pnpm typecheck`
Expected: PASS, exit 0.

- [ ] **Step 5: Commit** (`feat(site): format, money, route, market and model-year display libraries`).

---

### Task 6: Citation, unverified-mark and value libraries

**Files:**
- Create: `src/lib/citations.ts`, `src/lib/unverified-marks.ts`, `tests/support/value-at.ts`
- Test: `tests/unit/citations.test.ts`, `tests/unit/unverified-marks.test.ts`, `tests/unit/value-at.test.ts`

**Interfaces:**
- Consumes: `isCitationLinkable` (`src/lib/link-policy.ts`), `formatDate` (Task 5), `Source` (schemas), `loadDataSet` (tests only).
- Produces (`citations.ts`): `CitationView = { publisher: string; title: string; accessed: string; tier: 1 | 2 | 3; note?: string; href?: string }`; `citationView(source: Source): CitationView` (`href` only when `isCitationLinkable(source.url)`, and no `href` key otherwise); `latestAccessed(sources: readonly Source[]): string | undefined`; `TIER_LABEL: Record<1 | 2 | 3, string>`.
- Produces (`unverified-marks.ts`): `isUnverified(unverified: readonly string[] | undefined, path: string): boolean` (true when a listed entry equals `path` or is an ancestor of it at a dot boundary).
- Produces (`tests/support/value-at.ts`, used by the e2e marks helper): `valueAt(root: unknown, path: string): unknown`, which follows the `unverified.ts` grammar: a list element is named by its `id` or `code`, a tuple such as `years` by position, a record key as written; it returns `undefined` for a path that leads nowhere. `unverified.ts` is a contract file that returns reasons, not values, so the helper cannot reuse it and duplicates the grammar. `value-at.test.ts` pins the two together (below).

- [ ] **Step 1: Write the failing tests.**

```ts
test.each(['https://archive.org/download/x/x.pdf', 'https://web.archive.org/web/2026/https://a.example/p',
  'https://newsroom.bmwgroup.com/emea/x', 'https://en.wikipedia.org/wiki/X'])('links %s',
  (url) => expect(citationView(source({ url })).href).toBe(url))
test.each(['https://cdn.shopify.com/s/files/1/x.pdf', 'https://www.pistonheads.com/x', 'https://archive.org.evil.test/x',
  'https://newsroom.bmwgroup.com@evil.test/x', 'https://blog.ecstuning.com/x'])('shows %s as text only',
  (url) => expect('href' in citationView(source({ url }))).toBe(false))
test('no source in data/ is linked unless isCitationLinkable allows it (Review Focus 2)', async () => {
  // every source of every entry in loadDataSet('data'): href defined <=> isCitationLinkable(url)
})
```

Also: `accessed` is `YYYY-MM-DD`; a source with no `url` has no `href`; `note` passes through; `latestAccessed` of two dates is the later, and of `[]` is `undefined`. `isUnverified` with `['paints.A08', 'years.1', 'factoryWheels.optional-19.front.offsetMm']`: true for `paints.A08.code`, `paints.A08`, `years.1`; false for `paints.A080`, `years.0`, `factoryWheels.optional-19.front.widthIn`, `factoryWheels.optional-190.front.offsetMm`; an `undefined` list is false. `value-at.test.ts` also pins `valueAt` to `unverified.ts`: for every generation and variant in `loadDataSet('data')` and in `tests/fixtures/site-data`, each path in its `unverified` list is accepted by `unresolvedReason(Generation or Variant, data, path)` (it returns `undefined`) and by `valueAt` (it returns a defined value), and for paths `unresolvedReason` rejects (`paints.0.code`, `paints.nope.code`, `years.2`) `valueAt` returns `undefined`, so a change to the grammar breaks a test here instead of drifting silently. `valueAt` on a variant: `paints.A08.code` is `'A08'`, `factoryWheels.optional-19.front.offsetMm` is the front value and `...rear.offsetMm` the rear one, `years.1` is the end year, `paints.nope.code` is `undefined`.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test tests/unit/citations.test.ts tests/unit/unverified-marks.test.ts tests/unit/value-at.test.ts`
Expected: FAIL, modules not found.

- [ ] **Step 3: Implement the three modules.** `isUnverified` and `valueAt` split on `.` and never compare string prefixes alone.

- [ ] **Step 4: Format and verify**

Run: `pnpm exec biome check --write src/lib tests && pnpm test tests/unit/citations.test.ts tests/unit/unverified-marks.test.ts tests/unit/value-at.test.ts && pnpm typecheck`
Expected: PASS, exit 0.

- [ ] **Step 5: Commit** (`feat(site): citation view, unverified-mark and value-path libraries`).

---

### Task 7: Generation page: spec drawers

**Files:**
- Create: `src/data/site.ts`, `src/components/{Drawer,Tier,Mark,SourceList,GenerationNav}.astro`, `src/pages/[gen]/index.astro`, `tests/e2e/marks.ts`, `tests/e2e/inventories.ts`, `tests/e2e/shared/marks-selftest.spec.ts`, `tests/e2e/shared/generation.spec.ts`
- Modify: `src/lib/route-list.ts` and its test (add `generationPath(gen)` for every generation)

**Interfaces:**
- Consumes: Tasks 2 to 6.
- Produces (`src/data/site.ts`, uses `getCollection`, so no unit test: the e2e covers it): `GenerationData = { generation: Generation; variants: Variant[]; issues: KnownIssue[]; maintenance: MaintenanceItem[] }`; `generationIds(): Promise<string[]>`; `loadGeneration(id: string): Promise<GenerationData>` (throws `no generation "<id>"`; each list sorted by `id`).
- Produces (components): `Drawer` (props `name: string; label: string; span?: 4 | 5 | 7 | 8 | 12`, default slot, renders the tool-chest drawer with its tape label and handle, and `data-drawer={name}`); `Tier` (`tier: 1 | 2 | 3`, the `T1`/`T2`/`T3` badge with a text label for assistive tech); `Mark` (props `path: string; unverified: readonly string[] | undefined`, wraps its slot as `<span data-value-path={path}><span data-value>slot</span></span>` always, and when `isUnverified` adds a visible `†`, visually-hidden text "unverified" and the attribute `data-unverified`); `SourceList` (`sources: readonly Source[]; list: string`, an `<ol data-sources data-source-list={list}>` whose `<li>`s carry `data-source-index={i}`, so a row is addressed by its owning list and its position in it, never by its title, which repeats: the E46 data has the ST041 and the Koleso.ee titles in two lists each. List names: `sources` for an entity's own list, `dimensions.<body>`, `fitment` and `driverEyePoint` on the generation page. Each row is a citation: tier badge, publisher, title and accessed date as text, a link only when `citationView` gives an `href`, and `note` inside a closed `<details>`); `GenerationNav` (`gen: string; current: GenerationSection['key']`, links from `GENERATION_SECTIONS`).
- Produces for e2e (`tests/e2e/marks.ts`): `expectMarks(scope: Locator, args: { root: unknown; listed: readonly string[] | undefined; inventory: readonly { path: string; times: number }[]; complete: boolean; exempt?: readonly string[] | undefined }): Promise<void>`.
  - `listed` is the entry's full `unverified` list: it alone decides whether a rendered value is covered.
  - `inventory` names every path the scope must render and how many times it renders it. The test builds it from the data and the scope's render list (below) in `tests/e2e/inventories.ts`, independently of the page.
  - `complete` says the scope renders every flaggable value of its entry. A scope that shows only a subset (the home card) passes `false`.
  - It asserts:
    1. **Inventory.** For each inventory path the number of `[data-value-path="<path>"]` elements in `scope` equals `times`, and no `[data-value-path]` has a path outside the inventory. A value printed as plain text has no wrapper and fails here, which enumerating the wrappers that exist could never detect.
    2. **Flag.** Each wrapper has `data-unverified` exactly when `isUnverified(listed, path)`. A flag on an ancestor therefore marks every inventory value under it, repeats included, and nothing else.
    3. **Completeness**, only when `complete`. Every listed path outside `exempt` has an inventory path at or under it, so flagging a value the page never prints fails: add the value, do not weaken the test. When `complete` is false, a listed path with no inventory path under it is not required, so a scope is never asked to render values it does not show.
    4. **Binding.** For a path that holds a number or text the page prints unchanged, the `[data-value]` element's `textContent` (not `innerText`, so a value inside a closed `<details>` reads correctly) equals `String(v)` or `formatNumber(v)` of `valueAt(root, path)`. A front offset's path on the rear value fails here even though both paths are flagged. Enumerations the page prints as labels (`market`, `body`, `finish`, `material`, `basis`) and lists or objects (`bodies`, `transmissions`, `envelopes`) are checked for presence only.
- Produces (`tests/e2e/inventories.ts`): `generationInventory(generation: Generation, stage: { hero: boolean; drawing: boolean })`, `variantInventory(variant: Variant)` (Task 8) and `homeCardInventory(generation: Generation)` (Task 10). Render lists:
  - **Generation scope** (`[data-generation-specs]`, `complete: true`): `name` x1; `chassis` x1; `years.0` and `years.1` x1; `bodies` x1; per engine `engines.<code>.code|displacementCc|cylinders` x1; per body in `dimensions` the six `dimensions.<body>.lengthMm|widthMm|heightMm|wheelbaseMm|trackFrontMm|trackRearMm` x1; per axle `fitment.<axle>.boltPattern|centerBoreMm|stock.diameterIn|stock.widthIn|stock.offsetMm|stock.tire|envelopes` x1; `driverEyePoint.xMm|yMm|zMm|basis|note` x1. Task 9 adds the hero's repeats when `stage.hero` and `stage.drawing` are set: `years.0|1` and `bodies` x2, every engine's three paths x2 (the pit board lists each engine), the hero body's `wheelbaseMm` one more (the pit board), and, with a drawing, `lengthMm`, `heightMm` and `wheelbaseMm` of the hero body one more each (the SVG labels).
  - **Variant scope** (`#variant-<id>`, `complete: true`, `exempt: ['render']`, the site shows no render value): `name`, `market`, `body`, `years.0`, `years.1`, `transmissions` x1; per package `packages.<id>.name|summary`; per paint `paints.<code>.code|name|finish`; per wheel `factoryWheels.<id>.name` and `factoryWheels.<id>.<front|rear>.diameterIn|widthIn|offsetMm|tire`; per interior `interiors.<id>.name|color|material`, each x1.
  - **Home card** (`article[data-generation]`, `complete: false`): `name`, `chassis`, `years.0`, `years.1`, `bodies` x1.
- Produces (`tests/e2e/shared/marks-selftest.spec.ts`, run on both builds, using `page.setContent`): proof that `expectMarks` rejects what it must. (a) `paints.A08` flagged, `code` marked, `name` and `finish` printed as plain text with no wrapper: rejects (the inventory count). (b) `name` wrapped but without `data-unverified` under a flagged ancestor: rejects. (c) The front and rear offset paths swapped: rejects. (d) A flagged path with no rendered value: rejects when `complete` and passes when not. (e) One wrapper where the inventory expects two (a repeat that lost its mark): rejects. (f) The correct markup passes.

**Page content** (`/[gen]/`). The generation's own content sits in one `<div data-generation-specs>`, which the generation specs scope to. Every value the page prints from the entry is wrapped in a `Mark` with its schema path, scalars and lists alike, so a data PR that flags any of them cannot turn the `real` project red. The `h1` is the name (in a `Mark` for `name`); a "data checked `<latestAccessed>`" line; a legend line ("† marks a value below the verification rule: one Tier 1 source, or two independent Tier 2 sources"); then the drawers:
- Engine: `chassis`, years (`years.0` and `years.1` each in its own `Mark`, the en dash outside), `bodies` (one `Mark` around the list), and per engine code, displacement in cc and cylinders (`engines.<code>.code|displacementCc|cylinders`); sources `generation.sources`.
- Body, mm: one drawer per body in `dimensions`, six figures (`dimensions.<body>.<field>`), that body's sources.
- Stock wheels: per axle, `wheelParts` with a `Mark` around each part (`fitment.<axle>.stock.diameterIn|widthIn|offsetMm|tire`) and the literal "×" and "ET" outside, `boltPattern` and `centerBoreMm` each in a `Mark`, and `fitment.sources`. `fitment.<axle>.envelopes` is one `Mark` around the whole region: an empty list says "Fit limits not yet sourced: the build sheet will report fitment unknown", and a non-empty one renders a four-column table (ride drop, max inner, max outer, max outer with fender work, all mm).
- Driver eye point: `driverEyePoint.xMm|yMm|zMm` in mm, `basis` (the raw word in the `Mark`, styled by CSS) and `note`. When `basis` is `estimated` an "Estimated · no source" badge (the word `estimated` is the marked `basis`). When `sources` is not empty, their `SourceList`, whatever the basis (a measured point lists its sources).

- [ ] **Step 1: Write the failing tests.** Add the fixture facts first (the measured eye point of `fixture-gen2` and the rear `envelopes` row exist from Task 3). `generation.spec.ts`, in `shared/` and data-driven over `dataSet.generations`:
  - `marks-selftest.spec.ts`: cases (a) to (f) above, so the helper is proved before any page relies on it.
  - `the h1 contains the generation name`, and the page title is `<name> · m3-tool`.
  - `every engine, body figure and stock wheel value is shown`: each engine code and displacement; each body's six figures inside that body's drawer; each axle's `wheelParts`, bolt pattern and centre bore.
  - `every rendered value is marked exactly when its path is covered` and `each mark sits on the value its path names` (Review Focus 4): `expectMarks(page.locator('[data-generation-specs]'), { root: generation, listed: generation.unverified, inventory: generationInventory(generation, { hero: false, drawing: false }), complete: true })`. Scoped to the generation's own wrapper: variant panels are not inside it.
  - `an estimated eye point says so, and a measured one lists its sources`.
  - `non-empty envelopes render as a table`, `empty ones say fit limits are not yet sourced`.
  - `source anchors are exactly the linkable sources` (Review Focus 2): inside `[data-generation-specs] [data-sources]`, the sorted `href` list of the `a[href^="http"]` anchors equals the sorted list of URLs of the generation's `isCitationLinkable` sources (the generation's own, each body's dimension sources, the fitment sources and the eye point's), so a duplicated or missing link fails; and each source's row, addressed as `[data-source-list="<list>"] [data-source-index="<i>"]` for its owning list and index in the data, shows its publisher and title, and has one anchor with exactly that source's URL when it is linkable and none when it is not. A title that appears in two lists is checked once per list.
  - `the nav marks the current section`.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm build && pnpm build:fixture && pnpm e2e generation.spec.ts`
Expected: FAIL, no route `/<gen>/`.

- [ ] **Step 3: Implement** the loaders, components and page, and register the routes. Port the mock-up's `.chest`, `.drawer`, `.handle`, `.tape`, `.kv`, `.tier`, `.est` and `.srcs` rules into the components.

- [ ] **Step 4: Format and verify**

Run: `pnpm exec biome check --write src tests && pnpm check && pnpm build && pnpm build:fixture && pnpm e2e`
Expected: exit 0 for both. The route-wide specs from Task 2 (notice, noindex, axe, 390 px) now cover the page in both builds.

- [ ] **Step 5: Commit** (`feat(site): generation page with spec drawers, sources and per-value unverified marks`).

---

### Task 8: Variants on the generation page

**Files:**
- Create: `src/components/VariantPanel.astro`, `tests/e2e/shared/variants.spec.ts`
- Modify: `src/pages/[gen]/index.astro`

**Interfaces:**
- Consumes: `Mark`, `SourceList`, `Drawer`, `expectMarks` (Task 7); `transmissionLabel`, `bodyLabel`, `marketLabel`, `formatYears`, `wheelParts` (Task 5).
- Produces: `VariantPanel` (props `variant: Variant`): a `<details id="variant-{id}">` whose summary row shows name, market, body, years and transmissions, and whose body lists packages (name and summary), paints (swatch from `baseColor` through an inline `--c` custom property, code, name, finish), factory wheels (the name, then front and rear `wheelParts` with a `Mark` around each value), interiors (name, colour, material) and the variant's `SourceList`. A list with no entries (the CSL has no interiors) prints a plain "None recorded" line. The variants sit outside `[data-generation-specs]`. Spec 7.2 has no per-variant route, so variants render here (R87.8).
- Mark paths: every value the panel prints from the variant is wrapped in a `Mark`, as listed in Task 7's variant render list: `name`, `market`, `body`, `years.0`, `years.1` and `transmissions` (one `Mark` around the list) in the summary row; `packages.<id>.name|summary`; `paints.<code>.code|name|finish`; `factoryWheels.<id>.name` and `factoryWheels.<id>.<front|rear>.diameterIn|widthIn|offsetMm|tire`; `interiors.<id>.name|color|material`. A flagged element (`paints.<code>`, `interiors.<id>`, `packages.<id>`) marks every one of that element's rendered fields. `baseColor` is a render value with no source and is never printed as text or marked. Years print once, in the summary row.

- [ ] **Step 1: Write the failing tests** in `variants.spec.ts` (shared), per variant of each generation in `dataSet.variants`, with the panel found by `#variant-<id>`:
  - `each variant has a panel with its name, market, body, years and transmissions`.
  - `every rendered value is marked exactly when its path is covered`, `each mark sits on the value its path names` and `a flagged element marks all its fields` (Review Focus 4): `expectMarks(panel, { root: variant, listed: variant.unverified, inventory: variantInventory(variant), complete: true, exempt: ['render'] })`, once per variant against its own `unverified`. The fixture's `e46-us-coupe` lists `years.1`, scalar wheel paths on both axles, `paints.<code>` and `interiors.<id>` elements, so a front/rear swap and a field printed without a `Mark` under a flagged element each fail.
  - `every paint code and name, wheel, package and interior is shown`, and `a variant with no interiors says none recorded`.
  - `the swatch colour comes from the data`: each paint swatch's inline `--c` equals its `baseColor`.
  - `source anchors in a panel are exactly that variant's linkable sources`: the sorted `href` list of the panel's `a[href^="http"]` anchors equals the sorted URLs of the variant's `isCitationLinkable` sources, and each source's row, addressed by `data-source-list="sources"` and `data-source-index`, shows its publisher and title and has one anchor with exactly its URL when linkable and none when not.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm build && pnpm build:fixture && pnpm e2e variants.spec.ts`
Expected: FAIL, no `#variant-*` panels.

- [ ] **Step 3: Implement** `VariantPanel`, and add the "Variants" section to the page (the mock-up's `.lanes` list with an expanding panel per variant).

- [ ] **Step 4: Format and verify**

Run: `pnpm exec biome check --write src tests && pnpm check && pnpm build && pnpm build:fixture && pnpm e2e`
Expected: exit 0 for both. Pass criterion for the phone layout: `mobile.spec.ts` is green (it opens every disclosure before measuring).

- [ ] **Step 5: Commit** (`feat(site): variant panels with per-value unverified marks`).

---

### Task 9: Hero drawing and pit board

**Files:**
- Create: `src/lib/hero-layout.ts`, `src/components/hero/coupe-outline.ts`, `src/components/HeroDrawing.astro`, `src/components/PitBoard.astro`, `tests/unit/hero-layout.test.ts`, `tests/e2e/shared/hero.spec.ts`
- Modify: `src/pages/[gen]/index.astro`

**Interfaces:**
- Produces (`coupe-outline.ts`, the one file the spike's traced outline replaces later): `OUTLINE = { lengthMm: 4492, heightMm: 1372, wheelbaseMm: 2731, rearAxleXMm: 925, art: string }`, where `art` is the markup of `#coupe-art` from `docs/design/b2-garage.html` lines 659 to 679, kept with its `id="coupe-art"` (the reflection `<use href="#coupe-art">` needs it), its `id="tire-r"` and `id="tire-f"` circles, and unscaled. `HeroDrawing` owns the wrapper around the art: the `<defs>` (shadow, reflection and cone gradients, the reflection mask), the shadow ellipses, the reflection `<use>` and the ground line (mock-up lines 646 to 658). The `<defs>` gradient's `stop-color="#fff"` becomes `style="stop-color: var(--text)"`, so no colour literal is left.
- Produces (`hero-layout.ts`): `type BodyDimensions = NonNullable<Generation['dimensions'][Body]>`; `heroBody(generation: Generation): { body: Body; dimensions: BodyDimensions }` (the first body in `bodies` that has `dimensions`: the coupe for the E46; the hero and the pit board both use it); `heroLayout(dims: BodyDimensions, outline: typeof OUTLINE, unverified: readonly string[] | undefined, body: Body): HeroLayout | undefined`, with `HeroLayout = { viewBox: string; length: Dim; height: Dim; wheelbase: Dim }` and `Dim = { x1: number; y1: number; x2: number; y2: number; labelX: number; labelY: number; text: string; path: string; unverified: boolean }`.
  - It returns `undefined` unless length, height and wheelbase each differ from the outline's by at most 1 mm. The art is not scaled, so a drawing for other figures would lie: such a generation gets the hero text and the pit board and no drawing.
  - `viewBox` is `-640 -2000 {lengthMm + 1280} 2000`.
  - The wheelbase line runs from `rearAxleXMm` to `rearAxleXMm + wheelbaseMm` (925 and 3656), and the test checks those endpoints against the circles the art itself draws, not against the constants.
  - `text` is `formatNumber(value) + ' mm'`. `path` is the value's schema path (`dimensions.<body>.lengthMm`), and `unverified` is `isUnverified(unverified, path)`; a flagged label carries `†` in a `<tspan data-value-path>` with a nested `<tspan data-value>` that holds the number alone (` mm` follows it outside), the same hooks as `Mark`.
- Produces: `HeroDrawing` (props `layout: HeroLayout`), an `<svg role="img">` whose `<title>` and `<desc>` are built from the data; `PitBoard` (props `rows: { label: string; value: ComponentChild }[]`).

**Page.** The hero sits inside `[data-generation-specs]`: `h1` holds the generation name, with years and bodies in a `span` inside it as in the mock-up, and the years use `Mark` for `years.0` and `years.1`. The pit board rows come from the data only, each value in a `Mark`: for each engine, its code, displacement and cylinders, then the wheelbase. The mock-up's "Layout: Inline 6" row is dropped because the schema has no layout field. The hero actions come from `GENERATION_SECTIONS` after `overview`. The caption reads: "Generic two-door outline. The dimension lines show the factory figures. The 3D model replaces it when ready." Art rules (`.body`, `.tire`, `.glass` and the rest) go in `<style is:global>`, because `set:html` content carries no scope attribute.

- [ ] **Step 1: Write the failing tests.**

```ts
// hero-layout.test.ts
test('E46 dimensions give the mock-up coordinates, and the lines meet the drawn axles', () => {
  const l = heroLayout(E46_COUPE, OUTLINE, undefined, 'coupe')!
  expect(l.viewBox).toBe('-640 -2000 5772 2000')
  expect(l.length).toMatchObject({ x1: 0, x2: 4492, y1: -1780, y2: -1780, labelX: 2246, text: '4,492 mm' })
  expect(l.height).toMatchObject({ x1: -300, y1: 0, y2: -1372, text: '1,372 mm' })
  expect(l.wheelbase).toMatchObject({ x1: 925, x2: 3656, y1: 330, text: '2,731 mm' })
})
test('the dimension endpoints meet the circles the art draws', () => {
  const cx = (id: string) => Number(new RegExp(`id="${id}"[^>]*\\bcx="([\\d.]+)"`).exec(OUTLINE.art)?.[1])
  const l = heroLayout(E46_COUPE, OUTLINE, undefined, 'coupe')!
  expect(l.wheelbase.x1).toBe(cx('tire-r')); expect(l.wheelbase.x2).toBe(cx('tire-f')) // fails if a traced outline replaces the art and the constants stay stale
})
test('the 1 mm boundary: 4493 draws, 4494 does not', () => {
  expect(heroLayout({ ...E46_COUPE, lengthMm: 4493 }, OUTLINE, undefined, 'coupe')).toBeDefined()
  expect(heroLayout({ ...E46_COUPE, lengthMm: 4494 }, OUTLINE, undefined, 'coupe')).toBeUndefined()
})
test('a generation whose figures differ from the outline gets no drawing', () => {
  expect(heroLayout({ ...E46_COUPE, lengthMm: 4500 }, OUTLINE, undefined, 'coupe')).toBeUndefined()
})
test('a flagged dimension marks its label', () => {
  expect(heroLayout(E46_COUPE, OUTLINE, ['dimensions.coupe.lengthMm'], 'coupe')!.length.unverified).toBe(true)
})
```

Also `heroBody` picks `coupe` for `bodies: ['coupe', 'convertible']` and the first body with `dimensions` when the first has none. `hero.spec.ts` (shared): the generations with a drawing (`e46`) show an `<svg>` whose visible dimension texts equal the data's length, height and wheelbase, whose `<title>` and `<desc>` contain them, with no `image` element, and the caption; a generation without one (`fixture-gen2` in the fixture build) shows no drawing and still shows the pit board; the pit board shows each engine's code, displacement and cylinder count (the fixture's `e46` has two engines, so a pit board that lists only the first fails); the Task 7 `expectMarks` assertion is updated to `generationInventory(generation, { hero: true, drawing })`, where `drawing` is true when `heroLayout` returns a layout, so hero years, bodies, pit board values and SVG labels each carry their own mark and a repeat that loses its mark fails.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test tests/unit/hero-layout.test.ts && pnpm build && pnpm build:fixture && pnpm e2e hero.spec.ts`
Expected: FAIL, modules not found.

- [ ] **Step 3: Implement** the layout function, the outline file, the two components and the page changes.

- [ ] **Step 4: Format and verify**

Run: `pnpm exec biome check --write src tests && pnpm check && pnpm build && pnpm build:fixture && pnpm e2e`
Expected: exit 0 for both. Pass criterion for the look: the gates are green, and the CI artifact shows the hero at 390 and 1280 px for the orchestrator to compare with the mock-up.

- [ ] **Step 5: Commit** (`feat(site): hero drawing and pit board on the generation page`).

---

### Task 10: Home page: pick a generation

**Files:**
- Modify: `src/pages/index.astro`
- Test: `tests/e2e/shared/home.spec.ts`

**Interfaces:**
- Consumes: `generationIds`, `loadGeneration` (Task 7), `generationPath`, `formatYears`, `bodyLabel` (Task 5), `Mark`, `expectMarks`, `Drawer`.
- Produces: `/` with a short statement of what the site is ("A free reference for BMW M3 owners and shoppers: factory spec, known issues, maintenance and a used-buyer checklist. Nothing is for sale and there are no store links."), then one card per generation, each in `<article data-generation="{id}">`: `name`, `years.0` and `years.1`, `chassis` and `bodies`, each in a `Mark` with its schema path, and a link to `generationPath(id)`. Generations always exist in a built site, so there is no empty state.

- [ ] **Step 1: Write the failing e2e tests** (shared): `every generation is listed with its name, years and a working link` (click the first link, expect that generation's `h1` to contain its name; the fixture build lists two generations); `each card's values are marked exactly when covered`: `expectMarks(card, { root: generation, listed: generation.unverified, inventory: homeCardInventory(generation), complete: false })` per card. `listed` is the generation's full list, which decides coverage, while the inventory holds only what a card prints, so a card is not asked to render the wheel paths it does not show; `the home page makes no store claim it cannot keep`: the text contains "Nothing is for sale".

- [ ] **Step 2: Run to verify failure**

Run: `pnpm build && pnpm build:fixture && pnpm e2e home.spec.ts`
Expected: FAIL, no generation cards.

- [ ] **Step 3: Implement** the page to the Interfaces above.

- [ ] **Step 4: Format and verify**

Run: `pnpm exec biome check --write src tests && pnpm check && pnpm build && pnpm build:fixture && pnpm e2e`
Expected: exit 0 for both.

- [ ] **Step 5: Commit** (`feat(site): home page lists generations`).

---

### Task 11: Known issue detail page

**Files:**
- Create: `src/components/Chip.astro`, `src/components/CostBox.astro`, `src/pages/[gen]/issues/[issue].astro`, `tests/e2e/shared/issues.spec.ts`
- Modify: `src/lib/route-list.ts` and its test (add `issuePath(gen, id)` for every issue, and narrow `keyRoutes` to the first issue page per generation), `tests/unit/data/site-fixture.test.ts`, the fixture set

**Interfaces:**
- Consumes: `describeCost`, `frequencyLabel`, `marketsLabel`, `modelYearsLabel`, `issuePath` (Task 5); `SourceList`, `Drawer` (Task 7).
- Produces: `Chip` (props `kind: 'verified' | 'market' | 'years' | 'frequency' | 'checklist' | 'engine'; tone?: 'plain' | 'hot'`, slot; it renders `data-chip={kind}`, the stable hook every later spec uses); `CostBox` (props `cost: Parameters<typeof describeCost>[0]`: DIY and Shop tiles when sourced, the words "no sourced cost" and no currency symbol when not); `[issue].astro` with `getStaticPaths` over every issue and `data-section` hooks (`symptoms`, `cause`, `check`, `fix`, `costs`, `prevention`, `sources`).
- This page adds no back link and no nav entry: Task 12 adds both with the list page, so no commit links to a route that does not exist yet.

**Page** (the mock-up's tech card on the pegboard): the title and a frequency plate (`frequencyLabel`, `data-chip="frequency"`); chips for the engine code, `marketsLabel`, `modelYearsLabel` ("All model years" when the issue has no `modelYears`), "Verified" or "Unverified" (from `verified`) and "On the buyer checklist" when `inspectWhenBuying`; Symptoms (a list), Cause, How to check (when `howToCheck`), Fix (when `fix`; otherwise "No sourced fix yet. A fix needs a Tier 1 or Tier 2 source."), Costs (always, through `CostBox`), Prevention (when present), Sources (`SourceList`, and for an unverified issue the mock-up's line "Unverified: needs one Tier 1 source, or two Tier 2 sources from different publishers to read Verified.").

- [ ] **Step 1: Write the failing tests.**
  - `route-list.test.ts`: `keyRoutes` of a set with two issues in one generation contains the first issue page and not the second, every entry is also in `routesFor` of that set, and the issue routes appear in `routesFor`. The `shots` capture set now includes the first issue page.
  - Fixture: add issues with `modelYears` (`[2001, 2003]` for a market-split rod-bearing pair, `[2004, 2006]` for a late-build issue) and extend `site-fixture.test.ts` to assert they exist and that `checkDataSet` still reports nothing.
  - `issues.spec.ts` (shared), per issue in `dataSet.issues`:
    - `the page shows the title, every symptom and the cause`.
    - `the verified chip follows the flag` (Review Focus 4): `[data-chip="verified"]` reads "Verified" exactly when `issue.verified`, "Unverified" otherwise, and the sources line that mentions "to read Verified" is not the chip.
    - `frequency never shows as a slug`: `[data-chip="frequency"]` is `frequencyLabel(issue.frequency)`, and the page text contains no `very-common`.
    - `the market and model-year chips match the data`: `[data-chip="market"]` is `marketsLabel(issue)` and `[data-chip="years"]` is `modelYearsLabel(issue)`, "All model years" when there is no range.
    - `fix, prevention and how to check show exactly when the data has them`; an issue without a fix shows "No sourced fix yet".
    - `an issue with no cost says no sourced cost` (Review Focus 4): `[data-section="costs"]` has "no sourced cost" and no `$` when `cost` is absent, and the `describeCost` strings when present.
    - `sources show publisher, title, tier and date, linked only for citation hosts`: the sorted `href` list of the page's `a[href^="http"]` anchors in `[data-section="sources"]` equals the sorted URLs of the issue's `isCitationLinkable` sources (a duplicated or missing link fails), and each source's row, addressed by `data-source-list="sources"` and `data-source-index`, shows its publisher and title and has one anchor with exactly its URL when linkable and none when not.
    - `an issue marked inspectWhenBuying shows the checklist chip`.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm typecheck && pnpm build && pnpm build:fixture && pnpm e2e issues.spec.ts`
Expected: FAIL, no issue routes.

- [ ] **Step 3: Implement** the components and the page to the Interfaces above.

- [ ] **Step 4: Format and verify**

Run: `pnpm exec biome check --write src tests && pnpm check && pnpm build && pnpm build:fixture && pnpm e2e`
Expected: exit 0 for both.

- [ ] **Step 5: Commit** (`feat(site): known issue pages as tech cards`).

---

### Task 12: Issues list and the filter

**Files:**
- Create: `src/lib/issue-order.ts`, `src/lib/filters.ts`, `src/components/FilterScope.astro`, `src/pages/[gen]/issues/index.astro`, `tests/e2e/filter.ts`, `tests/unit/issue-order.test.ts`, `tests/unit/filters.test.ts`, `tests/e2e/fixture-only/issues-list.spec.ts`, `tests/e2e/shared/issues-list.spec.ts`
- Modify: `src/pages/[gen]/issues/[issue].astro` (back link and `GenerationNav current="issues"`), `src/lib/routes.ts` (the `issues` section, spec order) and its test, `src/lib/route-list.ts` and its test (`issuesPath(gen)`), `tests/e2e/shared/a11y.spec.ts` and `mobile.spec.ts` (filter states), the fixture set

**Interfaces:**
- Consumes: `marketsAttr`, `marketLabel`, `marketsLabel`, `yearsAttr`, `modelYearsLabel`, `sourcedShopMax`, `Market` (Task 5); `Chip`, `CostBox` (Task 11).
- Produces (`issue-order.ts`): `compareIssues(a: KnownIssue, b: KnownIssue): number` (frequency rank `very-common` > `common` > `rare`; then an issue with a sourced cost (`sourcedShopMax` defined) before one without, and the higher `sourcedShopMax` first; then `title.localeCompare(b.title, 'en')`); `sortIssues(issues: readonly KnownIssue[]): KnownIssue[]` (a copy).
- Produces (`filters.ts`, pure, so the browser script holds no rule): `Selection = { market: Market | 'all'; year: number | 'all' }`; `EntryTags = { markets: readonly Market[]; years: readonly number[] }`; `parseTags(attrs: { markets: string; years: string }): EntryTags`; `isVisible(tags: EntryTags, selection: Selection): boolean` (`all` matches everything; a market or a year must be in the entry's list); `describeSelection(selection: Selection): string` (`all cars`, `US cars`, `model year 2003 cars`, `US cars, model year 2003`); `filterStatus(args: { shown: number; total: number; noun: string; gapNote?: string | undefined; selection: Selection }): { status: string; gap: string | undefined }` (`status` is `Showing {shown} of {total} {noun}`; `gap` is set only when `shown === 0 && total > 0`, as `No sourced {noun} for {describeSelection} yet. {gapNote}`, trimmed so a missing note leaves no trailing space).
- Produces (`FilterScope.astro`, props `generationYears: readonly [number, number]; noun: string`, default slot, root `data-filter-scope`): a fieldset "Show" with a market control (radios named "All markets", "US" and "Euro") and a model-year control (a native `<select>` labelled "Model year", with "All model years" and one option per year of `generationYears`, so the options are the generation's years and nothing else), both `hidden` until the script runs, and a `role="status"` line (`data-filter-status`). One scope serves a whole page. Its bundled `<script>`, which imports `src/lib/filters.ts`, reveals the controls and, on change, reads `data-markets` and `data-years` from every `[data-entry]` element, sets each one's `hidden` from `isVisible`, updates the status line, and inside each `[data-filter-group]` container (a `data-noun`, an optional `data-gap-note`, and one `<p data-gap hidden>` child) fills and shows the gap text when that group shows nothing. The page owns the empty states: a group with no entries renders "No {noun} are published for this generation yet." in its place, and the scope, with its controls, renders whenever any group on the page has an entry, so one empty group never removes the controls its sibling needs. When no group has an entry, the page renders no `FilterScope` at all, only the empty texts. Without JavaScript the controls never appear and every entry stays visible, each carrying market and model-year chips.
- Produces (`tests/e2e/filter.ts`, used by Tasks 14 and 16 and the gates): `selectScope(page: Page, sel: { market?: 'all' | 'us' | 'euro'; year?: number | 'all' }): Promise<void>` (by the accessible names above), `visibleEntries(scope: Locator): Promise<string[]>` (the `data-entry` ids of the visible `[data-entry]` elements), `gapText(group: Locator): Promise<string | undefined>` (the visible `[data-gap]` text), `statusText(page: Page): Promise<string>`.

- [ ] **Step 1: Write the failing tests.**
  - Unit `issue-order.test.ts` (issues built from `loadDataSet(VALID_FIXTURES)` with overrides): `very-common` before `common` before `rare`; at equal frequency a sourced cost before none, and a higher cost first; **an issue with `cost: { shop: [0, 0] }` sorts with the no-cost issues, after a costed one**; titles break ties; `sortIssues` does not mutate its input and is stable on equal keys.
  - Unit `filters.test.ts`:

```ts
test('isVisible: a year outside the entry\'s years hides it (Review Focus 5)', () => {
  const tags = { markets: ['us'], years: [2001, 2002, 2003] } as const
  expect(isVisible(tags, { market: 'all', year: 2003 })).toBe(true)
  expect(isVisible(tags, { market: 'all', year: 2004 })).toBe(false)
  expect(isVisible(tags, { market: 'euro', year: 'all' })).toBe(false)
  expect(isVisible(tags, { market: 'all', year: 'all' })).toBe(true)
})
test('filterStatus names the gap when a selection shows nothing (Review Focus 1)', () => {
  const r = filterStatus({ shown: 0, total: 9, noun: 'maintenance items', gapNote: 'This is a gap in the data, not a sign that nothing is due.', selection: { market: 'euro', year: 2003 } })
  expect(r.status).toBe('Showing 0 of 9 maintenance items')
  expect(r.gap).toBe('No sourced maintenance items for Euro cars, model year 2003 yet. This is a gap in the data, not a sign that nothing is due.')
  expect(filterStatus({ shown: 0, total: 9, noun: 'x', selection: { market: 'us', year: 'all' } }).gap).toBe('No sourced x for US cars yet.')
  expect(filterStatus({ shown: 3, total: 9, noun: 'x', selection: { market: 'all', year: 'all' } }).gap).toBeUndefined()
  expect(filterStatus({ shown: 0, total: 0, noun: 'x', selection: { market: 'us', year: 'all' } }).gap).toBeUndefined()
})
```

    Also `parseTags({ markets: 'us euro', years: '2001 2002' })` and `describeSelection` for each of the four forms.
  - Shared `issues-list.spec.ts`: `every issue is listed once with a link to its page`; `the page links back from each issue and the nav marks issues`; `All markets and All model years are the defaults and show every issue`; `with JavaScript off every issue is visible, the controls are not shown, and each row's chips state its market and model years` (`test.use({ javaScriptEnabled: false })`).
  - Fixture `issues-list.spec.ts` (the fixture build has issues in both markets and with year ranges; each expectation is computed inline from the data, not from the lib):
    - `choosing a market hides exactly the issues that do not apply to it`.
    - `choosing a model year hides exactly the issues whose range excludes it, and an issue with no range always shows`.
    - `the filter reads each row's data attributes` (retag the first row with `evaluate`: `data-years` to one year, `data-markets` to `us`; it hides under another year and under Euro, and returns under All).
    - `the status line counts the visible rows`.
    - `a selection with no entries shows the group's gap text`, over every market and year choice of `fixture-gen2` (its one issue is `[us]`, so Euro is a gap) and of `e46`, compared with the count computed from the data.
    - `rows are in compareIssues order`, against an independent oracle written inline: consecutive rows satisfy (frequency rank desc, then has-cost desc, then high shop cost desc).
  - Extend `a11y.spec.ts` and `mobile.spec.ts`: on any route whose page has visible filter controls (a `[data-filter-scope] select` that is visible), repeat the axe run and the 390 px checks for each market choice and for the first and last year of the run (an empty selection shows the gap text, which axe must pass too). A page with no controls, such as the maintenance page of a generation with no items, still gets the ordinary axe and 390 px checks and skips the permutations, so a gate never waits on a control that is not there. Tasks 14 and 16 are covered by this without edits.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test tests/unit/issue-order.test.ts tests/unit/filters.test.ts && pnpm build && pnpm build:fixture && pnpm e2e issues-list.spec.ts`
Expected: FAIL.

- [ ] **Step 3: Implement** the order lib, the filter lib, `FilterScope`, the helper, the list page (rows: `data-entry={id}`, title link, frequency, chips for market, model years and verified, the first symptom, `data-markets={marketsAttr(issue)}` and `data-years={yearsAttr(issue, generation.years)}`; the list in one `data-filter-group` with `data-noun="known issues"` and `data-gap-note="This is a gap in the data, not a sign that no issues exist."`), the detail page's back link and nav, and the `issues` section.

- [ ] **Step 4: Format and verify**

Run: `pnpm exec biome check --write src tests && pnpm check && pnpm build && pnpm build:fixture && pnpm e2e`
Expected: exit 0 for both.

- [ ] **Step 5: Commit** (`feat(site): known issues list with market and model-year filters`).

---

### Task 13: Interval library

**Files:**
- Create: `src/lib/intervals.ts`
- Test: `tests/unit/intervals.test.ts`

**Interfaces:**
- Consumes: `formatNumber` (Task 5), `MaintenanceItem` (schemas).
- Produces: `type Trigger = NonNullable<MaintenanceItem['interval']['triggers']>[number]`; `TRIGGER_LABELS: Record<Trigger, string>`, with these exact texts:
  - `break-in`: `Break-in service`
  - `oil-service`: `Each oil service`
  - `inspection-i`: `Every inspection: Inspection I, and again at each Inspection II`
  - `inspection-ii`: `Inspection II only`
  - `lifetime-fill`: `Lifetime fill: no scheduled change`
  - `condition-based`: `Condition based: decided by monitoring the part`
- `IntervalView = { due: string[]; numbers: string[]; everyInspection: boolean; noScheduledService: boolean }`; `describeInterval(interval: MaintenanceItem['interval']): IntervalView`; `compareSchedule(a: MaintenanceItem, b: MaintenanceItem): number`.

Rules: `due` lists each trigger's label in schedule order. `numbers` has `Every 100,000 miles` and `Every 24 months` for a plain interval, and `Up to 60,000 miles (the manufacturer's stated maximum)` beside `condition-based`, never a mileage made up from a trigger. `everyInspection` is true when the triggers include `inspection-i`. `noScheduledService` is true for `lifetime-fill` and `condition-based`. `compareSchedule` sorts in four bands: items with a scheduled-service trigger first (by the lowest of `break-in` 0, `oil-service` 1, `inspection-i` 2, `inspection-ii` 3 across the item's triggers); then items with only `miles` or `months` (by miles, then months); then `condition-based`; then `lifetime-fill`; ties by `title`.

- [ ] **Step 1: Write the failing tests.**

```ts
test('inspection-i reads as every inspection (Review Focus 3)', () => {
  const v = describeInterval({ triggers: ['inspection-i'] })
  expect(v.due).toEqual(['Every inspection: Inspection I, and again at each Inspection II'])
  expect(v.everyInspection).toBe(true)
  expect(describeInterval({ triggers: ['oil-service', 'inspection-i'] }).everyInspection).toBe(true)
  expect(describeInterval({ triggers: ['inspection-ii'] })).toMatchObject({ due: ['Inspection II only'], everyInspection: false })
})
```

Also: `[break-in, inspection-ii]` gives two labels in that order and no numbers; `{ miles: 100000 }` gives `numbers` `['Every 100,000 miles']` and an empty `due`; `{ months: 24 }` gives `['Every 24 months']`; `{ triggers: ['condition-based'], miles: 60000 }` gives the "Up to ..." text and `noScheduledService`; `{ triggers: ['lifetime-fill'] }` gives its label and `noScheduledService`; `compareSchedule` orders a `break-in` item, an `oil-service` item, an `inspection-i` item, an `inspection-ii` item, a `{ miles: 60000 }` item, a `{ miles: 100000 }` item, a `condition-based` item and a `lifetime-fill` item exactly in that order, puts two `lifetime-fill` items in title order, and breaks a tie by title.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test tests/unit/intervals.test.ts`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement** the module to the signatures and rules above.

- [ ] **Step 4: Format and verify**

Run: `pnpm exec biome check --write src/lib tests/unit && pnpm test tests/unit/intervals.test.ts && pnpm typecheck`
Expected: PASS, exit 0.

- [ ] **Step 5: Commit** (`feat(site): maintenance interval description and schedule order`).

---

### Task 14: Maintenance page

**Files:**
- Create: `src/pages/[gen]/maintenance/index.astro`, `tests/e2e/shared/maintenance.spec.ts`, `tests/e2e/fixture-only/maintenance.spec.ts`
- Modify: `src/lib/routes.ts` (the `maintenance` section) and its test, `src/lib/route-list.ts` and its test, `tests/unit/data/site-fixture.test.ts`, the fixture set

**Interfaces:**
- Consumes: `describeInterval`, `compareSchedule` (Task 13); `FilterScope`, `filter.ts` helpers (Task 12); `Chip`, `CostBox` (Task 11); `SourceList`, `Tier` (Task 7); `marketsAttr`, `yearsAttr`, `marketsLabel`, `modelYearsLabel` (Task 5).
- Produces: `/[gen]/maintenance/`: `FilterScope` (`generationYears={generation.years}`, `noun="maintenance items"`) around one `data-filter-group` (`data-noun="maintenance items"`, `data-gap-note="This is a gap in the data, not a sign that nothing is due."`), a one-line legend ("BMW often ties a service to a trigger instead of a mileage. Triggers are shown as BMW gives them, and this site does not turn them into mileages."), and a schedule table in `compareSchedule` order. Columns: Service (title, the `engine` code when present, and `notes` when present), Due (`due` labels and `numbers`, with an `every inspection` emphasis when `everyInspection`), Parts and fluids, Cost (`CostBox`), Status (`Chip kind="verified"`), Applies to (`Chip kind="market"` and `Chip kind="years"`, "All model years" when the item has no `modelYears`), Sources (`SourceList` in a `<details>`). Each row carries `data-entry={id}`, `data-markets={marketsAttr(item)}` and `data-years={yearsAttr(item, generation.years)}`. On a phone the rows stack, as in the mock-up's `.lines` rules. A generation with no items renders "No maintenance items are published for this generation yet." and neither a table nor a `FilterScope`.

**Fixture additions** (`maintenance/e46/`, all `markets: [us]` except where noted; every item needs a Tier 1 source for `lifetime-fill` and `condition-based`): `fixture-coolant-us-2001-2003` (`modelYears: [2001, 2003]`, `months: 48`), `fixture-coolant-us-2004-2006` (`[2004, 2006]`, `lifetime-fill`), `fixture-engine-oil` (no `modelYears`, triggers `[break-in, oil-service, inspection-i]`, a sourced cost, `inspectWhenBuying: true`), `fixture-gearbox-oil` (`[break-in, inspection-ii]`), `fixture-brake-fluid` (`months: 24`, **`verified: false`** with one Tier 2 source, `inspectWhenBuying: true`), `fixture-air-filter` (`[inspection-ii]`, `inspectWhenBuying: false`), `fixture-transmission-monitored` (`markets: [euro]`, `modelYears: [2004, 2006]`, `condition-based` with `miles: 60000`, `inspectWhenBuying: false`). Euro with model year 2002 is therefore an empty selection, and Euro as a whole has one item. Extend `site-fixture.test.ts` to assert each fact.

- [ ] **Step 1: Write the failing tests.**
  - Shared `maintenance.spec.ts`, from `dataSet.maintenance` (it passes with zero items, with PR #41's nine and with the fixture's): `every item is a row`; `a generation with no items shows "No maintenance items are published" and no table`; `cost reads no sourced cost when the item has none, and the figures when it has`; `parts, fluids, engine, status and the market and model-year chips match the data`; `with JavaScript off every item is a row and the chips state market and model years`.
  - Fixture `maintenance.spec.ts`, expectations computed inline from the data:
    - `rows are in schedule order`: scheduled-trigger rows (`break-in`, `oil-service`, `inspection-i`, `inspection-ii`) come before every row without one, and among them the lowest trigger rank never decreases; after them come miles-or-months-only rows, then `condition-based`, then `lifetime-fill` rows. Only the four scheduled triggers are compared for rank.
    - `inspection-i rows say every inspection` (Review Focus 3): the `fixture-engine-oil` row text matches /every inspection/i, and the `[break-in, inspection-ii]` row says "Inspection II only".
    - `an unverified item shows Unverified`: `fixture-brake-fluid`'s `[data-chip="verified"]` reads "Unverified".
    - `selecting a model year hides exactly the rows that do not apply` (Review Focus 5): for every year of the run, a row is visible exactly when its item has no `modelYears` or `from <= year && year <= to`, written inline. For 2002 only the 2001 to 2003 coolant shows of the two coolant items, for 2005 only the 2004 to 2006 one, and the no-range oil row shows for every year.
    - `a selection with no sourced items says so` (Review Focus 1): over every market (All, US, Euro) and model year (All and each year), the group's gap text is visible exactly when items exist and none applies, and then no row is visible. Euro with 2002 is a gap here.
    - `a generation with no items shows the empty state` (`fixture-gen2`).

- [ ] **Step 2: Run to verify failure**

Run: `pnpm typecheck && pnpm build && pnpm build:fixture && pnpm e2e maintenance.spec.ts`
Expected: FAIL, no route.

- [ ] **Step 3: Implement** the page to the Interfaces above, the fixture items, and the nav section.

- [ ] **Step 4: Format and verify**

Run: `pnpm exec biome check --write src tests && pnpm check && pnpm build && pnpm build:fixture && pnpm e2e`
Expected: exit 0 for both.

- [ ] **Step 5: Commit** (`feat(site): maintenance schedule page`).

---

### Task 15: Checklist library

**Files:**
- Create: `src/lib/checklist.ts`
- Test: `tests/unit/checklist.test.ts`

**Interfaces:**
- Consumes: `sortIssues`, `compareIssues` (Task 12), `compareSchedule` (Task 13), `sourcedShopMax` (Task 5).
- Produces: `Checklist = { issues: KnownIssue[]; service: MaintenanceItem[] }`; `buildChecklist(input: { issues: readonly KnownIssue[]; maintenance: readonly MaintenanceItem[] }): Checklist`. It keeps only entries with `inspectWhenBuying: true`. Issues are in `compareIssues` order. Service items put a sourced cost first (`sourcedShopMax` defined, higher first, none last), then `compareSchedule`. It copies its inputs and never filters by market or model year (the page's `FilterScope` does).

- [ ] **Step 1: Write the failing tests** (entries built from `loadDataSet(VALID_FIXTURES)` with overrides): only `inspectWhenBuying: true` entries appear, and a fixture with `false` is excluded; issues run `very-common`, `common`, `rare`; at equal frequency a costed issue precedes an uncosted one and an issue costed `[0, 0]` counts as uncosted; service items sort by cost then schedule; the inputs are frozen with `Object.freeze` and not mutated; an empty input gives `{ issues: [], service: [] }`; an entry with `markets: ['us']` or a `modelYears` range is still returned.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test tests/unit/checklist.test.ts`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement** `buildChecklist` to the Interfaces above.

- [ ] **Step 4: Format and verify**

Run: `pnpm exec biome check --write src/lib tests/unit && pnpm test tests/unit/checklist.test.ts && pnpm typecheck`
Expected: PASS, exit 0.

- [ ] **Step 5: Commit** (`feat(site): used-buyer checklist ordering`).

---

### Task 16: Used-buyer checklist page

**Files:**
- Create: `src/pages/[gen]/buying/index.astro`, `tests/e2e/shared/buying.spec.ts`, `tests/e2e/fixture-only/buying.spec.ts`
- Modify: `src/lib/routes.ts` (the `buying` section) and its test, `src/lib/route-list.ts` and its test, the fixture set

**Interfaces:**
- Consumes: `buildChecklist` (Task 15); `describeInterval` (Task 13); `FilterScope`, `filter.ts` helpers (Task 12); `Chip`, `CostBox` (Task 11); `issuePath`, `marketsAttr`, `yearsAttr`, `marketsLabel`, `modelYearsLabel` (Task 5).
- Produces: `/[gen]/buying/` with two ordered groups (R87.1). An intro ("What to check on a used car, most common problem first, then most costly. An item with no sourced cost is not free: no source states a price."). One `FilterScope` (`generationYears={generation.years}`, `noun="checklist items"`) around both groups, each its own `data-filter-group` with its own `<p data-gap hidden>` and gap note ("This is a gap in the data, not a sign that nothing needs checking."). "Known problems": each entry has the title linked to `issuePath`, the frequency, market, model-year and verified chips, the `howToCheck` text and `CostBox`. "Service history to ask for": each entry has the title, the due labels and numbers from `describeInterval` (`inspection-i` reads as due at every inspection), the market, model-year **and verified** chips, the `howToCheck` text and `CostBox`. Every entry has `data-entry`, `data-markets` and `data-years`. An entry with no `modelYears` reads "All model years" and shows under every year. A group with no entries renders its own empty text and leaves the controls to its sibling.

**Fixture additions:** the issue costs and frequencies that make the order non-vacuous (a `very-common` issue with no cost, a `common` issue costed at the top of the range, a `common` issue costed lower, a `common` issue with no cost, a `rare` one), all with `inspectWhenBuying: true`; `fixture-engine-oil` and `fixture-brake-fluid` from Task 14 are the service entries (the first with an `inspection-i` trigger and a cost, the second unverified). Extend `site-fixture.test.ts` to assert them.

- [ ] **Step 1: Write the failing tests.**
  - Shared `buying.spec.ts`, data-driven (passes with an empty service group): `the checklist holds exactly the entries marked inspectWhenBuying` (the set of titles equals the set of flagged issues and maintenance items of the generation, and an entry with `false` is absent); `each entry shows its how-to-check text, and each problem links to its page`; `an entry with no cost says no sourced cost`; `with JavaScript off every entry is visible and labelled`.
  - Fixture `buying.spec.ts`, expectations computed inline:
    - `known problems run by frequency, then cost`: consecutive entries satisfy (frequency rank desc, then has-cost desc, then high shop cost desc), which is non-vacuous because the fixture mixes frequencies and costs.
    - `a service-history row for inspection-i says every inspection` (Review Focus 3).
    - `a service-history row shows the verified chip`, and `fixture-brake-fluid` reads "Unverified" (Review Focus 4).
    - `a selection with no sourced entries names the gap in each group` (Review Focus 1): over every market and model year, each group shows its gap text exactly when it has entries but none applies, and then shows no entry; the other group is judged on its own, and the controls stay while either group has entries. In the fixture, Euro empties the service group while known problems still show.
    - `selecting a market or a model year hides exactly the entries that do not apply` (Review Focus 5), the model-year rule written inline (`no modelYears`, or `from <= year && year <= to`).
    - `a generation whose service group is empty shows its empty text and keeps the controls` (`fixture-gen2`: one issue, no maintenance).

- [ ] **Step 2: Run to verify failure**

Run: `pnpm typecheck && pnpm build && pnpm build:fixture && pnpm e2e buying.spec.ts`
Expected: FAIL, no route.

- [ ] **Step 3: Implement** the page to the Interfaces above, the fixture additions, and the nav section.

- [ ] **Step 4: Format and verify**

Run: `pnpm exec biome check --write src tests && pnpm check && pnpm build && pnpm build:fixture && pnpm e2e`
Expected: exit 0 for both.

- [ ] **Step 5: Commit** (`feat(site): used-buyer checklist page`).

---

### Task 17: About page with derived data sources

**Files:**
- Create: `src/lib/data-sources.ts`, `tests/unit/data-sources.test.ts`, `tests/e2e/shared/about.spec.ts`
- Modify: `src/data/site.ts` (add `loadAllSources`), `src/pages/about.astro`

**Interfaces:**
- Consumes: `NOTICE`, `Drawer`, `Tier`, `TIER_LABEL`, `formatDate`.
- Produces (`data-sources.ts`): `SourceSummary = { publisher: string; bestTier: 1 | 2 | 3; citations: number; latestAccessed: string }`; `summarizeSources(sources: readonly Source[]): SourceSummary[]`, which groups by publisher compared after trimming, collapsing spaces and ignoring case (the same rule as `sources.ts`), keeps the first-seen spelling for display, and sorts by `bestTier` ascending, `citations` descending, then publisher.
- Produces (`site.ts`): `loadAllSources(): Promise<Source[]>`, every source of every entry in all five collections.

`/about` content: the notice (`NOTICE` in a `<p>`); what the site is and is not ("It sells nothing and links to no stores."); licenses (code MIT, data CC BY-SA 4.0, 3D models "to be confirmed", the existing allowlisted links); Data sources (a table of `summarizeSources`: publisher, best tier, citations, last accessed, all text, plus "Sources are cited as text. Only non-commercial references are linked."); Credits: the existing placeholder about reference photos, and the fonts, as text with no link: "Big Shoulders Display and Geist, SIL Open Font License 1.1" (self-hosting is redistribution).

- [ ] **Step 1: Write the failing tests.** Unit: `Shop A` and ` shop  a ` are one publisher with `citations` 2 and the first spelling shown; `bestTier` is the lowest tier cited; order is tier, then count, then name; `latestAccessed` is the latest date; `[]` gives `[]`. E2e (shared): `/about/` main contains `NOTICE` and the words MIT and CC BY-SA 4.0, and the fonts credit; every distinct publisher in the build's data appears once, and the row count equals the count of distinct normalised publishers computed independently in the test; no anchor on the page points outside the allowlist; the page still says nothing is for sale.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test tests/unit/data-sources.test.ts && pnpm build && pnpm build:fixture && pnpm e2e about.spec.ts`
Expected: FAIL.

- [ ] **Step 3: Implement** the lib, the loader and the page to the Interfaces above.

- [ ] **Step 4: Format and verify**

Run: `pnpm exec biome check --write src tests && pnpm check && pnpm build && pnpm build:fixture && pnpm e2e`
Expected: exit 0 for both.

- [ ] **Step 5: Commit** (`feat(site): about page lists data sources and credits the fonts`).

---

### Task 18: Docs and final verification

**Files:**
- Modify: `AGENTS.md` (Layout), `docs/standards/testing.md`, `CONTRIBUTING.md`

The route-wide gates (axe, 390 px, notice, noindex, links, cross-origin) already run on every page since Task 2, so this task fixes nothing open-ended: it documents and verifies.

- [ ] **Step 1: Update the docs.**
  - `AGENTS.md`: extend the `src/lib/` line in "Layout" to name the display libraries (format, money, markets, model years, citations, intervals, filters, checklist), add `src/data/site.ts`, `tests/e2e/{shared,fixture-only}`, `tests/fixtures/site-data` and `tests/shots`, name `SITE_DATA_DIR`, `SITE_OUT_DIR` and `SHOOT` as settings, and change the `pnpm e2e` row to say it needs `pnpm build && pnpm build:fixture` first.
  - `docs/standards/testing.md`: two builds and two projects (`real` runs `shared/`, `fixture` runs `shared/` and `fixture-only/`); page e2e tests are data-driven, and the rules the real data cannot exercise are tested against `tests/fixtures/site-data`; the route-wide gates; CI screenshots are a run artifact and never an assertion.
  - `CONTRIBUTING.md`: the `pnpm build:fixture` step before `pnpm e2e`.

- [ ] **Step 2: Final verification**

Run: `pnpm check && pnpm build && pnpm build:fixture && pnpm check:links:fixture && pnpm e2e`
Expected: exit 0 for all, with both projects green.

- [ ] **Step 3: Commit** (`docs: describe the display libraries, the fixture build and the page gates`).
