# 0001. Static site on Workers static assets

- **Status:** Accepted 2026-11-23
- **Date:** 2026-11-23

## Context

The site is mostly content: a page for every generation, part and issue, plus one app, the configurator. Hosting has to stay at $0 a month on free tiers. Static requests on Workers static assets are free and unlimited, and the free plan allows 25 MiB per file and 20,000 files per version. The pages must be findable in search, and the text tool must work without 3D.

Two later questions followed from that. Who deploys, and with what credentials? Which TypeScript do we run, given that `astro check` and the native compiler can't share one install?

## Decision

- **Astro 7 with React islands, built as a static site.** Every route is prerendered. The configurator is one `client:only="react"` island. No adapter is installed: the Cloudflare adapter arrives with the first dynamic route, the Phase 2 Worker for share-preview images.
- **Workers static assets** serve `dist/` (`wrangler.jsonc`). Unknown paths return the built `404.html` with a 404 status. GLBs are not in the Worker: they go to R2.
- **Deploys and PR previews run from GitHub Actions** (`deploy.yml`), not Workers Builds. The user chose this because it adds no GitHub app dependency and uses the same Node 26 toolchain as CI. A push to `main` runs `wrangler deploy`. A same-repo PR runs `wrangler versions upload --preview-alias pr-<n>` and gets its URL as a PR comment. `deploy` is not a required check, because fork PRs get no secrets.
- **Cloudflare tokens are minted through the API, one per purpose,** by the maintainer's session. Nothing is created in the dashboard. There are three:
  - a deploy token scoped to the one Worker, whose secrets only the wrangler steps can see;
  - an R2 token scoped to the two buckets;
  - a short-lived setup token.
- **TypeScript is split.** The root `typescript` is 6.0.3 so `astro check` works. TypeScript 7.0.2 is installed as the alias `typescript-7`, and `tsc` runs from it by path. `pnpm typecheck` runs `astro sync` first, so `astro:content` resolves on a fresh tree.

## Alternatives considered

- **Next.js:** heavier, Vercel-first, and full of server features this site doesn't need.
- **TanStack Start:** made for app-heavy products. This is mostly content plus one app.
- **SvelteKit with Threlte:** a smaller 3D ecosystem, and agents know React Three Fiber better.
- **A plain Vite single-page app:** its pages are invisible to search.
- **Workers Builds:** rejected for the app-dependency and toolchain reasons above.
- **One broad token, or tokens made by hand in the dashboard:** rejected. The spec asks for one narrowly scoped token per purpose and nothing created by hand.
- **One TypeScript version.** `astro check` needs 6.0.3, so a single install would mean giving up the TypeScript 7 native compiler for `tsc`.

## Consequences

- Cloudflare acquired Astro in January 2026, so the Workers adapter should be first-class when Phase 2 needs it. Adding it is a decision to make then: the site stops being purely static for that one route.
- Previews exist only for PRs from this repo. A fork PR gets the `check`, `e2e` and `gitleaks` gate and no preview.
- The deploy token never reaches checkout, install or build steps, because those run dependency code. Keep it that way when you edit `deploy.yml`.
- Two TypeScript copies are installed. A bare `tsc` runs whichever bin pnpm links, which depends on how pnpm resolves the two `tsc` bins. Always run `pnpm typecheck`.
- Run the deploy script as `pnpm run deploy`: `pnpm deploy` is a pnpm built-in.
- This settles the spec's open question about `astro check` with TypeScript 7 (section 17): it keeps its own TypeScript 6.
- Secrets are named in docs, never valued. `infra/README.md` lists each token and where it lives.
