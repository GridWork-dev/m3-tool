# M3 tool: design

- **Date:** 2026-11-23
- **Status:** approved 2026-11-23
- **Working name:** `m3-tool` (placeholder repo name). Public name and domain chosen before the public beta, with no BMW or M3 in the domain.
- **Repo:** `GridWork-dev/m3-tool`, public from day one.
- **Location:** `~/files/04-work/notes-and-planning/m3-tool/` until the repo exists, then `docs/superpowers/specs/` in the repo.

All versions in this doc were checked on npm on 2026-11-23.

## 1. Intent

A free public web tool for BMW M3 owners and shoppers. You pick a generation, see the car in 3D, inside and out, and spec it the way it left the factory. Then you add real aftermarket products and get a running cost sheet for parts and labor. Each generation also gets a maintenance plan, its known problems and a used-buyer checklist.

The tool doesn't sell anything and doesn't link to stores. Its value is pulling together knowledge that today is spread across retailer sites, parts catalogs and 15 years of forum threads.

## 2. Goals, non-goals, anti-goals

**Goals**
- Cover every M3 generation over time: E30, E36, E46, E9x, F80, G80/G81, and the 2027 car. The MVP is the E46 coupe.
- 3D at medium photoreal quality:
  - Exterior, plus an interior you can see through the glass.
  - A driver's-seat camera.
  - Selectable render quality and a photo mode.
- Real named aftermarket products. Each visible product looks like itself in 3D.
- Prices with a source and a checked date, refreshed weekly in a later phase.
- A build sheet that totals parts, labor (at your rate, or $0 for DIY) and tax. Shareable by link.
- Per generation: a maintenance schedule, known issues and a used-buyer checklist.
- Built and maintained mostly by coding agents, behind strong tests, previews and review gates.

**Non-goals for v1**
- Accounts, server-saved builds, comments, forums.
- Performance estimates such as horsepower or lap times. Manufacturer claims are shown, labeled as claims.
- M4 coupes (F82/G82). They're a cheap add later.
- Right-hand-drive interiors.
- Rendering differences between variants (Euro, CSL, CS) in 3D. Those variants exist in the data. In v1 they render with the US coupe body, and the UI says so.

**Anti-goals: failures even if the tool works**
- Affiliate links, ads, sponsored placements or store links of any kind.
- BMW logos or badges anywhere: the UI, the models or the textures, including the steering-wheel roundel.
- Prices with no date or source.
- Safety-relevant advice (maintenance intervals, fixes) that rests only on a forum post.
- A 3D scene so heavy that phones can't use the build sheet. The text tool must work without 3D.

## 3. Constraints

**Money**
- Hosting stays at $0/month on free tiers, plus a domain.
- Paid API calls (3D generation, later scraping) need a cap that the user approves each session. Every call is logged in `docs/spend-ledger.md`.

**Legal (not legal advice)**
- "BMW" and "M3" are used only to describe the car.
- No roundel, M logo or badges.
- A "not affiliated with BMW AG" notice appears in the footer and on `/about`.
- The 3D models show real cars, and products that look like real products, including wheel designs that may be protected. This is lower risk for a free tool that sells nothing, but not zero.

**Reference photos**
- Agents build the collection tooling (section 9.1). The user runs the collection runs, personally or with another model or harness, and decides which sources to use.
- The tooling's defaults: respect robots.txt, rate-limit, use a generic user agent, and record source URL, author, license and date for every image.
- It doesn't include features for getting past bot blocking.
- The collected images and the manifest stay private (private R2 bucket plus a local cache) and never go in the public repo.

**Generator licenses**
- Each 3D generator's terms decide whether its outputs can be published.
- The Hunyuan3D 2.x community license excludes the EU, UK and South Korea. Treat Hunyuan as experiment-only until that's cleared.
- Check Rodin/Hyper3D's terms (developer.hyper3d.ai) before publishing any output.

**Public repo hygiene**
- Commits and PRs carry no `Claude-Session` trailers or session URLs. This is the user's rule for public GridWork-dev repos.
- gitleaks runs in CI and as a pre-push hook.
- Secrets live only in `~/.config/secrets.env` and in GitHub Actions secrets. Use prefixed names (`M3_FAL_KEY`, `M3_BROWSERBASE_API_KEY`), never `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.

**Licenses**
- Code: MIT.
- Data (specs, parts, maintenance, issues): CC BY-SA 4.0.
- Published 3D models: proposed CC BY-SA 4.0. This stays compatible if Creative Commons share-alike photos fed a model, and every such photo is credited on `/about`. The license is final only after the generator terms are checked.

## 4. Who decided what

**The user decided:**
- Free, no selling, no store links.
- All generations eventually, starting with the M3.
- A 3D configurator, factory spec, aftermarket mods, a cost sheet, maintenance.
- A best-fit modern stack: current versions, agent-friendly.
- Order of work: settle the agent workflow, tooling, standards, roadmap and stack first. Then the data lane and the 3D lane run in parallel.
- Real named products with updated prices, plus a weekly price scraper later.
- Medium photoreal 3D: multiple render options, built and improved by agents, with good tooling, tests and previews.
- Car bodies generated from photos and descriptions, with a pipeline for that.
- The photo tooling: agents build it, and the user runs the collection.
- No access to a real E46. Online photos only.
- A visible interior plus a driver's-seat view.
- Each product looks like itself in 3D.
- Repo public from day one, under GridWork-dev.

**My calls in this doc (open to correction):**
- MVP is the US-spec, left-hand-drive E46 coupe. Other variants are data only in v1.
- The stack and versions (section 6), and hosting on Cloudflare.
- Data model, data quality rules and fitment rules (sections 7.3–7.6).
- The used-buyer checklist, built from flagged issues and maintenance items.
- The asset contract, the quality targets and the go/no-go spike.
- Per-product 3D comes in stages, with a labeled stand-in style until each product's own model ships (section 9.4).
- Agent roles and the roadmap phases.

## 5. Approaches considered

**Framework**
- **Astro 7 + React islands (chosen).**
  - Static pages for every generation, part and issue: fast, and findable in search.
  - The configurator is one React island.
  - Cloudflare acquired Astro in January 2026, so the Workers adapter is first-class.
  - Astro 7 added agent tooling: a background dev server and JSON logs.
- **Next.js:** heavier, Vercel-first, and full of server features this doesn't need.
- **TanStack Start:** made for app-heavy products. This is mostly content plus one app.
- **SvelteKit + Threlte:** smaller 3D ecosystem, and agents know React Three Fiber better.
- **Plain Vite single-page app:** pages are invisible to search.

**Where car bodies come from**
- **AI generation from curated photos plus a description, cleaned up by agents (the user's pick).**
  - Cheap per generation, and fully agent-driven.
  - Risks:
    - Generators output one fused mesh with lighting and paint baked in, so it has to be split and re-materialed.
    - Research shows generic generators are still inconsistent on cars.
    - With no walk-around set of a real car, getting matching views is harder.
  - The spike in section 9.9 gates this path.
- **Buying licensed marketplace models.** The highest and most predictable quality, but it costs money per generation, and each license needs checking for in-browser use. This is the documented fallback if the spike fails, and it's offered to the user, never switched to automatically.
- **Agents modeling bodies from scratch in Blender.** Not viable at photoreal quality today: in BlenderGym, top vision models struggle with tasks that are easy for humans. Used only for parametric parts.

## 6. Stack

| Layer | Choice | Version |
|---|---|---|
| Framework | Astro, with the React integration and the Cloudflare adapter | astro 7.4.13, @astrojs/react 7.1.9, @astrojs/cloudflare 14.4.9 |
| UI runtime | React | 19.3.1 |
| 3D | three.js WebGPURenderer (falls back to WebGL2 automatically), TSL node materials | three 0.187.0 |
| 3D in React | React Three Fiber, drei | @react-three/fiber 9.8.2, @react-three/drei 10.7.9 (switch to v10 when it reaches beta) |
| State | Zustand, with the build encoded in the URL | zustand 5.1.0 |
| Data validation | Zod, via Astro content collections | zod 4.6.7 |
| Styling and controls | Tailwind CSS, Base UI | tailwindcss 4.3.5, @base-ui/react 1.9.0 |
| Site search | Pagefind (static index) | pagefind 1.6.0 |
| Language | TypeScript 7 (native compiler) | typescript 7.0.2 |
| Build and test | Vite (Rolldown), Vitest, Playwright | vite 8.3.8, vitest 5.1.1, @playwright/test 1.65.1 |
| Lint and format | Biome | @biomejs/biome 2.6.8 |
| Package manager and runtime | pnpm, with Node pinned via mise | pnpm 12.23.0, Node 26 |
| Asset pipeline | Python with uv (ruff, pyright, pytest), headless Blender, glTF-Transform | Blender 5.2, @gltf-transform/cli 4.5.1 |
| Hosting | Cloudflare Workers static assets, Wrangler | wrangler 4.166.0 |
| Object storage | Cloudflare R2: a public bucket for published GLBs, a private one for references and intermediate files | |
| Analytics | Cloudflare Web Analytics (no cookies) | |
| Later | A Workers route for share-preview images. D1 and Better Auth only if accounts ever arrive | |

The pipeline is in Python because Blender scripting (bpy) and the image tools (background removal, perceptual hashing) are Python-native. The site is in TypeScript. Each side has its own check command, and the root `check` runs both.

## 7. Architecture

### 7.1 Overview

```
Data lane:  data/*.yaml -> Zod schemas + quality checks -> astro build -> static pages + configurator island -> Workers static assets
                                                                           (+ Pagefind index)

3D lane:    refs (private R2) -> generate -> Blender cleanup / split / assemble -> glTF-Transform -> validate + score
                                                                          -> publish hashed GLBs to public R2 + manifest.json in repo

Later:      weekly GitHub Action -> price scraper -> YAML changes -> PR -> checks -> merge -> deploy
```

### 7.2 Routes (all prerendered)

- `/`: pick a generation.
- `/[gen]/`: overview, variants, specs.
- `/[gen]/mods/` and `/[gen]/mods/[part]`
- `/[gen]/maintenance/`
- `/[gen]/issues/` and `/[gen]/issues/[issue]`
- `/[gen]/buying`: used-buyer checklist.
- `/[gen]/build`: configurator plus build sheet. The build state lives in the URL hash.
- `/about`: disclaimer, data sources, licenses, credits (including credits for reference photos).
- `/lab`: asset grid, turntables, quality and camera toggles. Preview deploys only, and marked `noindex`.

The only dynamic route planned is a Worker for share-preview images, in Phase 2. It stays on the free tier.

### 7.3 Data model

YAML under `data/`, one entry per file, validated by Zod schemas in `src/content.config.ts`. IDs are stable kebab-case and never reused.

**`generation`**
- `id` (`e46`), name, years, engine codes, body styles.
- Dimensions: length, width, height, wheelbase, front and rear track (mm), driver eye point (mm, for the driver's-seat camera), each with sources.
- Stock wheel fitment, per axle: bolt pattern, center bore, and the width and offset envelope that fits without rubbing, from stock height down to lowered. This feeds the fitment rules.

**`variant`**
- Generation, market (US or Euro), body, transmission, model years.
- Factory packages (ZCP, CSL, CS…) and factory paint codes.
- Factory wheel options (each with the ID of its 3D asset) and interior colors and trims.
- `render`: which base car asset to use. In v1, every E46 variant uses the US coupe asset.

**`part`**
- `id`, `name`, `brand` (none for the generic tier), `category`, `visible` (whether it shows in 3D).
- `fits { generation, years, body, transmission }` and `attributes`, used by the fitment rules (section 7.4).
- `requires[]` and `conflicts[]`, for anything the attribute rules don't cover.
- `labor { hours: [min, max], diy: easy | intermediate | pro }`.
- `prices[]`: real products only (see "price observation" below).
- `model`:
  - `{ asset: <asset id>, params }` once the product's own model exists.
  - Otherwise `{ standIn: <style id>, params }`, which the UI labels "3D look approximate".
  - Wheels: one asset per design, with size parameters (diameter, width, offset) per product size.
- `claims`: manufacturer claims, labeled as claims.
- `sources[]` with tiers (section 7.6), and `verified`.

**`price observation`** (real products only)
- `{ amount, currency, seller, checked, url? }`. `url` is stored only so the updater can check the price again. It's **never shown as a link**.
- The UI shows the range from the last 90 days, and marks it stale after 60 days.

**Generic-tier price**
- Each category gets one generic part with no brand, so every build can get an estimate.
- Its price is calculated: the minimum low and maximum high across that category's current real-product ranges. So it needs no seller of its own.

**`maintenance item`**
- Generation, engine, interval (miles and/or months), parts and fluids, cost range for DIY and shop.
- `inspectWhenBuying` plus `howToCheck`.
- `sources[]` and `verified`.

**`known issue`**
- Generation, engine, symptoms, cause, fix, prevention, cost range.
- How common: `rare`, `common` or `very common`.
- `inspectWhenBuying` plus `howToCheck`.
- `sources[]` and `verified`.

**Used-buyer checklist:** all known issues and maintenance items with `inspectWhenBuying: true`, ordered by how common and how costly they are. Shown at `/[gen]/buying`.

### 7.4 Logic modules (pure TypeScript, unit-tested)

**`src/lib/rules.ts`** checks a variant against a set of parts. Each result carries a reason.
- **Attribute rules** for wheels, tires and brakes:
  - The bolt pattern and center bore must match (or a hub ring must be in the build).
  - Width and offset against the generation's fitment envelope, at the build's ride height, give `fits`, `may need fender work` or `likely rubs`.
  - The tire size must match the wheel diameter and width range.
  - A brake kit's minimum wheel diameter must be no larger than the wheel diameter.
- **Lists** (`requires`, `conflicts`) for everything else.

**`src/lib/cost.ts`** computes:
- Parts, low and high.
- Labor: hours × rate.
- Tax rate and a contingency percentage.
- Totals and subtotals per category.

**`src/lib/codec.ts`** turns a build into a URL fragment and back.
- The format is versioned (`v1…`), so old links keep decoding forever.
- Unknown IDs decode as "part no longer available" instead of failing.

### 7.5 Configurator

- A React island, using `client:only="react"`, on `/[gen]/build`.
- The build sheet renders first and works without 3D. The 3D canvas loads lazily.
- Zustand holds the build, and each change is written to the URL hash.

**3D behavior**
- Wheel positions come from the wheelbase and track in the data, not from the mesh. Ride height moves the body relative to the wheel anchors.
- Paint is a parameter on the `paint` material.
- Window tint is a parameter on `glass`, and also a part (tint film).
- The interior is its own GLB. It loads after the body, on Medium and above, or right away when you open the driver's-seat view.

**Cameras**
- **Orbit:** the default.
- **Driver's seat:** placed at the data's driver eye point, looking around with drag, touch or gyroscope. The field of view is adjustable.
- **Detail presets:** wheel, rear, interior.

**Quality presets.** Picked automatically from what the device can do, and switchable by hand. Resolution adjusts on the fly.
- **Low:** WebGL2, environment-map reflections, a baked contact shadow, no post-processing. Dark glass, no interior (the driver's-seat view still loads it on demand).
- **Medium (default):** WebGPU; car paint with clear coat and metallic flake (TSL); studio HDRI; soft shadows; ambient occlusion; anti-aliasing; the interior visible through the glass.
- **High:** Medium plus screen-space reflections, higher-resolution shadows and depth of field.
- **Photo mode:** progressive path tracing with three-gpu-pathtracer, which supports clear coat. It's WebGL-based, so it runs in its own canvas, and it produces a downloadable still image.

### 7.6 Data quality rules

**Source tiers**
- **Tier 1:** BMW technical documents (owner's manuals, factory service intervals, service bulletins), manufacturer product pages and install guides.
- **Tier 2:** established specialist retailers' tech articles, reputable publications, well-known specialist shops.
- **Tier 3:** forums and owner reports.

**What counts as verified**
- Maintenance intervals, and fixes for known issues, need one Tier 1 source or two independent Tier 2 sources to be marked `verified: true`.
- Tier 3 alone is enough for symptoms and "how common". The entry stays `verified: false`, and the UI shows an "unverified" badge.

**Review**
- Every data PR gets an Opus data verifier, which re-reads the cited sources and checks the claims against them.
- PRs that touch maintenance or issues get the `safety` label. The user spot-checks those.

**Starting prices** (before the Phase 3 updater)
- Agents collect them from manufacturer list prices and retailer product pages, at normal browsing pace: one visit per product, recorded with the date.
- A seller whose terms forbid automated access is skipped.

## 8. Hosting and infrastructure

- **Site:** Cloudflare Workers static assets. Static requests are free and unlimited. The free plan allows 25 MiB per file and 20,000 files per version.
- **Deploys:** GitHub Actions. `main` runs `wrangler deploy`. Each PR runs `wrangler versions upload` and gets its preview URL as a comment. (This replaced Workers Builds on 2026-11-23, by the user's choice: no GitHub app dependency, and the same Node 26 toolchain as CI.)
- **Credentials:** Cloudflare tokens are minted through the API from the account's key-management token, one narrowly scoped token per purpose. Nothing is created by hand in the dashboard.
- **R2 buckets:**
  - `<name>-models`: public, behind a custom domain, with content-hashed GLB names that can be cached forever.
  - `<name>-refs`: private. Holds reference and product photos, generator outputs, Blender intermediate files and spike reports.
- **DNS, domain and analytics:** in Cloudflare.

## 9. 3D asset pipeline

Every change to a model is code in `pipeline/`. No hand edits in Blender that aren't captured as a script, so every asset can be rebuilt and agents can iterate safely. One command per stage: `pipeline run <asset> --stage <name>`.

### 9.1 Reference and product photos (`refs`; agents build it, the user runs it)

**Collectors**
- A Wikimedia Commons API client: one category per generation, with license metadata from `extmetadata`.
- A local-folder importer, for photos the user collects.
- A configurable page crawler: Playwright, with Browserbase as an optional backend for JavaScript-heavy pages. Defaults: respect robots.txt, rate-limit, use a generic user agent, and record source, author, license and date. Blocked pages are logged and skipped.
- The user decides which sources to run, and may run the collectors with another model or harness.

**Curation** (agents build it; it runs on whatever was collected)
1. Remove duplicates with perceptual hashes.
2. Classify each image with a vision model: generation, body, market, stock or modified, view (front, rear, side, front 3/4, rear 3/4, top, plus interior views: dash, seats, door, center console), occlusion and quality.
3. Reject modified cars for the body, and reject mismatched trims.
4. Remove backgrounds.
5. Build matched view sets: ideally 4–5 views per body style and per interior component.

**Product photos.** The same tooling collects and curates them per product, tagged with the product ID.

**Description.** One per body style and per product, built from the data files (dimensions, body lines, trim details, product specs). It's used as the generator prompt and as the critic's checklist.

### 9.2 Generation (`generate`)

- **Main generator:** Rodin Gen-2.5 through an API (Hyper3D directly, or fal).
  - Takes up to 5 views.
  - Outputs a quad or triangle mesh with PBR materials.
  - Resellers list about $0.40 per standard request.
- **Experiments in the spike:**
  - CubePart, Roblox's open generator that builds the mesh from a list of named parts.
  - Hunyuan3D (license limits; see section 3).
  - Models based on TRELLIS.
- Several candidates are generated per asset, and the best is kept by score (section 9.7).
- **Interior:** generated component by component (seats, dash with gauge cluster, steering wheel, door cards, center console), not as one enclosed scene. Today's generators build objects, not enclosed spaces.

### 9.3 Cleanup, splitting and assembly (`cleanup`, `assemble`; headless Blender)

**Exterior**
1. Scale and align to the data's dimensions: meters, standard axes.
2. Remesh or retopologize to the triangle budget.
3. Split into `body`, `glass`, `lights_front`, `lights_rear`, `trim`, `grille`, `undercarriage`. Candidate methods, compared in the spike:
   - Output that comes already split, from a part-aware generator.
   - 2D segmentation masks from several rendered views, projected back onto the mesh.
   - Clustering by texture and normals.
4. Remove the generated wheels, cap the wheel wells, and remove badges (meshes, and inpaint the texture).
5. Replace the baked body texture with the parametric `paint` material. Give the glass and lights proper materials.

**Interior**
1. Derive the cabin shell (floor, headliner, pillars, inner door skins) by insetting the exterior body mesh.
2. Place the generated components on the data's anchor points (driver eye point, seat rails, steering column).
3. Bake ambient occlusion for the cabin.
4. Remove the roundel on the steering wheel and gauges.

### 9.4 Product models (`product`)

Each visible product gets its own asset, built from its product photos and spec.

- **Round, symmetric parts** (wheels, brake discs, exhaust tips): parametric Blender scripts that agents fit to the product photos (spoke count and profile, lip, concavity), then size per product size. This is more accurate than AI generation for these shapes.
- **Complex parts** (seats, steering wheels, aero, calipers, lights): AI generation from product photos, cleaned up to the asset contract.
- **Parts you can't see** (tunes, bearings, fluids): `visible: false`, no 3D.
- **Stages:**
  - Each visible product starts with a stand-in style labeled "3D look approximate".
  - Its own asset replaces the stand-in as it passes review.
  - Phase 2 builds them in order of popularity.

### 9.5 Export and optimize (`export`)

- Export to GLB, then run glTF-Transform: weld, deduplicate, prune, meshopt geometry compression.
- KTX2 textures must be set explicitly. The `auto` default doesn't produce KTX2.
- LODs for the Low preset.

### 9.6 Asset contract (enforced by `validate`)

**Units and axes:** meters, Y up, nose toward −Z, origin on the ground under the middle of the wheelbase.

**Base car**
- Nodes: `body`.
- Anchors:
  - Wheels: `wheel_FL`, `wheel_FR`, `wheel_RL`, `wheel_RR`.
  - Aero and exhaust: `mount_front_lip`, `mount_trunk`, `mount_wing`, `mount_exhaust_L`, `mount_exhaust_R`.
  - Interior: `mount_interior`.
- Materials: `paint`, `glass`, `trim`, `lights_front`, `lights_rear`.

**Interior**
- Nodes: `interior` (root), `cabin_shell`, `dash`, `console`, `door_L`, `door_R`, `seat_driver`, `seat_passenger`, `steering_wheel`.
- Anchors: `mount_seat_L`, `mount_seat_R`, `mount_steering`, `camera_driver_eye`.

**Products:** one root node, with a pivot that matches the anchor they attach to.

**Budgets (proposed)**

| Asset | Triangles | File size | Textures |
|---|---|---|---|
| Base car | 100k–200k | ≤ 8 MB | ≤ 2K, 4K for body detail maps |
| Interior | ≤ 150k | ≤ 6 MB | 4K for dash and gauges, so the driver's-seat view stays sharp |
| One product | ≤ 30k | ≤ 1 MB | ≤ 2K |

### 9.7 Scoring and the critic loop (`score`)

**Automatic checks**
- The Khronos glTF validator passes.
- The asset contract passes.
- Dimensions are within 1% of the data file.
- Silhouette overlap is at least 0.90 against each reference view. The tool renders from the reference camera and compares masks. The 0.90 threshold is a starting point; the spike calibrates it.

**Vision critic**
- Reviews renders next to the references (product photos, for products) and the description checklist.
- Interiors are also reviewed from the driver's-seat camera.
- Returns a list of fixes and pass or fail.

**The loop.** The 3D agent adjusts parameters or scripts and runs again, up to 5 rounds per issue. After that, it brings the user a short report.

**Human gate.** The user approves each base car and interior in `/lab` before it's published. Products are approved in batches.

### 9.8 Publish (`publish`)

1. Upload content-hashed GLBs to the public bucket.
2. Update `src/assets/manifest.json`: logical ID → URL, hash, size, triangle count, sources, license.
3. Open a PR.

### 9.9 Go/no-go spike (Phase 0)

The spike runs on collected online photos; the user has no real car to photograph.

**Steps**
1. **Exterior:** the E46 coupe end to end. Collect references, generate with at least 2 generators, clean up and split, score, and view it at Medium.
2. **Interior test:** generate the dash and the driver's seat from interior photos, assemble them in a rough cabin shell, and view the result from the driver's seat.
3. **Product test:** one named wheel, built parametrically from its product photos, mounted on the car.

**Passes when**
- All automatic checks pass and the vision critic passes.
- The user agrees the car reads as an E46 M3 at medium quality.
- Paint, glass, wheels and interior can be changed separately.
- The driver's-seat view looks believable.
- The wheel is recognizable as that product.

**Outcomes**
- **Pass:** continue as designed.
- **Partial pass:** change methods within the spike's spend cap and run again. Options: more views, a different generator, a different way of splitting the mesh.
- **Fail:** bring the user the options, part by part. For example: buy licensed bodies or interiors for some or all generations, or lower the target for that part. Don't switch on my own.

The spike also runs the **model bake-off**:
- Claude (Sonnet) and Codex (gpt-6.1-sol) get the same tasks: a parametric wheel script fitted to product photos, and one splitting step.
- The screenshots are compared, and the winner takes that kind of task.
- The result is recorded in an ADR.

## 10. Testing and previews

- **Unit tests (Vitest)**
  - Rules: attribute fitment and lists.
  - Cost.
  - Codec, including decoding every saved old-version fixture.
  - Price range and staleness.
  - The generic-tier price calculation.
- **Data tests**
  - The build fails on any schema error.
  - Every `requires` and `conflicts` ID exists, and no part is orphaned.
  - Every real-product price has a seller and a checked date.
  - Every issue and maintenance item has sources, and `verified` matches the tier rules in section 7.6.
- **Pipeline tests (pytest).** The pure functions: manifest, deduplication, scoring math, view matching. Blender stages run on a small fixture model.
- **End-to-end tests (Playwright, against the built site)**
  - Pick a generation and add a part, and the total changes.
  - A wheel that doesn't fit shows its reason.
  - A share link restores the build.
  - The page works with 3D turned off.
  - The driver's-seat camera opens.
- **Visual regression**
  - Fixed views (front 3/4, rear 3/4, side, top, driver's seat, wheel detail) × each car × each preset, compared to approved baselines.
  - CI has no GPU, so it renders with the software WebGL path. A Mac script (`tools/shoot`) renders with the real GPU (WebGPU) for review.
  - The paint is checked against the Khronos Clear Coat Car Paint sample model.
- **Previews**
  - Every PR gets a Cloudflare preview URL, including `/lab`.
  - PRs that touch 3D attach before-and-after screenshots.

## 11. CI/CD

**Every PR (GitHub Actions)** runs `pnpm check`:
- Biome.
- `tsc` (TypeScript 7) and `astro check`.
- Vitest.
- `astro build`, which validates the data, plus the data quality checks.
- Pagefind.
- Pipeline checks: ruff, pyright, pytest.

Then it runs the Playwright end-to-end and visual tests on the build, then gitleaks. A deploy workflow uploads a preview version and comments its URL on the PR.

**Merging to `main`** deploys to production. `main` is protected: checks must pass and a review is required.

**Renovate** groups dependency updates weekly. Patch and minor updates merge automatically when checks pass.

**3D assets** are built on the Mac. Blender isn't in CI for v1. `pipeline run <asset> --stage publish` uploads them and opens a PR.

**Phase 3** adds a weekly price updater on a GitHub Actions schedule (section 13).

## 12. Agent workflow

### 12.1 Roles and model routing

These follow the user's global routing rules and the hooks that enforce them.

| Role | Claude | Codex |
|---|---|---|
| Orchestrator: owns specs, plans and merges, together with the user | Main session (Fable or Opus) | — |
| Architecture and code review | Opus 5.5 (when the orchestrator isn't Opus) | gpt-6-astra (high), via codex-review |
| Data verifier (every data PR) | Opus 5.5 | — |
| 3D vision critic | Opus 5.5 | — |
| Implementation, tests, bounded edits | Sonnet 5.5 | gpt-6.1-sol |
| Research, bulk data gathering, recon | Haiku 5.5 | gpt-6-luna (low) |

### 12.2 Lanes

After Phase 0, two lanes run in parallel, each in its own git worktree and branch:
- **App + data:** `src/`, `data/`.
- **3D:** `pipeline/`, `src/configurator/scene/`, the asset manifest.

The shared contracts (`src/content.config.ts`, `docs/standards/3d-assets.md`) change only through a dedicated PR that both lanes rebase onto.

### 12.3 Task lifecycle

1. Spec (this doc).
2. One plan per milestone (superpowers writing-plans).
3. Subagent-driven development: tests first where they fit, one task at a time.
4. A PR, with screenshots if the UI or 3D changed.
5. Review: Opus plus a Codex second opinion. Data PRs also go to the data verifier; `safety` PRs are spot-checked by the user.
6. Fix, then merge.

The roadmap and tasks live in GitHub Issues and milestones, so they're public. Decisions get short ADRs in `docs/decisions/`, written with the architecture-decision skill.

### 12.4 Agent tooling

- `AGENTS.md` at the root, with `CLAUDE.md` symlinked to it. Covers commands, contracts, hard rules and where things live.
- **MCP servers**
  - Astro docs (`https://mcp.docs.astro.build/mcp`) and Cloudflare docs (`https://docs.mcp.cloudflare.com/mcp`).
  - Playwright, for clicking through the configurator.
  - Exa, for research.
  - blender-mcp: optional, for inspecting a scene only. Changes still land as scripts.
- Astro 7's background dev server and JSON logs for agent runs.
- **One command per question**
  - `pnpm check`: everything.
  - `pnpm test`: unit tests.
  - `pnpm e2e`: browser tests.
  - `pnpm shoot <asset> [--view driver]`: screenshots.
  - `pipeline run <asset> --stage <name>`: one pipeline stage.

## 13. Price updater (Phase 3)

- A weekly scheduled GitHub Action. For each real product with a stored URL, it fetches the current price:
  - Playwright first.
  - Browserbase (this project's own key) or an Apify actor for pages that need a full browser.
  - Manufacturer list prices where they're published.
- It adds price observations to the YAML, then opens one PR a week with a table of changes (old → new, big jumps flagged).
- **Rules:**
  - Respect robots.txt and site terms.
  - At most one request per product per week.
  - A generic user agent, and results are cached.
  - A source that blocks access, or whose terms forbid it, is dropped, not worked around.
- Browserbase or Apify spending goes in the spend ledger.

## 14. Repo layout

```
<name>/
  AGENTS.md  CLAUDE.md -> AGENTS.md  CONTRIBUTING.md  LICENSE (MIT)  DATA_LICENSE (CC BY-SA 4.0)
  data/{generations,variants,parts,maintenance,issues}/<gen>/*.yaml
  src/content.config.ts        Zod schemas
  src/pages/                   routes from section 7.2
  src/components/              Astro + React UI
  src/configurator/            island: store, build sheet, cameras, scene/
  src/lib/{rules,cost,codec}.ts
  src/assets/manifest.json     published GLBs
  pipeline/                    Python (uv): refs, generate, cleanup, assemble, product, export, validate, score, publish
  pipeline/blender/            bpy scripts
  tools/                       shoot, helpers
  tests/{unit,e2e,visual}/
  docs/{standards,decisions,superpowers/specs,superpowers/plans}/  docs/spend-ledger.md
  .github/workflows/  renovate.json  biome.json  mise.toml
```

## 15. Roadmap

Each phase ends with a release or demo the user signs off on.

### Phase 0: foundations (in order)

1. Name. Repo `GridWork-dev/<name>`: public, `main` protected, labels and milestones. Cloudflare project and R2 buckets.
2. Scaffold the section 6 stack. `pnpm check` passes. An empty site deploys, with working PR previews.
3. Write `AGENTS.md` and the standards docs:
   - code
   - data (source tiers, verification, prices)
   - 3D assets
   - testing
   - legal and licenses
   - contributing, plus a PR template

   Plus ADRs for the decisions in this doc.
4. Contracts:
   - Zod schemas, including the fitment attributes and the buyer-checklist fields, with 2–3 sample E46 entries per collection.
   - The 3D asset contract and its validator.
5. Photo tooling (`refs` collectors and curation), handed to the user to run.
6. Go/no-go spike plus model bake-off (section 9.9), ending with a spike report and an ADR.
7. Spend cap approved for Phase 1 generation.

**Done when:** the spike decision is made, and both lanes can start against stable contracts.

### Phase 1: two lanes in parallel

**App + data lane**
- E46 variants.
- About 60 real products, plus a generic tier in every category.
- About 25 maintenance items and about 15 known issues, sourced and verified according to section 7.6.
- Pages for the generation, mods, maintenance, issues and buyer checklist.
- The build sheet (no 3D), with fitment rules.
- Share links, search, `/about`.

**Done when:** the text tool is out as a public beta.

**3D lane**
- The E46 coupe body and interior through the full pipeline.
- Paint shader; Low, Medium and High presets; the orbit and driver's-seat cameras.
- Stand-in styles for every visible product category.
- Studio scene, `/lab`, visual-regression baselines.

**Done when:** the body and interior pass every check and the user approves them in `/lab`.

### Phase 2: join

- The 3D configurator connected to the build sheet: wheels, ride height, aero, exhaust, interior parts, paint codes, tint.
- Product models, most popular first. Products without their own model keep the labeled stand-in.
- Photo mode and share-preview images.

**Done when:** public v1 ships, with at least the top 20 visible products modeled (a proposed target).

### Phase 3: weekly price updater

**Done when:** two weekly PRs have merged cleanly.

### Phase 4: more generations

1. The E46 convertible.
2. The next generation the user picks.
3. A contributor flow open to the public.

## 16. Open items for the user

Settled 2026-11-23:

- Repo name `m3-tool` as a placeholder. Hosting on the GridWork Cloudflare account. Deploys and previews from GitHub Actions, with Cloudflare tokens minted through the API. Phase 0 spike cap: $50 of paid 3D generation (Rodin plus 1-2 other generators for comparison), logged in `docs/spend-ledger.md`.

Still open:

1. Public name and domain, before the public beta. Keep BMW and M3 out of the domain.
2. Spend cap for Phase 1 generation, asked once the spike result is in.
3. Confirm the CC BY-SA 4.0 license for 3D models once the generator terms are checked.
4. Which generation comes second, before Phase 4.

## 17. Left to the builder

- Exact URL codec format.
- Tailwind theme and design system (run through the impeccable skill when the UI is built).
- Which splitting method wins (decided in the spike).
- LOD counts.
- Which post-processing nodes go in each preset.
- Visual-test tolerances.
- Pagefind UI details.
- Gyroscope details for the driver's-seat camera.
- Whether `astro check` works with TypeScript 7. If not, `tsc` handles `.ts` files and `astro check` uses its bundled TypeScript.

## 18. Risks

| Risk | Effect | How it's handled |
|---|---|---|
| AI-generated bodies fall short of medium photoreal, made worse by having online photos only | The 3D lane stalls | The Phase 0 spike decides before anything depends on it. A documented fallback, offered to the user |
| Interiors built from photos look wrong from the driver's seat | The interior goal is missed | Component-by-component generation, the interior test in the spike, and a fallback per part |
| Splitting fused meshes is unreliable | Paint, glass and wheels can't be changed separately | Part-aware generators and several splitting methods are tested in the spike |
| Volume of product models (about 60 products, visible ones modeled) | Phase 2 drags on | Parametric scripts for round parts, popularity order, labeled stand-ins meanwhile |
| Copyright of photos, generator terms, protected wheel designs | Takedown risk | Private references, license metadata, Commons credited, terms checked before publishing, free and non-commercial |
| BMW trademark or trade dress | Takedown risk | No logos or badges, disclaimer |
| Wrong fitment or maintenance advice | Harm to users, lost trust | Source tiers, `verified` flags, a data verifier on every PR, the user spot-checks safety PRs |
| Stale or wrong prices | Lost trust | Dated observations, stale flags, weekly updater |
| Scope (6+ generations × hundreds of parts) | Never ships | One generation end to end first, with phase exits |
| Gaps in WebGPU support | Blank 3D for some users | Automatic WebGL2 fallback, Low preset, a text tool that works without 3D |
