# 0011. Deploy pipeline hardening

- **Status:** Accepted 2026-11-23
- **Date:** 2026-11-23
- **Amends:** the deploy bullets of [0001](0001-static-site-on-workers.md)

## Context

ADR 0001 had one deploy job: check out, install, build, then run `wrangler` with the Cloudflare secrets set on the last steps. Those steps shared a runner, a workspace and a `node_modules` with the install that ran every dependency's code, and `pnpm wrangler` ran the repo's own copy of wrangler. A poisoned dependency could have swapped it for a copy that reads the token. Renovate PRs, which carry dependency bumps nobody has read, got the same job and the same secrets. The workflows pinned actions by moving tags. The Codex final review ranked this a P1.

## Decision

- **Two jobs.** `build` checks out the repo (`persist-credentials: false`), installs with `--frozen-lockfile`, runs `check:data`, builds, runs `check:links`, and uploads `dist/` and `wrangler.jsonc`. It is read-only and has no secrets at any level.
- **`deploy` runs on a fresh runner with no checkout.** It downloads that artifact, takes Node 26.13.1 from `actions/setup-node`, and runs `npx --yes wrangler@4.167.0`. The Cloudflare secrets are set on the two wrangler steps only. The pin must equal package.json's wrangler, and `tests/unit/workflows.test.ts` checks it.
- **No deploy for forks or for bots.** A PR from a fork gets no secrets. A PR whose actor or author ends in `[bot]` gets no deploy job, and no build job. A push to `main` always deploys.
- **A smoke test follows the production deploy.** It curls the live site and expects a 200 with the not-affiliated notice and a 404 on `/__nope`, with retries.
- **Every action is pinned to a full commit SHA** with a `# vX.Y.Z` comment, and every checkout sets `persist-credentials: false`.
- **Renovate waits three days after a release** (`minimumReleaseAge`). It never automerges `wrangler` or the github-actions manager, and groups each separately so they can't ride in an automerged group.

## Alternatives considered

- **Keep one job and scope the secrets to the last steps:** what 0001 did. Rejected: one runner and one workspace, so the scope hides nothing from code that ran earlier.
- **A preview token that can't deploy:** not available. Cloudflare has no token scope that uploads a preview version but can't deploy to production.
- **Run wrangler from the repo's install in the deploy job:** rejected. It is project code.
- **Tag pins (`@v7`):** rejected. A tag moves, so a compromised action reaches the job.
- **Workers Builds:** still rejected, for the reasons in 0001.

## Consequences

- **The preview token is the production token.** `m3-tool-deploy` runs both `versions upload` and `deploy`. A same-repo PR can edit `deploy.yml`, and its own copy runs with the secrets. That is acceptable with one maintainer, and it is why forks and bots are skipped.
- Deploys cost two runners, an artifact hop and a wrangler download. They are slower than before.
- `npx` resolves wrangler's own dependencies at deploy time, outside the lockfile, so only wrangler's version is pinned. A deploy job with its own lockfile would close that.
- Renovate's wrangler and Actions PRs need a manual merge. A wrangler bump fails the workflow test until `deploy.yml`'s pin matches, on purpose.
- A failed smoke test turns the run red after the deploy has happened. Fix forward, or redeploy the last good commit.
- The smoke test names the production URL. A new domain at the beta means editing `deploy.yml`.
- A pull request runs its own `deploy.yml`, so CI proves the build job, the preview upload and the comment. The production deploy and the smoke test run only from `main`, so the first deploy after this merges is the proof.
