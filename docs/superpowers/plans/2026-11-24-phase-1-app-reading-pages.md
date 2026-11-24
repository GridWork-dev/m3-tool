# Phase 1 App Lane, Plan 1: Reading Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The read side of the site, on the B2 "pit garage" design: home, the generation page (specs, variants, hero drawing), known issues (list and detail), maintenance, the used-buyer checklist and `/about`, all rendered from the data that exists on `main`. Issues, maintenance and the checklist filter and label by market and by model year.

**Architecture:**
- Static Astro pages over the content collections. Every rule that decides what a page shows (markets, model years, the filter, intervals, unverified marks, costs, citations, checklist order) is a pure function in `src/lib/`, unit-tested against fixtures. Components stay thin.
- The B2 tokens move into the Tailwind theme once, in `src/styles/`, and fonts are self-hosted through Astro's Fonts API.
- Page e2e tests are data-driven: they read `data/` through `loadDataSet` and assert what each page shows for each entry. New or changed data needs no test edit, and the plan does not wait for the maintenance data PR (#41). Its one outside dependency is the data lane's `modelYears` contract PR, for Tasks 9 to 14.

**Tech Stack:** Astro 7.4.13 (static, content collections, Fonts API), Tailwind 4.3.5, TypeScript 7.0.2 via `pnpm typecheck`, Vitest 5.1.1, Playwright 1.65.1, Biome 2.6.8, plus one new dev dependency, `@axe-core/playwright` 4.14.0 (Task 16). No React in this plan: it has no island.

**Spec:** `docs/superpowers/specs/2026-11-23-m3-tool-design.md` (sections 1, 2, 7.2, 7.3, 7.6, 10, 15, 17). Also `AGENTS.md` (it wins over the spec), `docs/standards/{code,testing,data,legal}.md` and `docs/design/` (B2 tokens and the mock-up `b2-garage.html`).

## Roadmap: the app lane in five plans

The spec's Phase 1 app lane has five subsystems that share only components and `src/lib`. Each plan below produces working, testable software on its own. This file is Plan 1.

1. **Reading pages (this plan).** B2 tokens, self-hosted fonts and the site shell; home, `/[gen]/` (specs, variants, hero drawing), known issues (list and detail), maintenance, buyer checklist, and `/about` with a derived data-sources list. Needs: the data on `main`, and for Tasks 9 to 14 the data lane's `contract` PR that adds an optional `modelYears` to `MaintenanceItem` and `KnownIssue` (this plan writes no schema change). Tasks 1 to 8 and 15 do not wait for it.
2. **Prices and mods.** `src/lib/price.ts` (90-day range, stale after 60 days, generic-tier price computed from the category's real products), then `/[gen]/mods/` and `/[gen]/mods/[part]` (seller and checked date as text, tier badge, "3D look approximate", labor marked "estimated", a part with no price shows "no price recorded"). Needs: Plan 1's components, parts data from the data lane, prices from the scraping lane.
3. **Build logic.** `src/lib/rules.ts`, `cost.ts` and `codec.ts` with unit tests, including a fixture for every saved link version. Pure TypeScript, no UI. Needs: the schemas, and `price.ts` (Plan 2, Task 1). Runs in parallel with the rest of Plan 2.
4. **Build sheet and share links.** `/[gen]/build` as one `client:only="react"` island (zustand, the B2 work order, fitment reasons, rate, tax and DIY, empty and first-visit states), with the build in the URL hash through the codec. No 3D. Needs: Plans 2 and 3.
5. **Search and beta readiness.** Pagefind UI and `data-pagefind-body`, sitemap and robots, Cloudflare Web Analytics, and the checklist for flipping `PUBLIC_INDEXABLE`. Needs: Plans 1 to 4, and the user's domain for the final flip.

**Why this order.** The spec's Phase 1 exit is a public beta of the whole text tool, so no plan can ship alone to the public. Reading pages go first because their data exists now (issues and variants on `main`, maintenance in #41), they need no prices and no parts, and they build the components and tokens Plans 2 to 4 reuse. Build logic is pure and could start first, but its only input that does not exist yet is price data, so it follows `price.ts` instead.

**Gated, in no plan here:** the hero outline swap waits for the 3D spike, and the Gearwell rename waits for the domain. Task 1 puts the site name in one constant (`SITE_NAME`) and the hero outline in one file, so each is a one-place change later.

## Global Constraints

Every task's requirements include this section. Quoted lines are copied from `AGENTS.md`, the spec and `docs/standards/data.md`.

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
- "Pages that render these fields show a per-value "unverified" marker, taken from this field and not from the comments. A value is covered, and gets the marker, when its own path is listed, or the path of an object or element above it." (`unverified` on a generation or variant.)
- "A page that shows an item's triggers shows an `inspection-i` item as due at every inspection, not only at Inspection I."
- "`markets` names the markets a maintenance item's or a known issue's sources speak for: a non-empty list of `us` or `euro`, each at most once." Spec 7.3: "(`us`, `euro`, or every market when left out)". This plan's reading: `markets` decides which market an entry is shown for, and an entry with no `markets` is shown for both.
- Model years (coordinator input, 2026-11-24, until the contract PR's `data.md` text lands, then quote that): BMW changed the E46 coolant schedule partway through the run (every 4 years for model years 2001 to 2003, lifetime from 2004), so a maintenance item or issue may carry `modelYears`, `[from, to]` with `to` optional. This plan's reading: `modelYears` decides which model years an entry is shown for. `[2001, 2003]` is 2001 to 2003, `[2004]` is 2004 and every later year of the run, and an entry with no `modelYears` applies to every year: it is labelled "All model years" and shown under every year choice.
- "A source renders as a citation: its publisher, title and accessed date, always as text. Its `url` is a link only when the host is on `CITATION_HOSTS` (`archive.org`, `web.archive.org`, `newsroom.bmwgroup.com`, `en.wikipedia.org`, `commons.wikimedia.org`), which `isCitationLinkable` tests. Any other URL is not linked, and a Tier 2 retailer never is."
- Dates are calendar dates, shown as `YYYY-MM-DD`. A frequency is `very-common` in YAML and "Very common" on the page, never the slug.

**Design (`docs/design/README.md`)**
- Direction B2: dark only, spec groups as tool-chest drawers, the key figures on a yellow pit board, a known issue as a tech card on a pegboard. Big Shoulders Display for headings, Geist for text, tabular numerals.
- WCAG AA contrast, a visible focus ring on every stop, 44 px tap targets on phone (390 px), and every state the mock-up settles (empty, stale, unverified).
- No colour literal outside `src/styles/tokens.css`: use tokens.
- Run each UI task through the `impeccable` skill before its commit (spec section 17), then check it against the mock-up.

**Code (AGENTS.md, `docs/standards/code.md`)**
- `tsconfig` extends `astro/tsconfigs/strictest`, so `exactOptionalPropertyTypes` is on: write optional parameters and fields as `x?: T | undefined`. Imports use explicit `.ts` extensions, `import type` for types, no enums, no namespaces. Run `pnpm typecheck`, never a bare `tsc`.
- Pure logic goes in `src/lib` with a unit test, written first. Components call into `src/lib` and render the result.
- Biome formats: single quotes, no semicolons, 100 columns. Pin dependencies exactly (`--save-exact`) and add one in the task that first uses it.
- Astro scoped styles do not reach slot content, so a rule that targets content a page passes into a component uses `:global()`.
- Contract files (`src/data/schemas.ts`, `src/data/unverified.ts`, `src/lib/asset-contract.ts`, `docs/standards/3d-assets.md`) "change only in a dedicated PR labeled `contract`". This plan changes none. If a task finds it needs one, stop and raise a `contract` PR first.

**Out of scope:** the 3D lane, the hero outline swap, the Gearwell rename, scraping or price collection, and writing data entries.

**Workflow (AGENTS.md)**
- "Run `pnpm check` and `pnpm e2e` green, push, and open a PR from the template. Say `Closes #<issue>`. UI and 3D changes carry before-and-after screenshots." Commits use Conventional Commits, staged by path, never `git add -A`. The only trailer is `Co-Authored-By:`, with no `Claude-Session` trailer and no session URL.
- Every subagent gets a pinned model. Implementers are Sonnet 5.5. Review is Sonnet plus a Codex second opinion through `codex-review` when the orchestrator is Opus.

**Landing procedure.** Tasks land in six groups, one PR each, in order. Work on branch `feat/p1-<group>` in its own worktree (`git worktree add ../m3-tool.worktrees/p1-<group> -b feat/p1-<group> origin/main`, then `pnpm install` and `uv sync --project pipeline`).

| Group | Tasks | PR title |
|---|---|---|
| A | 1 to 2 | `feat(site): B2 tokens, self-hosted fonts and the site shell` |
| B | 3 to 5 | `feat(site): display libraries and the generation page` |
| C | 6 to 8 | `feat(site): variants, hero drawing and the home page` |
| D | 9 to 10 | `feat(site): known issues pages` |
| E | 11 to 14 | `feat(site): maintenance schedule and buyer checklist` |
| F | 15 to 16 | `feat(site): about page data sources and site-wide gates` |

Before a PR opens: `pnpm check` exits 0, then `pnpm build && pnpm e2e` exits 0. Screenshots never enter the repo (`tests/unit/repo-hygiene.test.ts` forbids tracked images). Serve the branch with `pnpm preview --port 4321`, capture each changed route at 390 x 844 and 1280 x 800 with `pnpm exec playwright screenshot --viewport-size=390,844 --full-page http://localhost:4321/<route> <scratch>/after-<name>-390.png`, and capture the same routes from production (`https://m3-tool.broken-wood-97a9.workers.dev`) as the "before". A new route has no before: say so. The orchestrator attaches the PNGs to the PR by hand, because `gh` cannot upload images, and the PR body links the PR's preview URL.

## Review Focus

Inputs and conditions the spec implies and no happy path covers, most likely first. Each line has a named test in its owning task.

1. **A selection with no sourced entries, by market or by model year.** Every maintenance item in PR #41 is `markets: [us]`, so the Euro view of the maintenance page and the checklist is empty, and a model year can be empty too. Expect a visible "gap in the data" notice for that selection, in each group, never a blank list that reads as "nothing is due". Task 10 `filterStatus names the gap when a selection shows nothing`; Task 12 `a selection with no sourced items says so`; Task 14 `a selection with no sourced entries names the gap in each group`.
2. **A source URL on a retailer, CDN or forum host rendered as a link.** The data cites `cdn.shopify.com` copies of BMW bulletins and forum-adjacent publishers. Expect text only, and a link only for `CITATION_HOSTS`. Task 4 `no source in data/ is linked unless isCitationLinkable allows it`; Task 5 `source anchors are exactly the linkable sources`.
3. **An `inspection-i` item shown as due at Inspection I only.** It is due at every inspection, because Inspection II repeats it. Task 11 `inspection-i reads as every inspection`; Task 12 `inspection-i rows say every inspection`.
4. **A flag, marker or value misread.** `verified: false` shown as verified, a typo in an `unverified` path template silently dropping a marker, `very-common` leaking as a slug, an absent or `[0, 0]` cost shown as `$0`. Task 3 `describeCost never shows zero`; Task 6 `every listed unverified path is marked, and nothing else is`; Task 9 `the verified chip follows the flag`, `frequency never shows as a slug` and `an issue with no cost says no sourced cost`.
5. **Model-year scoping read wrongly.** `[2004]` treated as 2004 only (or as NaN, because `to` is missing), a range that runs past the generation's last year, a range wholly outside the run, or the split coolant items (2001 to 2003 and 2004 on) both showing for one year. Task 3 `appliesToYear: a missing to is open-ended` and `yearsAttr clamps to the run and is empty outside it`; Task 10 `isVisible: a year outside the entry's years hides it`; Task 12 `selecting a model year hides exactly the rows that do not apply`.

## File structure

```
src/styles/tokens.css            the mock-up's :root tokens, verbatim minus the two font stacks      (Task 1)
src/styles/theme.css             Tailwind @theme inline aliases for colours, radii and shadows        (Task 1)
src/styles/global.css            imports, base element rules, .sr utility                             (Task 1)
astro.config.ts                  `fonts`: Big Shoulders Display and Geist, self-hosted                (Task 1)
src/lib/notice.ts                NOTICE, the footer and /about text                                   (Task 1)
src/lib/site.ts                  SITE_NAME, pageTitle                                                 (Task 1)
src/layouts/Base.astro           skip link, top bar, fonts, noindex, footer                           (Task 2)
src/components/SiteNav.astro     top bar                                                              (Task 2)
src/components/SiteFooter.astro  footer, NOTICE from the constant                                     (Task 2)
src/lib/format.ts                dates, numbers, years, labels for frequency, transmission, body      (Task 3)
src/lib/money.ts                 USD ranges and "no sourced cost"                                     (Task 3)
src/lib/routes.ts                path builders, GENERATION_SECTIONS                                   (Task 3)
src/lib/markets.ts               Market, appliesToMarket, labels, data-markets value                  (Task 3)
src/lib/model-years.ts           ModelYears, appliesToYear, label, data-years value                   (Task 3)
src/lib/citations.ts             citationView, latestAccessed                                         (Task 4)
src/lib/unverified-marks.ts      isUnverified, unverifiedUnder                                        (Task 4)
src/data/site.ts                 typed loaders over the content collections                           (Task 5)
src/components/{Drawer,Tier,Mark,SourceList,GenerationNav}.astro                                      (Task 5)
src/pages/[gen]/index.astro      the generation page                                                  (Tasks 5 to 7)
src/components/VariantPanel.astro                                                                     (Task 6)
src/lib/hero-layout.ts           dimension-line geometry from the data                                (Task 7)
src/components/hero/coupe-outline.ts   the generic outline: the one file the spike's tracing replaces (Task 7)
src/components/{HeroDrawing,PitBoard}.astro                                                           (Task 7)
src/pages/index.astro            pick a generation                                                    (Task 8)
src/components/{Chip,CostBox}.astro, src/pages/[gen]/issues/[issue].astro                             (Task 9)
src/lib/issue-order.ts           compareIssues                                                        (Task 10)
src/lib/filters.ts               Selection, isVisible, filterStatus (the market and year filter)       (Task 10)
src/components/FilterScope.astro, src/pages/[gen]/issues/index.astro                                  (Task 10)
src/lib/intervals.ts             describeInterval, compareSchedule, TRIGGER_LABELS                    (Task 11)
src/pages/[gen]/maintenance/index.astro                                                               (Task 12)
src/lib/checklist.ts             buildChecklist                                                       (Task 13)
src/pages/[gen]/buying/index.astro                                                                    (Task 14)
src/lib/data-sources.ts          summarizeSources; src/pages/about.astro rewritten                    (Task 15)
tests/unit/*.test.ts  tests/unit/helpers/contrast.ts
tests/e2e/{data,routes,unverified}.ts  tests/e2e/{site,generation,variants,hero,home,issues,issues-list,maintenance,buying,about,a11y,mobile}.spec.ts
```

## Execution map

| Task | Needs | Parallel with |
|---|---|---|
| 1 Tokens, fonts, constants | none | none |
| 2 Site shell | 1 | none |
| 3 Display libs | 1 | 2, 4 |
| 4 Citation and unverified libs | none | 2, 3 |
| 5 Generation page: specs | 2, 3, 4 | none |
| 6 Variants | 5 | 7, 8 |
| 7 Hero and pit board | 3, 5 | 6, 8 |
| 8 Home page | 3, 5 | 6, 7 |
| 9 Issue detail | 3, 4, 5, contract PR | 11 |
| 10 Issues list and filter scope | 3, 5, 9 | 11 |
| 11 Interval lib | 3 | 9, 10 |
| 12 Maintenance page | 10, 11, contract PR | 13 |
| 13 Checklist lib | 3, 10 | 12 |
| 14 Buyer checklist page | 9, 10, 13, contract PR | none |
| 15 About: data sources | 4, 5 | 12 to 14 |
| 16 Site-wide gates and docs | all | none |

"contract PR" is the data lane's PR adding optional `modelYears` to `MaintenanceItem` and `KnownIssue`. Tasks 9, 12 and 14 read the field, and Task 9's type test fails `pnpm typecheck` until it is on `main`, so groups D and E wait for it. Groups A to C and Task 15 do not.

Tasks that run in parallel both touch `src/lib/routes.ts` or `tests/e2e/routes.ts`: merge one at a time and rebase between.

---

### Task 1: Design tokens, fonts and shared constants

**Files:**
- Create: `src/styles/tokens.css`, `src/styles/theme.css`, `src/lib/notice.ts`, `src/lib/site.ts`, `tests/unit/helpers/contrast.ts`
- Modify: `src/styles/global.css`, `astro.config.ts`
- Test: `tests/unit/notice.test.ts`, `tests/unit/site.test.ts`, `tests/unit/tokens.test.ts`

**Interfaces:**
- Produces: `NOTICE: string` (`src/lib/notice.ts`); `SITE_NAME = 'm3-tool'` and `pageTitle(title?: string | undefined): string` (`src/lib/site.ts`); CSS custom properties from `tokens.css` (`--floor`, `--board`, `--s-4`, `--fs-md`, `--r-md`, `--sh-board`, and the rest); Tailwind utilities `bg-floor`, `text-muted`, `border-line` and so on from `theme.css`; the font variables `--font-display` and `--font-sans`, provided by Astro's `<Font>` component (Task 2).
- Produces for tests: `contrastRatio(foreground: string, background: string): number` (WCAG 2.x, hex inputs) in `tests/unit/helpers/contrast.ts`.

- [ ] **Step 1: Write the failing tests**

```ts
// notice.test.ts: the notice is pinned to the rulebook, not just to itself
test('NOTICE is the exact text in AGENTS.md and the legal standard', () => {
  expect(NOTICE).toBe('Independent fan project. Not affiliated with, endorsed by, or sponsored by BMW AG. BMW and M3 are trademarks of BMW AG, used here only to describe the cars.')
  for (const file of ['AGENTS.md', 'docs/standards/legal.md']) expect(readFileSync(file, 'utf8')).toContain(NOTICE)
})
// site.test.ts
expect(pageTitle()).toBe('m3-tool')
expect(pageTitle('About')).toBe('About · m3-tool')
expect(pageTitle('   ')).toBe('m3-tool')
```

`tokens.test.ts` reads `src/styles/tokens.css` and checks:
- `contrastRatio('#000000', '#ffffff')` is 21 (helper self-check).
- `test.each` of text pairs, each at least 4.5: `--text`, `--muted`, `--dim` on `--floor`; `--muted` and `--dim` on `--steel-2`; `--board-ink` on `--board`; `--board` on `--floor` (link colour); `--canary-ink` on `--canary`; `--canary-muted` and `--stale` on `--canary` and on `--canary-2`; `--hot` on `--floor` and on `--steel-2`. Non-text: `--edge` on `--floor` is at least 3.
- `no raw colour literals outside tokens.css`: no match of `#[0-9a-fA-F]{6}\b`, `#[0-9a-fA-F]{8}\b`, `rgb(`, `rgba(`, `hsl(` in `src/{pages,components,layouts,styles}/**` except `tokens.css`.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test tests/unit/notice.test.ts tests/unit/site.test.ts tests/unit/tokens.test.ts`
Expected: FAIL, modules and `tokens.css` not found.

- [ ] **Step 3: Implement the constants, tokens and config**

- `src/lib/notice.ts` and `src/lib/site.ts` as specified above.
- `tokens.css`: one `:root { ... }` block copied from `docs/design/b2-garage.html` lines 17 to 98, minus `--font-display` and `--font-sans` (Astro generates those variables with fallbacks). Keep `color-scheme: dark`.
- `theme.css`: `@theme inline { --color-floor: var(--floor); ... }` with one alias per colour token, plus `--radius-*` and `--shadow-*` aliases. Spacing and the type scale stay plain custom properties, read through `var()`.
- `global.css`: `@import "tailwindcss"; @import "./tokens.css"; @import "./theme.css";` then the mock-up's Base block (lines 100 to 118: box-sizing, `html`, `body`, `::selection`, `:focus-visible`, link colours, `.sr`, heading rules) and its `prefers-reduced-motion` block (lines 602 to 607), plus `[hidden] { display: none !important }`, because the filter script (Task 10) hides rows with the `hidden` attribute and a component's `display` rule would otherwise override the browser default.
- `astro.config.ts`: add `fontProviders` to the `astro/config` import and this `fonts` entry (checked on 2026-11-24: it builds and emits both families as `/_astro/fonts/*.woff2`):

```ts
fonts: [
  { provider: fontProviders.fontsource(), name: 'Big Shoulders Display', cssVariable: '--font-display',
    weights: ['600 900'], styles: ['normal'], fallbacks: ['Arial Narrow', 'sans-serif'] },
  { provider: fontProviders.fontsource(), name: 'Geist', cssVariable: '--font-sans',
    weights: ['400 700'], styles: ['normal'], fallbacks: ['system-ui', 'sans-serif'] },
],
```

- [ ] **Step 4: Run to verify**

Run: `pnpm test tests/unit/notice.test.ts tests/unit/site.test.ts tests/unit/tokens.test.ts`
Expected: PASS.

- [ ] **Step 5: One-off check that the lift is verbatim**

Run: `diff <(sed -n '17,98p' docs/design/b2-garage.html | grep -E '^\s+--' | sort) <(grep -E '^\s+--' src/styles/tokens.css | sort)`
Expected: the only differences are the two `--font-*` lines, present only on the left. This is a one-time check, not a test: the design README makes the theme the source after the lift, so no test pins the mock-up.

- [ ] **Step 6: Typecheck and commit**

Run: `pnpm typecheck && pnpm lint`
Expected: exit 0.

```bash
git add src/styles src/lib/notice.ts src/lib/site.ts astro.config.ts tests/unit/notice.test.ts tests/unit/site.test.ts tests/unit/tokens.test.ts tests/unit/helpers/contrast.ts
git commit -m "feat(site): B2 tokens, self-hosted font config and shared constants"
```

---

### Task 2: Site shell

**Files:**
- Create: `src/components/SiteNav.astro`, `tests/e2e/site.spec.ts`, `tests/e2e/routes.ts`, `tests/e2e/data.ts`
- Modify: `src/layouts/Base.astro`, `src/components/SiteFooter.astro`, `src/pages/index.astro`, `src/pages/about.astro`, `src/pages/404.astro`

**Interfaces:**
- Consumes: Task 1's `NOTICE`, `SITE_NAME`, `pageTitle`, tokens.
- Produces: `Base.astro` with props `{ title?: string | undefined; description?: string | undefined }`. Pages pass the page's own title and the layout builds `<title>` with `pageTitle`. It renders a skip link to `#main`, the sticky top bar, `<main id="main">`, the footer, and `<meta name="robots" content="noindex">` unless `PUBLIC_INDEXABLE === 'true'` (unchanged).
- Produces for e2e: `allRoutes(): string[]` in `tests/e2e/routes.ts`, starting as `['/', '/about']`. Each later page task adds its routes. `set` (a loaded `DataSet` of the real `data/`) in `tests/e2e/data.ts`, from `loadDataSet('data')`.

- [ ] **Step 1: Write the failing e2e tests** in `site.spec.ts`, looping `allRoutes()` so later pages are covered the moment they register:
  - `footer carries the notice word for word`: `page.getByRole('contentinfo')` `toContainText(NOTICE)` (Playwright normalises whitespace). `/about` `main` contains it too.
  - `every route is noindex before the beta`.
  - `no route renders an img`: `locator('img')` count is 0 (no logos, no car photos).
  - `every route has exactly one h1`.
  - `no request leaves the origin`: collect `page.on('request')` URLs during `goto` with `waitUntil: 'networkidle'`, and assert each is same-origin or a `data:` URL. This catches a font CDN, an analytics tag and a store asset.
  - `the skip link is the first focus stop and targets main`: press Tab, expect the focused link's `href` to end with `#main`, and `#main` to exist.
  - `the fonts are self-hosted`: the page requests at least one `/_astro/fonts/*.woff2`.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm build && pnpm e2e site.spec.ts`
Expected: FAIL on the skip link, `main#main` and the fonts.

- [ ] **Step 3: Implement the shell**
  - `Base.astro`: `<Font cssVariable="--font-display" preload />` and `<Font cssVariable="--font-sans" preload />` from `astro:assets` in `<head>`, `<meta name="color-scheme" content="dark">`, the skip link (`.sr`, visible on focus), `SiteNav`, `<main id="main">`, `<footer>` with `SiteFooter`.
  - `SiteNav.astro`: the mock-up's `.top` bar: a `SITE_NAME` mark with the yellow square, and an "About" link. Tap targets 44 px.
  - `SiteFooter.astro`: renders `NOTICE` from the constant, and keeps the existing license line (MIT, CC BY-SA 4.0, source on GitHub: all allowlisted hosts).
  - `index.astro`, `about.astro` and `404.astro`: move to the new props and B2 typography only. Their content is unchanged, except `about.astro` renders `NOTICE` from the constant. Task 8 and Task 15 rewrite them.

- [ ] **Step 4: Run to verify**

Run: `pnpm build && pnpm e2e`
Expected: PASS, with `smoke.spec.ts` still green.

- [ ] **Step 5: Commit** (`feat(site): B2 shell with skip link, self-hosted fonts and route-wide invariants`). Stage the files by path.

---

### Task 3: Display libraries: format, money, routes, markets, model years

**Files:**
- Create: `src/lib/format.ts`, `src/lib/money.ts`, `src/lib/routes.ts`, `src/lib/markets.ts`, `src/lib/model-years.ts`
- Test: `tests/unit/format.test.ts`, `tests/unit/money.test.ts`, `tests/unit/routes.test.ts`, `tests/unit/markets.test.ts`, `tests/unit/model-years.test.ts`

**Interfaces:**
- Produces (`format.ts`): `formatDate(date: Date): string` (UTC `YYYY-MM-DD`); `formatNumber(value: number): string` (`4492` to `4,492`, `3.5` to `3.5`, `-370` to `-370`); `formatYears(years: readonly [number, number]): string` (`2000–2006` with an en dash, `2004` when equal); `frequencyLabel(f: KnownIssue['frequency']): string`; `transmissionLabel(t: Variant['transmissions'][number]): string` (`6mt` "6-speed manual", `smg` "SMG", `dct` "DCT", `auto` "Automatic", `7mt` "7-speed manual"); `bodyLabel(b: Variant['body']): string`; `wheelLabel(w: { diameterIn: number; widthIn: number; offsetMm: number }): string` (`18 × 8 ET47`).
- Produces (`money.ts`): `NO_SOURCED_COST = 'no sourced cost'`; `formatUsdRange(range: readonly [number, number]): string`; `describeCost(cost: { diy?: readonly [number, number] | undefined; shop: readonly [number, number] } | undefined): CostView`, where `CostView = { kind: 'sourced'; shop: string; diy?: string } | { kind: 'none'; label: typeof NO_SOURCED_COST }`.
- Produces (`routes.ts`): `generationPath(gen: string): string` (`/e46/`), `issuesPath(gen)`, `issuePath(gen, id)`, `maintenancePath(gen)`, `buyingPath(gen)`, all with a leading and trailing slash; `GenerationSection = { key: 'overview' | 'maintenance' | 'issues' | 'buying'; label: string; path: (gen: string) => string }`; `GENERATION_SECTIONS: readonly GenerationSection[]`, in spec order (overview, mods, maintenance, issues, buying, build) and holding only `overview` until later tasks add theirs.
- Produces (`markets.ts`): `type Market = Variant['market']`; `MARKETS: readonly ['us', 'euro']`; `appliesToMarket(entry: { markets?: readonly Market[] | undefined }, market: Market): boolean` (no `markets` means every market); `marketsOf(entry): readonly Market[]`; `marketsLabel(entry): string` ("All markets", "US only", "Euro only", "US and Euro"); `marketLabel(m: Market): 'US' | 'Euro'`; `marketsAttr(entry): string` (`'us euro'`, for `data-markets`).
- Produces (`model-years.ts`; it reads a structural type, so it needs no schema change and its tests need no contract PR): `type ModelYears = readonly [from: number, to?: number | undefined]` (`[2001, 2003]`, or `[2004]` for 2004 and every later year; if the contract PR lands a different tuple, only this alias changes); `appliesToYear(entry: { modelYears?: ModelYears | undefined }, year: number): boolean` (no `modelYears` means every year, and a missing `to` is open-ended); `modelYearsLabel(entry): string` (`All model years` when absent, `2001–2003`, `2004 and later`, `2004 only` for `[2004, 2004]`); `yearsAttr(entry, run: readonly [number, number]): string` (the applicable years inside the generation's run, space-separated, for `data-years`: `[2004]` in a 2000 to 2006 run is `2004 2005 2006`, an absent range is every year of the run, a range wholly outside the run is the empty string).

- [ ] **Step 1: Write the failing tests.** Key assertions:

```ts
// money.test.ts
test('formatUsdRange', () => {
  expect(formatUsdRange([500, 900])).toBe('$500–900')
  expect(formatUsdRange([60, 60])).toBe('$60')
  expect(formatUsdRange([1200, 3400])).toBe('$1,200–3,400')
})
test('describeCost never shows zero (Review Focus 4)', () => {
  const none = { kind: 'none', label: 'no sourced cost' }
  expect(describeCost(undefined)).toEqual(none)
  expect(describeCost({ shop: [0, 0] })).toEqual(none)
  expect(describeCost({ diy: [0, 0], shop: [0, 0] })).toEqual(none)
  expect(describeCost({ diy: [20, 40], shop: [60, 100] })).toEqual({ kind: 'sourced', shop: '$60–100', diy: '$20–40' })
  expect(describeCost({ shop: [60, 100] })).toEqual({ kind: 'sourced', shop: '$60–100' }) // no diy key at all
})
// model-years.test.ts (Review Focus 5)
test('appliesToYear: a missing to is open-ended', () => {
  expect(appliesToYear({ modelYears: [2004] }, 2004)).toBe(true)
  expect(appliesToYear({ modelYears: [2004] }, 2006)).toBe(true)
  expect(appliesToYear({ modelYears: [2004] }, 2003)).toBe(false)
  expect(appliesToYear({ modelYears: [2001, 2003] }, 2004)).toBe(false)
  expect(appliesToYear({}, 1999)).toBe(true) // no range: every year
})
test('yearsAttr clamps to the run and is empty outside it', () => {
  expect(yearsAttr({ modelYears: [2004] }, [2000, 2006])).toBe('2004 2005 2006')
  expect(yearsAttr({ modelYears: [2004, 2010] }, [2000, 2006])).toBe('2004 2005 2006')
  expect(yearsAttr({ modelYears: [2007] }, [2000, 2006])).toBe('')
  expect(yearsAttr({}, [2000, 2006])).toBe('2000 2001 2002 2003 2004 2005 2006')
})
```

Also: `modelYearsLabel({})` is `All model years`, `{ modelYears: [2001, 2003] }` is `2001–2003`, `[2004]` is `2004 and later`, `[2004, 2004]` is `2004 only`; `formatDate(new Date('2026-11-23'))` is `2026-11-23`; `frequencyLabel('very-common')` is `Very common` and contains no hyphen; `wheelLabel({ diameterIn: 18, widthIn: 8, offsetMm: 47 })` is `18 × 8 ET47`; `appliesToMarket({ markets: ['us'] }, 'euro')` is false and `appliesToMarket({}, 'euro')` is true; the label for `{ markets: ['us', 'euro'] }` is `US and Euro`; `marketsAttr({})` is `us euro` and `marketsAttr({ markets: ['us'] })` is `us`; every path builder starts and ends with `/`, `issuePath('e46', 'e46-vanos-wear')` is `/e46/issues/e46-vanos-wear/`, and `GENERATION_SECTIONS.map((s) => s.key)` is `['overview']`.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test tests/unit/format.test.ts tests/unit/money.test.ts tests/unit/routes.test.ts tests/unit/markets.test.ts tests/unit/model-years.test.ts`
Expected: FAIL, modules not found.

- [ ] **Step 3: Implement the five modules** to the signatures above. `formatUsdRange` uses `Intl.NumberFormat('en-US')` and an en dash. `describeCost` treats a `shop` range whose high end is 0 as no cost, and drops a `diy` range whose high end is 0: `check:data` does not reject `[0, 0]` (see Open Question 5 in the PR), so the page must not print it. Types come from `../data/schemas.ts` with `import type`.

- [ ] **Step 4: Run to verify**

Run: `pnpm test tests/unit/format.test.ts tests/unit/money.test.ts tests/unit/routes.test.ts tests/unit/markets.test.ts tests/unit/model-years.test.ts && pnpm typecheck`
Expected: PASS, exit 0.

- [ ] **Step 5: Commit** (`feat(site): format, money, route, market and model-year display libraries`).

---

### Task 4: Citation and unverified-mark libraries

**Files:**
- Create: `src/lib/citations.ts`, `src/lib/unverified-marks.ts`
- Test: `tests/unit/citations.test.ts`, `tests/unit/unverified-marks.test.ts`

**Interfaces:**
- Consumes: `isCitationLinkable` (`src/lib/link-policy.ts`), `formatDate` (Task 3), `Source` (schemas), `loadDataSet` (tests only).
- Produces (`citations.ts`): `CitationView = { publisher: string; title: string; accessed: string; tier: 1 | 2 | 3; note?: string; href?: string }`; `citationView(source: Source): CitationView` (`href` only when `isCitationLinkable(source.url)`, and absent otherwise, with no `href: undefined` key); `latestAccessed(sources: readonly Source[]): string | undefined`; `TIER_LABEL: Record<1 | 2 | 3, string>` (`Tier 1`, `Tier 2`, `Tier 3`).
- Produces (`unverified-marks.ts`): `isUnverified(unverified: readonly string[] | undefined, path: string): boolean` (true when a listed entry equals `path`, or is an ancestor of it at a dot boundary); `unverifiedUnder(unverified: readonly string[] | undefined, prefix: string): string[]` (the listed entries equal to `prefix`, below it, or above it).

- [ ] **Step 1: Write the failing tests.**

```ts
// citations.test.ts
test.each([
  'https://archive.org/download/x/x.pdf', 'https://web.archive.org/web/2026/https://a.example/p',
  'https://newsroom.bmwgroup.com/emea/x', 'https://en.wikipedia.org/wiki/X',
])('links %s', (url) => expect(citationView(source({ url })).href).toBe(url))
test.each([
  'https://cdn.shopify.com/s/files/1/x.pdf', 'https://www.pistonheads.com/x', 'https://archive.org.evil.test/x',
  'https://newsroom.bmwgroup.com@evil.test/x', 'https://blog.ecstuning.com/x',
])('shows %s as text only', (url) => expect('href' in citationView(source({ url }))).toBe(false))
test('no source in data/ is linked unless isCitationLinkable allows it (Review Focus 2)', async () => {
  // every source in every entry of loadDataSet('data'): href defined <=> isCitationLinkable(url)
})
```

Also: `accessed` is `YYYY-MM-DD`; a source with no `url` has no `href`; `note` passes through; `latestAccessed` of two dates is the later, and of `[]` is `undefined`.

`unverified-marks.test.ts`: with `['paints.A08', 'years.1', 'factoryWheels.optional-19.front.offsetMm']`, `isUnverified(list, 'paints.A08.code')` is true (descendant); `'paints.A08'` true (exact); `'paints.A080'` false (not a dot boundary); `'years.0'` false; `'years.1'` true; `'factoryWheels.optional-19.front.widthIn'` false; `'factoryWheels.optional-190.front.offsetMm'` false; `undefined` list is false. `unverifiedUnder(['a.b.c', 'a.d', 'x'], 'a')` is `['a.b.c', 'a.d']`; `unverifiedUnder(['a.b'], 'a.b.c.d')` is `['a.b']`.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test tests/unit/citations.test.ts tests/unit/unverified-marks.test.ts`
Expected: FAIL, modules not found.

- [ ] **Step 3: Implement both modules** to the signatures above. `isUnverified` splits on `.` rather than comparing string prefixes alone.

- [ ] **Step 4: Run to verify**

Run: `pnpm test tests/unit/citations.test.ts tests/unit/unverified-marks.test.ts && pnpm typecheck`
Expected: PASS, exit 0.

- [ ] **Step 5: Commit** (`feat(site): citation view and unverified-mark libraries`).

---

### Task 5: Generation page: spec drawers

**Files:**
- Create: `src/data/site.ts`, `src/components/{Drawer,Tier,Mark,SourceList,GenerationNav}.astro`, `src/pages/[gen]/index.astro`, `tests/e2e/generation.spec.ts`, `tests/e2e/unverified.ts`
- Modify: `src/lib/routes.ts` (the `overview` section), `tests/unit/routes.test.ts`, `tests/e2e/routes.ts` (add `generationPath(gen)` for every generation)

**Interfaces:**
- Consumes: Tasks 2 to 4.
- Produces (`src/data/site.ts`, uses `getCollection`, so it has no unit test: the e2e covers it): `GenerationData = { generation: Generation; variants: Variant[]; issues: KnownIssue[]; maintenance: MaintenanceItem[] }`; `generationIds(): Promise<string[]>`; `loadGeneration(id: string): Promise<GenerationData>` (throws `no generation "<id>"` when absent; each list sorted by `id`).
- Produces (components): `Drawer` (props `label: string; span?: 4 | 5 | 7 | 8 | 12`, default slot, renders the tool-chest drawer with its tape label and handle, and a `data-drawer` attribute taken from a `name` prop); `Tier` (`tier: 1 | 2 | 3`, the `T1`/`T2`/`T3` badge, with a text label for assistive tech); `Mark` (`path: string; unverified: readonly string[] | undefined`, wraps its slot and, when `isUnverified`, adds a visible `†`, visually-hidden text "unverified" and `data-unverified-path={path}`); `SourceList` (`sources: readonly Source[]`, an `<ol data-sources>` of citations: tier badge, publisher, title and accessed date as text, a link only when `citationView` gives an `href`, and `note` inside a closed `<details>`); `GenerationNav` (`gen: string; current: GenerationSection['key']`, links from `GENERATION_SECTIONS`).
- Produces for e2e (`tests/e2e/unverified.ts`): `expectMarksMatch(scope: Locator, listed: readonly string[] | undefined): Promise<void>`.

Page content (`/[gen]/`, from `generation`): `h1` is the name; a "data checked `<latestAccessed>`" line over all the generation's sources; a legend line ("† marks a value below the verification rule: one Tier 1 source, or two independent Tier 2 sources"); drawers for Engine (code, displacement in cc, cylinders, years, chassis; sources: `generation.sources`), Body in mm (one drawer per body in `dimensions`, six figures, that body's `sources`), Stock wheels (front and rear: `wheelLabel`, tire, bolt pattern and centre bore; `fitment.sources`; an empty `envelopes` list says "Fit limits not yet sourced: the build sheet will report fitment unknown"), and Driver eye point (x, y, z in mm, and an "Estimated · no source" badge with the `note` when `basis` is `estimated`). Every unverified-capable value is wrapped in `Mark` with its schema path (`fitment.front.stock.offsetMm`, `years.1`, and so on). Each drawer's `SourceList` sits in a `<details>`.

- [ ] **Step 1: Write the failing e2e tests** in `generation.spec.ts`, data-driven over `set.generations`:
  - `h1 is the generation name`, and the page title is `<name> · m3-tool`.
  - `every engine, body figure and stock wheel value is shown`: each engine code and `formatNumber(displacementCc)`; for each body in `dimensions`, the six figures in that body's drawer; each axle's `wheelLabel`, tire, bolt pattern and centre bore.
  - `every listed unverified path is marked, and nothing else is`: `expectMarksMatch(page.locator('main'), generation.unverified)`.
  - `an estimated eye point says so`: when `basis === 'estimated'`, the drawer contains "Estimated" and the `note`.
  - `source anchors are exactly the linkable sources` (Review Focus 2): the number of `a[href^="http"]` inside `[data-sources]` equals the number of `isCitationLinkable` sources, and each such `href` is one of them.
  - `the nav marks the current section`.
  `expectMarksMatch` asserts that each listed path `p` has a `[data-unverified-path]` whose value is `p` or starts with `p + '.'`, and that every marker's path satisfies `isUnverified(listed, path)`.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm build && pnpm e2e generation.spec.ts`
Expected: FAIL, no route `/e46/`.

- [ ] **Step 3: Implement** the loaders, components and page. Add the `overview` entry's test to `routes.test.ts` unchanged and register `generationPath(gen)` in `tests/e2e/routes.ts`. Port the mock-up's `.chest`, `.drawer`, `.handle`, `.tape`, `.kv`, `.tier`, `.est` and `.srcs` rules into the components.

- [ ] **Step 4: Run to verify**

Run: `pnpm check && pnpm build && pnpm e2e`
Expected: exit 0 for both. The route-wide invariants from Task 2 now cover `/e46/` too.

- [ ] **Step 5: Commit** (`feat(site): generation page with spec drawers, sources and unverified marks`).

---

### Task 6: Variants on the generation page

**Files:**
- Create: `src/components/VariantPanel.astro`, `tests/e2e/variants.spec.ts`
- Modify: `src/pages/[gen]/index.astro`

**Interfaces:**
- Consumes: `Mark`, `SourceList`, `Drawer` (Task 5); `transmissionLabel`, `bodyLabel`, `marketLabel`, `formatYears`, `wheelLabel` (Task 3).
- Produces: `VariantPanel` (props `variant: Variant`): a `<details id="variant-{id}">` whose summary row shows name, market, body, years and transmissions, and whose body lists packages (name and summary), paints (swatch from `baseColor` through an inline `--c` custom property, code, name, finish), factory wheels (front and rear `wheelLabel` and tire, with the name), interiors (name, colour, material) and the variant's `SourceList`. Spec 7.2 has no per-variant route, so variants render here. An empty list (a variant with no interiors, like the CSL) prints a plain "None recorded" line.

Marks use the paths from `unverified.ts`: `years.0` and `years.1` around each year, `paints.<code>.code|name|finish`, `factoryWheels.<id>.name`, `factoryWheels.<id>.<front|rear>.<widthIn|offsetMm|tire>`, `packages.<id>.name|summary`.

- [ ] **Step 1: Write the failing e2e tests** in `variants.spec.ts`, per variant of each generation in `set.variants`:
  - `each variant has a panel with its name, market, body, years and transmissions`.
  - `every listed unverified path is marked, and nothing else is` (Review Focus 4): `expectMarksMatch(page.locator('#variant-' + id), variant.unverified)`. This covers `years.1` on the CSL, paint codes, wheel widths, offsets and tires, and package summaries. A listed path with no rendered field fails the test: add the field, do not weaken the test.
  - `every paint code and name, wheel and package is shown`.
  - `the swatch colour comes from the data`: each paint swatch's inline `--c` equals its `baseColor`.
  - `a variant with no interiors says none recorded`.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm build && pnpm e2e variants.spec.ts`
Expected: FAIL, no `#variant-*` panels.

- [ ] **Step 3: Implement** `VariantPanel`, and add the "Variants" section to the page (the mock-up's `.lanes` list with an expanding panel per variant).

- [ ] **Step 4: Run to verify**

Run: `pnpm build && pnpm e2e variants.spec.ts generation.spec.ts`
Expected: PASS. Phone check (390 px): the panel rows stack and nothing scrolls sideways.

- [ ] **Step 5: Commit** (`feat(site): variant panels with per-value unverified marks`).

---

### Task 7: Hero drawing and pit board

**Files:**
- Create: `src/lib/hero-layout.ts`, `src/components/hero/coupe-outline.ts`, `src/components/HeroDrawing.astro`, `src/components/PitBoard.astro`, `tests/unit/hero-layout.test.ts`, `tests/e2e/hero.spec.ts`
- Modify: `src/pages/[gen]/index.astro`

**Interfaces:**
- Produces (`coupe-outline.ts`, the one file the spike's traced outline replaces later): `OUTLINE = { lengthMm: 4492, heightMm: 1372, wheelbaseMm: 2731, rearAxleXMm: 925, art: string }`, where `art` is the markup of `#coupe-art` from `docs/design/b2-garage.html` lines 659 to 679.
- Produces (`hero-layout.ts`): `heroLayout(dims: { lengthMm: number; heightMm: number; wheelbaseMm: number }, outline?: typeof OUTLINE): HeroLayout`, with `HeroLayout = { viewBox: string; scale: { x: number; y: number }; length: Dim; height: Dim; wheelbase: Dim }` and `Dim = { x1: number; y1: number; x2: number; y2: number; labelX: number; labelY: number; text: string }`. The art scales by `lengthMm / outline.lengthMm` and `heightMm / outline.heightMm`, so the dimension lines always meet the drawn car; the front axle sits at `rearAxleXMm + wheelbaseMm`. Label text is `formatNumber(value) + ' mm'`.
- Produces: `HeroDrawing` (props `dimensions: Dimensions-of-one-body`), an `<svg role="img">` with `<title>` and `<desc>` built from the data, the art through `set:html`, a caption, and `PitBoard` (props `rows: { label: string; value: string }[]`).

Page: the hero on the generation page, from the mock-up lines 142 to 199 and 640 to 700 (the stage, LED strips, scene, pit board). `h1` is the generation name with years and bodies under it. The pit board rows come from the data only: engine code, displacement, cylinders, wheelbase. The mock-up's "Layout: Inline 6" row is dropped because the schema has no layout field. The hero actions come from `GENERATION_SECTIONS` after `overview`, and the caption reads: "Generic two-door outline, scaled to the factory length, height and wheelbase. The 3D model replaces it when ready." Art rules (`.body`, `.tire`, `.glass` and the rest) go in `<style is:global>`, because `set:html` content carries no scope attribute.

- [ ] **Step 1: Write the failing tests.**

```ts
// hero-layout.test.ts: the E46 numbers reproduce the mock-up
test('E46 dimensions give the mock-up coordinates', () => {
  const l = heroLayout({ lengthMm: 4492, heightMm: 1372, wheelbaseMm: 2731 })
  expect(l.viewBox).toBe('-640 -2000 5772 2000')
  expect(l.length).toMatchObject({ x1: 0, x2: 4492, y1: -1780, y2: -1780, labelX: 2246, text: '4,492 mm' })
  expect(l.height).toMatchObject({ x1: -300, y1: 0, y2: -1372, text: '1,372 mm' })
  expect(l.wheelbase).toMatchObject({ x1: 925, x2: 3656, y1: 330, text: '2,731 mm' })
})
test('labels and lines come from the data, not the outline', () => {
  const l = heroLayout({ lengthMm: 4500, heightMm: 1372, wheelbaseMm: 2731 })
  expect(l.length.text).toBe('4,500 mm'); expect(l.length.x2).toBe(4500); expect(l.scale.x).toBeCloseTo(4500 / 4492)
})
```

`hero.spec.ts`: the svg's visible dimension texts equal `formatNumber` of the data's length, height and wheelbase; `<title>`/`<desc>` contain them; the SVG has no `image` element; the caption is shown; the pit board shows each engine code and the cylinder count.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test tests/unit/hero-layout.test.ts && pnpm build && pnpm e2e hero.spec.ts`
Expected: FAIL, modules not found.

- [ ] **Step 3: Implement** the layout function, the outline file, the two components and the page changes.

- [ ] **Step 4: Run to verify**

Run: `pnpm check && pnpm build && pnpm e2e`
Expected: exit 0 for both. Check the hero at 1280 and 390 px against the mock-up.

- [ ] **Step 5: Commit** (`feat(site): hero drawing and pit board on the generation page`).

---

### Task 8: Home page: pick a generation

**Files:**
- Modify: `src/pages/index.astro`
- Test: `tests/e2e/home.spec.ts`

**Interfaces:**
- Consumes: `generationIds`, `loadGeneration` (Task 5), `generationPath`, `formatYears`, `bodyLabel` (Task 3), `Drawer`.
- Produces: `/` with a short statement of what the site is ("A free reference for BMW M3 owners and shoppers: factory spec, known issues, maintenance and a used-buyer checklist. Nothing is for sale and there are no store links."), then one card per generation (name, years, chassis, bodies, a link to `generationPath(id)`), and an empty state ("No generations are published yet.") for a data set with none.

- [ ] **Step 1: Write the failing e2e tests:** `every generation is listed with its name, years and a working link` (click the first link, expect that generation's `h1`), and `the home page makes no store claim it cannot keep`: the page text contains "Nothing is for sale".

- [ ] **Step 2: Run to verify failure**

Run: `pnpm build && pnpm e2e home.spec.ts`
Expected: FAIL, no generation cards.

- [ ] **Step 3: Implement** the page.

- [ ] **Step 4: Run to verify**

Run: `pnpm build && pnpm e2e`
Expected: PASS.

- [ ] **Step 5: Commit** (`feat(site): home page lists generations`).

---

### Task 9: Known issue detail page

Needs the data lane's `modelYears` contract PR on `main` (Step 1 has the type test that enforces it).

**Files:**
- Create: `src/components/Chip.astro`, `src/components/CostBox.astro`, `src/pages/[gen]/issues/[issue].astro`, `tests/unit/model-years-schema.test.ts`, `tests/e2e/issues.spec.ts`
- Modify: `tests/e2e/routes.ts` (add `issuePath(gen, id)` for every issue)

**Interfaces:**
- Consumes: `describeCost`, `NO_SOURCED_COST`, `frequencyLabel`, `marketsLabel`, `modelYearsLabel`, `issuePath` (Task 3); `SourceList`, `Drawer` (Task 5).
- Produces: `Chip` (props `tone?: 'plain' | 'hot'`, slot); `CostBox` (props `cost: Parameters<typeof describeCost>[0]`: DIY and Shop tiles when sourced, the words "no sourced cost" and no currency symbol when not); `[issue].astro` with `getStaticPaths` over every issue, using `data-section` hooks (`symptoms`, `cause`, `check`, `fix`, `costs`, `prevention`, `sources`).

Page (the mock-up's tech card on the pegboard): the title and a frequency plate (`frequencyLabel`); chips for the engine code, `marketsLabel`, `modelYearsLabel` ("All model years" when the issue has no `modelYears`), "Verified" or "Unverified" (from `verified`), and "On the buyer checklist" when `inspectWhenBuying`; Symptoms (a list), Cause, How to check (when `howToCheck`), Fix (when `fix`; otherwise "No sourced fix yet. A fix needs a Tier 1 or Tier 2 source."), Costs (always, through `CostBox`), Prevention (when present), Sources (`SourceList`, and for an unverified issue the mock-up's line "Unverified: needs one Tier 1 source, or two Tier 2 sources from different publishers to read Verified."). A link back to the issues list, and `GenerationNav` with `current="issues"`.

- [ ] **Step 1: Write the failing tests.** `model-years-schema.test.ts` is a type-level gate: `const years: ModelYears | undefined = ({} as KnownIssue).modelYears ?? ({} as MaintenanceItem).modelYears; expect(years).toBeUndefined()`. It fails `pnpm typecheck` until the contract PR is on `main`, and it proves the schemas' shape is assignable to `ModelYears` (if not, fix the alias in `model-years.ts`, not the schema). Then, in `issues.spec.ts`, per issue in `set.issues`:
  - `the page shows the title, every symptom and the cause`.
  - `the verified chip follows the flag` (Review Focus 4): exactly one of "Verified" and "Unverified" is present, and it matches `issue.verified`.
  - `frequency never shows as a slug`: the page text has `frequencyLabel(issue.frequency)` and contains no `very-common`.
  - `the market and model-year chips match the data`: they equal `marketsLabel(issue)` and `modelYearsLabel(issue)`, and an issue with no `modelYears` shows "All model years".
  - `fix, prevention and how to check show exactly when the data has them`, and an issue without a fix shows "No sourced fix yet".
  - `an issue with no cost says no sourced cost` (Review Focus 4): `[data-section="costs"]` has the text "no sourced cost" and no `$` when `cost` is absent, and the `describeCost` strings when present.
  - `sources show publisher, title, tier and date, linked only when citation hosts`.
  - `an issue marked inspectWhenBuying shows the checklist chip`.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm typecheck && pnpm build && pnpm e2e issues.spec.ts`
Expected: FAIL, no issue routes (and a type error on `modelYears` if the contract PR is not on `main`: stop and wait for it).

- [ ] **Step 3: Implement** the components and page.

- [ ] **Step 4: Run to verify**

Run: `pnpm check && pnpm build && pnpm e2e`
Expected: exit 0 for both.

- [ ] **Step 5: Commit** (`feat(site): known issue pages as tech cards`).

---

### Task 10: Issues list and the filter scope

**Files:**
- Create: `src/lib/issue-order.ts`, `src/lib/filters.ts`, `src/components/FilterScope.astro`, `src/pages/[gen]/issues/index.astro`, `tests/unit/issue-order.test.ts`, `tests/unit/filters.test.ts`, `tests/e2e/issues-list.spec.ts`
- Modify: `src/lib/routes.ts` (add the `issues` section; spec order is overview, maintenance, issues, buying), `tests/unit/routes.test.ts`, `tests/e2e/routes.ts` (add `issuesPath(gen)`)

**Interfaces:**
- Consumes: `marketsAttr`, `marketLabel`, `marketsLabel`, `Market` (Task 3); `yearsAttr`, `modelYearsLabel` (Task 3, with the contract PR for the types); `Chip`, `CostBox` (Task 9).
- Produces (`issue-order.ts`): `compareIssues(a: KnownIssue, b: KnownIssue): number` (frequency rank `very-common` > `common` > `rare`, then an issue with a sourced `shop` cost before one without and the higher `cost.shop[1]` first, then `title.localeCompare(b.title, 'en')`); `sortIssues(issues: readonly KnownIssue[]): KnownIssue[]` (a copy).
- Produces (`filters.ts`, pure, so the browser script holds no rule):
  - `Selection = { market: Market | 'all'; year: number | 'all' }`; `EntryTags = { markets: readonly Market[]; years: readonly number[] }`.
  - `parseTags(attrs: { markets: string; years: string }): EntryTags` (splits the `data-markets` and `data-years` strings).
  - `isVisible(tags: EntryTags, selection: Selection): boolean` (`all` matches everything; a market or a year must be in the entry's lists; an entry whose `years` is empty shows only under year `all`).
  - `describeSelection(selection: Selection): string` (`all cars`, `US cars`, `model year 2003 cars`, `US cars, model year 2003`).
  - `filterStatus(args: { shown: number; total: number; noun: string; gapNote?: string | undefined; selection: Selection }): { status: string; gap: string | undefined }` (`status` is `Showing {shown} of {total} {noun}`; `gap` is set only when `shown === 0 && total > 0`: `No sourced {noun} for {describeSelection} yet. {gapNote}`).
- Produces (`FilterScope.astro`, props `generationYears: readonly [number, number]; noun: string`, default slot): a "Show" fieldset with a market control (three native radios: All, US, Euro) and a model-year control (a native `<select>`: "All model years" and one option per year of `generationYears`), both with the `hidden` attribute until the script runs, and a `role="status"` line. Its bundled `<script>` (it imports `src/lib/filters.ts`) reveals the controls, and on change reads `data-markets` and `data-years` from every `[data-markets]` element, sets each element's `hidden` from `isVisible`, updates the status line, and, inside each `[data-filter-group]` container (one `data-noun` and optional `data-gap-note` on it, and one `<p data-gap hidden>` child), fills and shows that group's gap text from `filterStatus` when the group shows nothing. Without JavaScript the controls never appear, every entry stays visible, and every entry's chips still say its market and model years, so the page stays true. The defaults are All and All model years. When a group has no entries at all, the page renders "No {noun} are published for this generation yet." and no controls.

- [ ] **Step 1: Write the failing tests.**
  - Unit `issue-order.test.ts` (issues built from `loadDataSet(VALID_FIXTURES)` with overrides): `very-common` before `common` before `rare`; at equal frequency a sourced cost before none, and a higher `shop[1]` first; titles break ties; `sortIssues` does not mutate its input and is stable on equal keys.
  - Unit `filters.test.ts`:

```ts
test('isVisible: a year outside the entry\'s years hides it (Review Focus 5)', () => {
  const tags = { markets: ['us'], years: [2001, 2002, 2003] } as const
  expect(isVisible(tags, { market: 'all', year: 2003 })).toBe(true)
  expect(isVisible(tags, { market: 'all', year: 2004 })).toBe(false)
  expect(isVisible(tags, { market: 'euro', year: 'all' })).toBe(false)
  expect(isVisible({ markets: ['us'], years: [] }, { market: 'all', year: 'all' })).toBe(true)
  expect(isVisible({ markets: ['us'], years: [] }, { market: 'all', year: 2003 })).toBe(false)
})
test('filterStatus names the gap when a selection shows nothing (Review Focus 1)', () => {
  const r = filterStatus({ shown: 0, total: 9, noun: 'maintenance items', gapNote: 'This is a gap in the data, not a sign that nothing is due.', selection: { market: 'euro', year: 2003 } })
  expect(r.status).toBe('Showing 0 of 9 maintenance items')
  expect(r.gap).toBe('No sourced maintenance items for Euro cars, model year 2003 yet. This is a gap in the data, not a sign that nothing is due.')
  expect(filterStatus({ shown: 3, total: 9, noun: 'x', selection: { market: 'all', year: 'all' } }).gap).toBeUndefined()
  expect(filterStatus({ shown: 0, total: 0, noun: 'x', selection: { market: 'us', year: 'all' } }).gap).toBeUndefined()
})
```

    Also `parseTags({ markets: 'us euro', years: '2001 2002' })` and `describeSelection` for each of the four forms.
  - E2e `issues-list.spec.ts`: `every issue is listed once with a link to its page`; `All and All model years are the defaults and show every issue`; `choosing a market hides exactly the issues that do not apply to it` (the expectation is computed inline from each issue's `markets`, independent of the lib, with real data: `e46-rod-bearing-wear-us` and `-euro` each show in only their own market); `choosing a model year hides exactly the issues whose range excludes it, and an issue with no range always shows`; `the filter reads each row's data attributes` (the data on `main` has no `modelYears` yet, so the test retags the first row in the page with `evaluate`: `data-years` set to its first year only, `data-markets` set to `us`; it must then hide under another year and under Euro, and return under All, which proves the mechanics without waiting for data); `the status line counts the visible rows`; `a selection with no entries shows the group's gap text` (looping every market and year choice and comparing with the count computed from the data); `rows are in compareIssues order`, checked against an independent oracle (frequency never increases down the list); and `with JavaScript off every issue is visible, the controls are not shown, and each row's chips state its market and model years` (`test.use({ javaScriptEnabled: false })`).

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test tests/unit/issue-order.test.ts tests/unit/filters.test.ts && pnpm build && pnpm e2e issues-list.spec.ts`
Expected: FAIL.

- [ ] **Step 3: Implement** the order lib, the filter lib, `FilterScope`, the page (rows: title link, frequency, chips for market, model years and verified, the first symptom, `data-markets={marketsAttr(issue)}` and `data-years={yearsAttr(issue, generation.years)}` on each row; the list wrapped in one `data-filter-group` with `data-noun="known issues"` and `data-gap-note="This is a gap in the data, not a sign that no issues exist."`), and the nav section.

- [ ] **Step 4: Run to verify**

Run: `pnpm check && pnpm build && pnpm e2e`
Expected: exit 0 for both.

- [ ] **Step 5: Commit** (`feat(site): known issues list with market and model-year filters`).

---

### Task 11: Interval library

**Files:**
- Create: `src/lib/intervals.ts`
- Test: `tests/unit/intervals.test.ts`

**Interfaces:**
- Consumes: `formatNumber` (Task 3), `MaintenanceItem` (schemas).
- Produces: `type Trigger = NonNullable<MaintenanceItem['interval']['triggers']>[number]`; `TRIGGER_LABELS: Record<Trigger, string>`, with these exact texts:
  - `break-in`: `Break-in service`
  - `oil-service`: `Each oil service`
  - `inspection-i`: `Every inspection: Inspection I, and again at each Inspection II`
  - `inspection-ii`: `Inspection II only`
  - `lifetime-fill`: `Lifetime fill: no scheduled change`
  - `condition-based`: `Condition based: decided by monitoring the part`
- `IntervalView = { due: string[]; numbers: string[]; everyInspection: boolean; noScheduledService: boolean }`; `describeInterval(interval: MaintenanceItem['interval']): IntervalView`; `compareSchedule(a: MaintenanceItem, b: MaintenanceItem): number`.

Rules: `due` lists each trigger's label in schedule order. `numbers` has `Every 100,000 miles` and `Every 24 months` for a plain interval, and `Up to 60,000 miles (the manufacturer's stated maximum)` beside `condition-based`, never a mileage made up from a trigger. `everyInspection` is true when the triggers include `inspection-i`. `noScheduledService` is true for `lifetime-fill` and `condition-based`. Schedule rank is the lowest of `break-in` 0, `oil-service` 1, `inspection-i` 2, `inspection-ii` 3 across the item's triggers; an item with only `miles` or `months` ranks 4 (then by miles, then months); `condition-based` 5; `lifetime-fill` 6; ties by `title`.

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

Also: `[break-in, inspection-ii]` gives two labels in that order and no numbers; `{ miles: 100000 }` gives `numbers` `['Every 100,000 miles']` and an empty `due`; `{ months: 24 }` gives `['Every 24 months']`; `{ triggers: ['condition-based'], miles: 60000 }` gives the "Up to ..." text and `noScheduledService`; `{ triggers: ['lifetime-fill'] }` gives its label and `noScheduledService`; `compareSchedule` orders a `break-in` item, an `oil-service` item, an `inspection-i` item, an `inspection-ii` item, a `{ miles: 60000 }` item, a `{ miles: 100000 }` item, a `condition-based` item and a `lifetime-fill` item exactly in that order, and breaks a tie by title.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test tests/unit/intervals.test.ts`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement** the module to the signatures and rules above.

- [ ] **Step 4: Run to verify**

Run: `pnpm test tests/unit/intervals.test.ts && pnpm typecheck`
Expected: PASS, exit 0.

- [ ] **Step 5: Commit** (`feat(site): maintenance interval description and schedule order`).

---

### Task 12: Maintenance page

Needs the `modelYears` contract PR on `main`, like Task 9.

**Files:**
- Create: `src/pages/[gen]/maintenance/index.astro`, `tests/e2e/maintenance.spec.ts`
- Modify: `src/lib/routes.ts` (the `maintenance` section), `tests/unit/routes.test.ts`, `tests/e2e/routes.ts`

**Interfaces:**
- Consumes: `describeInterval`, `compareSchedule` (Task 11); `FilterScope`, `Chip`, `CostBox`, `SourceList`, `Tier` (Tasks 5, 9, 10); `marketsAttr`, `marketsLabel`, `yearsAttr`, `modelYearsLabel` (Task 3).
- Produces: `/[gen]/maintenance/`: `FilterScope` (`generationYears={generation.years}`, `noun="maintenance items"`) around one `data-filter-group` (`data-noun="maintenance items"`, `data-gap-note="This is a gap in the data, not a sign that nothing is due."`), a one-line legend ("BMW often ties a service to a trigger instead of a mileage. Triggers are shown as BMW gives them, and this site does not turn them into mileages."), and a schedule table in `compareSchedule` order. Columns: Service (title and `notes` when present), Due (`due` labels and `numbers`, with an `every inspection` emphasis when `everyInspection`), Parts and fluids, Cost (`CostBox`), Status ("Verified" or "Unverified"), Applies to (a `Chip` for `marketsLabel` and one for `modelYearsLabel`, which reads "All model years" when the item has no `modelYears`), Sources (`SourceList` in a `<details>`). Each row carries `data-markets={marketsAttr(item)}` and `data-years={yearsAttr(item, generation.years)}`, so two items for one service split by year (a 2001 to 2003 coolant item and a 2004-on one) show only for their own years. On a phone the rows stack, as in the mock-up's `.lines` rules.

- [ ] **Step 1: Write the failing e2e tests** in `maintenance.spec.ts`, from `set.maintenance` for each generation (all of them are data-driven, so they pass with zero items and with PR #41's nine):
  - `every item is a row, in schedule order`: the row count equals the item count, and an independent oracle holds (no `lifetime-fill` or `condition-based` row above a row with triggers).
  - `inspection-i rows say every inspection` (Review Focus 3): for each item whose triggers include `inspection-i`, the row text matches /every inspection/i; an `inspection-ii`-only row says "Inspection II only".
  - `cost reads no sourced cost when the item has none, and the figures when it has`.
  - `parts, fluids, status and the market and model-year chips match the data`; an item with no `modelYears` shows "All model years".
  - `selecting a model year hides exactly the rows that do not apply` (Review Focus 5): for every year of the generation's run, a row is visible exactly when its item has no `modelYears`, or `from <= year` and (`to` is missing or `year <= to`), written inline in the test so it does not reuse `appliesToYear`. A `[2004]` item stays visible for 2005 and 2006.
  - `a selection with no sourced items says so` (Review Focus 1): for every combination of market (All, US, Euro) and model year (All and each year), select it, and the group's gap text is visible exactly when the data has items but none applies, and then no row is visible. With PR #41's data (all `[us]`) this proves Euro is announced as a gap.
  - `with JavaScript off every item is a row and the chips state market and model years`.
  - `a generation with no maintenance items shows "No maintenance items are published"`, when the data has none (assert on the data, so it holds before and after #41).

- [ ] **Step 2: Run to verify failure**

Run: `pnpm typecheck && pnpm build && pnpm e2e maintenance.spec.ts`
Expected: FAIL, no route.

- [ ] **Step 3: Implement** the page and the nav section.

- [ ] **Step 4: Run to verify**

Run: `pnpm check && pnpm build && pnpm e2e`
Expected: exit 0 for both.

- [ ] **Step 5: Commit** (`feat(site): maintenance schedule page`).

---

### Task 13: Checklist library

**Files:**
- Create: `src/lib/checklist.ts`
- Test: `tests/unit/checklist.test.ts`

**Interfaces:**
- Consumes: `sortIssues`, `compareIssues` (Task 10), `compareSchedule` (Task 11).
- Produces: `Checklist = { issues: KnownIssue[]; service: MaintenanceItem[] }`; `buildChecklist(input: { issues: readonly KnownIssue[]; maintenance: readonly MaintenanceItem[] }): Checklist`. It keeps only entries with `inspectWhenBuying: true`. Issues are in `compareIssues` order. Service items put a sourced `cost.shop[1]` first (higher first, none last), then `compareSchedule`. It copies its inputs and never filters by market or model year (the page's `FilterScope` does).

- [ ] **Step 1: Write the failing tests** (entries built from `loadDataSet(VALID_FIXTURES)` with overrides): only `inspectWhenBuying: true` entries appear, and a fixture with `false` is excluded; issues run `very-common`, `common`, `rare`; at equal frequency a costed issue precedes an uncosted one; service items sort by cost then schedule; the inputs are frozen with `Object.freeze` and are not mutated; an empty input gives `{ issues: [], service: [] }`; an entry with `markets: ['us']` or a `modelYears` range is still returned.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test tests/unit/checklist.test.ts`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement** `buildChecklist`.

- [ ] **Step 4: Run to verify**

Run: `pnpm test tests/unit/checklist.test.ts && pnpm typecheck`
Expected: PASS, exit 0.

- [ ] **Step 5: Commit** (`feat(site): used-buyer checklist ordering`).

---

### Task 14: Used-buyer checklist page

Needs the `modelYears` contract PR on `main`, like Task 9.

**Files:**
- Create: `src/pages/[gen]/buying/index.astro`, `tests/e2e/buying.spec.ts`
- Modify: `src/lib/routes.ts` (the `buying` section), `tests/unit/routes.test.ts`, `tests/e2e/routes.ts`

**Interfaces:**
- Consumes: `buildChecklist` (Task 13); `FilterScope`, `Chip`, `CostBox` (Tasks 9, 10); `issuePath`; `marketsAttr`, `yearsAttr`, `modelYearsLabel` (Task 3).
- Produces: `/[gen]/buying/`: an intro ("What to check on a used car, most common problem first, then most costly. An item with no sourced cost is not free: no source states a price."), a `FilterScope` (`noun="checklist items"`), then two ordered groups, each its own `data-filter-group` with its own `<p data-gap hidden>` and gap note ("This is a gap in the data, not a sign that nothing needs checking."): "Known problems" (each entry: title linked to `issuePath`, frequency, market, model-year and verified chips, the `howToCheck` text, `CostBox`) and "Service history to ask for" (title, due labels from `describeInterval`, the market and model-year chips, the `howToCheck` text, `CostBox`). Every entry has `data-markets` and `data-years`. An entry with no `modelYears` reads "All model years" and shows under every year.

- [ ] **Step 1: Write the failing e2e tests** in `buying.spec.ts`, data-driven:
  - `the checklist holds exactly the entries marked inspectWhenBuying`: the set of titles on the page equals the set of `inspectWhenBuying` issues and maintenance items for the generation, and an entry with `false` is absent.
  - `known problems run most common first`: the frequency rank never increases down the issue group, checked against the data.
  - `each entry shows its how-to-check text, and each problem links to its page`.
  - `an entry with no cost says no sourced cost`.
  - `a selection with no sourced entries names the gap in each group` (Review Focus 1): for every combination of market and model year, a group shows its gap text exactly when it has entries but none applies, and then shows no entry; the other group is judged on its own, and the expectation is computed from the data, so it holds with PR #41's all-`[us]` maintenance.
  - `choosing a market or a model year hides exactly the entries that do not apply`, with the model-year rule written inline in the test (no `modelYears`, or `from <= year` and `to` missing or `year <= to`).
  - `with JavaScript off every entry is visible and labelled`.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm typecheck && pnpm build && pnpm e2e buying.spec.ts`
Expected: FAIL, no route.

- [ ] **Step 3: Implement** the page and the nav section.

- [ ] **Step 4: Run to verify**

Run: `pnpm check && pnpm build && pnpm e2e`
Expected: exit 0 for both.

- [ ] **Step 5: Commit** (`feat(site): used-buyer checklist page`).

---

### Task 15: About page with derived data sources

**Files:**
- Create: `src/lib/data-sources.ts`, `tests/unit/data-sources.test.ts`, `tests/e2e/about.spec.ts`
- Modify: `src/data/site.ts` (add `loadAllSources`), `src/pages/about.astro`

**Interfaces:**
- Consumes: `NOTICE`, `Drawer`, `Tier`, `TIER_LABEL`, `formatDate`.
- Produces (`data-sources.ts`): `SourceSummary = { publisher: string; bestTier: 1 | 2 | 3; citations: number; latestAccessed: string }`; `summarizeSources(sources: readonly Source[]): SourceSummary[]`, which groups by publisher compared after trimming, collapsing spaces and ignoring case (the same rule as `sources.ts`), keeps the first-seen spelling for display, and sorts by `bestTier` ascending, `citations` descending, then publisher.
- Produces (`site.ts`): `loadAllSources(): Promise<Source[]>`, every source of every entry in all five collections.

`/about` content: the notice (`NOTICE` in a `<p>`); what the site is and is not ("It sells nothing and links to no stores."); licenses (code MIT, data CC BY-SA 4.0, 3D models "to be confirmed", the existing allowlisted links); Data sources (a table of `summarizeSources`: publisher, best tier, citations, last accessed, all text, plus "Sources are cited as text. Only non-commercial references are linked."); Credits (the existing placeholder about reference photos).

- [ ] **Step 1: Write the failing tests.** Unit: `Shop A` and ` shop  a ` are one publisher with `citations` 2 and the first spelling shown; `bestTier` is the lowest tier cited; order is tier, then count, then name; `latestAccessed` is the latest date; `[]` gives `[]`. E2e: `/about` main contains `NOTICE` and the words MIT and CC BY-SA 4.0; every distinct publisher in the data appears once, and the row count equals the count of distinct normalised publishers computed independently in the test; no anchor on the page points outside the allowlist; the page still says nothing is for sale.

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test tests/unit/data-sources.test.ts && pnpm build && pnpm e2e about.spec.ts`
Expected: FAIL.

- [ ] **Step 3: Implement** the lib, the loader and the page.

- [ ] **Step 4: Run to verify**

Run: `pnpm check && pnpm build && pnpm e2e`
Expected: exit 0 for both.

- [ ] **Step 5: Commit** (`feat(site): about page lists data sources`).

---

### Task 16: Site-wide gates and docs

**Files:**
- Create: `tests/e2e/a11y.spec.ts`, `tests/e2e/mobile.spec.ts`
- Modify: `package.json` and `pnpm-lock.yaml` (one dev dependency), `AGENTS.md` (Layout), `docs/standards/testing.md`, `docs/README.md`

**Interfaces:**
- Consumes: `allRoutes()` with every page registered by Tasks 5 to 15.
- Produces: an accessibility gate and a phone-layout gate over every route.

- [ ] **Step 1: Add the dependency.** Run `pnpm add -D --save-exact @axe-core/playwright@4.14.0` (4.14.1 is under three days old, and Renovate waits three days).

- [ ] **Step 2: Write the failing tests.**
  - `a11y.spec.ts`: for each route in `allRoutes()`, run `AxeBuilder` with tags `wcag2a`, `wcag2aa`, `wcag21aa` and expect no violations. For the issues list, maintenance and buying routes, repeat with the US market selected, with Euro selected, and with the first and last model year of the run selected, because each filtered state is a distinct page state (and an empty selection shows the gap text, which axe must also pass).
  - `mobile.spec.ts` at 390 x 844: for each route, `document.documentElement.scrollWidth <= clientWidth` (no sideways scroll, with the longest data strings in play); every `SiteNav` link, `GenerationNav` link, market radio label and the model-year `select` has a bounding box at least 44 px high; with the longest selection text in the status and gap lines, the page still does not scroll sideways; every `details > summary` is at least 44 px high.

- [ ] **Step 3: Run, then fix what they find.**

Run: `pnpm build && pnpm e2e a11y.spec.ts mobile.spec.ts`
Expected: first run may fail on contrast or tap size. Fix the component or the token usage, not the test. A contrast failure on a token pair the unit test already pins means the page used the pair wrongly. Rerun until PASS.

- [ ] **Step 4: Update the docs.** `AGENTS.md`: extend the `src/lib/` line in "Layout" to name the display libraries (format, money, markets, citations, intervals, checklist) and add `src/data/site.ts`. `docs/standards/testing.md`: add that page e2e tests are data-driven (they read `data/` through `loadDataSet` and assert what a page shows for each entry), and that a11y and 390 px checks cover every registered route. `docs/README.md`: link this plan under "Design and plans".

- [ ] **Step 5: Final verification**

Run: `pnpm check && pnpm build && pnpm e2e`
Expected: exit 0 for both. Then take the Landing procedure's before-and-after screenshots for the group's routes.

- [ ] **Step 6: Commit** (`test(site): axe and phone-layout gates over every route`, then `docs: describe the display libraries and data-driven page tests`).
